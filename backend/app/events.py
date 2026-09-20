"""Activity log shared by the API, the watcher and the bot (through bot_gate.event)."""
import sqlite3, time
from . import config as C

DB = C.BASE / "events.db"
SCHEMA = ("CREATE TABLE IF NOT EXISTS events ("
          "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, level TEXT, title TEXT, text TEXT)")
KEEP = 3000


def _con():
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def add(kind, title, text="", level="info"):
    """kind: position | trade | command | risk | profile | service | system | warning
    level: info | success | warning | error"""
    con = _con()
    try:
        con.execute("INSERT INTO events (ts, kind, level, title, text) VALUES (?,?,?,?,?)",
                    (time.time(), kind, level, title, text))
        con.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (KEEP,))
        con.commit()
    finally:
        con.close()


def _fetch(sql, args=()):
    con = _con()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def latest(limit=200):
    return _fetch("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))[::-1]


def since(last_id, limit=100):
    return _fetch("SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?", (last_id, limit))


def last_id():
    rows = _fetch("SELECT COALESCE(MAX(id), 0) AS m FROM events")
    return int(rows[0]["m"])
