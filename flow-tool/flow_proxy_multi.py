# -*- coding: utf-8 -*-
"""
Flow OpenAI-compatible Proxy (ĐA TÀI KHOẢN)
==========================================
- Phơi API kiểu OpenAI tại http://localhost:8790 cho tool vẽ.
- Nhiều acc Flow xoay vòng + chạy song song. Quản lý acc tại /accounts.

Chạy:  python flow_proxy_multi.py
"""

import os
import json
import time
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import parse

from flow_accounts import AccountManager, list_existing_profiles, BROWSERS, find_browser_exe
from flow_multi import MultiFlow
from flow_log import log as flog, tail as log_tail

PORT = int(os.environ.get("FLOW_PROXY_PORT", "8790"))
MAX_WORKERS = int(os.environ.get("FLOW_MAX_WORKERS", "4"))

SIZE_TO_ASPECT = {
    "1024x1024": "IMAGE_ASPECT_RATIO_SQUARE", "1024x1536": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1536x1024": "IMAGE_ASPECT_RATIO_LANDSCAPE", "1024x1792": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1792x1024": "IMAGE_ASPECT_RATIO_LANDSCAPE", "768x1344": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1344x768": "IMAGE_ASPECT_RATIO_LANDSCAPE", "896x1152": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "1152x896": "IMAGE_ASPECT_RATIO_LANDSCAPE",
}
IMAGE_MODELS = ["NARWHAL", "flow-narwhal", "flow"]

mgr = AccountManager()
multi = MultiFlow(mgr, max_workers=MAX_WORKERS)


def aspect_of(size):
    return SIZE_TO_ASPECT.get(str(size or "").strip(), "IMAGE_ASPECT_RATIO_LANDSCAPE")


