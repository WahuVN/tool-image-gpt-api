# -*- coding: utf-8 -*-
"""
Flow multi-account engine (v2 - kiểu 9Router)
=============================================
- Mỗi acc chỉ cần "Đăng nhập" 1 lần (cửa sổ thường) -> rồi "Kiểm tra" để LƯU COOKIE.
- Cookie được lưu trong accounts.json. Sau đó KHÔNG cần mở trình duyệt của acc nữa.
- Tạo ảnh: access_token + project gọi HTTP bằng cookie đã lưu (không cần trình duyệt).
- Token reCAPTCHA: dùng POOL WORKER (vài trình duyệt dùng chung). Mỗi lần mint:
  xoá cookie worker -> bơm cookie acc -> vào trang project -> execute. => 1 vài tab
  chứa được hết acc, chạy song song.
- Xoay vòng: acc 403/hết quota -> cooldown -> chuyển acc khác.
"""

import os
import re
import json
import time
import asyncio
import threading
import subprocess
import urllib.request
import pathlib
from typing import Optional, List, Dict, Any

try:
    import cookie_import
    from flow_log import log as _flog
except Exception:  # fallback nếu chạy lẻ
    cookie_import = None
    def _flog(msg, tag="info"):
        print(f"[{tag}] {msg}")

HERE = pathlib.Path(__file__).parent
ACCOUNTS_FILE = HERE / "accounts.json"
COOKIES_DIR = HERE / "cookies"          # thả file cookie vào đây để tự nạp
COOKIES_DIR.mkdir(exist_ok=True)
(COOKIES_DIR / "imported").mkdir(exist_ok=True)
WORKER_DATA = HERE / "worker_data"
WORKER_DATA.mkdir(exist_ok=True)
LOGIN_DATA = HERE / "login_data"   # user-data-dir cho login dedicated
LOGIN_DATA.mkdir(exist_ok=True)

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
RECAPTCHA_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
RECAPTCHA_ACTION = "IMAGE_GENERATION"
FLOW_URL = "https://labs.google/fx/tools/flow"
WORKER_BASE_PORT = 9500
NUM_WORKERS = int(os.environ.get("FLOW_WORKERS", "3"))
COOLDOWN_SECONDS = 120
COOKIE_KEYS = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}

BROWSERS = {
    "chrome": {"exes": [rf"{os.environ.get('ProgramFiles','')}\Google\Chrome\Application\chrome.exe",
                        rf"{os.environ.get('ProgramFiles(x86)','')}\Google\Chrome\Application\chrome.exe"],
               "user_data": rf"{LOCALAPPDATA}\Google\Chrome\User Data"},
    "coccoc": {"exes": [rf"{os.environ.get('ProgramFiles(x86)','')}\CocCoc\Browser\Application\browser.exe",
                        rf"{os.environ.get('ProgramFiles','')}\CocCoc\Browser\Application\browser.exe",
                        rf"{LOCALAPPDATA}\CocCoc\Browser\Application\browser.exe"],
               "user_data": rf"{LOCALAPPDATA}\CocCoc\Browser\User Data"},
    "brave": {"exes": [rf"{os.environ.get('ProgramFiles','')}\BraveSoftware\Brave-Browser\Application\brave.exe",
                       rf"{LOCALAPPDATA}\BraveSoftware\Brave-Browser\Application\brave.exe"],
              "user_data": rf"{LOCALAPPDATA}\BraveSoftware\Brave-Browser\User Data"},
}
WORKER_BROWSER = "chrome"   # trình duyệt cho worker pool

EXEC_JS = """
async ([key, action]) => {
  try {
    return await new Promise((resolve) => {
      const to = setTimeout(() => resolve({error:'timeout'}), 30000);
      const run = () => window.grecaptcha.enterprise.execute(key, {action})
        .then(t => { clearTimeout(to); resolve({token:t}); })
        .catch(e => { clearTimeout(to); resolve({error:String(e)}); });
      if (window.grecaptcha && window.grecaptcha.enterprise && window.grecaptcha.enterprise.ready)
        window.grecaptcha.enterprise.ready(run);
      else run();
    });
  } catch(e){ return {error:String(e)}; }
}
"""


