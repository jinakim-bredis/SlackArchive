"""SQLite helper — connection management and common queries."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "slack_archive.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def db_ready() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = get_conn()
        conn.execute("SELECT 1 FROM messages LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False
