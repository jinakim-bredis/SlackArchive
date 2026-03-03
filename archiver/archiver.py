"""
Slack DM Archiver — tkinter GUI
Python이 없는 PC에서도 실행 가능한 독립 실행 EXE로 패키징 가능.

빌드: archiver/build.bat 실행 → dist/SlackDMArchiver.exe 생성
"""

import os
import sys
import subprocess
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ── slackdump.exe 경로 결정 ──────────────────────────────────────────────────

def get_slackdump_path() -> str:
    """PyInstaller 빌드 여부에 따라 slackdump.exe 경로 반환."""
    if getattr(sys, 'frozen', False):
        # PyInstaller 번들 실행 시 — 임시 압축 해제 폴더
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        # 개발/테스트 시 — archiver.py 위쪽 폴더(프로젝트 루트)
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'slackdump.exe')


# ── 도움말 텍스트 ─────────────────────────────────────────────────────────────

TOKEN_HELP = """\
[Slack Token 추출 방법]

1. 브라우저에서 Slack 웹앱(app.slack.com)에 로그인합니다.
2. F12 → Console 탭을 엽니다.
3. 아래 코드를 붙여넣고 Enter:

   JSON.parse(localStorage.localConfig_v2).teams[
     document.location.pathname.match(/^\\/client\\/([A-Z0-9]+)/)[1]
   ].token

4. 출력된 'xoxc-...' 값을 복사해 Token 필드에 붙여넣습니다.
"""

COOKIE_HELP = """\
[Slack Cookie 추출 방법]

1. 브라우저에서 Slack 웹앱(app.slack.com)에 로그인합니다.
2. F12 → Application 탭 → Cookies → https://app.slack.com 를 엽니다.
3. 이름이 'd' 인 쿠키의 Value를 복사합니다.
   (값이 'xoxd-...' 형태로 시작합니다)
4. 복사한 값을 Cookie 필드에 붙여넣습니다.

※ 쿠키 값이 URL 인코딩(%xx)된 경우 그대로 붙여넣어도 됩니다.
"""


# ── 메인 애플리케이션 ─────────────────────────────────────────────────────────

class SlackDMArchiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Slack DM Archiver")
        self.resizable(False, False)
        self._process: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._build_ui()
        self._set_default_output_path()

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # ── 입력 프레임 ──
        frame_input = ttk.LabelFrame(self, text="인증 정보", padding=10)
        frame_input.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        frame_input.columnconfigure(1, weight=1)

        # Token
        ttk.Label(frame_input, text="Token").grid(row=0, column=0, sticky="w")
        self.var_token = tk.StringVar()
        ttk.Entry(frame_input, textvariable=self.var_token, width=52,
                  show="").grid(row=0, column=1, sticky="ew", padx=(6, 4))
        ttk.Button(frame_input, text="?", width=2,
                   command=lambda: self._show_help("Token 추출 방법", TOKEN_HELP)
                   ).grid(row=0, column=2)

        # Cookie
        ttk.Label(frame_input, text="Cookie").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_cookie = tk.StringVar()
        ttk.Entry(frame_input, textvariable=self.var_cookie, width=52,
                  show="").grid(row=1, column=1, sticky="ew", padx=(6, 4), pady=(6, 0))
        ttk.Button(frame_input, text="?", width=2,
                   command=lambda: self._show_help("Cookie 추출 방법", COOKIE_HELP)
                   ).grid(row=1, column=2, pady=(6, 0))

        # ── 저장 위치 프레임 ──
        frame_output = ttk.LabelFrame(self, text="저장 위치", padding=10)
        frame_output.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        frame_output.columnconfigure(0, weight=1)

        self.var_outpath = tk.StringVar()
        ttk.Entry(frame_output, textvariable=self.var_outpath, width=54
                  ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(frame_output, text="폴더 선택",
                   command=self._browse_output).grid(row=0, column=1)

        # ── 시작 버튼 ──
        self.btn_start = ttk.Button(self, text="  아카이빙 시작  ",
                                    command=self._on_start)
        self.btn_start.grid(row=2, column=0, pady=8)

        # ── 로그 패널 ──
        frame_log = ttk.LabelFrame(self, text="로그", padding=6)
        frame_log.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(3, weight=1)
        self.columnconfigure(0, weight=1)

        self.log_box = scrolledtext.ScrolledText(
            frame_log, width=70, height=14,
            state="disabled", font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.log_box.pack(fill="both", expand=True)

    # ── 기본 저장 경로 ────────────────────────────────────────────────────────

    def _set_default_output_path(self):
        today = datetime.date.today().strftime("%Y-%m-%d")
        default_name = f"slack_dm_{today}.zip"
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        self.var_outpath.set(os.path.join(desktop, default_name))

    # ── 폴더 선택 ────────────────────────────────────────────────────────────

    def _browse_output(self):
        today = datetime.date.today().strftime("%Y-%m-%d")
        init_file = f"slack_dm_{today}.zip"
        path = filedialog.asksaveasfilename(
            title="저장 위치 선택",
            initialfile=init_file,
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")]
        )
        if path:
            self.var_outpath.set(path)

    # ── 도움말 팝업 ──────────────────────────────────────────────────────────

    @staticmethod
    def _show_help(title: str, body: str):
        win = tk.Toplevel()
        win.title(title)
        win.resizable(False, False)
        txt = scrolledtext.ScrolledText(win, width=60, height=18, font=("Consolas", 9))
        txt.pack(padx=10, pady=(10, 4))
        txt.insert("end", body)
        txt.config(state="disabled")
        ttk.Button(win, text="닫기", command=win.destroy).pack(pady=(0, 10))

    # ── 로그 출력 ────────────────────────────────────────────────────────────

    def _log(self, text: str):
        """스레드 안전한 로그 추가."""
        self.after(0, self._log_main, text)

    def _log_main(self, text: str):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    # ── 시작 버튼 핸들러 ──────────────────────────────────────────────────────

    def _on_start(self):
        token = self.var_token.get().strip()
        cookie = self.var_cookie.get().strip()
        outpath = self.var_outpath.get().strip()

        if not token:
            messagebox.showwarning("입력 필요", "Token을 입력해 주세요.")
            return
        if not token.startswith("xoxc-"):
            if not messagebox.askyesno("확인",
                    "Token이 'xoxc-'로 시작하지 않습니다.\n계속하시겠습니까?"):
                return
        if not cookie:
            messagebox.showwarning("입력 필요", "Cookie를 입력해 주세요.")
            return
        if not outpath:
            messagebox.showwarning("입력 필요", "저장 위치를 입력해 주세요.")
            return

        slackdump = get_slackdump_path()
        if not os.path.isfile(slackdump):
            messagebox.showerror("오류",
                f"slackdump.exe를 찾을 수 없습니다:\n{slackdump}")
            return

        self.btn_start.config(state="disabled")
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")
        self._log(f"[시작] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._log(f"출력 경로: {outpath}\n\n")

        thread = threading.Thread(
            target=self._run_archiver,
            args=(token, cookie, outpath, slackdump),
            daemon=True
        )
        thread.start()

    # ── 아카이빙 실행 (백그라운드 스레드) ────────────────────────────────────

    def _run_archiver(self, token: str, cookie: str, outpath: str, slackdump: str):
        env = os.environ.copy()
        env["SLACK_TOKEN"] = token
        env["COOKIE"] = cookie

        cmd = [
            slackdump, "export",
            "-chan-types", "im,mpim",
            "-files=false",
            "-o", outpath,
        ]

        self._log(f"실행: {' '.join(cmd)}\n")
        self._log("─" * 50 + "\n")

        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW  # 콘솔 창 숨김 (Windows)
            )
        except FileNotFoundError:
            self._log("[오류] slackdump.exe 실행 실패. 파일이 존재하는지 확인하세요.\n")
            self.after(0, self._on_done, False)
            return

        # 실시간 로그 스트리밍
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._log(line)

        self._process.wait()
        rc = self._process.returncode

        self._log("─" * 50 + "\n")
        if rc == 0:
            self._log(f"[완료] 종료 코드: {rc}\n")
            self._log(f"ZIP 파일 위치: {outpath}\n\n")
            self._log("viewer PC로 ZIP을 복사한 뒤\n")
            self._log("  python init_db.py <zip 경로>\n")
            self._log("  python server.py\n")
            self._log("로 viewer를 실행하세요.\n")
            self.after(0, self._on_done, True)
        else:
            self._log(f"[오류] 종료 코드: {rc}\n")
            if rc == 1:
                self._log("토큰/쿠키가 만료되었을 수 있습니다. 다시 추출해 주세요.\n")
            self.after(0, self._on_done, False)

    # ── 완료 처리 ────────────────────────────────────────────────────────────

    def _on_done(self, success: bool):
        self.btn_start.config(state="normal")
        if success:
            messagebox.showinfo("완료",
                "아카이빙이 완료되었습니다!\n\n"
                "생성된 ZIP 파일을 viewer PC로 복사하세요.")
        else:
            messagebox.showerror("오류",
                "아카이빙 중 오류가 발생했습니다.\n로그를 확인해 주세요.")

    # ── 창 닫기 ──────────────────────────────────────────────────────────────

    def destroy(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
        super().destroy()


# ── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = SlackDMArchiver()
    app.mainloop()
