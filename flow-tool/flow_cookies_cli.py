# -*- coding: utf-8 -*-
"""
Quản lý cookie Flow từ dòng lệnh - KHÔNG cần mở web/trình duyệt.

Ví dụ:
  # Nạp cookie cho acc "flow01" từ file (header / JSON / cookies.txt)
  python flow_cookies_cli.py import flow01 --file cookie.txt

  # Nạp từ clipboard (đã copy chuỗi cookie)
  python flow_cookies_cli.py import flow01 --clip

  # Nạp tất cả file trong thư mục cookies/
  python flow_cookies_cli.py reload

  # Xem danh sách acc + trạng thái
  python flow_cookies_cli.py list

  # Xem log gần đây
  python flow_cookies_cli.py log -n 50
"""

import sys
import argparse

from flow_accounts import AccountManager
from flow_log import tail as log_tail


def _read_clip():
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception as e:
        print(f"[LỖI] Không đọc được clipboard: {e}")
        return ""


def cmd_import(mgr, args):
    if args.file:
        raw = open(args.file, encoding="utf-8", errors="ignore").read()
    elif args.clip:
        raw = _read_clip()
    else:
        print("Dán cookie rồi Enter, kết thúc bằng dòng trống + Ctrl+Z (Windows):")
        raw = sys.stdin.read()
    res = mgr.add_or_update_with_cookies(args.name, raw)
    if not res.get("ok"):
        print(f"[LỖI] {res.get('error')}")
        return
    flag = "✓" if res.get("has_session") else "⚠ THIẾU session-token"
    print(f"{flag} Nạp {res.get('count')} cookie cho '{args.name}'. logged_in={res.get('logged_in')}")


def cmd_reload(mgr, args):
    n = mgr.autoload_cookie_files()
    print(f"Đã nạp từ {n} file trong cookies/.")


def cmd_list(mgr, args):
    for a in mgr.states():
        sess = "🔑" if a["logged_in"] else "  "
        cd = f" cooldown {a['cooldown']}s" if a["cooldown"] else ""
        print(f"{sess} {a['name']:<18} {a['status']:<12} dùng={a['uses']} lỗi={a['failures']}{cd}"
              + (f"  | {a['last_error']}" if a["last_error"] else ""))
    print(f"\nSẵn sàng: {len(mgr.healthy_accounts())}/{len(mgr.accounts)}")


def cmd_log(mgr, args):
    for line in log_tail(args.n):
        print(line)


def main():
    p = argparse.ArgumentParser(description="Quản lý cookie Flow từ CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="Nạp cookie cho 1 acc")
    pi.add_argument("name")
    pi.add_argument("--file", help="Đường dẫn file cookie")
    pi.add_argument("--clip", action="store_true", help="Đọc cookie từ clipboard")

    sub.add_parser("reload", help="Nạp tất cả file trong cookies/")
    sub.add_parser("list", help="Liệt kê acc + trạng thái")

    pl = sub.add_parser("log", help="Xem log gần đây")
    pl.add_argument("-n", type=int, default=100)

    args = p.parse_args()
    mgr = AccountManager()
    {"import": cmd_import, "reload": cmd_reload,
     "list": cmd_list, "log": cmd_log}[args.cmd](mgr, args)


if __name__ == "__main__":
    main()
