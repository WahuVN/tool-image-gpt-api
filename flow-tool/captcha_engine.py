# -*- coding: utf-8 -*-
"""
CaptchaEngine - bao bọc captcha solver (flow-captcha-solver) với API đồng bộ ổn định
và HỖ TRỢ ĐĂNG NHẬP SẴN bằng cookie.

Vì sao tự viết thay vì dùng FlowCaptchaManager của thư viện:
- Manager gốc có race condition khiến event loop nền thoát sớm trên Python 3.14 /
  Windows, làm get_token trả None.
- Engine này giữ 1 event loop chạy nền (run_forever), dùng ProactorEventLoop
  (bắt buộc để Playwright spawn được tiến trình trên Windows).

Cải tiến quan trọng để token reCAPTCHA đạt điểm cao hơn:
- Bơm cookie đăng nhập Flow vào context trình duyệt của solver -> token được sinh
  trong PHIÊN ĐÃ ĐĂNG NHẬP (giống người dùng thật) thay vì phiên ẩn danh.
"""

import asyncio
import threading
from typing import Optional, List

from flow_captcha_solver import FlowCaptchaPool
from flow_captcha_solver.browser import BrowserInstance


# Khoá hợp lệ cho Playwright add_cookies
_ALLOWED = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}


def _sanitize(cookies: List[dict]) -> List[dict]:
    out = []
    for c in cookies or []:
        d = {k: v for k, v in c.items() if k in _ALLOWED}
        ss = d.get("sameSite")
        if ss not in ("Strict", "Lax", "None"):
            d["sameSite"] = "Lax"
        out.append(d)
    return out


class AuthBrowserInstance(BrowserInstance):
    """BrowserInstance có nạp cookie đăng nhập sau khi tạo context (kể cả khi reset)."""

    def __init__(self, instance_id=0, headless=True, cookies=None):
        super().__init__(instance_id, headless)
        self._auth_cookies = _sanitize(cookies)

    async def initialize(self) -> bool:
        ok = await super().initialize()
        if ok and self._auth_cookies and self.context:
            try:
                await self.context.add_cookies(self._auth_cookies)
                print(f"[Browser-{self.instance_id}] Đã nạp {len(self._auth_cookies)} cookie đăng nhập.")
            except Exception as e:
                print(f"[Browser-{self.instance_id}] Lỗi nạp cookie: {e}")
        return ok


class AuthPool(FlowCaptchaPool):
    """Pool dùng AuthBrowserInstance (đăng nhập sẵn)."""

    def __init__(self, num_browsers=2, headless=True, cookies=None):
        super().__init__(num_browsers=num_browsers, headless=headless)
        self._cookies = cookies

    async def initialize(self) -> bool:
        if self._initialized:
            return True
        print(f"[AuthPool] Initializing {self.num_browsers} browser(s) (đăng nhập sẵn)...")
        success = 0
        for i in range(self.num_browsers):
            b = AuthBrowserInstance(i, self.headless, cookies=self._cookies)
            if await b.initialize():
                self._browsers.append(b)
                success += 1
            else:
                print(f"[AuthPool] Browser {i} FAILED")
        if success:
            self._initialized = True
            print(f"[AuthPool] {success}/{self.num_browsers} browsers ready!")
            return True
        print("[AuthPool] No browsers initialized!")
        return False


class CaptchaEngine:
    def __init__(self, num_browsers: int = 2, headless: bool = True, cookies=None):
        self.num_browsers = num_browsers
        self.headless = headless
        self.cookies = cookies
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._pool: Optional[FlowCaptchaPool] = None
        self._started = False

    def _run_loop(self):
        if hasattr(asyncio, "ProactorEventLoop"):
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro, timeout: float = 120):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def start(self, timeout: float = 120) -> bool:
        if self._started:
            return True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        while self._loop is None or not self._loop.is_running():
            threading.Event().wait(0.02)

        if self.cookies:
            self._pool = AuthPool(num_browsers=self.num_browsers,
                                  headless=self.headless, cookies=self.cookies)
        else:
            self._pool = FlowCaptchaPool(num_browsers=self.num_browsers, headless=self.headless)
        ok = self._submit(self._pool.initialize(), timeout=timeout)
        self._started = bool(ok)
        return self._started

    def get_token(self, project_id: str, timeout: float = 90) -> Optional[str]:
        if not self._started or not self._pool:
            return None
        return self._submit(self._pool.get_token(project_id), timeout=timeout)

    def report_success(self):
        if self._pool:
            self._pool.report_success()

    def report_failure(self, reason: str = ""):
        if self._pool:
            self._pool.report_failure(reason)

    def get_status(self):
        if self._pool:
            return self._pool.get_status()
        return {"initialized": False}

    def stop(self):
        if self._pool and self._loop:
            try:
                self._submit(self._pool.close(), timeout=20)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        self._pool = None
        self._started = False
