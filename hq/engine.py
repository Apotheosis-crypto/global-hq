"""Cluster items into events and score how globally significant each event is.

Rules of evidence:
  * Only items from verified sources (sources.json "sources") count as evidence.
  * Discovery items (GDELT whole-web scan) can raise attention on an event that
    verified sources already report, but can never create or confirm one.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone

STOP = set("""a an the of to in on for and or but with by at from as is are was were be been has have had
it its this that these those after over into amid says said say new news live latest update updates
more than up out about how why what who will would could may can not no he she they we you his her their
our us un uk eu
green orange red magnitude depth utc notification alert unknown report reports""".split())  # incl. GDACS boilerplate

# (category, weight, patterns). The highest-weighted match decides the category.
SIGNALS = [
    ("Nuclear / WMD", 55, r"\bnuclear (test|strike|attack|weapon)|chemical weapon|radiation leak|dirty bomb"),
    ("Conflict",      50, r"\bcoup\b|assassinat|declares? war|invasion|invades?|martial law"),
    ("Conflict",      40, r"airstrike|air strike|missile|shelling|offensive|bombing|drone strike|troops|ceasefire (collapse|violat)"),
    ("Conflict",      30, r"\battack|\bclashes?\b|militants?|insurgen|hostages?|terror|\bwar\b|violence|riots?|looted"),
    ("Disaster",      35, r"earthquake|tsunami|cyclone|hurricane|typhoon|volcan|flood|wildfire|landslide|famine"),
    ("Health",        40, r"pandemic|public health emergency|pheic|outbreak|epidemic|ebola|cholera|mpox|h5n1"),
    ("Diplomacy",     30, r"security council|ceasefire|peace (deal|talks|agreement)|treaty|sanctions|summit|expel+s? (diplomat|ambassador)"),
    ("Politics",      25, r"state of emergency|resigns?|ousted|election (result|fraud)|protests?|unrest|impeach"),
    ("Economy",       25, r"default|currency (crash|collapse)|market crash|oil price|tariffs?|recession|central bank"),
    ("Humanitarian",  30, r"refugees?|displaced|humanitarian (crisis|aid)|starvation|aid convoy"),
]
CASUALTY = re.compile(r"(\d[\d,]*)\s+(?:people\s+)?(?:killed|dead|deaths|died|casualties)|(?:killed|kills|killing)\s+(?:at least\s+)?(\d[\d,]*)", re.I)

REGIONS = {
    "Europe": "ukraine ukrainian russia russian france french germany german poland polish britain british italy spain nato kyiv moscow serbia kosovo moldova belarus georgia",
    "Middle East": "israel israeli gaza palestinian iran iranian iraq syria syrian lebanon yemen saudi riyadh qatar turkey jordan houthi houthis hezbollah hamas tehran oman uae emirates kuwait bahrain",
    "Asia": "china chinese taiwan japan japanese korea korean india indian pakistan afghanistan myanmar philippines indonesia vietnam bangladesh beijing nepal thailand malaysia cambodia mongolia kazakhstan",
    "Africa": "africa african sudan sudanese darfur ethiopia ethiopian eritrea somalia nigeria congo drc kenya sahel mali niger libya egypt uganda tanzania rwanda chad cameroon ghana senegal mozambique zimbabwe angola algeria morocco tunisia",
    "Americas": "washington canada mexico brazil venezuela venezuelan colombia argentina haiti cuba peru chile panama guatemala honduras nicaragua ecuador bolivia jamaica florida texas california",
    "Oceania": "australia zealand papua fiji macquarie tonga samoa vanuatu solomon",
}
REGION_WORDS = {w: r for r, ws in REGIONS.items() for w in ws.split()}


def tokens(text):
    return {w for w in re.findall(r"[a-z][a-z'\-]{2,}", text.lower()) if w not in STOP}


def similar(a, b):
    shared = a & b
    if len(shared) < 2:
        return False
    return len(shared) / min(len(a), len(b)) >= 0.4


def cluster(items, distinct_sources=()):
    """Greedy single-pass clustering over items sorted oldest first.

    Items are compared with each cluster's first report only, so a cluster
    cannot snowball into unrelated stories through a chain of loose matches.
    Items from `distinct_sources` (structured hazard feeds such as USGS or
    GDACS, where every entry is a separate event) never share a cluster.
    """
    clusters = []
    for it in sorted(items, key=lambda i: i["published"]):
        tok = tokens(it["title"])
        for c in clusters:
            if it["source_id"] in distinct_sources and any(i["source_id"] == it["source_id"] for i in c["items"]):
                continue
            if similar(tok, c["tokens"]):
                c["items"].append(it)
                break
        else:
            clusters.append({"tokens": tok, "items": [it]})
    return clusters


def score(cluster_items, sources):
    verified = [i for i in cluster_items if i["verified"]]
    if not verified:
        return None
    text = " ".join(i["title"] + " " + (i["summary"] or "") for i in verified)
    reasons, base, category = [], 0, "General"
    for cat, w, pat in SIGNALS:
        if re.search(pat, text, re.I) and w > base:
            base, category = w, cat
    if base:
        reasons.append(f"{category} signal (+{base})")

    casualties = max((int((m.group(1) or m.group(2)).replace(",", "")) for m in CASUALTY.finditer(text)), default=0)
    if casualties:
        bump = min(25, int(6 * math.log10(casualties + 1) + 4))
        base += bump
        reasons.append(f"{casualties}+ casualties reported (+{bump})")

    for i in verified:
        extra = json.loads(i.get("extra") or "{}")
        mag = extra.get("magnitude") or 0
        if mag >= 6:
            bump = 15 + int((mag - 6) * 20)
            base += bump
            category = "Disaster"
            reasons.append(f"M{mag} quake (+{bump})")
        if extra.get("pager") in ("orange", "red"):
            base += 25
            reasons.append(f"USGS PAGER {extra['pager']} (+25)")

    srcs = {i["source_id"] for i in verified}
    tier1 = any(sources[s]["tier"] == 1 for s in srcs if s in sources)
    corroboration = min(24, 8 * (len(srcs) - 1))
    if corroboration:
        reasons.append(f"{len(srcs)} independent verified sources (+{corroboration})")
    if tier1:
        reasons.append("official / intergovernmental source (+10)")
    web = sum(1 for i in cluster_items if not i["verified"])
    web_bump = min(10, 2 * web)
    if web_bump:
        reasons.append(f"{web} matching articles across the open web (+{web_bump})")

    words = tokens(text)
    region_votes = {}
    for w in words:
        if w in REGION_WORDS:
            region_votes[REGION_WORDS[w]] = region_votes.get(REGION_WORDS[w], 0) + 1
    region = max(region_votes, key=region_votes.get) if region_votes else sources.get(verified[0]["source_id"], {}).get("region", "Global")

    lead = next((i for i in verified if sources.get(i["source_id"], {}).get("tier") == 1), verified[0])
    return {
        "headline": lead["title"], "category": category, "region": region,
        "score": min(100, base + corroboration + (10 if tier1 else 0) + web_bump),
        "sources": len(srcs), "tier1": int(tier1), "reasons": reasons,
        "first_seen": min(i["published"] for i in verified), "last_seen": max(i["published"] for i in verified),
    }


def rebuild(db, sources, window_hours=48, now=None):
    """Recluster the recent window and upsert events, keeping alert state."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=window_hours)).isoformat()
    items = [dict(r) for r in db.execute("SELECT * FROM items WHERE published >= ?", (since,))]
    events = []
    for c in cluster(items, {sid for sid, s in sources.items() if s.get("distinct_items")}):
        ev = score(c["items"], sources)
        if ev is None:
            continue
        anchor = min((i for i in c["items"] if i["verified"]), key=lambda i: (i["published"], i["id"]))
        ev["id"] = hashlib.sha1(anchor["id"].encode()).hexdigest()[:12]
        prev = db.execute("SELECT alerted FROM events WHERE id=?", (ev["id"],)).fetchone()
        db.execute(
            "INSERT OR REPLACE INTO events (id, headline, category, region, score, sources, tier1, first_seen, last_seen, reasons, alerted) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ev["id"], ev["headline"], ev["category"], ev["region"], ev["score"], ev["sources"], ev["tier1"],
             ev["first_seen"], ev["last_seen"], json.dumps(ev["reasons"]), prev["alerted"] if prev else 0),
        )
        db.executemany("UPDATE items SET event_id=? WHERE id=?", [(ev["id"], i["id"]) for i in c["items"]])
        events.append(ev)
    db.commit()
    return events


def should_alert(ev, cfg):
    a = cfg["alerts"]
    return ev["score"] >= a["threshold"] and (ev["sources"] >= a["min_independent_sources"] or ev["tier1"])
