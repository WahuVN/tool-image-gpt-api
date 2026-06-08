# -*- coding: utf-8 -*-
"""
CLI tạo ảnh Flow.

Chuẩn bị 1 lần:
  1. Mở Brave, đăng nhập https://labs.google/fx/vi/tools/flow
  2. F12 -> tab Network -> bấm 1 request bất kỳ tới labs.google
     -> Headers -> Request Headers -> copy TOÀN BỘ giá trị dòng "cookie:"
  3. Dán vào file flow_cookie.txt (cùng thư mục này)

Chạy:
  python generate.py "a cute cat sitting on a sofa"
  python generate.py "phong canh nui" --model NARWHAL --aspect PORTRAIT --n 2
"""

import sys
import argparse
import pathlib

import cookie_grabber as cg
from flow_client import FlowClient

ASPECT_MAP = {
    "LANDSCAPE": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "PORTRAIT": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "SQUARE": "IMAGE_ASPECT_RATIO_SQUARE",
}

COOKIE_FILE = pathlib.Path(__file__).parent / "flow_cookie.txt"


def load_cookie() -> str:
    if not COOKIE_FILE.exists():
        print(f"[LỖI] Chưa có file cookie: {COOKIE_FILE}")
        print("Hãy tạo file đó và dán chuỗi cookie từ trình duyệt vào (xem hướng dẫn đầu file).")
        sys.exit(1)
    cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    if not cookie:
        print(f"[LỖI] File cookie rỗng: {COOKIE_FILE}")
        sys.exit(1)
    return cookie


def main():
    parser = argparse.ArgumentParser(description="Tạo ảnh qua Google Labs Flow API")
    parser.add_argument("prompt", help="Mô tả ảnh")
    parser.add_argument("--model", default="NARWHAL", help="Model ảnh (mặc định NARWHAL)")
    parser.add_argument("--aspect", default="LANDSCAPE",
                        choices=list(ASPECT_MAP.keys()), help="Tỉ lệ khung")
    parser.add_argument("--n", type=int, default=1, help="Số ảnh")
    parser.add_argument("--seed", type=int, default=None, help="Seed (mặc định ngẫu nhiên)")
    parser.add_argument("--project", default=None, help="projectId có sẵn (bỏ trống = tạo mới)")
    parser.add_argument("--browsers", type=int, default=2, help="Số trình duyệt captcha")
    parser.add_argument("--show", action="store_true", help="Hiện cửa sổ trình duyệt (debug)")
    parser.add_argument("--out", default="output", help="Thư mục lưu ảnh")
    parser.add_argument("--grab", default=None, choices=["brave", "chrome", "edge"],
                        help="(chế độ solver) Lấy cookie + đăng nhập sẵn cho captcha headless")
    parser.add_argument("--mode", default="brave", choices=["brave", "solver"],
                        help="brave = token qua Brave thật (ĐÃ HOẠT ĐỘNG); solver = headless")
    args = parser.parse_args()

    auth_cookies = None
    if args.mode == "brave":
        # Brave thật tự lo cả token lẫn cookie -> không cần grab/cookie file
        cookie = ""
    elif args.grab:
        print(f"[Flow] Lấy cookie từ {args.grab} (sẽ mở trình duyệt)...")
        auth_cookies = cg.grab_cookies_struct(args.grab)
        labs = {}
        for c in auth_cookies:
            if "labs.google" in c.get("domain", ""):
                labs[c["name"]] = c["value"]
        cookie = "; ".join(f"{k}={v}" for k, v in labs.items())
        (pathlib.Path(__file__).parent / "flow_cookie.txt").write_text(cookie, encoding="utf-8")
        print(f"[Flow] Đã lấy {len(auth_cookies)} cookie (header labs.google: {len(labs)}, "
              f"session-token: {'__Secure-next-auth.session-token' in labs}).")
    else:
        cookie = load_cookie()

    client = FlowClient(
        cookie=cookie,
        headless=not args.show,
        num_browsers=args.browsers,
        output_dir=args.out,
        auth_cookies=auth_cookies,
        token_mode=args.mode,
    )

    print("[Flow] Khởi động pool captcha...")
    client.start()
    try:
        paths = client.generate_images(
            prompt=args.prompt,
            model=args.model,
            aspect_ratio=ASPECT_MAP[args.aspect],
            n=args.n,
            seed=args.seed,
            project_id=args.project,
        )
        print("\n=== HOÀN TẤT ===")
        for p in paths:
            print(" -", p)
    finally:
        client.stop()


if __name__ == "__main__":
    main()
