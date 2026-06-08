"""Wahu Image Studio - Desktop launcher.

Khởi server Streamlit (nếu chưa chạy) rồi mở app trong cửa sổ Edge/Chrome dạng
desktop. Nếu server đã chạy thì chỉ mở thêm cửa sổ trình duyệt mới.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("WAHU_PORT", os.environ.get("ARTIFY_PORT", "8501")))
HOST = os.environ.get("WAHU_HOST", os.environ.get("ARTIFY_HOST", "127.0.0.1"))
URL = f"http://{HOST}:{PORT}"


def is_server_alive(url: str) -> bool:
    """Quick probe: returns True if Streamlit is already serving on `url`."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def is_port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def wait_for_server(url: str, timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_server_alive(url):
            return True
        time.sleep(0.5)
    return False


def open_app_window(url: str) -> None:
    """Open the URL as a desktop app via Edge/Chrome --app, fallback to default browser."""
    edge_paths = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    chrome_paths = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for path in edge_paths + chrome_paths:
        if path.exists():
            subprocess.Popen([str(path), f"--app={url}", "--window-size=1600,1000"])
            return
    webbrowser.open(url)


def main() -> int:
    python_exe = APP_DIR / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        print("Chua setup app. Hay chay setup_9router_image_app.bat truoc.")
        return 1

    env_file = APP_DIR / ".env.9router"
    if not env_file.exists():
        print("Chua co .env.9router. Hay copy .env.9router.example thanh .env.9router va dien URL/KEY.")
        return 1

    # If server is already running, just attach a new browser window.
    if is_server_alive(URL):
        print(f"Wahu Image Studio da chay tai {URL} - chi mo cua so trinh duyet moi.")
        open_app_window(URL)
        return 0

    if is_port_in_use(HOST, PORT):
        print(
            f"Cong {PORT} dang ban nhung khong phai cua Wahu Image Studio. "
            f"Dat bien moi truong WAHU_PORT roi chay lai, vd: set WAHU_PORT=8502"
        )
        return 1

    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_GLOBAL_EMAIL"] = ""

    process = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "streamlit",
            "run",
            "nine_router_image_app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(PORT),
            "--server.address",
            HOST,
        ],
        cwd=str(APP_DIR),
        env=env,
    )

    if not wait_for_server(URL):
        print("Khong mo duoc server Streamlit trong 30 giay.")
        process.terminate()
        return 1

    open_app_window(URL)
    print(f"Wahu Image Studio dang chay tai {URL}")

    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
