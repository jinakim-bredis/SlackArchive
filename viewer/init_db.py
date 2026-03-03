"""
init_db.py — slack_export.zip → SQLite

Usage:
    python init_db.py ../backup/slack_export.zip

Creates slack_archive.db in the same directory as this script.
Safe to re-run: drops and recreates all tables.
"""
import sys
import json
import zipfile
import sqlite3
import os
from pathlib import PurePosixPath

DB_PATH = os.path.join(os.path.dirname(__file__), "slack_archive.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    type     TEXT NOT NULL,
    archived INTEGER DEFAULT 0,
    topic    TEXT,
    purpose  TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    display_name TEXT,
    real_name    TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    ts            TEXT PRIMARY KEY,
    channel_id    TEXT NOT NULL,
    thread_ts     TEXT,
    is_root       INTEGER DEFAULT 0,
    user_id       TEXT,
    user_name     TEXT,
    text          TEXT,
    timestamp_str TEXT,
    reply_count   INTEGER DEFAULT 0,
    reactions     TEXT,
    files         TEXT,
    is_broadcast  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_thread  ON messages(thread_ts);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, user_name,
    content=messages, content_rowid=rowid
);
"""

SKIP_SUBTYPES = {
    "channel_join", "channel_leave", "channel_archive",
    "channel_unarchive", "channel_name", "channel_purpose",
    "channel_topic", "bot_add", "bot_remove",
    "group_join", "group_leave",
}


def drop_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS messages_fts;
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS channels;
        DROP TABLE IF EXISTS users;
    """)


def load_json_from_zip(zf: zipfile.ZipFile, name: str):
    """Load a JSON file from the ZIP by name (returns [] if not found)."""
    try:
        with zf.open(name) as f:
            return json.load(f)
    except KeyError:
        return []
    except json.JSONDecodeError:
        print(f"  [WARN] JSON parse error: {name}")
        return []


def ingest_users(zf: zipfile.ZipFile, conn: sqlite3.Connection) -> dict:
    """Insert users; return id→display_name map."""
    users = load_json_from_zip(zf, "users.json")
    user_map = {}
    rows = []
    for u in users:
        uid = u.get("id", "")
        profile = u.get("profile", {})
        display = profile.get("display_name") or profile.get("real_name") or u.get("name", uid)
        real = profile.get("real_name", "")
        rows.append((uid, u.get("name", ""), display, real))
        user_map[uid] = display
    conn.executemany(
        "INSERT OR REPLACE INTO users VALUES (?,?,?,?)", rows
    )
    print(f"  Users: {len(rows)}")
    return user_map


def ingest_channels(zf: zipfile.ZipFile, conn: sqlite3.Connection, user_map: dict) -> list[dict]:
    """Insert all channel types; return list of channel dicts with 'folder_name'."""
    channel_list = []

    def _add(items, ch_type, folder_attr="name"):
        for item in items:
            cid = item.get("id", "")
            raw_name = item.get(folder_attr, "") or cid

            # For DMs: use the other user's name as display name
            if ch_type == "dm":
                members = item.get("members", [])
                names = [user_map.get(m, m) for m in members if m]
                display_name = " & ".join(names) if names else cid
                folder_name = item.get("id", "")
            elif ch_type == "group_dm":
                members = item.get("members", [])
                names = [user_map.get(m, m) for m in members if m]
                display_name = ", ".join(names) if names else raw_name
                folder_name = raw_name  # ZIP에서 mpim은 name(mpdm-...)으로 폴더가 생성됨
            else:
                display_name = raw_name
                folder_name = raw_name

            topic = ""
            purpose = ""
            if isinstance(item.get("topic"), dict):
                topic = item["topic"].get("value", "")
            if isinstance(item.get("purpose"), dict):
                purpose = item["purpose"].get("value", "")

            archived = 1 if item.get("is_archived") else 0

            conn.execute(
                "INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?)",
                (cid, display_name, ch_type, archived, topic, purpose),
            )
            channel_list.append({
                "id": cid,
                "name": display_name,
                "folder_name": folder_name,
                "type": ch_type,
            })

    _add(load_json_from_zip(zf, "channels.json"), "public")
    _add(load_json_from_zip(zf, "groups.json"), "private")
    _add(load_json_from_zip(zf, "mpims.json"), "group_dm")
    _add(load_json_from_zip(zf, "dms.json"), "dm")

    print(f"  Channels: {len(channel_list)}")
    return channel_list


