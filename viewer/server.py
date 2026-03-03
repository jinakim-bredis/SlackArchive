"""
server.py — FastAPI backend for Slack Archive Viewer

Run:
    python server.py
Then open: http://localhost:8000
"""
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from db import get_conn, db_ready, DB_PATH
import os

app = FastAPI(title="Slack Archive Viewer")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── static files ───────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── helpers ────────────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))


def ts_to_str(ts: str) -> str:
    try:
        dt = datetime.fromtimestamp(float(ts), tz=KST)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def row_to_msg(row) -> dict:
    d = dict(row)
    d["timestamp_str"] = ts_to_str(d.get("ts", ""))
    if d.get("reactions"):
        try:
            d["reactions"] = json.loads(d["reactions"])
        except Exception:
            d["reactions"] = []
    if d.get("files"):
        try:
            d["files"] = json.loads(d["files"])
        except Exception:
            d["files"] = []
    return d


def require_db():
    if not db_ready():
        raise HTTPException(
            status_code=503,
            detail="Database not ready. Run: python init_db.py <slack_export.zip>",
        )


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    ready = db_ready()
    size_mb = 0.0
    if ready and os.path.exists(DB_PATH):
        size_mb = round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)
    return {"ready": ready, "db_size_mb": size_mb}


@app.get("/api/channels")
def get_channels():
    require_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, type, archived, topic, purpose FROM channels ORDER BY type, name"
    ).fetchall()
    conn.close()

    grouped = {"public": [], "private": [], "group_dm": [], "dm": []}
    for r in rows:
        d = dict(r)
        grouped.setdefault(d["type"], []).append(d)
    return grouped


@app.get("/api/channels/{channel_id}/messages")
def get_channel_messages(
    channel_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    require_db()
    conn = get_conn()

    # Verify channel exists
    ch = conn.execute("SELECT id, name FROM channels WHERE id=?", (channel_id,)).fetchone()
    if not ch:
        conn.close()
        raise HTTPException(status_code=404, detail="Channel not found")

    total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE channel_id=? AND is_root=1",
        (channel_id,),
    ).fetchone()[0]

    offset = (page - 1) * per_page
    # DESC so page 1 = newest; reversed() restores chronological order for display
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE channel_id=? AND is_root=1
           ORDER BY ts DESC
           LIMIT ? OFFSET ?""",
        (channel_id, per_page, offset),
    ).fetchall()

    msgs_list = list(reversed([row_to_msg(r) for r in rows]))

    # Enrich thread_broadcast messages with root message preview
    # thread_broadcast: is_broadcast=1 (reply also posted to channel)
    broadcast_thread_ts = list({
        m["thread_ts"] for m in msgs_list
        if m.get("is_broadcast") and m.get("thread_ts")
    })
    if broadcast_thread_ts:
        ph = ",".join("?" * len(broadcast_thread_ts))
        root_rows = conn.execute(
            f"SELECT ts, user_name, text, reply_count FROM messages WHERE ts IN ({ph})",
            broadcast_thread_ts,
        ).fetchall()
        root_map = {r["ts"]: dict(r) for r in root_rows}
        for m in msgs_list:
            if m.get("is_broadcast") and m.get("thread_ts"):
                root = root_map.get(m["thread_ts"])
                if root:
                    m["thread_root_preview"] = {
                        "ts": root["ts"],
                        "user_name": root["user_name"] or "",
                        "text": (root["text"] or "")[:120],
                        "reply_count": root["reply_count"] or 0,
                    }

    conn.close()

    return {
        "channel_id": channel_id,
        "channel_name": ch["name"],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
        "messages": msgs_list,
    }


@app.get("/api/threads/{thread_ts}")
def get_thread(thread_ts: str):
    require_db()
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM messages
           WHERE thread_ts=?
           ORDER BY ts ASC""",
        (thread_ts,),
    ).fetchall()

    # Fallback: thread_ts로 못 찾으면 ts로 메시지를 찾아 실제 thread_ts를 사용
    if not rows:
        pivot = conn.execute(
            "SELECT * FROM messages WHERE ts=?", (thread_ts,)
        ).fetchone()
        if pivot:
            actual_ts = pivot["thread_ts"] or thread_ts
            if actual_ts != thread_ts:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE thread_ts=? ORDER BY ts ASC",
                    (actual_ts,),
                ).fetchall()
            if not rows:
                rows = [pivot]  # 최소한 해당 메시지 단독 표시

    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="Thread not found")

    return {"thread_ts": thread_ts, "messages": [row_to_msg(r) for r in rows]}


def _date_to_ts(date_str: str, end_of_day: bool = False) -> Optional[float]:
    """YYYY-MM-DD 문자열을 KST 기준 Unix timestamp로 변환."""
    try:
        from datetime import datetime as dt
        d = dt.strptime(date_str.strip(), "%Y-%m-%d")
        if end_of_day:
            d = d.replace(hour=23, minute=59, second=59)
        return d.replace(tzinfo=KST).timestamp()
    except Exception:
        return None