def sniff_ct(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/png"


def _page_html() -> str:
    from flow_accounts_ui import ACCOUNTS_HTML
    return ACCOUNTS_HTML


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, ct="image/png"):
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._json({"ok": True})

    # ----------------------------------------------------------- GET
    def do_GET(self):
        path = parse.urlparse(self.path).path.rstrip("/") or "/"
        qs_get = dict(parse.parse_qsl(parse.urlparse(self.path).query))
        if path in ("/v1/models", "/v1/models/image"):
            self._json({"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "google-flow"} for m in IMAGE_MODELS]})
        elif path in ("/api/health", "/health"):
            pool = mgr.healthy_accounts()
            self._json({"status": "ok", "provider": "flow",
                        "accounts_total": len(mgr.accounts), "accounts_ready": len(pool)})
        elif path == "/v1/models/info":
            self._json({"id": "flow", "status": "ok"})
        elif path in ("/accounts", "/"):
            self._html(_page_html())
        elif path == "/api/accounts":
            try:
                mgr.autoload_cookie_files()
            except Exception:
                pass
            self._json({"accounts": mgr.states(),
                        "ready": len(mgr.healthy_accounts())})
        elif path in ("/api/logs", "/logs"):
            try:
                n = int(qs_get.get("n", "200"))
            except Exception:
                n = 200
            self._json({"lines": log_tail(n)})
        elif path == "/api/accounts/browsers":
            out = {}
            for b in BROWSERS:
                out[b] = {"installed": find_browser_exe(b) is not None,
                          "profiles": list_existing_profiles(b)}
            self._json({"browsers": out})
        elif path.startswith("/api/accounts/") and path.endswith("/status"):
            acc_id = path.split("/")[3]
            acc = mgr.get(acc_id)
            if not acc:
                return self._json({"ok": False, "error": "not found"}, 404)
            self._json({"ok": True, "status": multi.get_account_status(acc)})
        else:
            self._json({"error": "not found"}, 404)

    # ----------------------------------------------------------- POST
    def do_POST(self):
        path = parse.urlparse(self.path).path.rstrip("/") or "/"
        qs = dict(parse.parse_qsl(parse.urlparse(self.path).query))

        if path in ("/v1/images/generations", "/v1/images/edits"):
            return self._handle_generate(qs)

        if path == "/api/accounts":
            d = self._body()
            name = (d.get("name") or "").strip()
            if not name:
                return self._json({"ok": False, "error": "Thiếu tên"}, 400)
            acc = mgr.add_account(name=name, browser=d.get("browser", "chrome"),
                                  mode=d.get("mode", "dedicated"),
                                  profile_directory=d.get("profile_directory", "Default"))
            return self._json({"ok": True, "account": acc.public_state()})

        if path == "/api/accounts/import":
            d = self._body()
            return self._json(mgr.add_or_update_with_cookies(
                name=(d.get("name") or "").strip(),
                raw=d.get("raw") or d.get("cookie") or d.get("cookies") or "",
                browser=d.get("browser", "manual"),
                mode=d.get("mode", "manual")))

        if path == "/api/accounts/reload-cookies":
            n = mgr.autoload_cookie_files()
            return self._json({"ok": True, "loaded": n})

        # /api/accounts/{id}/{action}
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "accounts":
            acc_id = parts[2]
            action = parts[3] if len(parts) >= 4 else ""
            if action == "cookies":
                d = self._body()
                return self._json(mgr.import_cookies(
                    acc_id, d.get("raw") or d.get("cookie") or d.get("cookies") or ""))
            if action == "login":
                return self._json(mgr.login_account(acc_id))
            if action == "check":
                return self._json({"ok": True, "logged_in": mgr.check_login(acc_id)})
            if action == "start":
                return self._json({"ok": mgr.start_account(acc_id)})
            if action == "enable":
                mgr.set_enabled(acc_id, True); return self._json({"ok": True})
            if action == "disable":
                mgr.set_enabled(acc_id, False); return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = parse.urlparse(self.path).path.rstrip("/")
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "accounts":
            mgr.delete_account(parts[2])
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def _handle_generate(self, qs):
        d = self._body()
        prompt = (d.get("prompt") or "").strip()
        if not prompt:
            return self._json({"error": {"message": "prompt trống"}}, 400)
        model = str(d.get("model") or "NARWHAL").strip()
        if model.lower() in ("flow", "flow-narwhal", "narwhal"):
            model = "NARWHAL"
        n = int(d.get("n") or 1)
        aspect = aspect_of(d.get("size"))
        rf = (qs.get("response_format") or d.get("response_format") or "b64_json").lower()
        seed = d.get("seed")
        try:
            t0 = time.time()
            images = multi.generate(prompt, model, aspect, n=n, seed=seed)
            flog(f"gen n={n} -> {len(images)} anh / {time.time()-t0:.1f}s | {prompt[:60]}", "gen")
            if not images:
                return self._json({"error": {"message": "Không tạo được ảnh"}}, 502)
            if rf == "binary":
                return self._bytes(images[0], sniff_ct(images[0]))
            data = [{"b64_json": base64.b64encode(im).decode("ascii")} for im in images]
            self._json({"created": int(time.time()), "data": data})
        except Exception as e:
            print(f"[gen] LỖI: {e}")
            flog(f"gen LỖI: {e}", "gen")
            self._json({"error": {"message": str(e)}}, 502)


def main():
    print(f"[Flow Multi] {len(mgr.accounts)} acc trong cấu hình.")
    try:
        n = mgr.autoload_cookie_files()
        if n:
            print(f"[Flow Multi] Đã tự nạp cookie từ {n} file trong cookies/.")
    except Exception:
        pass
    flog(f"khởi động proxy: {len(mgr.accounts)} acc, {len(mgr.healthy_accounts())} sẵn sàng", "boot")
    print("[Flow Multi] (Acc khởi động khi bạn bấm 'Mở'/'Đăng nhập' hoặc khi có request vẽ.)")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[Flow Multi] Sẵn sàng: http://127.0.0.1:{PORT}")
    print(f"[Flow Multi] Quản lý acc: http://127.0.0.1:{PORT}/accounts")
    print(f"[Flow Multi] Base URL cho tool vẽ: http://localhost:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[Flow Multi] Dừng...")
    finally:
        mgr.stop_all()
        srv.server_close()


if __name__ == "__main__":
    main()
