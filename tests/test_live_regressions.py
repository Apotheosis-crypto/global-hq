"""Regressions taken from the first live sweep (2026-10-10)."""
import unittest
from datetime import datetime, timezone

from hq import app, engine


def item(i, source, title, verified=1):
    return {"id": str(i), "source_id": source, "title": title, "summary": "", "url": f"https://x/{i}",
            "published": f"2026-10-09T0{i % 10}:00:00+00:00", "verified": verified, "extra": "{}"}


class Clustering(unittest.TestCase):
    def test_separate_gdacs_quakes_stay_separate(self):
        titles = ["Green earthquake (Magnitude 5.5M, Depth:10km) in West Of Macquarie Island 08/10/2026 06:46 UTC, [unknown].",
                  "Green earthquake (Magnitude 5.1M, Depth:35km) in Tonga 08/10/2026 09:12 UTC, [unknown].",
                  "Orange earthquake (Magnitude 6.6M, Depth:12km) in Panama 09/10/2026 01:02 UTC, [unknown]."]
        clusters = engine.cluster([item(n, "gdacs", t) for n, t in enumerate(titles)], {"gdacs"})
        self.assertEqual(len(clusters), 3)

    def test_no_snowballing_into_unrelated_stories(self):
        items = [item(1, "un-news", "Secretary-General congratulates Navi Pillay on receiving 2026 Nobel Peace Prize"),
                 item(2, "npr-world", "Navi Pillay wins Nobel Peace Prize for human rights work"),
                 item(3, "guardian", "Human rights groups condemn new US sanctions on International Criminal Court"),
                 item(4, "bbc-world", "International Criminal Court judges hit by sanctions")]
        groups = sorted(sorted(i["id"] for i in c["items"]) for c in engine.cluster(items))
        self.assertEqual(groups, [["1", "2"], ["3", "4"]])

    def test_regions(self):
        sources = app.source_index(app.load("/none")[1])
        ev = engine.score([item(1, "usgs", "M7.7 earthquake - 12 km WSW of Pitaloza Arriba, Panama")], sources)
        self.assertEqual(ev["region"], "Americas")
        ev = engine.score([item(1, "gdacs", "Green earthquake (Magnitude 5.5M) in West Of Macquarie Island")], sources)
        self.assertEqual(ev["region"], "Oceania")


class BriefingWindow(unittest.TestCase):
    def test_only_sends_in_the_morning_window(self):
        cfg = {"briefing": {"time": "07:00", "timezone": "America/Los_Angeles"}}
        at = lambda h, m: datetime(2026, 10, 10, h, m, tzinfo=timezone.utc)
        self.assertFalse(app.briefing_due(cfg, at(3, 26))[0])   # 20:26 PDT the evening before (first deploy)
        self.assertFalse(app.briefing_due(cfg, at(13, 59))[0])  # 06:59 PDT
        self.assertEqual(app.briefing_due(cfg, at(14, 0)), (True, "2026-10-10"))  # 07:00 PDT
        self.assertTrue(app.briefing_due(cfg, at(16, 30))[0])   # late run still sends
        self.assertFalse(app.briefing_due(cfg, at(17, 0))[0])   # 10:00 PDT, window closed


if __name__ == "__main__":
    unittest.main()
