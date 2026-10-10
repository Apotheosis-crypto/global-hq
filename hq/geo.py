"""Place events on the map: exact coordinates from hazard feeds, otherwise the country named in the reports."""
import json
import re
from pathlib import Path

CENTROIDS = json.loads((Path(__file__).parent / "geo.json").read_text())
CENTROIDS.update({  # vertex-mean centroids that land in the wrong place
    "Russia": [60.0, 95.0], "United States of America": [39.0, -98.0], "Canada": [58.0, -100.0],
    "Fiji": [-17.8, 178.0], "Chile": [-33.0, -71.0], "Norway": [61.0, 9.0], "Indonesia": [-2.0, 118.0],
    "Antarctica": [-80.0, 0.0],
})

# Words that point at a country without naming it the way world-atlas does.
ALIASES = {
    "United States of America": "united states|usa|american|americans|washington|white house|pentagon|trump|florida|texas|california",
    "United Kingdom": "uk|britain|british|london|downing street",
    "Russia": "russian|moscow|kremlin|putin",
    "Ukraine": "ukrainian|kyiv|kharkiv|odesa|zelensky",
    "China": "chinese|beijing|xi jinping",
    "Taiwan": "taipei|taiwanese",
    "Palestine": "gaza|west bank|palestinian|palestinians|hamas",
    "Israel": "israeli|jerusalem|tel aviv|netanyahu",
    "Iran": "iranian|tehran",
    "Lebanon": "lebanese|beirut|hezbollah",
    "Yemen": "yemeni|houthi|houthis|sanaa",
    "Saudi Arabia": "saudi|saudis|riyadh",
    "Syria": "syrian|damascus",
    "Sudan": "sudanese|darfur|khartoum",
    "S. Sudan": "south sudan",
    "Dem. Rep. Congo": "drc|dr congo|democratic republic of congo|kinshasa|goma",
    "North Korea": "pyongyang|north korean",
    "South Korea": "seoul|south korean",
    "Japan": "japanese|tokyo",
    "India": "indian|new delhi",
    "Pakistan": "pakistani|islamabad",
    "Afghanistan": "afghan|kabul|taliban",
    "Turkey": "turkish|ankara|erdogan|türkiye",
    "Ethiopia": "ethiopian|addis ababa",
    "Eritrea": "eritrean",
    "Somalia": "somali|mogadishu|al-shabaab",
    "Venezuela": "venezuelan|caracas|maduro",
    "Mexico": "mexican",
    "Brazil": "brazilian",
    "France": "french|paris|macron",
    "Germany": "german|berlin",
    "Belgium": "brussels",
    "Australia": "australian|macquarie",
    "Haiti": "haitian|port-au-prince",
    "Myanmar": "burma|burmese",
    "Philippines": "philippine|filipino|manila",
    "United Arab Emirates": "uae|emirati|dubai|abu dhabi",
    "Nigeria": "nigerian",
    "Egypt": "egyptian|cairo",
    "Iraq": "iraqi|baghdad",
    "Cuba": "cuban|havana",
    "Nepal": "nepalese|kathmandu",
    "Kenya": "kenyan|nairobi",
}

PATTERNS = []
for name in CENTROIDS:
    words = [re.escape(name.lower())] + ALIASES.get(name, "").split("|")
    words = [w for w in words if w]
    PATTERNS.append((name, re.compile(r"(?<![\w.])(" + "|".join(sorted(words, key=len, reverse=True)) + r")(?![\w])", re.I)))
# Names like "Niger" must not match inside "Nigeria"; the lookarounds above handle that.
US_ABBR = re.compile(r"(?<![\w.])U\.?S\.?(?![\w])")  # case-sensitive, so the pronoun "us" doesn't count


def locate(headline, text, extras=()):
    """Return {lat, lon, place} or None. Headline mentions outweigh body mentions."""
    for ex in extras:
        if ex.get("lat") is not None and ex.get("lon") is not None:
            return {"lat": ex["lat"], "lon": ex["lon"], "place": ex.get("place") or "", "exact": True}
    best, best_score = None, 0
    for name, pat in PATTERNS:
        score = 3 * len(pat.findall(headline)) + len(pat.findall(text))
        if name == "United States of America":
            score += 3 * len(US_ABBR.findall(headline)) + len(US_ABBR.findall(text))
        if score > best_score:
            best, best_score = name, score
    if not best:
        return None
    lat, lon = CENTROIDS[best]
    return {"lat": lat, "lon": lon, "place": best.replace("United States of America", "United States"), "exact": False}
