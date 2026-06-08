# -*- coding: utf-8 -*-
"""
HTTP server cục bộ để tool vẽ ảnh (D:\\TOOL\\TOOL Anh) gọi qua HTTP.

Chạy:
  python server.py            # mặc định http://127.0.0.1:8799
  python server.py --port 9000 --show

API:
  POST /generate
    body JSON: {
       "prompt": "a cat",
       "model": "NARWHAL",          (tuỳ chọn)
       "aspect": "LANDSCAPE",       (LANDSCAPE/PORTRAIT/SQUARE, tuỳ chọn)
       "n": 1,                       (tuỳ chọn)
       "seed": 123,                  (tuỳ chọn)
       "download": true              (true=tải file & trả path, false=trả fifeUrl)
    }
    -> { "ok": true, "images": ["<path hoặc url>", ...] }
    -> { "ok": false, "error": "..." }

  GET /health  -> { "ok": true }

Server giữ pool captcha sống suốt vòng đời để tạo ảnh nhanh cho các lần sau.
"""

import sys
import json
import argparse
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from flow_client import FlowClient, FlowError

ASPECT_MAP = {
    "LANDSCAPE": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "PORTRAIT": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "SQUARE": "IMAGE_ASPECT_RATIO_SQUARE",
}

COOKIE_FILE = pathlib.Path(__file__).parent / "flow_cookie.txt"

_client: FlowClient = None
_lock = threading.Lock()


def _json(handler, code, obj):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # tắt log mặc định

    def do_OPTIONS(self):
        _json(self, 200, {"ok": True})

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            _json(self, 200, {"ok": True})
        else:
            _json(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/generate":
            _json(self, 404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            _json(self, 400, {"ok": False, "error": f"JSON lỗi: {e}"})
            return

        prompt = req.get("prompt")
        if not prompt:
            _json(self, 400, {"ok": False, "error": "Thiếu 'prompt'"})
            return

        aspect = ASPECT_MAP.get(str(req.get("aspect", "LANDSCAPE")).upper(),
                                ASPECT_MAP["LANDSCAPE"])
        try:
            # Serialize: pool captcha không nên gọi song song quá mức từ 1 server đơn
            with _lock:
                images = _client.generate_images(
                    prompt=prompt,
                    model=req.get("model", "NARWHAL"),
                    aspect_ratio=aspect,
                    n=int(req.get("n", 1)),
                    seed=req.get("seed"),
                    project_id=req.get("project_id"),
                    download=bool(req.get("download", True)),
                )
            _json(self, 200, {"ok": True, "images": images})
        except FlowError as e:
            _json(self, 502, {"ok": False, "error": str(e)})
        except Exception as e:
            _json(self, 500, {"ok": False, "error": str(e)})


def main():
    global _client
    parser = argparse.ArgumentParser(description="Flow image server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--browsers", type=int, default=2)
    parser.add_argument("--show", action="store_true", help="Hiện cửa sổ trình duyệt")
    parser.add_argument("--out", default="output")
    args = parser.parse_args()

    if not COOKIE_FILE.exists() or not COOKIE_FILE.read_text(encoding="utf-8").strip():
        cookie = ""  # chế độ brave tự lấy cookie từ Brave đang mở
    else:
        cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()

    _client = FlowClient(
        cookie=cookie,
        headless=not args.show,
        num_browsers=args.browsers,
        output_dir=args.out,
        token_mode="brave",
    )
    print("[Server] Mở Brave và lấy token (lần đầu hơi chậm)...")
    _client.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[Server] Sẵn sàng tại http://{args.host}:{args.port}")
    print("[Server] POST /generate  |  GET /health  |  Ctrl+C để dừng")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Đang dừng...")
    finally:
        _client.stop()
        server.server_close()


if __name__ == "__main__":
    main()