def find_browser_exe(browser: str) -> Optional[str]:
    for p in BROWSERS.get(browser, {}).get("exes", []):
        if p and os.path.exists(p):
            return p
    return None


def list_existing_profiles(browser: str) -> List[Dict[str, str]]:
    ud = BROWSERS.get(browser, {}).get("user_data")
    out = []
    if not ud or not os.path.exists(os.path.join(ud, "Local State")):
        return out
    try:
        ls = json.load(open(os.path.join(ud, "Local State"), encoding="utf-8"))
        for d, info in ls.get("profile", {}).get("info_cache", {}).items():
            out.append({"dir": d, "name": info.get("name", d), "email": info.get("user_name", "")})
    except Exception:
        pass
    return out


def _sanitize_cookies(cookies):
    out = []
    for c in cookies or []:
        d = {k: v for k, v in c.items() if k in COOKIE_KEYS}
        if not d.get("name") or "value" not in d:
            continue
        if d.get("sameSite") not in ("Strict", "Lax", "None"):
            d["sameSite"] = "Lax"
        out.append(d)
    return out


class Account:
    def __init__(self, d):
        self.id = d["id"]
        self.name = d.get("name", d["id"])
        self.browser = d.get("browser", "chrome")
        self.mode = d.get("mode", "dedicated")
        self.profile_directory = d.get("profile_directory", "Default")
        self.enabled = bool(d.get("enabled", True))
        self.email = d.get("email", "")
        self.cookies = d.get("cookies", [])   # đã lưu (CDP format)
        # runtime
        self.status = "ready" if self.cookies else "login_needed"
        self.failures = 0
        self.uses = 0
        self.cooldown_until = 0.0
        self.last_error = ""

    @property
    def logged_in(self):
        return any(c.get("name") == "__Secure-next-auth.session-token"
                   and "labs.google" in c.get("domain", "") for c in self.cookies)

    @property
    def login_user_data_dir(self):
        if self.mode == "existing":
            return BROWSERS[self.browser]["user_data"]
        return str(LOGIN_DATA / self.id)

    @property
    def login_profile(self):
        return self.profile_directory if self.mode == "existing" else "Default"

    def cookie_header(self):
        labs = {c["name"]: c["value"] for c in self.cookies if "labs.google" in c.get("domain", "")}
        return "; ".join(f"{k}={v}" for k, v in labs.items())

    def to_dict(self):
        return {"id": self.id, "name": self.name, "browser": self.browser, "mode": self.mode,
                "profile_directory": self.profile_directory, "enabled": self.enabled,
                "email": self.email, "cookies": self.cookies}

    def public_state(self):
        return {"id": self.id, "name": self.name, "browser": self.browser, "mode": self.mode,
                "profile_directory": self.profile_directory, "enabled": self.enabled,
                "email": self.email, "status": self.status, "failures": self.failures,
                "uses": self.uses, "logged_in": self.logged_in,
                "cooldown": max(0, int(self.cooldown_until - time.time())),
                "has_cookies": len(self.cookies) > 0, "last_error": self.last_error[:120]}


class _Worker:
    """1 trình duyệt worker dùng chung để mint token (bơm cookie acc vào)."""
    def __init__(self, idx):
        self.idx = idx
        self.port = WORKER_BASE_PORT + idx
        self.udd = str(WORKER_DATA / f"w{idx}")
        self.proc = None
        self.cdp = None
        self.ctx = None
        self.page = None
        self.lock = None  # asyncio.Lock
        self.busy = False


