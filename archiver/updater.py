"""
Slack 증분 업데이트 GUI
=======================
이전 Export 이후의 새 메시지를 가져와 SQLite DB에 반영한다.

빌드: archiver/build_updater.bat → dist/SlackUpdater.exe
"""

import datetime
import json
import os
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, scrolledtext, ttk


# ── 경로 ─────────────────────────────────────────────────────────────────────

def get_slackdump_path() -> str:
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'slackdump.exe')


# ── 타임존 ────────────────────────────────────────────────────────────────────

KST = datetime.timezone(datetime.timedelta(hours=9))
UTC = datetime.timezone.utc


# ── 마지막 Export 시각 ────────────────────────────────────────────────────────

def get_last_export_time(backup_dir: str) -> datetime.datetime | None:
    """last_export.json → thread_archive/summary.json 순으로 시각 반환."""
    for path in [
        os.path.join(backup_dir, "last_export.json"),
        os.path.join(backup_dir, "thread_archive", "summary.json"),
    ]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            key = "exported_at" if "exported_at" in data else "generated_at"
            dt = datetime.datetime.fromisoformat(data[key])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt
        except Exception:
            continue
    return None


def update_last_export(backup_dir: str, zip_name: str):
    now = datetime.datetime.now(tz=KST)
    path = os.path.join(backup_dir, "last_export.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"exported_at": now.isoformat(), "zip_file": zip_name},
                  f, ensure_ascii=False, indent=2)
    return now


# ── DB 인제스트 (init_db.py 로직 내장) ─────────────────────────────────────────

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


def _load_json(zf: zipfile.ZipFile, name: str):
    try:
        with zf.open(name) as f:
            return json.load(f)
    except (KeyError, json.JSONDecodeError):
        return []


