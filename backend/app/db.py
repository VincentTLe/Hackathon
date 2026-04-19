import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from app.config import settings

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS founders (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  communication_profile TEXT NOT NULL,
  receiver_seed_profile TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  founder_id TEXT NOT NULL REFERENCES founders(id),
  receiver_display_name TEXT NOT NULL,
  relationship TEXT NOT NULL,
  invite_note TEXT DEFAULT '',
  magic_link_token TEXT NOT NULL UNIQUE,
  magic_link_expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  accepted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_connections_founder ON connections(founder_id);

CREATE TABLE IF NOT EXISTS receivers (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL UNIQUE REFERENCES connections(id),
  display_name TEXT NOT NULL,
  session_token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_previews (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES connections(id),
  sender_role TEXT NOT NULL CHECK(sender_role IN ('founder','receiver')),
  sender_id TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  translated_content TEXT NOT NULL,
  emotional_interpretation TEXT DEFAULT '',
  educational_context TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES connections(id),
  sender_role TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  translated_content TEXT NOT NULL,
  emotional_interpretation TEXT DEFAULT '',
  educational_context TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conn ON messages(connection_id, created_at);

CREATE TABLE IF NOT EXISTS conversation_memory (
  connection_id TEXT PRIMARY KEY REFERENCES connections(id),
  summary TEXT NOT NULL DEFAULT '',
  key_themes TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    path = settings.resolved_database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        _conn.executescript(SCHEMA)


def get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
            _conn.executescript(SCHEMA)
        return _conn


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_conn()
    with _lock:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
