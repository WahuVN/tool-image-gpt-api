import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import parse, request, error

CPAB_IMAGE_MODELS = [
    "gpt-image-2",
]

CPAB_CHAT_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
]

CPAB_ALLOWED_MODELS = CPAB_CHAT_MODELS + CPAB_IMAGE_MODELS

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
        if key:
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
    headers = {"Content-Type": "application/json", "User-Agent": "curl/8.13.0"}
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


def is_cpab_base_url(base_url: str) -> bool:
    return "cpab.hiennq.dev" in str(base_url or "").lower()


def is_cpab_chat_model(model_id: str) -> bool:
    return str(model_id or "").strip().lower() in {item.lower() for item in CPAB_CHAT_MODELS}


def decode_data_image_url(url: str) -> tuple[bytes, str] | None:
    clean = str(url or "").strip()
    if not clean.lower().startswith("data:image/") or "," not in clean:
        return None
    header, encoded = clean.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "image/png"
    return base64.b64decode(encoded), content_type


def build_cpab_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "") or "").strip() or "Generate an image."
    details = []
    for key in ("size", "quality", "style"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            details.append(f"{key}: {value}")
    if details:
        prompt = f"{prompt}\n\nGeneration settings: {', '.join(details)}"
    return {
        "model": str(payload.get("model", "")).strip(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(payload.get("temperature", 0.7) or 0.7),
        "max_tokens": int(payload.get("max_tokens", 500) or 500),
    }


def cmd_generate_cpab_chat(
    base_url: str,
    api_key: str | None,
    payload: dict[str, Any],
    output_file: Path,
    response_format: str,
) -> int:
    body, _ = http_post(build_url(base_url, "/v1/chat/completions"), build_cpab_chat_payload(payload), api_key)
    parsed = json.loads(body.decode("utf-8"))
    choices = parsed.get("choices", [])
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    images = message.get("images", []) if isinstance(message, dict) else []
    for image_item in images:
        image_url = image_item.get("image_url", {}) if isinstance(image_item, dict) else {}
        url = image_url.get("url", "") if isinstance(image_url, dict) else ""
        decoded = decode_data_image_url(url)
        if decoded:
            image_bytes, content_type = decoded
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(image_bytes)
            print(f"Đã lưu ảnh: {output_file.resolve()}")
            print(f"Content-Type: {content_type}")
            return 0
        if url and response_format == "url":
            print("Image URL:")
            print(url)
            return 0
    print("CPAB chat completion không trả ảnh trong message.images.")
    print(json.dumps(parsed, ensure_ascii=False, indent=2)[:2000])
    return 1


def cmd_discover(base_url: str, api_key: str | None) -> int:
    try:
        data = http_get_json(build_url(base_url, "/v1/models/image"), api_key)
    except Exception:
        data = http_get_json(build_url(base_url, "/v1/models"), api_key)
    models = data.get("data", [])
    allowed = {item.lower() for item in CPAB_CHAT_MODELS}
    models = [item for item in models if str(item.get("id", "")).lower() in allowed]

    if not models:
        print("Không tìm thấy model chat nào.")
        return 0

    print("Danh sách model chat:")
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

    if is_cpab_base_url(base_url) and is_cpab_chat_model(model):
        return cmd_generate_cpab_chat(base_url, api_key, payload, output_file, response_format)

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


