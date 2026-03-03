"""
fix_db.py — 기존 DB를 재처리 없이 두 가지 수정
1. thread_broadcast 메시지를 is_root=1로 업데이트 (채널에 업데이트 기능)
2. DM 채널의 thread_reply도 메인 뷰에서 보이도록 is_root=1로 업데이트

Usage:
    python fix_db.py ../backup/slack_export.zip
"""
import sys, json, zipfile, sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = "slack_archive.db"
KST = timezone(timedelta(hours=9))

def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "../backup/slack_export.zip"

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # DM 채널 ID 목록
    dm_ids = set(
        r[0] for r in conn.execute("SELECT id FROM channels WHERE type='dm'").fetchall()
    )
    print(f"DM 채널 수: {len(dm_ids)}")

    # Fix 1: thread_broadcast — ZIP을 스캔해서 해당 ts를 is_root=1로
    print("Fix 1: thread_broadcast 메시지 스캔 중...")
    broadcast_ts = set()
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            # 채널 일별 파일만 (users.json 등 제외)
            parts = name.split("/")
            if len(parts) != 2:
                continue
            try:
                with zf.open(name) as f:
                    msgs = json.load(f)
                for m in msgs:
                    if m.get("subtype") == "thread_broadcast" and m.get("ts"):
                        broadcast_ts.add(m["ts"])
            except Exception:
                continue

    print(f"  thread_broadcast 메시지 수: {len(broadcast_ts)}")
    if broadcast_ts:
        updated = 0
        for ts in broadcast_ts:
            cur = conn.execute(
                "UPDATE messages SET is_root=1 WHERE ts=? AND is_root=0",
                (ts,)
            )
            updated += cur.rowcount
        print(f"  is_root=1 로 업데이트: {updated}개")

    # Fix 2: DM 채널의 thread reply → is_root=1
    # (DM에서 스레드 답글도 메인 뷰에 표시)
    print("Fix 2: DM 채널 thread reply를 is_root=1로 업데이트...")
    if dm_ids:
        placeholders = ",".join("?" * len(dm_ids))
        cur = conn.execute(
            f"UPDATE messages SET is_root=1 WHERE channel_id IN ({placeholders}) AND is_root=0",
            list(dm_ids)
        )
        print(f"  DM reply 업데이트: {cur.rowcount}개")

    conn.commit()

    # FTS 재빌드
    print("FTS5 인덱스 재빌드...")
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    print("완료!")

if __name__ == "__main__":
    main()
