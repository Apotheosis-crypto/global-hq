"""Collection cycle, briefing scheduler, and the HQ web dashboard."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from . import briefing, engine, feeds, notify, store

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.Lock()


def load(cfg_path):
    cfg_file = Path(cfg_path)
    cfg = json.loads((cfg_file if cfg_file.exists() else ROOT / "config.example.json").read_text())
    src = json.loads((ROOT / "sources.json").read_text())
    # Environment overrides, so hosted runs (GitHub Actions) keep secrets out of the repo.
    env = os.environ
    if env.get("HQ_NTFY_TOPIC"):
        cfg["ntfy"]["topic"] = env["HQ_NTFY_TOPIC"]
    if env.get("HQ_BRIEFING_TIME"):
        cfg["briefing"]["time"] = env["HQ_BRIEFING_TIME"]
    if env.get("HQ_BRIEFING_TZ"):
        cfg["briefing"]["timezone"] = env["HQ_BRIEFING_TZ"]
    if env.get("HQ_CHANNELS"):
        cfg["alerts"]["channels"] = [c.strip() for c in env["HQ_CHANNELS"].split(",") if c.strip()]
    if env.get("HQ_EMAIL_TO"):
        cfg["email"]["to"] = env["HQ_EMAIL_TO"]
    if env.get("HQ_EMAIL_USER"):
        cfg["email"]["username"] = env["HQ_EMAIL_USER"]
    return cfg, src


def source_index(src):
    return {s["id"]: s for s in src["sources"] + src["discovery"]}


def cycle(db, cfg, src, fetcher=feeds.fetch, now=None):
    """One sweep: pull every feed in parallel, recluster, fire alerts. Returns new alerts."""
    now = now or datetime.now(timezone.utc)
    jobs = [(s, True) for s in src["sources"]] + [(s, False) for s in src["discovery"]]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda j: (j, feeds.pull(j[0], fetcher)), jobs))
    sources = source_index(src)
    with LOCK:
        for (s, verified), (items, err) in results:
            store.save_items(db, items, verified)
            store.record_health(db, s["id"], err, len(items), now.isoformat())
        events = engine.rebuild(db, sources, now=now)
        fired = []
        for ev in events:
            if not engine.should_alert(ev, cfg) or not store.mark_sent(db, "alert", ev["id"], now.isoformat()):
                continue
            row = db.execute("SELECT * FROM events WHERE id=?", (ev["id"],)).fetchone()
            items = [dict(i, source_name=sources.get(i["source_id"], {}).get("name", i["source_id"]))
                     for i in db.execute("SELECT * FROM items WHERE event_id=?", (ev["id"],))]
            notify.send(cfg, f"FLASH: {ev['headline']}", notify.alert_text(row, items), urgent=ev["score"] >= 85)
            db.execute("UPDATE events SET alerted=1 WHERE id=?", (ev["id"],))
            fired.append(ev)
        db.commit()
    return fired


def briefing_due(cfg, now):
    tz = ZoneInfo(cfg["briefing"]["timezone"])
    local = now.astimezone(tz)
    hh, mm = map(int, cfg["briefing"]["time"].split(":"))
    return (local.hour, local.minute) >= (hh, mm), local.date().isoformat()


def maybe_send_briefing(db, cfg, src, now=None):
    now = now or datetime.now(timezone.utc)
    due, day = briefing_due(cfg, now)
    if not due:
        return False
    with LOCK:
        if not store.mark_sent(db, "briefing", day, now.isoformat()):
            return False
        title, text, page = briefing.build(db, source_index(src), now)
    (ROOT / "briefings").mkdir(exist_ok=True)
    (ROOT / "briefings" / f"{day}.html").write_text(page)
    notify.send(cfg, title, text, html_body=page)
    return True


DASHBOARD = (Path(__file__).parent / "dashboard.html")


def serve(db, cfg, src):
    sources = source_index(src)

    class H(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            with LOCK:
                if self.path in ("/api/events.json", "/api/health.json"):
                    events, health = api_payloads(db, cfg, sources)
                    return self._send(json.dumps(events if "events" in self.path else health))
                if self.path in ("/briefing", "/briefing/"):
                    return self._send(briefing.build(db, sources)[2], "text/html")
            if self.path in ("/", "/index.html"):
                return self._send(DASHBOARD.read_bytes(), "text/html")
            self.send_error(404)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", cfg["port"]), H)
    print(f"Global HQ dashboard on http://localhost:{cfg['port']}")
    srv.serve_forever()


def api_payloads(db, cfg, sources):
    events = briefing.gather(db, sources, hours=48, limit=80)
    health = [dict(r, name=sources.get(r["source_id"], {}).get("name"), tier=sources.get(r["source_id"], {}).get("tier", 0))
              for r in db.execute("SELECT * FROM health ORDER BY source_id")]
    return {"events": events, "config": {"briefing": cfg["briefing"], "threshold": cfg["alerts"]["threshold"]}}, health


def export(db, cfg, src, out):
    """Write the dashboard as a static site (for GitHub Pages or any static host)."""
    out = Path(out)
    sources = source_index(src)
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "briefing").mkdir(exist_ok=True)
    events, health = api_payloads(db, cfg, sources)
    (out / "api" / "events.json").write_text(json.dumps(events))
    (out / "api" / "health.json").write_text(json.dumps(health))
    (out / "briefing" / "index.html").write_text(briefing.build(db, sources)[2])
    (out / "index.html").write_bytes(DASHBOARD.read_bytes())
    archive = ROOT / "briefings"
    if archive.exists():
        (out / "archive").mkdir(exist_ok=True)
        for f in archive.glob("*.html"):
            (out / "archive" / f.name).write_text(f.read_text())


def run(cfg, src, once=False):
    db = store.connect(str(ROOT / cfg["db_path"]))
    if once:
        fired = cycle(db, cfg, src)
        sent = maybe_send_briefing(db, cfg, src)
        print(f"cycle done, {len(fired)} alert(s){', briefing sent' if sent else ''}")
        return db
    threading.Thread(target=serve, args=(db, cfg, src), daemon=True).start()
    while True:
        try:
            fired = cycle(db, cfg, src)
            print(f"{datetime.now(timezone.utc):%H:%M:%S} sweep complete, {len(fired)} alert(s)")
            maybe_send_briefing(db, cfg, src)
        except Exception as e:  # noqa: BLE001 - keep the watch running
            print("cycle error:", e)
        time.sleep(cfg["poll_minutes"] * 60)
