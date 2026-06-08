# -*- coding: utf-8 -*-
"""
Flow API Client - Tạo ảnh qua Google Labs Flow, tự lấy reCAPTCHA token.

Ghép trọn luồng trong PHAN_TICH_FLOW_API.md mục 9.1:
  cookie -> access_token -> projectId -> [recaptcha_token tự động] -> batchGenerateImages -> tải ảnh

Bước [ẨN] recaptcha_token được lấy tự động bằng thư viện flow-captcha-solver.
"""

import json
import time
import uuid
import random
import pathlib
from typing import List, Optional, Dict, Any

import requests
from captcha_engine import CaptchaEngine
from brave_token import BraveTokenEngine

# ---------------------------------------------------------------------------
# Hằng số endpoint (theo tài liệu phân tích)
# ---------------------------------------------------------------------------
SESSION_URL = "https://labs.google/fx/api/auth/session"
CREATE_PROJECT_URL = "https://labs.google/fx/api/trpc/project.createProject"
SANDBOX_BASE = "https://aisandbox-pa.googleapis.com"

DEFAULT_MODEL = "NARWHAL"  # Nano Banana
DEFAULT_ASPECT = "IMAGE_ASPECT_RATIO_LANDSCAPE"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class FlowError(Exception):
    """Lỗi chung khi gọi Flow API."""


class TokenRejected(FlowError):
    """Server từ chối recaptcha token (403 unusual activity)."""


