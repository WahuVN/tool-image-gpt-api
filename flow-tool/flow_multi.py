# -*- coding: utf-8 -*-
"""
MultiFlow - tạo ảnh Flow qua nhiều tài khoản, xoay vòng + chạy song song.
Mỗi acc tự quản access_token + projectId riêng (theo cookie của acc).
"""

import json
import time
import uuid
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List

import requests

from flow_accounts import AccountManager, Account

SESSION_URL = "https://labs.google/fx/api/auth/session"
CREATE_PROJECT_URL = "https://labs.google/fx/api/trpc/project.createProject"
SANDBOX_BASE = "https://aisandbox-pa.googleapis.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class _AccSession:
    """Phiên HTTP + access_token + project cho 1 acc."""
    def __init__(self, mgr: AccountManager, acc: Account):
        self.mgr = mgr
        self.acc = acc
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.access_token = None
        self.access_ts = 0.0
        self.project_id = None
        self.last_detail = ""
        self.lock = threading.Lock()

    def refresh_cookie(self):
        cookie = self.mgr.get_cookie_header(self.acc)
        if cookie:
            self.session.headers["Cookie"] = cookie
        return cookie

    def get_access_token(self, force=False) -> Optional[str]:
        if not force and self.access_token and time.time() - self.access_ts < 50 * 60:
            return self.access_token
        if "Cookie" not in self.session.headers:
            self.refresh_cookie()
        r = self.session.get(SESSION_URL, timeout=30)
        if r.status_code != 200:
            self.last_detail = f"session HTTP {r.status_code}: {r.text[:120]}"
            return None
        tok = (r.json() or {}).get("access_token")
        if tok:
            self.access_token = tok
            self.access_ts = time.time()
        else:
            self.last_detail = "session ko co access_token (cookie het han?)"
        return tok

    def get_project(self) -> Optional[str]:
        if self.project_id:
            return self.project_id
        body = {"json": {"projectTitle": f"Auto {self.acc.id}", "toolName": "PINHOLE"}}
        r = self.session.post(CREATE_PROJECT_URL, json=body,
                              headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code != 200:
            self.last_detail = f"createProject HTTP {r.status_code}: {r.text[:150]}"
            return None
        try:
            self.project_id = r.json()["result"]["data"]["json"]["result"]["projectId"]
        except Exception as e:
            self.last_detail = f"createProject parse: {e} | {r.text[:150]}"
            return None
        return self.project_id


class MultiFlow:
    def __init__(self, manager: AccountManager, max_workers: int = 4, max_account_retries: int = 3):
        self.mgr = manager
        self.max_workers = max_workers
        self.max_account_retries = max_account_retries
        self._sessions = {}
        self._sessions_lock = threading.Lock()

    def _sess(self, acc: Account) -> _AccSession:
        with self._sessions_lock:
            s = self._sessions.get(acc.id)
            if not s:
                s = _AccSession(self.mgr, acc)
                self._sessions[acc.id] = s
            return s

    def _build_body(self, prompt, model, aspect, seed, project_id, recaptcha_token):
        cc = {
            "recaptchaContext": {"token": recaptcha_token,
                                 "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"},
            "projectId": project_id, "tool": "PINHOLE",
            "sessionId": ";" + str(int(time.time() * 1000)),
        }
        return {
            "clientContext": cc,
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "useNewMedia": True,
            "requests": [{
                "clientContext": cc,
                "imageModelName": model,
                "imageAspectRatio": aspect,
                "structuredPrompt": {"parts": [{"text": prompt}]},
                "seed": seed if seed is not None else random.randint(1, 2_147_483_646),
                "imageInputs": [],
            }],
        }

    def _gen_with_account(self, acc: Account, prompt, model, aspect, seed) -> Optional[bytes]:
        """Tạo 1 ảnh bằng 1 acc cụ thể. Raise nếu token bị từ chối (để xoay acc)."""
        s = self._sess(acc)
        with s.lock:
            access = s.get_access_token()
            if not access:
                raise RuntimeError(f"no_access_token: {s.last_detail}")
            project = s.get_project()
            if not project:
                raise RuntimeError(f"no_project: {s.last_detail}")
        token = self.mgr.get_token(acc, project_id=project)
        if not token:
            raise RuntimeError("no_recaptcha_token")
        body = self._build_body(prompt, model, aspect, seed, project, token)
        url = f"{SANDBOX_BASE}/v1/projects/{project}/flowMedia:batchGenerateImages"
        r = s.session.post(url, data=json.dumps(body),
                           headers={"Authorization": f"Bearer {access}",
                                    "Content-Type": "text/plain;charset=UTF-8"}, timeout=120)
        if r.status_code == 401:
            s.get_access_token(force=True)
            raise RuntimeError("401_token_expired")
        if r.status_code == 403:
            raise PermissionError(f"403:{r.text[:400]}")
        if r.status_code != 200:
            raise RuntimeError(f"http_{r.status_code}:{r.text[:400]}")
        data = r.json()
        media = data.get("media", [])
        if not media:
            raise RuntimeError("no_media")
        fife = media[0].get("image", {}).get("generatedImage", {}).get("fifeUrl")
        if not fife:
            raise RuntimeError("no_fifeurl")
        img = requests.get(fife, timeout=120)
        img.raise_for_status()
        return img.content

    def generate_one(self, prompt, model, aspect, seed) -> bytes:
        """Tạo 1 ảnh, tự xoay acc khi lỗi/quota."""
        last = "no_account"
        tried = 0
        for _ in range(self.max_account_retries):
            acc = self.mgr.pick_account()
            if not acc:
                reasons = []
                for a in self.mgr.accounts:
                    if not a.enabled:
                        continue
                    if not a.logged_in:
                        reasons.append(f"{a.name}: chưa đăng nhập/cookie")
                    elif a.cooldown_until > time.time():
                        reasons.append(f"{a.name}: cooldown ({a.last_error[:60]})")
                detail = " | ".join(reasons) if reasons else "chưa có acc nào đăng nhập"
                if tried == 0:
                    raise RuntimeError(f"Không có acc sẵn sàng. {detail}")
                raise RuntimeError(f"Hết acc khỏe. Lỗi gần nhất: {last}")
            tried += 1
            try:
                data = self._gen_with_account(acc, prompt, model, aspect, seed)
                self.mgr.report_success(acc)
                return data
            except PermissionError as e:
                last = str(e)
                self.mgr.report_failure(acc, last, quota=True)
                time.sleep(0.3)
            except Exception as e:
                last = str(e)
                quota = ("401" in last or "Unauthorized" in last)
                self.mgr.report_failure(acc, last, quota=quota)
                time.sleep(0.2)
        raise RuntimeError(f"Hết lượt thử. Lỗi cuối: {last}")

    def get_account_status(self, acc: Account) -> dict:
        """Trạng thái acc: email + còn đăng nhập + điểm/quota còn lại."""
        info = {"email": None, "expires": None, "credits": None,
                "logged_in": False, "error": None}
        # cần browser chạy (cổng debug) để đọc cookie qua CDP
        if acc.status != "ready":
            self.mgr.start_account(acc.id)
        cookie = self.mgr.get_cookie_header(acc)
        if not cookie:
            info["error"] = "Chưa lấy được cookie (acc chưa đăng nhập / chưa mở được)."
            return info
        s = self._sess(acc)
        s.session.headers["Cookie"] = cookie
        try:
            r = s.session.get(SESSION_URL, timeout=20)
            if r.status_code == 200:
                j = r.json() or {}
                u = j.get("user") or {}
                info["email"] = u.get("email") or u.get("name")
                info["expires"] = j.get("expires")
                tok = j.get("access_token")
                if tok:
                    s.access_token = tok
                    s.access_ts = time.time()
                    info["logged_in"] = True
        except Exception as e:
            info["error"] = f"session: {e}"
        # điểm/quota
        try:
            if s.access_token:
                cr = s.session.get(f"{SANDBOX_BASE}/v1/credits",
                                   headers={"Authorization": f"Bearer {s.access_token}"}, timeout=20)
                if cr.status_code == 200:
                    info["credits"] = cr.json()
                else:
                    info["credits"] = {"http": cr.status_code, "body": cr.text[:120]}
        except Exception as e:
            info["credits"] = {"error": str(e)}
        return info

    def generate(self, prompt, model, aspect, n=1, seed=None) -> List[bytes]:
        """Tạo n ảnh SONG SONG qua nhiều acc."""
        results = [None] * n
        errors = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, n))) as ex:
            futs = {}
            for i in range(n):
                sd = seed if (seed is not None and n == 1) else None
                futs[ex.submit(self.generate_one, prompt, model, aspect, sd)] = i
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    results[i] = fut.result()
                except Exception as e:
                    errors.append(str(e))
        out = [r for r in results if r]
        if not out and errors:
            raise RuntimeError(errors[0])
        return out
