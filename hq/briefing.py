"""Daily intelligence briefing: top events of the last 24h, grouped by region."""
import html
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import geo

REGION_ORDER = ["Global", "Europe", "Middle East", "Africa", "Asia", "Americas", "Oceania"]


def gather(db, sources, now=None, hours=24, limit=25):
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    events = [dict(e) for e in db.execute(
        "SELECT * FROM events WHERE last_seen >= ? ORDER BY score DESC, sources DESC LIMIT ?", (since, limit))]
    for e in events:
        e["reasons"] = json.loads(e["reasons"])
        e["evidence"] = [dict(i, source_name=sources.get(i["source_id"], {}).get("name", i["source_id"]))
                         for i in db.execute("SELECT * FROM items WHERE event_id=? AND verified=1 ORDER BY published", (e["id"],))]
        body = " ".join(i["title"] + " " + (i["summary"] or "") for i in e["evidence"])
        e["geo"] = geo.locate(e["headline"], body, [json.loads(i["extra"] or "{}") for i in e["evidence"]])
    return events


def build(db, sources, now=None, tz="UTC"):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(tz))
    events = [e for e in gather(db, sources, now) if e["score"] >= 15]  # drop routine noise
    title = f"Global Intelligence Briefing - {local:%A %d %B %Y}"
    key = [e for e in events if e["score"] >= 60][:5]

    text = [title, "", "KEY JUDGEMENTS"]
    text += [f"{n}. {e['headline']} ({e['region']}, {e['category']}, score {e['score']}, {e['sources']} sources)" for n, e in enumerate(key, 1)] or ["No events above the significance threshold."]
    by_region = {}
    for e in events:
        by_region.setdefault(e["region"], []).append(e)
    for r in sorted(by_region, key=lambda r: REGION_ORDER.index(r) if r in REGION_ORDER else 99):
        text += ["", r.upper()] + [f"- {e['headline']} [{e['score']}] {e['evidence'][0]['url'] if e['evidence'] else ''}" for e in by_region[r]]

    esc = html.escape
    def card(e):
        ev = "".join(f'<li><a href="{esc(i["url"])}">{esc(i["source_name"])}</a>: {esc(i["title"])}</li>' for i in e["evidence"][:5])
        return (f'<div class="ev"><div class="meta">{esc(e["category"])} &middot; score <b>{e["score"]}</b> &middot; {e["sources"]} source(s)</div>'
                f'<h3>{esc(e["headline"])}</h3><ul>{ev}</ul></div>')
    sections = "".join(f"<h2>{esc(r)}</h2>" + "".join(card(e) for e in by_region[r])
                       for r in sorted(by_region, key=lambda r: REGION_ORDER.index(r) if r in REGION_ORDER else 99))
    keys = "".join(f"<li>{esc(e['headline'])} <span class=meta>({esc(e['region'])}, {e['score']})</span></li>" for e in key) or "<li>No events above threshold.</li>"
    page = f"""<!doctype html><meta charset=utf-8><title>{esc(title)}</title>
<style>body{{font:15px/1.5 Georgia,serif;max-width:760px;margin:24px auto;padding:0 16px;color:#1b1f24}}
h1{{font-size:22px;border-bottom:3px solid #0b3d91;padding-bottom:6px}}h2{{color:#0b3d91;font-size:16px;text-transform:uppercase;letter-spacing:.06em;margin-top:28px}}
.ev{{border-left:3px solid #c9d3e3;padding-left:12px;margin:12px 0}}.ev h3{{font-size:16px;margin:2px 0}}.meta{{font:12px system-ui;color:#5b6573}}
.key{{background:#f2f5fa;padding:10px 14px 10px 32px}}a{{color:#0b3d91}}</style>
<h1>{esc(title)}</h1><div class=meta>Classification: OPEN SOURCE &middot; Compiled {local:%H:%M %Z} from verified sources only</div>
<h2>Key judgements</h2><ol class=key>{keys}</ol>{sections}"""
    return title, "\n".join(text), page