def ingest_zip_to_db(zip_path: str, db_path: str, log_fn) -> int:
    """ZIP → SQLite 증분 반영. 반환값: 추가된 메시지 수."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")
    conn.executescript(SCHEMA)  # 테이블이 없으면 생성, 있으면 유지

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Users
        users = _load_json(zf, "users.json")
        user_map = {}
        user_rows = []
        for u in users:
            uid = u.get("id", "")
            p = u.get("profile", {})
            display = p.get("display_name") or p.get("real_name") or u.get("name", uid)
            real = p.get("real_name", "")
            user_rows.append((uid, u.get("name", ""), display, real))
            user_map[uid] = display
        conn.executemany("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", user_rows)
        log_fn(f"유저: {len(user_rows)}명\n")

        # Channels
        channel_list = []

        def _add_channels(items, ch_type, folder_attr="name"):
            for item in items:
                cid = item.get("id", "")
                raw_name = item.get(folder_attr, "") or cid
                if ch_type == "dm":
                    members = item.get("members", [])
                    display_name = " & ".join(user_map.get(m, m) for m in members if m) or cid
                    folder_name = cid
                elif ch_type == "group_dm":
                    members = item.get("members", [])
                    display_name = ", ".join(user_map.get(m, m) for m in members if m) or raw_name
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
                channel_list.append({"id": cid, "name": display_name,
                                     "folder_name": folder_name, "type": ch_type})

        _add_channels(_load_json(zf, "channels.json"), "public")
        _add_channels(_load_json(zf, "groups.json"), "private")
        _add_channels(_load_json(zf, "mpims.json"), "group_dm")
        _add_channels(_load_json(zf, "dms.json"), "dm")
        log_fn(f"채널: {len(channel_list)}개\n")

        # Messages
        zip_names = set(zf.namelist())
        total = 0
        for ch in channel_list:
            folder = ch["folder_name"]
            cid = ch["id"]
            prefix = folder + "/"
            day_files = sorted(n for n in zip_names
                               if n.startswith(prefix) and n.endswith(".json"))
            if not day_files:
                continue
            batch = []
            for day_file in day_files:
                try:
                    with zf.open(day_file) as f:
                        msgs = json.load(f)
                except Exception:
                    continue
                for msg in msgs:
                    subtype = msg.get("subtype", "")
                    if subtype in SKIP_SUBTYPES:
                        continue
                    ts = msg.get("ts", "")
                    if not ts:
                        continue
                    thread_ts = msg.get("thread_ts")
                    is_broadcast = 1 if subtype == "thread_broadcast" else 0
                    if is_broadcast:
                        is_root = 1
                    elif thread_ts:
                        is_root = 1 if ts == thread_ts else 0
                    else:
                        is_root = 1
                    uid = msg.get("user") or msg.get("bot_id") or ""
                    reactions = msg.get("reactions")
                    reactions_json = json.dumps(
                        [{"name": r.get("name", ""), "count": r.get("count", 0)} for r in reactions],
                        ensure_ascii=False
                    ) if reactions else None
                    files = msg.get("files")
                    files_json = json.dumps(
                        [{"name": f.get("name", ""), "size": f.get("size", 0),
                          "mimetype": f.get("mimetype", "")} for f in files],
                        ensure_ascii=False
                    ) if files else None
                    batch.append((
                        ts, cid, thread_ts, is_root,
                        uid, user_map.get(uid, uid),
                        msg.get("text", ""), "",
                        msg.get("reply_count", 0),
                        reactions_json, files_json, is_broadcast,
                    ))
            if batch:
                conn.executemany(
                    "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                total += len(batch)
                log_fn(f"  [{ch['type']:8}] {ch['name'][:35]:<35} {len(batch):>5}개\n")

    log_fn("FTS5 인덱스 재구축 중...\n")
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    return total


# ── GUI ──────────────────────────────────────────────────────────────────────

class SlackUpdater(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Slack 증분 업데이트")
        self.resizable(False, False)
        self._process: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._build_ui()
        self._detect_defaults()

    def _build_ui(self):
        # ── 경로 설정 프레임 ──
        frame_paths = ttk.LabelFrame(self, text="경로 설정", padding=10)
        frame_paths.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        frame_paths.columnconfigure(1, weight=1)

        ttk.Label(frame_paths, text="백업 폴더").grid(row=0, column=0, sticky="w")
        self.var_backup = tk.StringVar()
        ttk.Entry(frame_paths, textvariable=self.var_backup, width=48
                  ).grid(row=0, column=1, sticky="ew", padx=(6, 4))
        ttk.Button(frame_paths, text="선택",
                   command=self._browse_backup).grid(row=0, column=2)

        ttk.Label(frame_paths, text="DB 파일").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_db = tk.StringVar()
        ttk.Entry(frame_paths, textvariable=self.var_db, width=48
                  ).grid(row=1, column=1, sticky="ew", padx=(6, 4), pady=(6, 0))
        ttk.Button(frame_paths, text="선택",
                   command=self._browse_db).grid(row=1, column=2, pady=(6, 0))

        # ── 마지막 Export 시각 표시 ──
        self.var_last_time = tk.StringVar(value="마지막 Export: (백업 폴더를 선택하세요)")
        ttk.Label(frame_paths, textvariable=self.var_last_time,
                  foreground="#555"
                  ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # ── 시작 버튼 ──
        self.btn_start = ttk.Button(self, text="  업데이트 시작  ",
                                    command=self._on_start)
        self.btn_start.grid(row=1, column=0, pady=8)

        # ── 로그 패널 ──
        frame_log = ttk.LabelFrame(self, text="로그", padding=6)
        frame_log.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        self.log_box = scrolledtext.ScrolledText(
            frame_log, width=70, height=16,
            state="disabled", font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4",
        )
        self.log_box.pack(fill="both", expand=True)

    def _detect_defaults(self):
        """실행 파일 위치 기준으로 백업 폴더·DB 경로 자동 감지."""
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 백업 폴더 후보
        for candidate in [
            os.path.join(base, "backup"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
        ]:
            if os.path.isdir(candidate):
                self.var_backup.set(candidate)
                self._refresh_last_time(candidate)
                break

        # DB 파일 후보
        for candidate in [
            os.path.join(base, "viewer", "slack_archive.db"),
            os.path.join(base, "slack_archive.db"),
        ]:
            if os.path.isfile(candidate):
                self.var_db.set(candidate)
                break

    def _refresh_last_time(self, backup_dir: str):
        dt = get_last_export_time(backup_dir)
        if dt:
            kst = dt.astimezone(KST)
            self.var_last_time.set(f"마지막 Export: {kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
        else:
            self.var_last_time.set("마지막 Export: 기록 없음 (first run?)")

    def _browse_backup(self):
        path = filedialog.askdirectory(title="백업 폴더 선택")
        if path:
            self.var_backup.set(path)
            self._refresh_last_time(path)

    def _browse_db(self):
        path = filedialog.askopenfilename(
            title="DB 파일 선택",
            filetypes=[("SQLite DB", "*.db"), ("모든 파일", "*.*")]
        )
        if path:
            self.var_db.set(path)

    def _log(self, text: str):
        self.after(0, self._log_main, text)

    def _log_main(self, text: str):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _on_start(self):
        backup_dir = self.var_backup.get().strip()
        db_path = self.var_db.get().strip()

        if not backup_dir or not os.path.isdir(backup_dir):
            messagebox.showwarning("입력 필요", "유효한 백업 폴더를 선택해 주세요.")
            return
        if not db_path:
            messagebox.showwarning("입력 필요", "DB 파일 경로를 입력해 주세요.")
            return

        slackdump = get_slackdump_path()
        if not os.path.isfile(slackdump):
            messagebox.showerror("오류", f"slackdump.exe를 찾을 수 없습니다:\n{slackdump}")
            return

        last_dt = get_last_export_time(backup_dir)
        if not last_dt:
            messagebox.showerror(
                "오류",
                "마지막 Export 기록을 찾을 수 없습니다.\n"
                "backup/last_export.json 또는 backup/thread_archive/summary.json이 필요합니다."
            )
            return

        self.btn_start.config(state="disabled")
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")
        self._log(f"[시작] {datetime.datetime.now(tz=KST).strftime('%Y-%m-%d %H:%M:%S KST')}\n\n")

        thread = threading.Thread(
            target=self._run_update,
            args=(backup_dir, db_path, slackdump, last_dt),
            daemon=True,
        )
        thread.start()

    def _run_update(self, backup_dir: str, db_path: str,
                    slackdump: str, last_dt: datetime.datetime):
        # 1. slackdump export
        last_utc = last_dt.astimezone(UTC)
        time_from_str = last_utc.strftime("%Y-%m-%dT%H:%M:%S")
        now_kst = datetime.datetime.now(tz=KST)
        zip_name = f"slack_export_incremental_{now_kst.strftime('%Y-%m-%d_%H-%M-%S')}.zip"
        zip_path = os.path.join(backup_dir, zip_name)

        cmd = [slackdump, "export",
               "-time-from", time_from_str,
               "-files=false",
               "-o", zip_path]

        self._log(f"기준 시각 (UTC): {time_from_str}\n")
        self._log(f"출력 ZIP: {zip_path}\n")
        self._log("─" * 50 + "\n")

        try:
            self._process = subprocess.Popen(
                cmd,
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            self._log("[오류] slackdump.exe 실행 실패\n")
            self.after(0, self._on_done, False)
            return

        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._log(line)
        self._process.wait()

        if self._process.returncode != 0:
            self._log(f"\n[오류] slackdump 종료 코드: {self._process.returncode}\n")
            self.after(0, self._on_done, False)
            return

        if not os.path.exists(zip_path):
            self._log("[오류] ZIP 파일이 생성되지 않았습니다.\n")
            self.after(0, self._on_done, False)
            return

        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        self._log(f"\n[완료] ZIP: {zip_path} ({size_mb:.1f} MB)\n")
        self._log("─" * 50 + "\n")

        # 2. DB 인제스트
        self._log("DB 업데이트 중...\n")
        try:
            total = ingest_zip_to_db(zip_path, db_path, self._log)
        except Exception as e:
            self._log(f"[오류] DB 업데이트 실패: {e}\n")
            self.after(0, self._on_done, False)
            return

        # 3. last_export.json 갱신
        updated_at = update_last_export(backup_dir, zip_name)
        self._log(f"\n[기록] last_export.json 갱신: {updated_at.strftime('%Y-%m-%d %H:%M:%S KST')}\n")

        self._log("─" * 50 + "\n")
        self._log(f"완료! 새 메시지 {total:,}개가 DB에 반영됐습니다.\n")
        self.after(0, self._on_done, True, total)

    def _on_done(self, success: bool, total: int = 0):
        self.btn_start.config(state="normal")
        self._refresh_last_time(self.var_backup.get())
        if success:
            messagebox.showinfo("완료", f"업데이트 완료!\n새 메시지 {total:,}개 반영됐습니다.")
        else:
            messagebox.showerror("오류", "업데이트 중 오류가 발생했습니다.\n로그를 확인해 주세요.")

    def destroy(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
        super().destroy()


if __name__ == "__main__":
    app = SlackUpdater()
    app.mainloop()