class AccountManager:
    def __init__(self):
        self.accounts: List[Account] = []
        self._loop = None
        self._thread = None
        self._rr = 0
        self._sel_lock = threading.Lock()
        self._workers: List[_Worker] = []
        self._workers_started = False
        self.load()

    # ----- loop nền -----
    def _run_loop(self):
        self._loop = asyncio.ProactorEventLoop() if hasattr(asyncio, "ProactorEventLoop") else asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def ensure_loop(self):
        if self._loop and self._loop.is_running():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        while self._loop is None or not self._loop.is_running():
            threading.Event().wait(0.02)

    def _submit(self, coro, timeout=120):
        self.ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    # ----- lưu/đọc -----
    def load(self):
        self.accounts = []
        if ACCOUNTS_FILE.exists():
            try:
                for d in json.load(open(ACCOUNTS_FILE, encoding="utf-8")).get("accounts", []):
                    self.accounts.append(Account(d))
            except Exception as e:
                print("[accounts] load error:", e)
        # Tự nạp cookie từ file thả vào thư mục cookies/
        try:
            self.autoload_cookie_files()
        except Exception as e:
            _flog(f"autoload error: {e}", "cookie")

    def save(self):
        ACCOUNTS_FILE.write_text(json.dumps(
            {"accounts": [a.to_dict() for a in self.accounts]}, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, acc_id):
        return next((a for a in self.accounts if a.id == acc_id), None)

    def add_account(self, name, browser="chrome", mode="dedicated", profile_directory="Default"):
        base = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_") or "acc"
        acc_id, i = base, 1
        while self.get(acc_id):
            i += 1; acc_id = f"{base}_{i}"
        acc = Account({"id": acc_id, "name": name, "browser": browser, "mode": mode,
                       "profile_directory": profile_directory, "enabled": True})
        self.accounts.append(acc); self.save()
        return acc

    def delete_account(self, acc_id):
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        self.save()

    def set_enabled(self, acc_id, enabled):
        acc = self.get(acc_id)
        if acc:
            acc.enabled = enabled; self.save()

    # ----- NẠP COOKIE THỦ CÔNG (không cần mở trình duyệt) -----
    def import_cookies(self, acc_id, raw):
        """Nạp cookie cho 1 acc từ chuỗi header / JSON / Netscape."""
        if cookie_import is None:
            return {"ok": False, "error": "Thiếu module cookie_import"}
        acc = self.get(acc_id)
        if not acc:
            return {"ok": False, "error": "Không tìm thấy acc"}
        cookies = cookie_import.parse_cookies(raw)
        if not cookies:
            return {"ok": False, "error": "Không parse được cookie nào"}
        acc.cookies = cookies
        has_sess = cookie_import.has_session(cookies)
        acc.status = "ready" if has_sess else "login_needed"
        if has_sess:
            acc.cooldown_until = 0
            acc.failures = 0
            acc.last_error = ""
        else:
            acc.last_error = "Thiếu __Secure-next-auth.session-token (labs.google)"
        self.save()
        _flog(f"import cookie -> {acc.name}: {len(cookies)} cookie, session={has_sess}", "cookie")
        return {"ok": True, "logged_in": acc.logged_in, "count": len(cookies),
                "has_session": has_sess, "account": acc.public_state()}

    def add_or_update_with_cookies(self, name, raw, browser="manual", mode="manual"):
        """Tạo acc mới (nếu chưa có) rồi nạp cookie. Trùng tên -> cập nhật."""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "Thiếu tên acc"}
        acc = next((a for a in self.accounts if a.name == name or a.id == name), None)
        if not acc:
            acc = self.add_account(name=name, browser=browser, mode=mode)
        return self.import_cookies(acc.id, raw)

    def autoload_cookie_files(self):
        """Quét thư mục cookies/ : mỗi file <tên>.txt|.json -> nạp cho acc cùng tên,
        nạp xong chuyển vào cookies/imported/. Trả về số file đã nạp."""
        if cookie_import is None:
            return 0
        loaded = 0
        for f in list(COOKIES_DIR.glob("*.txt")) + list(COOKIES_DIR.glob("*.json")):
            if f.stem.lower() in ("readme", "readme.txt") or f.stem.startswith("_"):
                continue
            try:
                raw = f.read_text(encoding="utf-8", errors="ignore").strip()
                if not raw:
                    continue
                res = self.add_or_update_with_cookies(f.stem, raw)
                if res.get("ok"):
                    loaded += 1
                    dest = COOKIES_DIR / "imported" / f"{f.stem}_{int(time.time())}{f.suffix}"
                    try:
                        f.replace(dest)
                    except Exception:
                        pass
                    _flog(f"autoload {f.name}: {res.get('count')} cookie, "
                          f"session={res.get('has_session')}", "cookie")
                else:
                    _flog(f"autoload {f.name} LỖI: {res.get('error')}", "cookie")
            except Exception as e:
                _flog(f"autoload {f.name} EXC: {e}", "cookie")
        return loaded

    # ----- launch helper -----
    def _close_browser_procs(self, browser):
        exe = {"chrome": "chrome.exe", "coccoc": "browser.exe", "brave": "brave.exe"}.get(browser)
        if exe:
            subprocess.run(["taskkill", "/F", "/IM", exe, "/T"], capture_output=True)
            time.sleep(1.2)

    def _port_alive(self, port):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    def _launch(self, exe, udd, profile, port, url=None, headless=False, close_browser=None):
        if self._port_alive(port):
            return
        if close_browser:
            self._close_browser_procs(close_browser)
        args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={udd}",
                f"--profile-directory={profile}", "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate,IsolateOrigins,site-per-process"]
        if headless:
            args.append("--headless=new")
        if url:
            args.append(url)
        subprocess.Popen(args)
        for _ in range(60):
            if self._port_alive(port):
                return
            time.sleep(0.5)
        raise RuntimeError(f"Không mở được cổng debug {port}")

    # ----- login + capture cookie -----
    def login_account(self, acc_id):
        acc = self.get(acc_id)
        if not acc:
            return {"ok": False, "error": "not found"}
        exe = find_browser_exe(acc.browser)
        if not exe:
            return {"ok": False, "error": f"Không tìm thấy {acc.browser}"}
        try:
            subprocess.Popen([exe, f"--user-data-dir={acc.login_user_data_dir}",
                              f"--profile-directory={acc.login_profile}",
                              "--no-first-run", "--no-default-browser-check", FLOW_URL])
            acc.status = "login_needed"
            return {"ok": True, "message": "Đăng nhập Google + mở Flow trong cửa sổ. "
                    "Xong ĐÓNG cửa sổ rồi bấm 'Kiểm tra' để lưu cookie."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _capture_async(self, acc: Account):
        """Mở browser acc (cổng debug) đọc cookie google+labs, lưu lại, đóng."""
        from playwright.async_api import async_playwright
        port = WORKER_BASE_PORT + 50 + (abs(hash(acc.id)) % 40)  # cổng tạm riêng
        exe = find_browser_exe(acc.browser)
        close = acc.browser if acc.mode == "existing" else None
        # launch (sync) trong executor để không chặn loop
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._launch(exe, acc.login_user_data_dir, acc.login_profile, port,
                                       FLOW_URL, headless=False, close_browser=close))
        pw = await async_playwright().start()
        try:
            cdp = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = cdp.contexts[0] if cdp.contexts else await cdp.new_context()
            # đảm bảo có page labs.google để cookie nạp
            page = None
            for p in ctx.pages:
                if "labs.google" in (p.url or ""):
                    page = p; break
            if not page:
                page = await ctx.new_page()
                await page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=30000)
            cks = []
            for _ in range(6):
                cks = await ctx.cookies()
                if any(c.get("name") == "__Secure-next-auth.session-token" for c in cks):
                    break
                await asyncio.sleep(1.0)
            wanted = [c for c in cks if "google" in c.get("domain", "")]
            acc.cookies = _sanitize_cookies(wanted)
            await cdp.close()
        finally:
            await pw.stop()
        return acc.logged_in

    def check_login(self, acc_id):
        acc = self.get(acc_id)
        if not acc:
            return False
        try:
            logged = bool(self._submit(self._capture_async(acc), timeout=120))
        except Exception as e:
            acc.last_error = str(e); logged = acc.logged_in
        acc.status = "ready" if acc.logged_in else "login_needed"
        if acc.logged_in:
            acc.cooldown_until = 0; acc.failures = 0
        self.save()
        return acc.logged_in

    # tương thích cũ
    def start_account(self, acc_id, headless=False):
        return self.check_login(acc_id)


    # ----- worker pool -----
    async def _ensure_workers(self):
        from playwright.async_api import async_playwright
        if self._workers_started:
            return
        exe = find_browser_exe(WORKER_BROWSER)
        if not exe:
            raise RuntimeError(f"Worker cần {WORKER_BROWSER} nhưng chưa cài")
        pw = await async_playwright().start()
        self._pw_workers = pw
        for i in range(NUM_WORKERS):
            w = _Worker(i)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda w=w: self._launch(exe, w.udd, "Default", w.port, FLOW_URL, headless=False))
            w.cdp = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{w.port}")
            w.ctx = w.cdp.contexts[0] if w.cdp.contexts else await w.cdp.new_context()
            w.lock = asyncio.Lock()
            self._workers.append(w)
        self._workers_started = True

    async def _mint_async(self, acc: Account, project_id: str):
        await self._ensure_workers()
        # chọn worker rảnh (round-robin qua lock)
        worker = None
        for _ in range(200):
            for w in self._workers:
                if not w.busy:
                    worker = w; w.busy = True; break
            if worker:
                break
            await asyncio.sleep(0.2)
        if not worker:
            worker = self._workers[0]; 
        try:
            async with worker.lock:
                # bơm cookie acc
                try:
                    await worker.ctx.clear_cookies()
                except Exception:
                    pass
                await worker.ctx.add_cookies(acc.cookies)
                page = worker.page
                if page is None:
                    page = await worker.ctx.new_page()
                    worker.page = page
                url = f"https://labs.google/fx/tools/flow/project/{project_id}" if project_id else FLOW_URL
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_function(
                        "() => window.grecaptcha && window.grecaptcha.enterprise && "
                        "typeof window.grecaptcha.enterprise.execute === 'function'", timeout=20000)
                except Exception:
                    pass
                await asyncio.sleep(0.8)
                res = await page.evaluate(EXEC_JS, [RECAPTCHA_KEY, RECAPTCHA_ACTION])
            return res.get("token") if isinstance(res, dict) else None
        finally:
            worker.busy = False

    def get_token(self, acc: Account, project_id=None, timeout=90):
        if not acc.cookies:
            acc.last_error = "chưa có cookie (chưa đăng nhập/kiểm tra)"
            return None
        try:
            return self._submit(self._mint_async(acc, project_id), timeout=timeout)
        except Exception as e:
            acc.last_error = str(e)
            return None

    def get_cookie_header(self, acc: Account, timeout=30):
        return acc.cookie_header()

    # ----- scheduler -----
    def healthy_accounts(self):
        now = time.time()
        return [a for a in self.accounts
                if a.enabled and a.cooldown_until <= now and a.logged_in]

    def pick_account(self):
        with self._sel_lock:
            pool = self.healthy_accounts()
            if not pool:
                return None
            pool.sort(key=lambda a: (a.failures, a.uses))
            acc = pool[self._rr % len(pool)]
            self._rr += 1
            acc.uses += 1
            return acc

    def report_success(self, acc):
        acc.failures = 0; acc.status = "ready"; acc.last_error = ""

    def report_failure(self, acc, reason="", quota=False):
        acc.failures += 1; acc.last_error = reason
        if quota or acc.failures >= 2:
            acc.cooldown_until = time.time() + COOLDOWN_SECONDS
            acc.status = "cooldown"
            _flog(f"{acc.name} -> cooldown {COOLDOWN_SECONDS}s ({reason[:80]})", "acc")
        else:
            _flog(f"{acc.name} lỗi (#{acc.failures}): {reason[:80]}", "acc")

    def start_all_enabled(self, headless=False):
        # với mô hình v2 không cần mở trình duyệt acc; chỉ cần đã có cookie
        pass

    def states(self):
        return [a.public_state() for a in self.accounts]

    def stop_all(self):
        async def _close():
            for w in self._workers:
                try:
                    await w.cdp.close()
                except Exception:
                    pass
            try:
                if getattr(self, "_pw_workers", None):
                    await self._pw_workers.stop()
            except Exception:
                pass
        try:
            self._submit(_close(), timeout=15)
        except Exception:
            pass
