import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import parse, request, error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("NINEROUTER_URL đang trống.")
    if not normalized.startswith("http://") and not normalized.startswith("https://"):
        raise ValueError("NINEROUTER_URL phải bắt đầu bằng http:// hoặc https://")
    return normalized


def build_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    url = f"{base_url}{path}"
    if not query:
        return url
    return f"{url}?{parse.urlencode(query)}"


def build_headers(api_key: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def http_get_json(url: str, api_key: str | None = None) -> dict[str, Any]:
    req = request.Request(url=url, method="GET")
    for key, value in build_headers(api_key).items():
        req.add_header(key, value)

    try:
        with request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} thất bại [{ex.code}]\n{text}") from ex
    except error.URLError as ex:
        raise RuntimeError(f"Không kết nối được tới {url}: {ex.reason}") from ex

    return json.loads(body)


def http_post(url: str, payload: dict[str, Any], api_key: str | None = None) -> tuple[bytes, str]:
    req = request.Request(url=url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for key, value in build_headers(api_key).items():
        req.add_header(key, value)

    try:
        with request.urlopen(req, timeout=300) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} thất bại [{ex.code}]\n{text}") from ex
    except error.URLError as ex:
        raise RuntimeError(f"Không kết nối được tới {url}: {ex.reason}") from ex

    return body, content_type


def cmd_discover(base_url: str, api_key: str | None) -> int:
    data = http_get_json(build_url(base_url, "/v1/models/image"), api_key)
    models = data.get("data", [])

    if not models:
        print("Không tìm thấy model image nào.")
        return 0

    print("Danh sách model image:")
    for item in models:
        model_id = item.get("id", "")
        print(f"- {model_id}")
    return 0


def cmd_info(base_url: str, api_key: str | None, model_id: str) -> int:
    data = http_get_json(
        build_url(base_url, "/v1/models/info", {"id": model_id}),
        api_key,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_generate(
    base_url: str,
    api_key: str | None,
    model: str,
    prompt: str,
    output_file: Path,
    size: str | None,
    quality: str | None,
    style: str | None,
    count: int | None,
    response_format: str,
    extra_json: str | None,
) -> int:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
    }
    if size:
        payload["size"] = size
    if quality:
        payload["quality"] = quality
    if style:
        payload["style"] = style
    if count is not None:
        payload["n"] = count
    if response_format in {"url", "b64_json"}:
        payload["response_format"] = response_format

    if extra_json:
        extra = json.loads(extra_json)
        if not isinstance(extra, dict):
            raise ValueError("--extra-json phải là JSON object.")
        payload.update(extra)

    endpoint = build_url(base_url, "/v1/images/generations")
    if response_format == "binary":
        endpoint = build_url(base_url, "/v1/images/generations", {"response_format": "binary"})

    body, content_type = http_post(endpoint, payload, api_key)

    if response_format == "binary":
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(body)
        print(f"Đã lưu ảnh: {output_file.resolve()}")
        print(f"Content-Type: {content_type or 'unknown'}")
        return 0

    parsed = json.loads(body.decode("utf-8"))
    data = parsed.get("data", [])
    if not data:
        print("API trả về không có trường data.")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        return 1

    first = data[0]
    if first.get("url"):
        print("Image URL:")
        print(first["url"])
        return 0

    if first.get("b64_json"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(base64.b64decode(first["b64_json"]))
        print(f"Đã giải mã base64 và lưu: {output_file.resolve()}")
        return 0

    print("Không tìm thấy url hoặc b64_json trong response.")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="9Router Image CLI: discover / model info / generate",
    )
    parser.add_argument(
        "--env-file",
        default=".env.9router",
        help="File env chứa NINEROUTER_URL và NINEROUTER_KEY (mặc định: .env.9router)",
    )
    parser.add_argument("--url", default=None, help="Override NINEROUTER_URL")
    parser.add_argument("--key", default=None, help="Override NINEROUTER_KEY")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover", help="Liệt kê model image")

    info_cmd = subparsers.add_parser("info", help="Xem thông tin model")
    info_cmd.add_argument("--id", required=True, help="Model ID (vd: openai/dall-e-3)")

    generate = subparsers.add_parser("generate", help="Tạo ảnh")
    generate.add_argument("--model", required=True, help="Model ID")
    generate.add_argument("--prompt", required=True, help="Prompt tạo ảnh")
    generate.add_argument("--size", default=None, help="Ví dụ: 1024x1024")
    generate.add_argument("--quality", default=None, help="Ví dụ: standard | hd")
    generate.add_argument("--style", default=None, help="Style (nếu provider hỗ trợ)")
    generate.add_argument("--n", type=int, default=None, help="Số lượng ảnh")
    generate.add_argument(
        "--response-format",
        default="binary",
        choices=["binary", "url", "b64_json"],
        help="Định dạng trả về",
    )
    generate.add_argument(
        "--output",
        default="out.png",
        help="File output cho binary/b64_json",
    )
    generate.add_argument(
        "--extra-json",
        default=None,
        help="JSON object để truyền thêm field theo provider",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))

    base_url = normalize_base_url(args.url or os.getenv("NINEROUTER_URL", ""))
    api_key = args.key or os.getenv("NINEROUTER_KEY")

    if args.command == "discover":
        return cmd_discover(base_url, api_key)

    if args.command == "info":
        return cmd_info(base_url, api_key, args.id)

    return cmd_generate(
        base_url=base_url,
        api_key=api_key,
        model=args.model,
        prompt=args.prompt,
        output_file=Path(args.output),
        size=args.size,
        quality=args.quality,
        style=args.style,
        count=args.n,
        response_format=args.response_format,
        extra_json=args.extra_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())


