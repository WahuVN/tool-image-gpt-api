# -*- coding: utf-8 -*-
"""
Gemini OpenAI-compatible Proxy
==============================
Một server nhỏ phơi ra API kiểu OpenAI (giống 9Router) nhưng bên trong gọi
Google Gemini API CHÍNH THỨC để tạo ảnh. Nhờ vậy tool Wahu/9Router hiện có
chỉ cần đổi Base URL sang proxy này là dùng được Nano Banana (gemini-2.5-flash-image)
và Imagen — hợp pháp, ổn định, không sợ khóa tài khoản.

Hỗ trợ:
  GET  /v1/models            -> danh sách model (OpenAI format)
  GET  /v1/models/image      -> danh sách model ảnh
  GET  /api/health           -> trạng thái
  POST /v1/images/generations-> tạo ảnh (OpenAI format, trả b64_json hoặc binary)

Cấu hình: tạo file .env.gemini cạnh file này:
  GEMINI_API_KEY=AIza...     (lấy ở https://aistudio.google.com/apikey)
  PROXY_PORT=8788            (tuỳ chọn)

Chạy:
  python gemini_openai_proxy.py
Rồi trong app Wahu đặt Base URL = http://localhost:8788  (Key để trống hoặc bất kỳ).
"""

import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Map "size" (WxH) -> aspectRatio cho Imagen / imageConfig
SIZE_TO_RATIO = {
    "1024x1024": "1:1", "1024x1536": "2:3", "1536x1024": "3:2",
    "1024x1792": "9:16", "1792x1024": "16:9", "768x1344": "9:16",
    "1344x768": "16:9", "896x1152": "3:4", "1152x896": "4:3",
}

# Model phơi ra cho app
IMAGE_MODELS = [
    "gemini-2.5-flash-image",        # Nano Banana
    "gemini-2.5-flash-image-preview",
    "imagen-4.0-generate-001",
    "imagen-4.0-fast-generate-001",
    "imagen-4.0-ultra-generate-001",
    "imagen-3.0-generate-002",
]


def load_env():
    env_file = BASE_DIR / ".env.gemini"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_api_key(header_auth: str | None) -> str:
    # Ưu tiên key trong header Authorization nếu nó là key Gemini (AIza...)
    if header_auth:
        tok = header_auth.replace("Bearer", "").strip()
        if tok.startswith("AIza"):
            return tok
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if not key:
        raise RuntimeError("Thiếu GEMINI_API_KEY (đặt trong .env.gemini).")
    return key


def _http_post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", api_key)
    try:
        with request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API lỗi [{ex.code}]: {text[:600]}") from ex


def gen_gemini_image(model: str, prompt: str, n: int, size: str | None, api_key: str) -> list[bytes]:
    """gemini-2.5-flash-image: dùng generateContent, trả nhiều ảnh bằng cách gọi n lần."""
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    gen_cfg = {"responseModalities": ["IMAGE"]}
    ratio = SIZE_TO_RATIO.get((size or "").lower())
    if ratio:
        gen_cfg["imageConfig"] = {"aspectRatio": ratio}

    images: list[bytes] = []
    for _ in range(max(1, n)):
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        data = _http_post_json(url, payload, api_key)
        for cand in data.get("candidates", []):
            for part in (cand.get("content", {}) or {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    images.append(base64.b64decode(inline["data"]))
    if not images:
        raise RuntimeError("Gemini không trả ảnh (có thể bị chặn nội dung).")
    return images


def gen_imagen(model: str, prompt: str, n: int, size: str | None, api_key: str) -> list[bytes]:
    """imagen-*: dùng :predict."""
    url = f"{GEMINI_BASE}/models/{model}:predict"
    params = {"sampleCount": max(1, min(n, 4))}
    ratio = SIZE_TO_RATIO.get((size or "").lower())
    if ratio:
        params["aspectRatio"] = ratio
    payload = {"instances": [{"prompt": prompt}], "parameters": params}
    data = _http_post_json(url, payload, api_key)
    images = []
    for pred in data.get("predictions", []):
        b64 = pred.get("bytesBase64Encoded") or pred.get("bytes_base64_encoded")
        if b64:
            images.append(base64.b64decode(b64))
    if not images:
        raise RuntimeError("Imagen không trả ảnh.")
    return images


def generate(model: str, prompt: str, n: int, size: str | None, api_key: str) -> list[bytes]:
    if model.startswith("imagen"):
        return gen_imagen(model, prompt, n, size, api_key)
    return gen_gemini_image(model, prompt, n, size, api_key)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  " + (fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type="image/png"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse_path(self.path)
        if path in ("/v1/models", "/v1/models/image"):
            self._send_json({"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "google"} for m in IMAGE_MODELS
            ]})
        elif path == "/api/health":
            self._send_json({"status": "ok", "provider": "gemini"})
        elif path == "/v1/models/info":
            self._send_json({"id": "gemini", "status": "ok"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse_path(self.path)
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
            api_key = get_api_key(self.headers.get("Authorization"))
            model = str(payload.get("model") or "gemini-2.5-flash-image").strip()
            prompt = str(payload.get("prompt") or "").strip()
            n = int(payload.get("n") or 1)
            size = payload.get("size")
            rf = (qs.get("response_format") or payload.get("response_format") or "b64_json").lower()

            if not prompt:
                self._send_json({"error": {"message": "prompt trống"}}, 400)
                return

            print(f"[gen] model={model} n={n} size={size} rf={rf} prompt={prompt[:50]!r}")
            t0 = time.time()
            images = generate(model, prompt, n, size, api_key)
            print(f"      -> {len(images)} ảnh trong {time.time()-t0:.1f}s")

            if rf == "binary":
                self._send_bytes(images[0], "image/png")
                return
            data = [{"b64_json": base64.b64encode(im).decode("ascii")} for im in images]
            self._send_json({"created": int(time.time()), "data": data})
        except Exception as ex:
            print(f"      !! lỗi: {ex}")
            self._send_json({"error": {"message": str(ex)}}, 502)


def urlparse_path(p: str) -> str:
    return parse.urlparse(p).path.rstrip("/") or "/"


def main():
    load_env()
    port = int(os.environ.get("PROXY_PORT", "8788"))
    try:
        get_api_key(None)
        key_ok = "OK"
    except Exception:
        key_ok = "CHƯA CÓ KEY (đặt GEMINI_API_KEY trong .env.gemini)"
    print("=" * 64)
    print("GEMINI OpenAI-compatible Proxy")
    print(f"  URL    : http://localhost:{port}")
    print(f"  API key: {key_ok}")
    print(f"  Models : {', '.join(IMAGE_MODELS)}")
    print("=" * 64)
    print("Trong app Wahu/9Router: Base URL = http://localhost:%d , Key để trống." % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
