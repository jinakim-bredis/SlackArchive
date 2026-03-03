"""
slack_thread_archive.py
=======================
slackdump export ZIP → 스레드별 JSON + TXT 변환 스크립트

사용법:
    python slack_thread_archive.py <slack_export.zip> <출력폴더>

예시:
    python slack_thread_archive.py ./backup/slack_export.zip ./backup/thread_archive

출력:
    <출력폴더>/json/<채널명>__<ISO타임스탬프>__<thread|standalone>.json
    <출력폴더>/txt/<채널명>__<ISO타임스탬프>__<thread|standalone>.txt
    <출력폴더>/summary.json

의존성: Python 표준 라이브러리만 사용 (zipfile, json, os, datetime, re, sys)
"""

import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone, timedelta

# KST = UTC+9
KST = timezone(timedelta(hours=9))

# 건너뛸 메시지 subtype (시스템 이벤트)
SKIP_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_archive",
    "channel_unarchive",
    "channel_name",
    "channel_purpose",
    "channel_topic",
    "bot_add",
    "bot_remove",
    "pinned_item",
    "unpinned_item",
    "tombstone",
    "sh_room_created",
    "sh_room_updated",
}


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

def load_zip(zip_path: str) -> zipfile.ZipFile:
    """ZIP 파일 열기."""
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"ZIP 파일을 찾을 수 없습니다: {zip_path}")
    return zipfile.ZipFile(zip_path, "r")


def load_json_from_zip(zf: zipfile.ZipFile, name: str) -> object:
    """ZIP 내 JSON 파일을 읽어 파싱."""
    try:
        with zf.open(name) as f:
            return json.loads(f.read().decode("utf-8"))
    except KeyError:
        return None


def build_user_map(users: list) -> dict:
    """users.json → {user_id: display_name} 딕셔너리."""
    user_map = {}
    if not users:
        return user_map
    for u in users:
        uid = u.get("id", "")
        if not uid:
            continue
        profile = u.get("profile", {})
        display = (
            profile.get("display_name")
            or profile.get("real_name")
            or u.get("name")
            or uid
        )
        user_map[uid] = display
    return user_map


def build_channel_map(channels: list) -> dict:
    """channels.json → {channel_id: channel_name} 딕셔너리."""
    ch_map = {}
    if not channels:
        return ch_map
    for ch in channels:
        cid = ch.get("id", "")
        name = ch.get("name", cid)
        if cid:
            ch_map[cid] = name
    return ch_map


def discover_channels(zf: zipfile.ZipFile) -> list:
    """
    ZIP 내 채널 폴더 목록을 반환.
    slackdump export 구조:
      - 폴더가 있고, 그 안에 날짜별 JSON이 있는 경우
      - 또는 channels.json 파일에서 목록을 얻는 경우
    둘 다 시도해 합집합을 반환.
    """
    names = zf.namelist()

    # channels.json 에서 목록 구성
    channels_json = load_json_from_zip(zf, "channels.json")
    channel_names_from_json = set()
    if channels_json:
        for ch in channels_json:
            n = ch.get("name")
            if n:
                channel_names_from_json.add(n)

    # ZIP 내 폴더 구조에서 채널 폴더 추출
    channel_names_from_zip = set()
    for name in names:
        parts = name.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            # 날짜 패턴 파일이 있는 폴더를 채널로 간주
            if re.match(r"\d{4}-\d{2}-\d{2}\.json$", parts[1]):
                channel_names_from_zip.add(parts[0])

    all_channels = channel_names_from_json | channel_names_from_zip
    return sorted(all_channels)


def load_channel_messages(zf: zipfile.ZipFile, channel_name: str) -> list:
    """채널 폴더 내 날짜별 JSON 파일을 모두 읽어 메시지 리스트 반환."""
    all_messages = []
    names = zf.namelist()
    pattern = re.compile(rf"^{re.escape(channel_name)}/(\d{{4}}-\d{{2}}-\d{{2}})\.json$")

    date_files = sorted(n for n in names if pattern.match(n))

    for fname in date_files:
        data = load_json_from_zip(zf, fname)
        if isinstance(data, list):
            all_messages.extend(data)
        elif isinstance(data, dict):
            # slackdump v3 일부 버전: {"messages": [...]} 구조
            msgs = data.get("messages", [])
            if isinstance(msgs, list):
                all_messages.extend(msgs)

    return all_messages


# ---------------------------------------------------------------------------
# 스레드 그룹화
# ---------------------------------------------------------------------------