def parse_reactions(msg: dict) -> str | None:
    reactions = msg.get("reactions")
    if not reactions:
        return None
    simplified = [{"name": r.get("name", ""), "count": r.get("count", 0)} for r in reactions]
    return json.dumps(simplified, ensure_ascii=False)


def parse_files(msg: dict) -> str | None:
    files = msg.get("files")
    if not files:
        return None
    simplified = [
        {
            "name": f.get("name", ""),
            "size": f.get("size", 0),
            "mimetype": f.get("mimetype", ""),
        }
        for f in files
    ]
    return json.dumps(simplified, ensure_ascii=False)


def ingest_messages(
    zf: zipfile.ZipFile,
    conn: sqlite3.Connection,
    channels: list[dict],
    user_map: dict,
) -> int:
    """Insert messages for all channels. Returns total message count."""
    # Build set of all zip entry names for fast lookup
    zip_names = set(zf.namelist())
    total = 0

    for ch in channels:
        folder = ch["folder_name"]
        cid = ch["id"]
        ch_type = ch["type"]

        # Collect all YYYY-MM-DD.json files for this channel folder
        prefix = folder + "/"
        day_files = sorted(
            n for n in zip_names
            if n.startswith(prefix) and n.endswith(".json")
        )

        if not day_files:
            continue

        batch = []
        for day_file in day_files:
            try:
                with zf.open(day_file) as f:
                    messages = json.load(f)
            except Exception:
                continue

            for msg in messages:
                subtype = msg.get("subtype", "")
                if subtype in SKIP_SUBTYPES:
                    continue

                ts = msg.get("ts", "")
                if not ts:
                    continue

                thread_ts = msg.get("thread_ts")
                if subtype == "thread_broadcast":
                    # "채널에 업데이트" 기능: 스레드 답글이지만 채널 타임라인에도 표시
                    is_root = 1
                elif thread_ts:
                    is_root = 1 if ts == thread_ts else 0
                else:
                    is_root = 1  # standalone

                uid = msg.get("user") or msg.get("bot_id") or ""
                user_name = user_map.get(uid, uid)

                reply_count = msg.get("reply_count", 0)
                is_broadcast = 1 if subtype == "thread_broadcast" else 0

                batch.append((
                    ts,
                    cid,
                    thread_ts,
                    is_root,
                    uid,
                    user_name,
                    msg.get("text", ""),
                    "",  # timestamp_str: generated at query time
                    reply_count,
                    parse_reactions(msg),
                    parse_files(msg),
                    is_broadcast,
                ))

        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            total += len(batch)

        print(f"  [{ch_type:8}] {ch['name'][:40]:<40} {len(batch):>6} msgs")

    return total


def build_fts(conn: sqlite3.Connection) -> None:
    print("  Building FTS5 index...")
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="slack_export.zip → SQLite")
    parser.add_argument("zip_path", help="Path to slack export ZIP file")
    parser.add_argument(
        "--merge", action="store_true",
        help="Merge into existing DB (skip drop; upsert only). Use for incremental ZIPs."
    )
    args = parser.parse_args()

    zip_path = args.zip_path
    if not os.path.exists(zip_path):
        print(f"Error: file not found: {zip_path}")
        sys.exit(1)

    print(f"Opening: {zip_path}")
    print(f"Database: {DB_PATH}")
    print(f"Mode: {'merge (incremental)' if args.merge else 'full rebuild'}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB page cache

    if not args.merge:
        print("Dropping existing tables...")
        drop_tables(conn)
    conn.executescript(SCHEMA)

    with zipfile.ZipFile(zip_path, "r") as zf:
        print("Ingesting users...")
        user_map = ingest_users(zf, conn)
        conn.commit()

        print("Ingesting channels...")
        channels = ingest_channels(zf, conn, user_map)
        conn.commit()

        print("Ingesting messages...")
        total = ingest_messages(zf, conn, channels, user_map)
        conn.commit()

    print("Building FTS5 index...")
    build_fts(conn)
    conn.commit()
    conn.close()

    print(f"\nDone. Total messages ingested: {total:,}")
    print(f"Database size: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
