from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("ARTIFY_PORT", "8501"))
HOST = os.environ.get("ARTIFY_HOST", "127.0.0.1")
URL = f"http://{HOST}:{PORT}"


def wait_for_server(url: str, timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return 200 <= response.status < 500
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    python_exe = APP_DIR / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        print("Chua setup app. Hay chay setup_9router_image_app.bat truoc.")
        return 1

    env_file = APP_DIR / ".env.9router"
    if not env_file.exists():
        print("Chua co .env.9router. Hay copy .env.9router.example thanh .env.9router va dien URL/KEY.")
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

    launched = False
    edge_paths = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    chrome_paths = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]

    for edge in edge_paths:
        if edge.exists():
            subprocess.Popen([str(edge), f"--app={URL}", "--window-size=1600,1000"])
            launched = True
            break
    if not launched:
        for chrome in chrome_paths:
            if chrome.exists():
                subprocess.Popen([str(chrome), f"--app={URL}", "--window-size=1600,1000"])
                launched = True
                break
    if not launched:
        webbrowser.open(URL)

    print(f"Artify AI Desktop App dang chay tai {URL}")
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