def group_into_threads(messages: list) -> dict:
    """
    ts/thread_ts 기준으로 스레드 그룹화.

    반환값:
        {
            thread_ts_str: {
                "root": <메시지>,
                "replies": [<메시지>, ...],
                "is_thread": bool,  # 답글이 1개 이상이면 True
            }
        }
    """
    # 1단계: root 메시지 수집
    roots = {}
    for msg in messages:
        subtype = msg.get("subtype", "")
        if subtype in SKIP_SUBTYPES:
            continue

        ts = msg.get("ts", "")
        thread_ts = msg.get("thread_ts", "")

        if not thread_ts:
            # standalone 또는 thread root (아직 모름)
            roots[ts] = {"root": msg, "replies": [], "is_thread": False}
        elif ts == thread_ts:
            # thread root
            if ts not in roots:
                roots[ts] = {"root": msg, "replies": [], "is_thread": True}
            else:
                roots[ts]["root"] = msg
                roots[ts]["is_thread"] = True

    # 2단계: 답글 분류
    for msg in messages:
        subtype = msg.get("subtype", "")
        if subtype in SKIP_SUBTYPES:
            continue

        ts = msg.get("ts", "")
        thread_ts = msg.get("thread_ts", "")

        if thread_ts and ts != thread_ts:
            # 답글
            if thread_ts in roots:
                roots[thread_ts]["replies"].append(msg)
                roots[thread_ts]["is_thread"] = True
            else:
                # orphan reply — root가 없는 경우 root로 등록
                roots[thread_ts] = {
                    "root": None,
                    "replies": [msg],
                    "is_thread": True,
                }

    # 3단계: 답글을 ts 순으로 정렬
    for key in roots:
        roots[key]["replies"].sort(key=lambda m: float(m.get("ts", "0")))

    return roots


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def resolve_user_mention(text: str, user_map: dict) -> str:
    """<@U12345> → @이름 변환."""
    if not text:
        return text

    def replace(m):
        uid = m.group(1)
        name = user_map.get(uid, uid)
        return f"@{name}"

    return re.sub(r"<@([UW][A-Z0-9]+)>", replace, text)


def resolve_channel_mention(text: str, channel_map: dict) -> str:
    """<#C12345|channel-name> → #channel-name 변환."""
    if not text:
        return text

    def replace(m):
        cid = m.group(1)
        label = m.group(2) if m.group(2) else channel_map.get(cid, cid)
        return f"#{label}"

    return re.sub(r"<#([C][A-Z0-9]+)\|?([^>]*)>", replace, text)


def clean_slack_markup(text: str) -> str:
    """기타 Slack 마크업 정리."""
    if not text:
        return text
    # URL 링크: <https://example.com|표시텍스트> → 표시텍스트 (https://example.com)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
    # URL only: <https://example.com>
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    # 이메일: <mailto:foo@bar.com|foo@bar.com> → foo@bar.com
    text = re.sub(r"<mailto:[^|>]+\|([^>]+)>", r"\1", text)
    return text


def format_timestamp(ts: str) -> str:
    """Unix epoch 문자열 → 'YYYY-MM-DD HH:MM:SS KST'."""
    try:
        epoch = float(ts)
        dt = datetime.fromtimestamp(epoch, tz=KST)
        return dt.strftime("%Y-%m-%d %H:%M:%S KST")
    except (ValueError, OSError):
        return ts


