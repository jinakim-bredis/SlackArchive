import sqlite3
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
conn = sqlite3.connect("slack_archive.db")

def ts2str(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=KST).strftime("%Y-%m-%d %H:%M")
    except:
        return ts

# 1. DB 전체 최신 메시지
print("=== DB 전체 최신 메시지 top 10 ===")
rows = conn.execute("SELECT ts, channel_id, user_name, text FROM messages ORDER BY ts DESC LIMIT 10").fetchall()
for r in rows:
    ch = conn.execute("SELECT name FROM channels WHERE id=?", (r[1],)).fetchone()
    cname = ch[0] if ch else r[1]
    print(f"  {ts2str(r[0])}  [{cname}]  {r[2]}: {r[3][:50]}")

print()

# 2. hhwang DM 확인
print("=== hhwang DM 채널 ===")
dms = conn.execute("SELECT id, name FROM channels WHERE name LIKE '%hwang%' OR name LIKE '%hhwang%'").fetchall()
for dm in dms:
    print(f"  id={dm[0]}  name={dm[1]}")
    rows = conn.execute(
        "SELECT ts, user_name, text, is_root, thread_ts FROM messages WHERE channel_id=? ORDER BY ts DESC LIMIT 5",
        (dm[0],)
    ).fetchall()
    for r in rows:
        print(f"    {ts2str(r[0])}  is_root={r[2]}  user={r[1]}: {r[2][:40] if r[2] else ''}")

print()

# 3. thread_broadcast 확인 (슬랙 채널에 업데이트 기능)
print("=== thread_broadcast 서브타입 메시지 수 ===")
# init_db.py의 SKIP_SUBTYPES에 thread_broadcast가 없지만, is_root 판별이 잘못됐을 수 있음
# thread_broadcast는 thread_ts != ts 이지만 채널에도 보여야 하는 메시지
rows = conn.execute("""
    SELECT COUNT(*) FROM messages
    WHERE thread_ts IS NOT NULL AND ts != thread_ts AND is_root = 0
""").fetchone()
print(f"  reply 메시지 수 (is_root=0): {rows[0]}")

# 4. 오늘(2026-03-02) 메시지 있는지 확인
print()
print("=== 2026-03-02 메시지 ===")
# 2026-03-02 KST = 2026-03-01 15:00 UTC = 1772496000
start = 1772496000  # 2026-03-02 00:00 KST
end   = 1772582400  # 2026-03-03 00:00 KST
rows = conn.execute(
    "SELECT ts, channel_id, user_name, text FROM messages WHERE CAST(ts AS REAL) >= ? AND CAST(ts AS REAL) < ? LIMIT 20",
    (start, end)
).fetchall()
if rows:
    for r in rows:
        ch = conn.execute("SELECT name FROM channels WHERE id=?", (r[1],)).fetchone()
        cname = ch[0] if ch else r[1]
        print(f"  {ts2str(r[0])}  [{cname}]  {r[2]}: {r[3][:50]}")
else:
    print("  없음 (ZIP 내 2026-03-02 데이터가 없음)")

conn.close()
