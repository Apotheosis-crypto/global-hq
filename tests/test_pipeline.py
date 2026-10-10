"""Offline end-to-end test: fixture feeds -> clustering -> scoring -> alert -> briefing."""
import json
import unittest
from datetime import datetime, timezone

from hq import app, briefing, engine, notify, store

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
                   f"<pubDate>Thu, 08 Oct 2026 {h} GMT</pubDate></item>" for t, u, d, h in items)
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>".encode()


FEEDS = {
    "un-news": rss(("Security Council meets as military coup unfolds in Niger capital", "https://news.un.org/1", "Soldiers seized the presidential palace.", "09:00:00")),
    "bbc-world": rss(("Niger military coup: soldiers seize presidential palace", "https://bbc.co.uk/1", "At least 12 people killed in clashes.", "08:40:00"),
                     ("Local festival draws crowds in Lisbon", "https://bbc.co.uk/2", "Annual event.", "07:00:00")),
    "aljazeera": rss(("Coup in Niger as soldiers seize presidential palace", "https://aljazeera.com/1", "", "08:55:00")),
    "usgs": json.dumps({"features": [{"properties": {"time": 1791450000000, "mag": 7.4, "place": "off the coast of Chile",
                                                     "url": "https://usgs.gov/q1", "tsunami": 1, "alert": "orange", "felt": 300}}]}).encode(),
    "gdelt": json.dumps({"articles": [
        {"title": "Niger coup soldiers seize presidential palace", "url": "https://blog.example/1", "domain": "blog.example", "seendate": "20261008T085000Z"},
        {"title": "Aliens land in Paris says anonymous blogger", "url": "https://fake.example/2", "domain": "fake.example", "seendate": "20261008T090000Z"}]}).encode(),
}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.cfg, self.src = app.load("/nonexistent")
        self.cfg["alerts"]["channels"] = ["console"]
        self.db = store.connect(":memory:")
        urls = {s["url"]: s["id"] for s in self.src["sources"] + self.src["discovery"]}
        self.sent = []
        notify.send = lambda cfg, subj, body, **kw: self.sent.append(subj) or []

        def fetcher(url):
            sid = urls[url]
            if sid not in FEEDS:
                raise OSError("offline in test")
            return FEEDS[sid]
        self.fetcher = fetcher

    def test_end_to_end(self):
        fired = app.cycle(self.db, self.cfg, self.src, self.fetcher, now=NOW)
        heads = {e["headline"] for e in fired}
        self.assertEqual(len(fired), 2, heads)
        coup = next(e for e in fired if "Niger" in e["headline"])
        self.assertEqual(coup["sources"], 3)
        self.assertEqual(coup["region"], "Africa")
        self.assertEqual(coup["category"], "Conflict")
        self.assertTrue(coup["headline"].startswith("Security Council"), "official source should lead")
        quake = next(e for e in fired if "earthquake" in e["headline"])
        self.assertEqual(quake["category"], "Disaster")

        events = {e["headline"]: e for e in engine.rebuild(self.db, app.source_index(self.src), now=NOW)}
        self.assertFalse(any("Aliens" in h for h in events), "web-only rumours must never become events")
        lisbon = next(e for h, e in events.items() if "Lisbon" in h)
        self.assertLess(lisbon["score"], self.cfg["alerts"]["threshold"])

        # a second sweep must not re-alert
        self.assertEqual(app.cycle(self.db, self.cfg, self.src, self.fetcher, now=NOW), [])
        self.assertEqual(len(self.sent), 2)

        health = {r["source_id"]: r["ok"] for r in self.db.execute("SELECT * FROM health")}
        self.assertEqual(health["bbc-world"], 1)
        self.assertEqual(health["who"], 0)

    def test_briefing_schedule(self):
        app.cycle(self.db, self.cfg, self.src, self.fetcher, now=NOW)
        self.cfg["briefing"] = {"time": "07:00", "timezone": "America/New_York"}
        early = datetime(2026, 10, 8, 10, 30, tzinfo=timezone.utc)  # 06:30 New York
        self.assertFalse(app.briefing_due(self.cfg, early)[0])
        title, text, page = briefing.build(self.db, app.source_index(self.src), NOW)
        self.assertIn("KEY JUDGEMENTS", text)
        self.assertIn("Niger", text)
        self.assertIn("<h2>Africa</h2>", page)


if __name__ == "__main__":
    unittest.main()