class FlowClient:
    """
    Client tạo ảnh Flow.

    Cách dùng:
        client = FlowClient(cookie="<chuỗi cookie từ trình duyệt>")
        client.start()                       # khởi động pool captcha
        imgs = client.generate_images("a cat", n=1)
        for p in imgs: print(p)
        client.stop()
    """

    def __init__(
        self,
        cookie: str,
        headless: bool = True,
        num_browsers: int = 2,
        output_dir: str = "output",
        max_token_retries: int = 4,
        auth_cookies: Optional[list] = None,
        token_mode: str = "brave",
    ):
        if token_mode != "brave" and (not cookie or not cookie.strip()):
            raise ValueError("Thiếu cookie phiên đăng nhập Flow.")
        self.cookie = (cookie or "").strip()
        self.headless = headless
        self.num_browsers = num_browsers
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_token_retries = max_token_retries
        # cookie dạng có cấu trúc để bơm vào trình duyệt solver (đăng nhập sẵn)
        self.auth_cookies = auth_cookies
        # "brave" = lấy token qua Brave thật (ĐÃ HOẠT ĐỘNG); "solver" = flow-captcha-solver headless
        self.token_mode = token_mode

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Cookie": self.cookie,
        })

        self._access_token: Optional[str] = None
        self._access_token_ts: float = 0.0
        self._engine: Optional[CaptchaEngine] = None

    # ------------------------------------------------------------------ pool
    def start(self):
        """Khởi động bộ lấy recaptcha token."""
        if self.token_mode == "brave":
            # Cách đã hoạt động: lấy token qua Brave thật + action IMAGE_GENERATION
            self._engine = BraveTokenEngine()
            self._engine.start()
            # Lấy cookie từ chính phiên Brave đang mở (nếu chưa cung cấp)
            try:
                fresh = self._engine.get_cookies_header(labs_only=True)
                if fresh:
                    self.cookie = fresh
                    self._session.headers["Cookie"] = fresh
                    # access_token cũ (nếu có) không còn hợp -> xoá cache
                    self._access_token = None
            except Exception as e:
                print(f"[Flow] Cảnh báo: không tự lấy cookie từ Brave: {e}")
        else:
            # flow-captcha-solver (headless) - hiện bị reCAPTCHA chặn
            self._engine = CaptchaEngine(num_browsers=self.num_browsers,
                                         headless=self.headless,
                                         cookies=self.auth_cookies)
            self._engine.start()

    def stop(self):
        """Dừng pool trình duyệt."""
        if self._engine:
            self._engine.stop()
            self._engine = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    # --------------------------------------------------------------- BƯỚC 1
    def get_access_token(self, force: bool = False) -> str:
        """Lấy Bearer access_token từ session (cache ~50 phút)."""
        if (not force and self._access_token
                and time.time() - self._access_token_ts < 50 * 60):
            return self._access_token

        resp = self._session.get(SESSION_URL, timeout=30)
        if resp.status_code != 200:
            raise FlowError(f"Lấy session lỗi HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except Exception:
            raise FlowError("Session trả về không phải JSON. Cookie có thể đã hết hạn.")

        token = data.get("access_token")
        if not token:
            raise FlowError(
                "Không có access_token trong session. "
                "Cookie sai hoặc đã đăng xuất. Hãy lấy lại cookie mới."
            )
        self._access_token = token
        self._access_token_ts = time.time()
        return token

    # --------------------------------------------------------------- BƯỚC 2
    def create_project(self, title: str = "Auto Project") -> str:
        """Tạo project mới, trả projectId."""
        body = {"json": {"projectTitle": title, "toolName": "PINHOLE"}}
        resp = self._session.post(
            CREATE_PROJECT_URL,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise FlowError(f"Tạo project lỗi HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            return data["result"]["data"]["json"]["result"]["projectId"]
        except Exception:
            raise FlowError(f"Không đọc được projectId từ phản hồi: {json.dumps(data)[:300]}")

    # --------------------------------------------------------------- BƯỚC 3
    def _get_recaptcha_token(self, project_id: str) -> str:
        """[BƯỚC ẨN] Lấy recaptcha token tự động qua captcha solver."""
        if not self._engine:
            raise FlowError("Chưa gọi start(). Hãy start() trước khi tạo ảnh.")
        token = self._engine.get_token(project_id)
        if not token:
            raise FlowError("Không lấy được recaptcha token.")
        return token

    # ------------------------------------------------------- BƯỚC 4 + 5 + 6
    def _build_body(self, prompt, model, aspect_ratio, n, seed,
                    project_id, recaptcha_token) -> Dict[str, Any]:
        session_id = ";" + str(int(time.time() * 1000))
        batch_id = str(uuid.uuid4())
        client_context = {
            "recaptchaContext": {
                "token": recaptcha_token,
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
            "projectId": project_id,
            "tool": "PINHOLE",
            "sessionId": session_id,
        }
        requests_list = []
        for _ in range(n):
            requests_list.append({
                "clientContext": client_context,
                "imageModelName": model,
                "imageAspectRatio": aspect_ratio,
                "structuredPrompt": {"parts": [{"text": prompt}]},
                "seed": seed if seed is not None else random.randint(1, 2_147_483_646),
                "imageInputs": [],
            })
        return {
            "clientContext": client_context,
            "mediaGenerationContext": {"batchId": batch_id},
            "useNewMedia": True,
            "requests": requests_list,
        }

    def _call_generate(self, project_id, body, access_token) -> Dict[str, Any]:
        url = f"{SANDBOX_BASE}/v1/projects/{project_id}/flowMedia:batchGenerateImages"
        resp = self._session.post(
            url,
            data=json.dumps(body),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "text/plain;charset=UTF-8",
            },
            timeout=120,
        )
        if resp.status_code == 401:
            raise FlowError("401 - access_token hết hạn")
        if resp.status_code == 403:
            raise TokenRejected(f"403 - {resp.text[:200]}")
        if resp.status_code != 200:
            raise FlowError(f"Generate lỗi HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def generate_images(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        aspect_ratio: str = DEFAULT_ASPECT,
        n: int = 1,
        seed: Optional[int] = None,
        project_id: Optional[str] = None,
        project_title: str = "Auto Project",
        download: bool = True,
    ) -> List[str]:
        """
        Tạo ảnh từ prompt. Trả về danh sách đường dẫn file (nếu download=True)
        hoặc danh sách fifeUrl (nếu download=False).

        Tự retry khi token bị từ chối (403): báo failure -> lấy token mới -> thử lại.
        """
        access_token = self.get_access_token()
        if not project_id:
            project_id = self.create_project(project_title)
            print(f"[Flow] Project mới: {project_id}")

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_token_retries + 1):
            print(f"[Flow] Lần thử {attempt}/{self.max_token_retries} - lấy recaptcha token...")
            recaptcha_token = self._get_recaptcha_token(project_id)
            body = self._build_body(prompt, model, aspect_ratio, n, seed,
                                    project_id, recaptcha_token)
            try:
                data = self._call_generate(project_id, body, access_token)
                self._engine.report_success()
                return self._handle_response(data, download)
            except TokenRejected as e:
                last_err = e
                print(f"[Flow] Token bị từ chối: {e}. Lấy token mới và thử lại...")
                self._engine.report_failure("403 token rejected")
                time.sleep(1.5)
            except FlowError as e:
                if "401" in str(e):
                    print("[Flow] Token Bearer hết hạn, làm mới...")
                    access_token = self.get_access_token(force=True)
                    continue
                raise

        raise FlowError(f"Hết lượt thử. Lỗi cuối: {last_err}")

    # --------------------------------------------------------------- BƯỚC 7
    def _handle_response(self, data: Dict[str, Any], download: bool) -> List[str]:
        media = data.get("media", [])
        if not media:
            raise FlowError(f"Phản hồi không có media: {json.dumps(data)[:300]}")
        results = []
        for i, m in enumerate(media):
            img = m.get("image", {}).get("generatedImage", {})
            url = img.get("fifeUrl")
            if not url:
                continue
            if not download:
                results.append(url)
                continue
            fname = self.output_dir / f"flow_{int(time.time())}_{i}_{img.get('seed', 0)}.png"
            self._download(url, fname)
            print(f"[Flow] Đã lưu: {fname}")
            results.append(str(fname))
        return results

    def _download(self, url: str, path: pathlib.Path):
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
