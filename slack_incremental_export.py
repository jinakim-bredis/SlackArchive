"""
slack_incremental_export.py
============================
이전 아카이빙 이후의 새 메시지를 증분으로 가져온다.

사용법:
    python slack_incremental_export.py [옵션]

옵션:
    --backup-dir  DIR    백업 폴더 경로 (기본값: ./backup)
    --no-convert         ZIP 변환(JSON/TXT) 건너뛰기
    --from       DATE    기준 시각 강제 지정 (YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS, KST)
    --dry-run            실제 실행 없이 명령만 출력

동작 순서:
    1. 마지막 Export 시각 조회 (backup/last_export.json → thread_archive/summary.json 순)
    2. KST → UTC 변환 후 slackdump export -time-from <UTC> 실행
    3. 새 ZIP을 slack_thread_archive.py로 JSON/TXT 변환 (--no-convert 없을 시)
    4. backup/last_export.json 갱신

의존성: Python 표준 라이브러리만 사용
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

# ── 상수 ──────────────────────────────────────────────────────────────────────

KST = datetime.timezone(datetime.timedelta(hours=9))
UTC = datetime.timezone.utc

SCRIPT_DIR = Path(__file__).parent.resolve()
SLACKDUMP_PATH = SCRIPT_DIR / "slackdump.exe"
THREAD_ARCHIVE_SCRIPT = SCRIPT_DIR / "slack_thread_archive.py"


# ── 마지막 Export 시각 조회 ───────────────────────────────────────────────────

def get_last_export_time(backup_dir: Path, force_from: str | None) -> datetime.datetime:
    """
    마지막 Export 시각을 KST aware datetime으로 반환.

    우선순위:
      1. --from 옵션으로 강제 지정
      2. backup/last_export.json
      3. backup/thread_archive/summary.json
    """
    if force_from:
        # YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS
        if "T" in force_from:
            dt = datetime.datetime.fromisoformat(force_from)
        else:
            dt = datetime.datetime.strptime(force_from, "%Y-%m-%d")
        # 타임존이 없으면 KST로 간주
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        print(f"[기준 시각] --from 옵션 사용: {dt.isoformat()}")
        return dt

    last_export_file = backup_dir / "last_export.json"
    if last_export_file.exists():
        with open(last_export_file, encoding="utf-8") as f:
            data = json.load(f)
        dt = datetime.datetime.fromisoformat(data["exported_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        print(f"[기준 시각] last_export.json: {dt.isoformat()}")
        return dt

    summary_file = backup_dir / "thread_archive" / "summary.json"
    if summary_file.exists():
        with open(summary_file, encoding="utf-8") as f:
            data = json.load(f)
        dt = datetime.datetime.fromisoformat(data["generated_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        print(f"[기준 시각] thread_archive/summary.json: {dt.isoformat()}")
        return dt

    raise FileNotFoundError(
        "이전 Export 기록을 찾을 수 없습니다.\n"
        "  backup/last_export.json 또는 backup/thread_archive/summary.json이 필요합니다.\n"
        "  또는 --from YYYY-MM-DD 옵션으로 기준 날짜를 직접 지정하세요."
    )


# ── slackdump export 실행 ────────────────────────────────────────────────────

def run_export(last_dt: datetime.datetime, output_zip: Path, dry_run: bool) -> bool:
    """
    slackdump export -time-from <UTC> -files=false -o <zip> 실행.
    반환값: 성공 여부
    """
    # KST → UTC 변환 후 slackdump 형식으로 포맷
    last_utc = last_dt.astimezone(UTC)
    time_from_str = last_utc.strftime("%Y-%m-%dT%H:%M:%S")

    cmd = [
        str(SLACKDUMP_PATH),
        "export",
        "-time-from", time_from_str,
        "-files=false",
        "-o", str(output_zip),
    ]

    print()
    print(f"[Export] 기준 시각 (UTC): {time_from_str}")
    print(f"[Export] 출력 ZIP:       {output_zip}")
    print(f"[Export] 실행 명령:      {' '.join(cmd)}")
    print()

    if dry_run:
        print("[dry-run] 실제 실행을 건너뜁니다.")
        return True

    if not SLACKDUMP_PATH.exists():
        print(f"[오류] slackdump.exe를 찾을 수 없습니다: {SLACKDUMP_PATH}", file=sys.stderr)
        return False

    env = os.environ.copy()
    proc = subprocess.run(cmd, env=env)
    if proc.returncode != 0:
        print(f"[오류] slackdump 종료 코드: {proc.returncode}", file=sys.stderr)
        return False

    if not output_zip.exists():
        print(f"[오류] ZIP 파일이 생성되지 않았습니다: {output_zip}", file=sys.stderr)
        return False

    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"[완료] ZIP 생성: {output_zip} ({size_mb:.1f} MB)")
    return True


# ── slack_thread_archive.py 실행 ─────────────────────────────────────────────

def run_thread_archive(zip_path: Path, output_dir: Path, dry_run: bool) -> bool:
    """
    slack_thread_archive.py <zip> <output_dir> 실행.
    반환값: 성공 여부
    """
    cmd = [sys.executable, str(THREAD_ARCHIVE_SCRIPT), str(zip_path), str(output_dir)]

    print()
    print(f"[변환] slack_thread_archive.py 실행 중...")
    print(f"[변환] 출력 폴더: {output_dir}")

    if dry_run:
        print(f"[dry-run] 실행 명령: {' '.join(cmd)}")
        return True

    if not THREAD_ARCHIVE_SCRIPT.exists():
        print(f"[오류] slack_thread_archive.py를 찾을 수 없습니다: {THREAD_ARCHIVE_SCRIPT}",
              file=sys.stderr)
        return False

    proc = subprocess.run(cmd)
    return proc.returncode == 0


# ── last_export.json 갱신 ────────────────────────────────────────────────────

def update_last_export(backup_dir: Path, zip_path: Path, dry_run: bool):
    """backup/last_export.json에 현재 Export 완료 시각 기록."""
    now_kst = datetime.datetime.now(tz=KST)
    data = {
        "exported_at": now_kst.isoformat(),
        "zip_file": zip_path.name,
    }

    last_export_file = backup_dir / "last_export.json"
    if not dry_run:
        with open(last_export_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[기록] last_export.json 갱신: {now_kst.isoformat()}")
    else:
        print(f"\n[dry-run] last_export.json에 기록할 내용: {json.dumps(data, ensure_ascii=False)}")


# ── 메인 ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="이전 Export 이후의 새 메시지를 증분으로 아카이빙합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--backup-dir", default="./backup",
        metavar="DIR",
        help="백업 폴더 경로 (기본값: ./backup)",
    )
    p.add_argument(
        "--no-convert", action="store_true",
        help="JSON/TXT 변환 건너뛰기 (ZIP만 생성)",
    )
    p.add_argument(
        "--from", dest="from_date", default=None,
        metavar="DATE",
        help="기준 시각 강제 지정 (YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS, KST 기준)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="실제 실행 없이 명령만 출력",
    )
    return p.parse_args()


def main():
    args = parse_args()
    backup_dir = Path(args.backup_dir).resolve()

    print("=" * 60)
    print("  Slack 증분 Export")
    print("=" * 60)
    print(f"  백업 폴더: {backup_dir}")

    # 1. 마지막 Export 시각 조회
    try:
        last_dt = get_last_export_time(backup_dir, args.from_date)
    except FileNotFoundError as e:
        print(f"\n[오류] {e}", file=sys.stderr)
        sys.exit(1)

    # 2. 출력 ZIP 경로 결정
    now_kst = datetime.datetime.now(tz=KST)
    zip_name = f"slack_export_incremental_{now_kst.strftime('%Y-%m-%d_%H-%M-%S')}.zip"
    output_zip = backup_dir / zip_name

    # 3. slackdump export 실행
    ok = run_export(last_dt, output_zip, args.dry_run)
    if not ok:
        print("\n[실패] Export 중 오류가 발생했습니다.", file=sys.stderr)
        sys.exit(1)

    # 4. JSON/TXT 변환
    if not args.no_convert:
        archive_dir_name = f"thread_archive_{now_kst.strftime('%Y-%m-%d_%H-%M-%S')}"
        incremental_archive_dir = backup_dir / archive_dir_name
        ok = run_thread_archive(output_zip, incremental_archive_dir, args.dry_run)
        if not ok:
            print("\n[경고] JSON/TXT 변환 실패. ZIP 파일은 유지됩니다.", file=sys.stderr)
        else:
            print(f"\n[완료] 변환 결과: {incremental_archive_dir}")
    else:
        print("\n[건너뜀] --no-convert 옵션으로 변환을 건너뜁니다.")

    # 5. last_export.json 갱신
    update_last_export(backup_dir, output_zip, args.dry_run)

    print()
    print("=" * 60)
    print("  증분 Export 완료!")
    print(f"  ZIP:  {output_zip}")
    if not args.no_convert:
        print(f"  변환: {backup_dir}/thread_archive_{now_kst.strftime('%Y-%m-%d_%H-%M-%S')}/")
    print()
    print("  viewer DB 갱신 방법:")
    print(f"    cd viewer")
    print(f"    python init_db.py ../backup/{zip_name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
