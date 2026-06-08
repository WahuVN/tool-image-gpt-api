# -*- coding: utf-8 -*-
"""Ghi log Flow ra file flow.log (xem được không cần mở web)."""

import pathlib
import time
import threading

LOG_FILE = pathlib.Path(__file__).parent / "flow.log"
_lock = threading.Lock()
_MAX_BYTES = 2 * 1024 * 1024  # tự cắt khi > 2MB


def log(msg, tag="info"):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{tag}] {msg}"
    print(line)
    try:
        with _lock:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > _MAX_BYTES:
                tail_lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]
                LOG_FILE.write_text("\n".join(tail_lines) + "\n", encoding="utf-8")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def tail(n=200):
    if not LOG_FILE.exists():
        return []
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-n:]
    except Exception:
        return []
