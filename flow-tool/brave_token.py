# -*- coding: utf-8 -*-
"""
BraveTokenEngine - lấy reCAPTCHA Enterprise token bằng chính BRAVE THẬT (qua CDP).

ĐÂY LÀ CÁCH ĐÃ CHỨNG MINH HOẠT ĐỘNG (tạo được ảnh thật), nhờ 2 yếu tố:
1. action = "IMAGE_GENERATION" (đúng action web Flow dùng; KHÔNG phải FLOW_GENERATION).
2. Token sinh trong Brave thật (profile thật, có reputation) -> điểm reCAPTCHA đủ cao.
   Trình duyệt headless/profile mới bị chấm điểm bot -> 403.

Engine giữ 1 event loop nền (ProactorEventLoop) + 1 phiên Playwright connect_over_cdp
tới Brave đang mở với --remote-debugging-port.
"""

import time
import asyncio
import threading
import subprocess
import urllib.request
from typing import Optional

import cookie_grabber as cg

RECAPTCHA_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
RECAPTCHA_ACTION = "IMAGE_GENERATION"
DEBUG_PORT = 9222

_EXEC_JS = """
async ([key, action]) => {
  try {
    return await new Promise((resolve) => {
      const to = setTimeout(() => resolve({error: 'timeout'}), 30000);
      const run = () => window.grecaptcha.enterprise.execute(key, {action})
        .then(t => { clearTimeout(to); resolve({token: t}); })
        .catch(e => { clearTimeout(to); resolve({error: String(e)}); });
      if (window.grecaptcha && window.grecaptcha.enterprise && window.grecaptcha.enterprise.ready)
        window.grecaptcha.enterprise.ready(run);
      else run();
    });
  } catch (e) { return {error: String(e)}; }
}
"""


class BraveTokenEngine:
    def __init__(self, browser: str = "brave", port: int = DEBUG_PORT,
                 action: str = RECAPTCHA_ACTION, close_existing: bool = True):
        self.browser = browser
        self.port = port
        self.action = action
        self.close_existing = close_existing

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._pw = None
        self._cdp = None
        self._ctx = None
        self._page = None
        self._current_project = None
        self._proc = None
        self._started = False

    # ---------------------------------------------------------------- loop
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

    # ------------------------------------------------------------- launch
    def _launch_brave(self):
        exe = cg._find_exe(self.browser)
        if not exe:
            raise RuntimeError(f"Không tìm thấy {self.browser}.exe")
        user_data = cg.BROWSERS[self.browser]

        # Nếu cổng debug đã sống thì tái dùng, khỏi mở lại
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            pass

        if self.close_existing and cg.is_browser_running(self.browser):
            cg.close_browser(self.browser)
            time.sleep(1.0)

        self._proc = subprocess.Popen([
            exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={user_data}",
            "--profile-directory=Default",
            "https://labs.google/fx/tools/flow",
        ])
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("Không kết nối được cổng debug Brave")

    async def _connect(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._cdp = await self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self._ctx = self._cdp.contexts[0] if self._cdp.contexts else await self._cdp.new_context()

    async def _ensure_page(self, project_id: Optional[str]):
        target = (f"https://labs.google/fx/tools/flow/project/{project_id}"
                  if project_id else "https://labs.google/fx/tools/flow")
        # tái dùng page nếu cùng project
        if self._page is not None and self._current_project == project_id:
            try:
                _ = self._page.url
                return self._page
            except Exception:
                self._page = None

        # tìm tab sẵn có khớp
        for p in self._ctx.pages:
            try:
                if project_id and f"project/{project_id}" in p.url:
                    self._page = p
                    self._current_project = project_id
                    return p
            except Exception:
                pass

        # mở/đi tới trang
        page = None
        for p in self._ctx.pages:
            try:
                if "labs.google" in p.url:
                    page = p
                    break
            except Exception:
                pass
        if page is None:
            page = await self._ctx.new_page()
        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        # chờ grecaptcha.enterprise
        try:
            await page.wait_for_function(
                "() => window.grecaptcha && window.grecaptcha.enterprise && "
                "typeof window.grecaptcha.enterprise.execute === 'function'",
                timeout=20000)
        except Exception:
            pass
        self._page = page
        self._current_project = project_id
        return page

    async def _get_token_async(self, project_id: Optional[str]):
        page = await self._ensure_page(project_id)
        result = await page.evaluate(_EXEC_JS, [RECAPTCHA_KEY, self.action])
        if isinstance(result, dict):
            return result.get("token")
        return None

    async def _get_cookies_async(self):
        return await self._ctx.cookies()

    def get_cookies_header(self, labs_only: bool = True, timeout: float = 30) -> str:
        """Đọc cookie từ chính phiên Brave đang mở. Trả chuỗi 'name=value; ...'."""
        cks = self._submit(self._get_cookies_async(), timeout=timeout)
        out = {}
        for c in cks:
            dom = c.get("domain", "")
            if labs_only:
                if "labs.google" in dom:
                    out[c["name"]] = c["value"]
            else:
                if "google" in dom:
                    out[c["name"]] = c["value"]
        return "; ".join(f"{k}={v}" for k, v in out.items())

    # -------------------------------------------------------------- public
    def start(self, timeout: float = 120) -> bool:
        if self._started:
            return True
        self._launch_brave()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        while self._loop is None or not self._loop.is_running():
            threading.Event().wait(0.02)
        self._submit(self._connect(), timeout=timeout)
        self._started = True
        return True

    def get_token(self, project_id: Optional[str] = None, timeout: float = 90) -> Optional[str]:
        if not self._started:
            return None
        return self._submit(self._get_token_async(project_id), timeout=timeout)

    # API tương thích với CaptchaEngine (để FlowClient dùng chung)
    def report_success(self):
        pass

    def report_failure(self, reason: str = ""):
        pass

    def stop(self):
        async def _close():
            try:
                if self._cdp:
                    await self._cdp.close()
            except Exception:
                pass
            try:
                if self._pw:
                    await self._pw.stop()
            except Exception:
                pass
        if self._loop:
            try:
                self._submit(_close(), timeout=15)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        self._started = False
