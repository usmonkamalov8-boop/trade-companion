"""Persistent memory for the AI Assistant tab: full chat transcripts (so a conversation survives an app
restart, not just a tab switch - the Flutter nav shell already keeps the Assistant tab's widget state
alive across tab switches via IndexedStack, so the real gap was surviving a restart, not the tabs) and
short user-stated notes/preferences.

Notes are captured ONLY when the person's own wording explicitly asks to be remembered (a fixed phrase
list in maybe_capture_note below) - never by guessing which messages "sound important", which would be
unreliable and risks silently turning an offhand remark into a standing fact fed back into every future
reply.

Same connection pattern as journal.py: a small sqlite file under config.BASE, opened per-call, so it
survives service restarts and lives alongside the other app databases."""
import sqlite3
import time

from . import config as C

DB = C.BASE / "assistant_memory.db"
MAX_MESSAGES = 800   # keeps the table bounded; recent_messages() only ever asks for a small slice anyway

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_notes_ts ON notes(ts);
"""


class _Conn:
    def __enter__(self):
        self.c = sqlite3.connect(DB, timeout=15)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)
        return self.c

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.c.commit()
        else:
            self.c.rollback()
        self.c.close()


def _db():
    return _Conn()


def log_message(role, content):
    """Best-effort append. Never raises - a memory-write failure should not break a chat reply."""
    if not content or not content.strip():
        return
    try:
        with _db() as c:
            c.execute("INSERT INTO messages (ts, role, content) VALUES (?, ?, ?)",
                      (int(time.time()), role, content[:8000]))
            n = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            if n > MAX_MESSAGES:
                c.execute("DELETE FROM messages WHERE id IN "
                          "(SELECT id FROM messages ORDER BY id ASC LIMIT ?)", (n - MAX_MESSAGES,))
    except Exception:
        pass


def recent_messages(limit=40):
    """Oldest-first slice of the most recent `limit` messages, in the {"role", "content"} shape the
    Flutter app already uses locally - so the app can simply prepend these to its in-memory list on
    startup instead of opening on an empty conversation."""
    try:
        with _db() as c:
            rows = c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception:
        return []


def clear_messages():
    try:
        with _db() as c:
            c.execute("DELETE FROM messages")
        return True
    except Exception:
        return False


_NOTE_TRIGGERS = (
    "remember that", "remember this", "please remember", "remember i", "remember my",
    "don't forget", "do not forget", "note that", "please note", "keep in mind",
    "from now on", "always ", "never ",
)


def maybe_capture_note(text):
    """Stores a short user-stated preference/note ONLY when the person's own wording explicitly asks to
    be remembered (the fixed phrase list above) - never by parsing every message for anything that
    "sounds important". Returns True if a note was captured."""
    if not text:
        return False
    low = text.strip().lower()
    if not any(low.startswith(t) or f" {t}" in low for t in _NOTE_TRIGGERS):
        return False
    try:
        with _db() as c:
            c.execute("INSERT INTO notes (ts, text) VALUES (?, ?)", (int(time.time()), text.strip()[:500]))
        return True
    except Exception:
        return False


def notes_text(limit=8):
    """Short joined block of the most recent stored notes, for background-context injection - same role
    as engine._quick_state_summary()'s position/status lines, just for standing user preferences instead
    of live account state."""
    try:
        with _db() as c:
            rows = c.execute("SELECT text FROM notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            return None
        return "\n".join(f"- {r['text']}" for r in reversed(rows))
    except Exception:
        return None