def _enrich_channel_info(msgs: list, conn) -> None:
    """메시지 목록에 channel_name / channel_type 필드 추가."""
    cids = list({m["channel_id"] for m in msgs if m.get("channel_id")})
    if not cids:
        return
    ph = ",".join("?" * len(cids))
    rows = conn.execute(
        f"SELECT id, name, type FROM channels WHERE id IN ({ph})", cids
    ).fetchall()
    ch_map = {r["id"]: (r["name"], r["type"]) for r in rows}
    for m in msgs:
        info = ch_map.get(m.get("channel_id"), ("", ""))
        m["channel_name"] = info[0]
        m["channel_type"] = info[1]


@app.get("/api/search")
def search(
    q: str = Query(""),
    channel_id: Optional[str] = Query(None),    # 채널 ID (직접 지정)
    channel_name: Optional[str] = Query(None),  # 채널 이름 (in:#xxx 에서 파싱)
    from_user: Optional[str] = Query(None),     # 발신자 이름 (from:@xxx)
    after: Optional[str] = Query(None),         # YYYY-MM-DD
    before: Optional[str] = Query(None),        # YYYY-MM-DD
    sort: str = Query("newest"),                # newest | oldest | relevant
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    require_db()
    q = q.strip()
    has_text = bool(q)
    has_filters = bool(channel_id or channel_name or from_user or after or before)
    if not has_text and not has_filters:
        raise HTTPException(status_code=400, detail="검색어 또는 필터를 입력하세요.")

    conn = get_conn()

    # 채널 이름 → ID 변환
    if channel_name and not channel_id:
        row = conn.execute(
            "SELECT id FROM channels WHERE name = ? LIMIT 1", (channel_name,)
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM channels WHERE name LIKE ? LIMIT 1", (f"%{channel_name}%",)
            ).fetchone()
        if row:
            channel_id = row["id"]

    # 날짜 → timestamp 변환 (KST)
    after_ts = _date_to_ts(after) if after else None
    before_ts = _date_to_ts(before, end_of_day=True) if before else None

    # WHERE 절 조립 (FTS 없는 필터 전용)
    where_parts: list[str] = []
    filter_params: list = []
    if channel_id:
        where_parts.append("messages.channel_id = ?")
        filter_params.append(channel_id)
    if from_user:
        where_parts.append("messages.user_name LIKE ?")
        filter_params.append(f"%{from_user}%")
    if after_ts:
        where_parts.append("CAST(messages.ts AS REAL) >= ?")
        filter_params.append(after_ts)
    if before_ts:
        where_parts.append("CAST(messages.ts AS REAL) <= ?")
        filter_params.append(before_ts)

    # 텍스트 검색: LIKE 기반 부분 일치 (공백으로 구분된 각 단어를 AND 조건으로)
    # → "딥슨바이오" "딥슨바이오에서" 등 포함 검색 가능
    if has_text:
        for word in q.split():
            where_parts.append("(messages.text LIKE ? OR messages.user_name LIKE ?)")
            filter_params.extend([f"%{word}%", f"%{word}%"])

    filter_sql = " AND ".join(where_parts) if where_parts else "1=1"
    # filter_params의 테이블 prefix 제거 (단독 쿼리용)
    bare_sql = filter_sql.replace("messages.", "")
    offset = (page - 1) * per_page

    total = conn.execute(
        f"SELECT COUNT(*) FROM messages WHERE {bare_sql}", filter_params
    ).fetchone()[0]

    if sort == "oldest":
        order_clause = "CAST(ts AS REAL) ASC"
    elif sort == "relevant" and has_text:
        # Score = number of search words found in text; ties broken by recency
        match_cases = " + ".join(
            f"(CASE WHEN text LIKE ? THEN 1 ELSE 0 END)"
            for _ in q.split()
        )
        match_params = [f"%{word}%" for word in q.split()]
        order_clause = f"({match_cases}) DESC, CAST(ts AS REAL) DESC"
        rows = conn.execute(
            f"SELECT * FROM messages WHERE {bare_sql} ORDER BY {order_clause} LIMIT ? OFFSET ?",
            filter_params + match_params + [per_page, offset],
        ).fetchall()
        msgs = [row_to_msg(r) for r in rows]
        _enrich_channel_info(msgs, conn)
        conn.close()
        return {
            "q": q,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if total else 1,
            "messages": msgs,
        }
    else:
        order_clause = "CAST(ts AS REAL) DESC"

    rows = conn.execute(
        f"SELECT * FROM messages WHERE {bare_sql} ORDER BY {order_clause} LIMIT ? OFFSET ?",
        filter_params + [per_page, offset],
    ).fetchall()

    msgs = [row_to_msg(r) for r in rows]
    _enrich_channel_info(msgs, conn)
    conn.close()

    return {
        "q": q,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
        "messages": msgs,
    }


@app.get("/api/suggest/channels")
def suggest_channels(q: str = Query("")):
    require_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, type FROM channels WHERE name LIKE ? ORDER BY type, name LIMIT 15",
        (f"%{q}%",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/suggest/users")
def suggest_users(q: str = Query("")):
    require_db()
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, name, display_name, real_name FROM users
           WHERE name LIKE ? OR display_name LIKE ? OR real_name LIKE ?
           ORDER BY display_name LIMIT 15""",
        (f"%{q}%", f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/users")
def get_users():
    require_db()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return {r["id"]: dict(r) for r in rows}


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
