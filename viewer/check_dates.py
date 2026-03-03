import sqlite3
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))

conn = sqlite3.connect("slack_archive.db")
channels = conn.execute(
    "SELECT id, name, type FROM channels WHERE name LIKE '%daily%' OR name LIKE '%general%' OR name LIKE '%test_service%' ORDER BY name"
).fetchall()

for ch in channels:
    cid, cname = ch[0], ch[1]
    row = conn.execute(
        "SELECT MIN(ts), MAX(ts), COUNT(*), COUNT(CASE WHEN is_root=1 THEN 1 END) FROM messages WHERE channel_id=?",
        (cid,)
    ).fetchone()
    if row and row[1]:
        oldest = datetime.fromtimestamp(float(row[0]), tz=KST).strftime("%Y-%m-%d")
        newest = datetime.fromtimestamp(float(row[1]), tz=KST).strftime("%Y-%m-%d")
        print("name=%s  total=%d  root=%d  oldest=%s  newest=%s" % (cname, row[2], row[3], oldest, newest))
    else:
        print("name=%s  NO MESSAGES" % cname)

conn.close()
