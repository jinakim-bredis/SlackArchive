"""
migrate_broadcast.py — messages 테이블에 is_broadcast 컬럼 추가 후 ZIP에서 값 채우기

Usage:
    python migrate_broadcast.py ../backup/slack_export.zip
"""
import sys, json, zipfile, sqlite3

DB_PATH = "slack_archive.db"

def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "../backup/slack_export.zip"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # 컬럼 없으면 추가
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "is_broadcast" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN is_broadcast INTEGER DEFAULT 0")
        conn.commit()
        print("is_broadcast 컬럼 추가 완료")
    else:
        print("is_broadcast 컬럼 이미 존재")

    # ZIP 스캔 → thread_broadcast ts 수집
    print("ZIP 스캔 중...")
    broadcast_ts = set()
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
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

    # 배치 업데이트
    updated = 0
    batch = list(broadcast_ts)
    for i in range(0, len(batch), 500):
        chunk = batch[i:i+500]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"UPDATE messages SET is_broadcast=1 WHERE ts IN ({ph})",
            chunk
        )
        updated += cur.rowcount
    conn.commit()
    print(f"  is_broadcast=1 업데이트: {updated}개")

    conn.close()
    print("완료!")

if __name__ == "__main__":
    main()
