"""Fetch and parse source feeds (RSS, Atom, RDF, USGS GeoJSON, GDELT) using only the standard library."""
import email.utils
import hashlib
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = "GlobalHQ/0.1 (+news aggregation prototype)"
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def parse_date(s):
    if not s:
        return datetime.now(timezone.utc)
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el, *names):
    for n in names:
        c = _child(el, n)
        if c is not None:
            if n == "link" and c.get("href"):
                return c.get("href")
            if c.text:
                return c.text
    return ""


def item_id(url, title):
    return hashlib.sha1((url or title).encode()).hexdigest()[:16]


def parse_xml(raw, source):
    root = ET.fromstring(raw)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    out = []
    for e in entries:
        title = clean(_text(e, "title"))
        if not title:
            continue
        url = _text(e, "link", "guid", "id").strip()
        out.append({
            "id": item_id(url, title),
            "source_id": source["id"],
            "title": title,
            "summary": clean(_text(e, "description", "summary", "content"))[:600],
            "url": url,
            "published": parse_date(_text(e, "pubDate", "published", "updated", "date")).isoformat(),
        })
    return out


def parse_usgs(raw, source):
    out = []
    for f in json.loads(raw).get("features", []):
        p = f["properties"]
        ts = datetime.fromtimestamp(p["time"] / 1000, timezone.utc)
        title = f"M{p.get('mag')} earthquake - {p.get('place')}"
        out.append({
            "id": item_id(p.get("url"), title), "source_id": source["id"], "title": title,
            "summary": f"Tsunami flag: {p.get('tsunami')}. PAGER alert: {p.get('alert') or 'none'}. Felt reports: {p.get('felt') or 0}.",
            "url": p.get("url"), "published": ts.isoformat(), "magnitude": p.get("mag"),
            "pager": p.get("alert"),
        })
    return out


def parse_gdelt(raw, source):
    out = []
    for a in json.loads(raw or b"{}").get("articles", []):
        out.append({
            "id": item_id(a.get("url"), a.get("title", "")), "source_id": source["id"],
            "title": clean(a.get("title")), "summary": a.get("domain", ""), "url": a.get("url"),
            "published": parse_date(a.get("seendate", "").replace(" ", "")).isoformat(),
        })
    return out


PARSERS = {"rss": parse_xml, "atom": parse_xml, "geojson": parse_usgs, "gdelt": parse_gdelt}


def pull(source, fetcher=fetch):
    """Return (items, error). Never raises, so one bad feed cannot stop the cycle."""
    try:
        return PARSERS[source["kind"]](fetcher(source["url"]), source), None
    except Exception as e:  # noqa: BLE001 - report and continue
        return [], f"{type(e).__name__}: {e}"
