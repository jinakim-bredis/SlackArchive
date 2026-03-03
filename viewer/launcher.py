import os
import sys
import threading
import webbrowser
import socket
import time
import urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # server.py 상대경로 보장

PORT = 8000


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_and_open():
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=1)
            webbrowser.open(f"http://localhost:{PORT}")
            return
        except Exception:
            time.sleep(0.5)


def run_server():
    import uvicorn
    from server import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def make_tray_icon(stop_event):
    try:
        import pystray
        from PIL import Image, ImageDraw

        # 간단한 보라색 원형 아이콘 생성 (이미지 파일 불필요)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill="#3f0e40")
        draw.text((20, 18), "SA", fill="white")

        def on_open(_):
            webbrowser.open(f"http://localhost:{PORT}")

        def on_quit(_):
            stop_event.set()
            icon.stop()

        icon = pystray.Icon(
            "slack_archive",
            img,
            "Slack Archive Viewer",
            menu=pystray.Menu(
                pystray.MenuItem("브라우저에서 열기", on_open),
                pystray.MenuItem("종료", on_quit),
            ),
        )
        icon.run()
    except ImportError:
        # pystray 없으면 트레이 없이 그냥 실행
        stop_event.wait()


def main():
    stop_event = threading.Event()

    if is_port_in_use(PORT):
        # 이미 서버 실행 중 → 브라우저만 열기
        webbrowser.open(f"http://localhost:{PORT}")
    else:
        # 서버 시작 + 브라우저 오픈
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        threading.Thread(target=wait_and_open, daemon=True).start()

    # 트레이 아이콘 (종료 수단 제공) — 블로킹 호출
    make_tray_icon(stop_event)


if __name__ == "__main__":
    main()
