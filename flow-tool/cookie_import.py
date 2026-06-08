# -*- coding: utf-8 -*-
"""
Nạp cookie Flow THỦ CÔNG - không cần mở trình duyệt đăng nhập.
=============================================================
Parser nhận 3 định dạng dán vào và trả về list cookie kiểu CDP/Playwright:
    {name, value, domain, path, expires, httpOnly, secure, sameSite}

1. Chuỗi header:  "name1=value1; name2=value2; ..."
   (copy ở DevTools > Network > chọn request labs.google > Headers > Cookie)
2. JSON mảng:     export từ extension "Cookie-Editor" / "EditThisCookie"
   (list dict có name/value/domain/expirationDate...), hoặc {"cookies":[...]}
3. Netscape cookies.txt (tab-separated, 7 cột)

Chỉ cần cookie của domain labs.google (đặc biệt là
__Secure-next-auth.session-token) là account dùng được.
"""

import json
import time
from typing import List, Dict, Any

COOKIE_KEYS = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
SESSION_COOKIE = "__Secure-next-auth.session-token"
DEFAULT_DOMAIN = "labs.google"


def _norm_same_site(v) -> str:
    s = str(v or "").strip().lower().replace("-", "_")
    return {
        "strict": "Strict", "lax": "Lax", "none": "None",
        "no_restriction": "None", "unspecified": "Lax",
    }.get(s, "Lax")


def _pick_domain(name: str, given: str, default_domain: str) -> str:
    d = str(given or "").strip()
    if d:
        return d
    # Không kèm domain (paste header) -> đoán: cookie next-auth thuộc labs.google
    if "next-auth" in name or name.startswith("__Secure-") or name.startswith("__Host-"):
        return "labs.google"
    return default_domain


def _mk(name, value, domain, path="/", expires=None,
        http_only=True, secure=True, same_site="Lax") -> Dict[str, Any]:
    try:
        exp = float(expires) if expires not in (None, "", 0, "0") else (time.time() + 180 * 86400)
    except (TypeError, ValueError):
        exp = time.time() + 180 * 86400
    return {
        "name": str(name).strip(),
        "value": str(value),
        "domain": domain,
        "path": path or "/",
        "expires": exp,
        "httpOnly": bool(http_only),
        "secure": bool(secure),
        "sameSite": _norm_same_site(same_site),
    }


def parse_header_string(raw: str, default_domain: str = DEFAULT_DOMAIN) -> List[Dict]:
    out = []
    # Bỏ tiền tố "Cookie:" nếu copy cả tên header
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1]
    for part in raw.replace("\r", "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if not name:
            continue
        out.append(_mk(name, value.strip(), _pick_domain(name, "", default_domain)))
    return out


def parse_json_array(raw: str, default_domain: str = DEFAULT_DOMAIN) -> List[Dict]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("cookies") or data.get("cookie") or []
    out = []
    for c in data:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("Name")
        value = c.get("value", c.get("Value"))
        if not name or value is None:
            continue
        dom = c.get("domain") or c.get("Domain") or ""
        out.append(_mk(
            name, value, _pick_domain(name, dom, default_domain),
            c.get("path") or "/",
            c.get("expirationDate") or c.get("expires") or c.get("expiry"),
            c.get("httpOnly", c.get("HttpOnly", True)),
            c.get("secure", c.get("Secure", True)),
            c.get("sameSite") or c.get("SameSite") or "Lax",
        ))
    return out


def parse_netscape(raw: str, default_domain: str = DEFAULT_DOMAIN) -> List[Dict]:
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 7:
            continue
        domain, _flag, path, secure, expires, name, value = f[:7]
        out.append(_mk(name, value, (domain or default_domain).strip(),
                       path, expires, True, str(secure).upper() == "TRUE", "Lax"))
    return out


def parse_cookies(raw: str, default_domain: str = DEFAULT_DOMAIN) -> List[Dict]:
    """Tự nhận dạng định dạng và parse."""
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw[0] in "[{":
        try:
            return sanitize(parse_json_array(raw, default_domain))
        except Exception:
            pass
    if "\t" in raw and any(len(l.split("\t")) >= 7 for l in raw.splitlines()):
        return sanitize(parse_netscape(raw, default_domain))
    return sanitize(parse_header_string(raw, default_domain))


def has_session(cookies: List[Dict]) -> bool:
    return any(c.get("name") == SESSION_COOKIE and "labs.google" in c.get("domain", "")
               for c in cookies)


def sanitize(cookies: List[Dict]) -> List[Dict]:
    out = []
    for c in cookies or []:
        d = {k: c[k] for k in COOKIE_KEYS if k in c}
        if not d.get("name") or "value" not in d:
            continue
        if d.get("sameSite") not in ("Strict", "Lax", "None"):
            d["sameSite"] = "Lax"
        out.append(d)
    return out