def safe_filename(name: str) -> str:
    """파일 시스템에 안전한 이름으로 변환."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def get_user_name(msg: dict, user_map: dict) -> str:
    """메시지에서 발신자 이름 추출."""
    uid = msg.get("user", "")
    bot_id = msg.get("bot_id", "")
    username = msg.get("username", "")

    if uid:
        return user_map.get(uid, uid)
    if username:
        return username
    if bot_id:
        return user_map.get(bot_id, f"bot:{bot_id}")
    return "(unknown)"


def get_message_text(msg: dict, user_map: dict, channel_map: dict) -> str:
    """메시지 텍스트를 읽기 좋게 변환."""
    text = msg.get("text", "")
    text = resolve_user_mention(text, user_map)
    text = resolve_channel_mention(text, channel_map)
    text = clean_slack_markup(text)

    # 첨부파일 메타 추가
    attachments = msg.get("attachments", [])
    for att in attachments:
        fallback = att.get("fallback") or att.get("text") or att.get("pretext") or ""
        if fallback:
            text = text + f"\n  [첨부] {fallback}" if text else f"[첨부] {fallback}"

    # 파일 공유 메타 추가
    files = msg.get("files", [])
    for f in files:
        fname = f.get("name", "(unnamed)")
        fsize = f.get("size", 0)
        size_str = f"{fsize:,} bytes" if fsize else ""
        text = text + f"\n  [파일] {fname}" + (f" ({size_str})" if size_str else "")

    return text


# ---------------------------------------------------------------------------
# JSON 출력
# ---------------------------------------------------------------------------

def build_thread_json(channel_name: str, thread_data: dict, user_map: dict, channel_map: dict) -> dict:
    """스레드 데이터를 JSON 직렬화 가능한 딕셔너리로 변환."""
    root = thread_data["root"]
    replies = thread_data["replies"]
    is_thread = thread_data["is_thread"]

    def msg_to_dict(msg):
        ts = msg.get("ts", "")
        return {
            "ts": ts,
            "timestamp": format_timestamp(ts),
            "user_id": msg.get("user", msg.get("bot_id", "")),
            "user_name": get_user_name(msg, user_map),
            "text": get_message_text(msg, user_map, channel_map),
            "raw_text": msg.get("text", ""),
            "thread_ts": msg.get("thread_ts", ""),
            "reply_count": msg.get("reply_count", 0),
            "reactions": [
                {"name": r.get("name", ""), "count": r.get("count", 0)}
                for r in msg.get("reactions", [])
            ],
            "files": [
                {"name": f.get("name", ""), "size": f.get("size", 0), "mimetype": f.get("mimetype", "")}
                for f in msg.get("files", [])
            ],
        }

    result = {
        "channel": channel_name,
        "is_thread": is_thread,
        "root": msg_to_dict(root) if root else None,
        "replies": [msg_to_dict(r) for r in replies],
        "reply_count": len(replies),
    }
    return result


def write_thread_json(output_dir: str, channel_name: str, thread_ts: str,
                      thread_data: dict, user_map: dict, channel_map: dict):
    """스레드 JSON 파일 저장."""
    json_dir = os.path.join(output_dir, "json")
    os.makedirs(json_dir, exist_ok=True)

    kind = "thread" if thread_data["is_thread"] else "standalone"
    ts_iso = format_timestamp(thread_ts).replace(":", "-").replace(" ", "_").replace("_KST", "")
    fname = f"{safe_filename(channel_name)}__{ts_iso}__{kind}.json"
    fpath = os.path.join(json_dir, fname)

    data = build_thread_json(channel_name, thread_data, user_map, channel_map)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return fpath


# ---------------------------------------------------------------------------
# TXT 출력
# ---------------------------------------------------------------------------

def write_thread_txt(output_dir: str, channel_name: str, thread_ts: str,
                     thread_data: dict, user_map: dict, channel_map: dict):
    """스레드 TXT 파일 저장 (사람이 읽기 좋은 형식)."""
    txt_dir = os.path.join(output_dir, "txt")
    os.makedirs(txt_dir, exist_ok=True)

    root = thread_data["root"]
    replies = thread_data["replies"]
    is_thread = thread_data["is_thread"]

    kind = "thread" if is_thread else "standalone"
    ts_iso = format_timestamp(thread_ts).replace(":", "-").replace(" ", "_").replace("_KST", "")
    fname = f"{safe_filename(channel_name)}__{ts_iso}__{kind}.txt"
    fpath = os.path.join(txt_dir, fname)

    lines = []
    sep = "=" * 80
    lines.append(sep)

    header_kind = "[스레드]" if is_thread else "[단독메시지]"
    root_ts_str = format_timestamp(thread_ts)
    lines.append(f"{header_kind} #{channel_name} | {root_ts_str}")
    lines.append(sep)

    if root:
        root_time = format_timestamp(root.get("ts", "")).split(" ")[1]  # HH:MM:SS
        root_user = get_user_name(root, user_map)
        root_text = get_message_text(root, user_map, channel_map)
        lines.append(f"[{root_time}] {root_user}: {root_text}")
    else:
        lines.append("(루트 메시지 없음)")

    if replies:
        lines.append(f"\n--- 답글 {len(replies)}개 ---")
        for reply in replies:
            reply_time = format_timestamp(reply.get("ts", "")).split(" ")[1]
            reply_user = get_user_name(reply, user_map)
            reply_text = get_message_text(reply, user_map, channel_map)
            # 답글 들여쓰기
            indented = reply_text.replace("\n", "\n    ")
            lines.append(f"  [{reply_time}] {reply_user}: {indented}")

    lines.append(sep)
    lines.append("")

    with open(fpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return fpath


# ---------------------------------------------------------------------------
# 요약 파일
# ---------------------------------------------------------------------------

def write_summary(output_dir: str, stats: dict):
    """summary.json 저장."""
    total_messages = stats["total_messages"]

    if total_messages <= 100_000:
        option = "A"
        reason = (
            f"총 {total_messages:,}개 메시지 — 클라이언트 사이드 JSON 로드로 충분. "
            "백엔드 없이 React/Next.js에서 직접 JSON 파일을 임포트하거나 fetch로 로드."
        )
    elif total_messages <= 500_000:
        option = "B"
        reason = (
            f"총 {total_messages:,}개 메시지 — FastAPI 또는 Django REST API 서버 권장. "
            "JSON 파일을 API로 서빙하고, 프론트엔드는 페이지네이션으로 로드."
        )
    else:
        option = "C"
        reason = (
            f"총 {total_messages:,}개 메시지 — SQLite 또는 PostgreSQL DB 마이그레이션 권장. "
            "FTS5 전문 검색 인덱스로 빠른 검색 지원."
        )

    summary = {
        "generated_at": datetime.now(tz=KST).isoformat(),
        "totals": {
            "channels": stats["channels"],
            "total_messages": total_messages,
            "thread_count": stats["thread_count"],
            "standalone_count": stats["standalone_count"],
            "skipped_messages": stats["skipped_messages"],
        },
        "channels": stats["channel_details"],
        "phase2_recommendation": {
            "recommended_option": option,
            "reason": reason,
        },
    }

    fpath = os.path.join(output_dir, "summary.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return fpath


# ---------------------------------------------------------------------------
# 메인 파이프라인
# ---------------------------------------------------------------------------

def main(zip_path: str, output_dir: str):
    print(f"[슬랙 아카이브] ZIP: {zip_path}")
    print(f"[슬랙 아카이브] 출력: {output_dir}")
    print()

    os.makedirs(output_dir, exist_ok=True)

    zf = load_zip(zip_path)

    # 사용자 맵 구성
    users_data = load_json_from_zip(zf, "users.json")
    user_map = build_user_map(users_data or [])
    print(f"  유저 수: {len(user_map):,}")

    # 채널 맵 구성
    channels_data = load_json_from_zip(zf, "channels.json")
    channel_map = build_channel_map(channels_data or [])

    # 채널 목록 발견
    channel_names = discover_channels(zf)
    print(f"  채널 수: {len(channel_names):,}")
    print()

    stats = {
        "channels": len(channel_names),
        "total_messages": 0,
        "thread_count": 0,
        "standalone_count": 0,
        "skipped_messages": 0,
        "channel_details": [],
    }

    for ch_name in channel_names:
        print(f"  처리 중: #{ch_name}", end=" ", flush=True)

        messages = load_channel_messages(zf, ch_name)
        if not messages:
            print("(메시지 없음)")
            continue

        # 스킵된 메시지 수 계산
        skipped = sum(
            1 for m in messages if m.get("subtype", "") in SKIP_SUBTYPES
        )

        threads = group_into_threads(messages)
        thread_count = sum(1 for t in threads.values() if t["is_thread"])
        standalone_count = len(threads) - thread_count

        ch_total = sum(
            1 + len(t["replies"]) for t in threads.values()
        )

        print(f"→ 메시지 {len(messages):,}개 | 스레드 {thread_count:,}개 | 단독 {standalone_count:,}개")

        stats["total_messages"] += len(messages) - skipped
        stats["skipped_messages"] += skipped
        stats["thread_count"] += thread_count
        stats["standalone_count"] += standalone_count
        stats["channel_details"].append({
            "channel_name": ch_name,
            "total_messages": len(messages),
            "valid_messages": len(messages) - skipped,
            "skipped": skipped,
            "thread_count": thread_count,
            "standalone_count": standalone_count,
        })

        for thread_ts, thread_data in threads.items():
            if thread_data["root"] is None and not thread_data["replies"]:
                continue
            write_thread_json(output_dir, ch_name, thread_ts, thread_data, user_map, channel_map)
            write_thread_txt(output_dir, ch_name, thread_ts, thread_data, user_map, channel_map)

    zf.close()

    print()
    print("요약 파일 작성 중...")
    summary_path = write_summary(output_dir, stats)

    print()
    print("=" * 60)
    print("완료!")
    print(f"  총 채널:     {stats['channels']:,}")
    print(f"  총 메시지:   {stats['total_messages']:,}")
    print(f"  스레드:      {stats['thread_count']:,}")
    print(f"  단독 메시지: {stats['standalone_count']:,}")
    print(f"  스킵:        {stats['skipped_messages']:,} (채널 입퇴장 등)")
    print()
    print(f"  JSON 파일:   {output_dir}/json/")
    print(f"  TXT 파일:    {output_dir}/txt/")
    print(f"  요약:        {summary_path}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python slack_thread_archive.py <slack_export.zip> <출력폴더>")
        print("예시:   python slack_thread_archive.py ./backup/slack_export.zip ./backup/thread_archive")
        sys.exit(1)

    zip_path = sys.argv[1]
    output_dir = sys.argv[2]
    main(zip_path, output_dir)
