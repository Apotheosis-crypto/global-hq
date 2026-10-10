"""SQLite storage for raw items, clustered events, and sent notifications."""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, source_id TEXT, title TEXT, summary TEXT, url TEXT,
  published TEXT, extra TEXT, event_id TEXT, verified INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, headline TEXT, category TEXT, region TEXT, score INTEGER,
  sources INTEGER, tier1 INTEGER, first_seen TEXT, last_seen TEXT, reasons TEXT,
  alerted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sent (kind TEXT, key TEXT, at TEXT, PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS health (source_id TEXT PRIMARY KEY, ok INTEGER, error TEXT, at TEXT, count INTEGER);
"""


def connect(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def save_items(db, items, verified):
    new = 0
    for it in items:
        extra = {k: v for k, v in it.items() if k not in ("id", "source_id", "title", "summary", "url", "published")}
        cur = db.execute(
            "INSERT OR IGNORE INTO items (id, source_id, title, summary, url, published, extra, verified) VALUES (?,?,?,?,?,?,?,?)",
            (it["id"], it["source_id"], it["title"], it["summary"], it["url"], it["published"], json.dumps(extra), int(verified)),
        )
        new += cur.rowcount
    db.commit()
    return new


def record_health(db, source_id, error, count, at):
    db.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)", (source_id, int(error is None), error, at, count))
    db.commit()


def mark_sent(db, kind, key, at):
    try:
        db.execute("INSERT INTO sent VALUES (?,?,?)", (kind, key, at))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False
