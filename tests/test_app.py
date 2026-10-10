"""Map placement, the local server, and the static export used by GitHub Pages."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hq import app, geo, store


class Geo(unittest.TestCase):
    def test_places(self):
        cases = {
            "Coup in Niger as soldiers seize presidential palace": "Niger",
            "Nigeria floods displace thousands": "Nigeria",
            "Three Saudis killed in Riyadh airport attack claimed by Houthis": "Saudi Arabia",
            "Guterres condemns new US sanctions on International Criminal Court": "United States",
            "At least 33 killed in strikes on Ukrainian public buses": "Ukraine",
        }
        for headline, place in cases.items():
            self.assertEqual(geo.locate(headline, "")["place"], place, headline)

    def test_pronoun_us_is_not_a_country(self):
        self.assertIsNone(geo.locate("They told us nothing", ""))

    def test_exact_coordinates_win(self):
        g = geo.locate("M7.7 earthquake - Panama", "", [{"lat": 7.33, "lon": -80.52, "place": "Panama"}])
        self.assertEqual((g["lat"], g["lon"], g["exact"]), (7.33, -80.52, True))


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.src = app.load("/nonexistent")
        cls.db = store.connect(":memory:")
        app.seed_sample(cls.db, cls.src)

    def test_sample_events_are_placed_and_flagged(self):
        events, health = app.api_payloads(self.db, self.cfg, app.source_index(self.src))
        top = events["events"][0]
        self.assertIn("Panama", top["headline"])
        self.assertTrue(top["alerted"])
        self.assertTrue(top["geo"]["exact"])
        self.assertGreater(sum(1 for e in events["events"] if e["geo"]), 15)
        self.assertTrue(events["generated_at"])

    def test_export_includes_map(self):
        with tempfile.TemporaryDirectory() as d:
            app.export(self.db, self.cfg, self.src, d)
            for f in ("index.html", "static/worldmap.js", "api/events.json", "api/health.json", "briefing/index.html"):
                self.assertTrue((Path(d) / f).is_file(), f)

    def test_local_server(self):
        cfg = dict(self.cfg, port=8197)
        threading.Thread(target=app.serve, args=(self.db, cfg, self.src), daemon=True).start()
        get = lambda p: urllib.request.urlopen(f"http://127.0.0.1:8197{p}", timeout=5)
        for _ in range(50):
            try:
                get("/")
                break
            except OSError:
                threading.Event().wait(0.1)
        self.assertIn(b"WORLD", get("/static/worldmap.js").read(200))
        self.assertTrue(json.loads(get("/api/events.json").read())["events"])
        with self.assertRaises(urllib.error.HTTPError):
            get("/static/../app.py")


if __name__ == "__main__":
    unittest.main()
