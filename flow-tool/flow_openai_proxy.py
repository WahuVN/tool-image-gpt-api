# -*- coding: utf-8 -*-
"""
Flow OpenAI-compatible Proxy
============================
Phơi ra API kiểu OpenAI (giống 9Router / proxy Gemini) nhưng bên trong dùng
Google Labs Flow (qua FlowClient + Brave thật để lấy reCAPTCHA token).

=> Trong tool vẽ (Wahu / 9Router app) chỉ cần đặt Base URL = http://localhost:8790
   là vẽ bằng Flow, KHÔNG phải sửa giao diện.

Endpoints (khớp với tool vẽ hiện có):
  GET  /v1/models, /v1/models/image   -> danh sách model
  GET  /api/health, /v1/models/info   -> health
  POST /v1/images/generations         -> tạo ảnh (trả b64_json hoặc binary)

Chạy:  python flow_openai_proxy.py        (mặc định cổng 8790)
Lần đầu sẽ mở Brave (đóng Brave cũ rồi mở lại kèm cổng debug) để lấy token.
"""

import os
import sys
import time
import json
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import parse

import requests

from flow_client import FlowClient, FlowError

# size (WxH) -> aspect ratio của Flow
SIZE_TO_ASPECT = {
    "1024x1024": "IMAGE_ASPECT_RATIO_SQUARE",
    "1024x1536": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1536x1024": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "1024x1792": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1792x1024": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "768x1344": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1344x768": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "896x1152": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1152x896": "IMAGE_ASPECT_RATIO_LANDSCAPE",
}

# Model phơi ra cho app (đều map về model ảnh Flow)
IMAGE_MODELS = ["NARWHAL", "flow-narwhal", "flow"]
MODEL_MAP = {
    "flow": "NARWHAL",
    "flow-narwhal": "NARWHAL",
    "narwhal": "NARWHAL",
}

_client: FlowClient = None
_lock = threading.Lock()


def sniff_content_type(data: bytes) -> str:
    """Nhận dạng định dạng ảnh từ magic bytes (Flow có thể trả JPEG hoặc PNG)."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def size_to_aspect(size):
    if not size:
        return "IMAGE_ASPECT_RATIO_LANDSCAPE"
    return SIZE_TO_ASPECT.get(str(size).strip(), "IMAGE_ASPECT_RATIO_LANDSCAPE")


def map_model(model):
    m = str(model or "").strip()
    return MODEL_MAP.get(m.lower(), "NARWHAL")


def generate_bytes(model, prompt, n, size):
    """Tạo ảnh qua Flow, trả về list bytes PNG."""
    aspect = size_to_aspect(size)
    with _lock:
        urls = _client.generate_images(
            prompt=prompt,
            model=map_model(model),
            aspect_ratio=aspect,
            n=n,
            download=False,   # lấy fifeUrl rồi tự tải bytes
        )
    out = []
    for u in urls:
        r = requests.get(u, timeout=120)
        r.raise_for_status()
        out.append(r.content)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  " + (fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type="image/png"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        path = parse.urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/v1/models", "/v1/models/image"):
            self._send_json({"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "google-flow"} for m in IMAGE_MODELS
            ]})
        elif path in ("/api/health", "/health"):
            self._send_json({"status": "ok", "provider": "flow"})
        elif path == "/v1/models/info":
            self._send_json({"id": "flow", "status": "ok"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = parse.urlparse(self.path).path.rstrip("/") or "/"
        qs = dict(parse.parse_qsl(parse.urlparse(self.path).query))
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if path not in ("/v1/images/generations", "/v1/images/edits"):
            self._send_json({"error": "not found"}, 404)
            return

        try:
            model = str(payload.get("model") or "NARWHAL").strip()
            prompt = str(payload.get("prompt") or "").strip()
            n = int(payload.get("n") or 1)
            size = payload.get("size")
            rf = (qs.get("response_format") or payload.get("response_format") or "b64_json").lower()

            if not prompt:
                self._send_json({"error": {"message": "prompt trống"}}, 400)
                return

            print(f"[gen] model={model} n={n} size={size} rf={rf} prompt={prompt[:50]!r}")
            t0 = time.time()
            images = generate_bytes(model, prompt, n, size)
            print(f"      -> {len(images)} ảnh trong {time.time()-t0:.1f}s")

            if not images:
                self._send_json({"error": {"message": "Flow không trả ảnh"}}, 502)
                return

            if rf == "binary":
                self._send_bytes(images[0], sniff_content_type(images[0]))
                return
            data = [{"b64_json": base64.b64encode(im).decode("ascii")} for im in images]
            self._send_json({"created": int(time.time()), "data": data})
        except FlowError as ex:
            print(f"      !! Flow lỗi: {ex}")
            self._send_json({"error": {"message": str(ex)}}, 502)
        except Exception as ex:
            print(f"      !! lỗi: {ex}")
            self._send_json({"error": {"message": str(ex)}}, 502)


def main():
    global _client
    port = int(os.environ.get("FLOW_PROXY_PORT", "8790"))
    out_dir = os.environ.get("FLOW_OUTPUT_DIR", "output")

    _client = FlowClient(cookie="", token_mode="brave", output_dir=out_dir)
    print("[Flow Proxy] Mở Brave & lấy token (lần đầu hơi chậm)...")
    _client.start()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[Flow Proxy] Sẵn sàng tại http://127.0.0.1:{port}")
    print(f"[Flow Proxy] Trong tool vẽ đặt Base URL = http://localhost:{port} (Key để trống/bất kỳ)")
    print("[Flow Proxy] Ctrl+C để dừng.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Flow Proxy] Đang dừng...")
    finally:
        try:
            _client.stop()
        except Exception:
            pass
        server.server_close()


if __name__ == "__main__":
    main()
