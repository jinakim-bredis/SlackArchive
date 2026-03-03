import sqlite3, sys
from datetime import datetime, timezone, timedelta
sys.stdout.reconfigure(encoding='utf-8')
KST = timezone(timedelta(hours=9))
conn = sqlite3.connect("slack_archive.db")

def ts2str(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=KST).strftime("%Y-%m-%d %H:%M")
    except:
        return ts

# 1. hhwang & jnkim DM (D04T33VQKCN) 최신 10개 (is_root 포함)
print("=== hhwang & jnkim DM 최신 10개 ===")
rows = conn.execute(
    "SELECT ts, user_name, is_root, thread_ts FROM messages WHERE channel_id='D04T33VQKCN' ORDER BY ts DESC LIMIT 10"
).fetchall()
for r in rows:
    flag = "ROOT" if r[2] else "REPLY"
    same = "(thread_ts=ts)" if r[3] == r[0] else f"(thread_ts={r[3][:8] if r[3] else 'NULL'}...)"
    print(f"  {ts2str(r[0])}  {flag}  {r[1]}  {same}")

print()

# 2. is_root=0 인데 채널 타임라인에서 보여야 할 subtype=thread_broadcast 비율 추정
# thread_broadcast는 thread_ts가 있고 ts!=thread_ts이지만 채널에서 보여야 함
# ZIP에서 재확인 필요 - 일단 is_root=0인 reply 중 오늘 것 확인
print("=== 오늘(2026-03-02) 전체 메시지 is_root 분포 ===")
start, end = 1772496000, 1772582400
rows = conn.execute(
    "SELECT is_root, COUNT(*) FROM messages WHERE CAST(ts AS REAL)>=? AND CAST(ts AS REAL)<? GROUP BY is_root",
    (start, end)
).fetchall()
for r in rows:
    print(f"  is_root={r[0]}: {r[1]}개")

print()

# 3. ZIP 안에 thread_broadcast 서브타입이 있는지 확인 (최근 날짜 파일로)
print("=== thread_broadcast 가 있는지 ZIP 샘플 확인 ===")
import zipfile, json, os

zip_path = "../backup/slack_export.zip"
with zipfile.ZipFile(zip_path) as zf:
    names = zf.namelist()
    # 2026-03 파일만
    recent = [n for n in names if "2026-03" in n or "2026-02" in n]
    print(f"  2026-02~03 파일 수: {len(recent)}")

    broadcast_count = 0
    sample = []
    for fname in recent[:30]:
        try:
            with zf.open(fname) as f:
                msgs = json.load(f)
            for m in msgs:
                if m.get("subtype") == "thread_broadcast":
                    broadcast_count += 1
                    if len(sample) < 3:
                        sample.append((fname, m.get("ts",""), m.get("text","")[:60]))
        except:
            pass
    print(f"  thread_broadcast 메시지 수 (샘플 30파일): {broadcast_count}")
    for s in sample:
        print(f"    {s[0]}  ts={s[1]}  text={s[2]}")

conn.close()
