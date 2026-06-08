"""Vẽ art còn thiếu cho Tu Tiên Cờ vào D:\\TOOL\\TOOL Anh\\TuTien5.

- Item trong suốt  -> vẽ trên nền chroma hồng (#FF00FF) rồi tách alpha PNG.
- Item opaque (banner/nền) -> vẽ scene thường, resize fill canvas.

Catalog: tutien5_art_catalog (nguồn ART-DANH-SACH-VE-HET-2026-06-06.md).
Tái dùng prompt builder + post-process của tutienco_art_workflow.

Ví dụ:
    .venv\\Scripts\\python.exe tools\\generate_tutien5_art.py --dry-run
    .venv\\Scripts\\python.exe tools\\generate_tutien5_art.py --groups "A. Skin UI + FX" --workers 4
    .venv\\Scripts\\python.exe tools\\generate_tutien5_art.py --priorities P0,P1 --contact-sheet
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nine_router_image import build_headers, build_url, load_env_file, normalize_base_url
from tutien5_art_catalog import CATALOG, GROUP_ORDER, ArtItem
from tutienco_art_workflow import (
    build_item_prompt_chroma,
    build_negative_prompt_chroma,
    post_process_chroma_image,
    resolve_output_path,
    resolve_raw_background_output_path,
)

EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien5"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_OUTPUT_DIR = "outputs/tutien5_generation"
DEFAULT_COLOR_KEY = "pink"
COLOR_CHOICES = ("green", "blue", "pink")
OUTPUT_MODE_CHOICES = ("remove", "keep")


def parse_api_keys() -> list[str]:
    raw_pool = os.getenv("NINEROUTER_KEYS", "")
    keys = [part.strip() for part in raw_pool.replace("\n", ",").split(",") if part.strip()]
    single = os.getenv("NINEROUTER_KEY", "").strip()
    if single:
        keys.insert(0, single)
    unique: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def select_items(groups: str = "", priorities: str = "") -> list[ArtItem]:
    items = list(CATALOG)
    if groups.strip():
        wanted = {part.strip() for part in groups.split(",") if part.strip()}
        items = [
            item for item in items
            if item.group in wanted
            or item.group.split(".", 1)[0] in wanted
            or item.subgroup in wanted
        ]
    if priorities.strip():
        wanted_priority = {part.strip() for part in priorities.split(",") if part.strip()}
        items = [item for item in items if item.priority in wanted_priority]
    return items


def build_payload(item: ArtItem, model: str, color_key: str, output_mode: str, extra_note: str = "") -> dict[str, Any]:
    return {
        "model": model,
        "prompt": build_item_prompt_chroma(item, extra_note, color_key=color_key, output_mode=output_mode),
        "n": 1,
        "aspect_ratio": item.aspect,
        "output_format": "png",
        "negative_prompt": build_negative_prompt_chroma(item, color_key, output_mode),
    }


def http_post_image(base_url: str, api_key: str, payload: dict[str, Any], timeout_seconds: int) -> bytes:
    endpoint = build_url(base_url, "/v1/images/generations", {"response_format": "binary"})
    req = request.Request(url=endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    for key, value in build_headers(api_key or None).items():
        req.add_header(key, value)
    with request.urlopen(req, timeout=timeout_seconds) as resp:
        content_type = resp.headers.get("Content-Type", "")
        body = resp.read()
    if "json" not in content_type.lower():
        return body
    parsed = json.loads(body.decode("utf-8"))
    data = parsed.get("data", [])
    if not data:
        raise RuntimeError(f"API returned JSON without data: {parsed}")
    first = data[0]
    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])
    raise RuntimeError(f"API returned JSON without image bytes: {parsed}")


def generate_with_retry(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    retry_count: int,
    retry_backoff: float,
) -> bytes:
    attempts = max(1, retry_count + 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return http_post_image(base_url, api_key, payload, timeout_seconds + (attempt - 1) * 90)
        except error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {text}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < attempts:
            delay = min(15.0, retry_backoff * (2 ** (attempt - 1)))
            print(f"RETRY attempt={attempt}/{attempts} after {delay:.1f}s error={last_error}", flush=True)
            time.sleep(delay)
    assert last_error is not None
    raise RuntimeError(str(last_error))


def raw_path_for(target_path: Path, color_key: str) -> Path:
    return resolve_raw_background_output_path(target_path, color_key, 1)


def inspect_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        width, height = rgba.size
        alpha = rgba.getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        hist = alpha.histogram()
        total = max(1, width * height)
        return {
            "size": rgba.size,
            "mode": im.mode,
            "alpha_min": int(alpha_min),
            "alpha_max": int(alpha_max),
            "transparent_ratio": int(hist[0]) / total,
        }


def validate(items: list[ArtItem], export_root: str, output_mode: str) -> list[tuple[str, str, str]]:
    failures: list[tuple[str, str, str]] = []
    by_group: dict[str, list[int]] = {}
    for item in items:
        path = resolve_output_path(item, export_root)
        counts = by_group.setdefault(item.group, [0, 0])
        counts[1] += 1
        if not path.exists():
            failures.append((item.code, "missing final", str(path)))
            continue
        try:
            check = inspect_png(path)
        except Exception as exc:  # noqa: BLE001
            failures.append((item.code, f"unreadable: {exc}", str(path)))
            continue
        size_ok = check["size"] == item.size
        if item.transparent and output_mode == "remove":
            content_ok = check["alpha_min"] == 0 and check["transparent_ratio"] >= 0.005
        else:
            content_ok = check["alpha_min"] >= 250  # opaque (banner hoặc giữ nền màu)
        if size_ok and content_ok:
            counts[0] += 1
        else:
            failures.append((item.code, f"invalid: {check}", str(path)))
    for group in GROUP_ORDER:
        if group in by_group:
            ok_count, total_count = by_group[group]
            print(f"VALIDATE {group}: {ok_count}/{total_count} ok", flush=True)
    print(f"VALIDATE total={sum(t for _, t in by_group.values())} failures={len(failures)}", flush=True)
    for code, reason, path in failures[:80]:
        print(f"VALIDATE_FAIL {code}: {reason} -> {path}", flush=True)
    if len(failures) > 80:
        print(f"VALIDATE_FAIL ... {len(failures) - 80} more", flush=True)
    return failures


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    width, height = size
    img = Image.new("RGB", size, (235, 238, 242))
    draw = ImageDraw.Draw(img)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(205, 210, 220))
    return img


def create_contact_sheets(items: list[ArtItem], export_root: str, output_dir: str) -> list[Path]:
    out_dir = Path(output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    saved: list[Path] = []
    for group in GROUP_ORDER:
        group_items = [item for item in items if item.group == group]
        if not group_items:
            continue
        cols = 8
        tile_w, tile_h = 150, 184
        rows = (len(group_items) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * tile_w, rows * tile_h), (235, 238, 242))
        draw = ImageDraw.Draw(canvas)
        for idx, item in enumerate(group_items):
            path = resolve_output_path(item, export_root)
            if not path.exists():
                continue
            x = (idx % cols) * tile_w
            y = (idx // cols) * tile_h
            icon = Image.open(path).convert("RGBA")
            icon.thumbnail((128, 128), Image.LANCZOS)
            bg = checkerboard((128, 128), 16).convert("RGBA")
            bg.alpha_composite(icon, ((128 - icon.width) // 2, (128 - icon.height) // 2))
            canvas.paste(bg.convert("RGB"), (x + 11, y + 8))
            label = item.code
            parts: list[str] = []
            while len(label) > 18:
                cut = label.rfind("_", 0, 18)
                if cut <= 0:
                    cut = 18
                parts.append(label[:cut])
                label = label[cut + 1:] if label[cut:cut + 1] == "_" else label[cut:]
            parts.append(label)
            for line_index, line in enumerate(parts[:3]):
                draw.text((x + 8, y + 140 + line_index * 13), line, fill=(20, 24, 32), font=font)
        slug = group.split(".", 1)[0].strip().lower().replace(" ", "_")
        out_path = out_dir / f"tutien5_{slug}_sheet.jpg"
        canvas.save(out_path, quality=95)
        saved.append(out_path.resolve())
        print(f"CONTACT_SHEET {out_path.resolve()}", flush=True)
    return saved


def generate_one(
    *,
    item: ArtItem,
    target_path: Path,
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
    retry_count: int,
    retry_backoff: float,
    extra_note: str,
    save_raw: bool,
    color_key: str,
    output_mode: str,
    resize_enabled: bool,
) -> dict[str, Any]:
    start = time.monotonic()
    image_bytes = generate_with_retry(
        base_url=base_url,
        api_key=api_key,
        payload=build_payload(item, model, color_key, output_mode, extra_note),
        timeout_seconds=timeout_seconds,
        retry_count=retry_count,
        retry_backoff=retry_backoff,
    )
    raw_path = raw_path_for(target_path, color_key)
    if save_raw:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(image_bytes)
    final_bytes = post_process_chroma_image(
        item,
        image_bytes,
        color_key=color_key,
        output_mode=output_mode,
        resize_enabled=resize_enabled,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(final_bytes)
    check = inspect_png(target_path)
    if resize_enabled and check["size"] != item.size:
        raise RuntimeError(f"invalid final size: {check}")
    if item.transparent and output_mode == "remove" and check["alpha_min"] != 0:
        raise RuntimeError(f"transparent png has no alpha: {check}")
    return {
        "code": item.code,
        "path": str(target_path),
        "raw_path": str(raw_path) if save_raw else "",
        "seconds": round(time.monotonic() - start, 1),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate missing TuTien5 game assets.")
    parser.add_argument("--env-file", default=".env.9router")
    parser.add_argument("--export-root", default=EXPORT_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=os.getenv("NINEROUTER_IMAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--backoff", type=float, default=1.4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--groups", default="", help="Comma list of group names/prefixes/subgroups.")
    parser.add_argument("--priorities", default="", help="Comma list, e.g. P0,P1.")
    parser.add_argument("--extra-note", default="")
    parser.add_argument("--color", default=DEFAULT_COLOR_KEY, choices=COLOR_CHOICES,
                        help="Màu nền chroma khi vẽ (mặc định pink).")
    parser.add_argument("--output-mode", default="remove", choices=OUTPUT_MODE_CHOICES,
                        help="remove = tách nền ra alpha; keep = giữ nền màu trong ảnh final.")
    parser.add_argument("--no-resize", action="store_true", help="Không tự resize về size catalog.")
    parser.add_argument("--no-raw", action="store_true", help="Do not save raw chroma backups.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--contact-sheet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    items = select_items(args.groups, args.priorities)
    if args.limit > 0:
        items = items[: args.limit]

    color_key = str(args.color)
    output_mode = str(args.output_mode)
    resize_enabled = not args.no_resize

    if args.validate_only:
        failures = validate(items, str(args.export_root), output_mode)
        if args.contact_sheet:
            create_contact_sheets(items, str(args.export_root), str(args.output_dir))
        return 1 if failures else 0

    pending: list[tuple[ArtItem, Path]] = []
    for item in items:
        path = resolve_output_path(item, str(args.export_root))
        if path.exists() and not args.overwrite:
            continue
        pending.append((item, path))

    print(f"export_root={args.export_root}", flush=True)
    print(
        f"model={args.model} workers={args.workers} color={color_key} output={output_mode} "
        f"resize={resize_enabled} selected={len(items)} pending={len(pending)} keys={len(parse_api_keys())}",
        flush=True,
    )
    for item, path in pending:
        print(f"PENDING {item.group} / {item.subgroup} {item.code} -> {path}", flush=True)
    if args.dry_run:
        if args.contact_sheet:
            create_contact_sheets(items, str(args.export_root), str(args.output_dir))
        return 0
    if not pending:
        failures = validate(items, str(args.export_root), output_mode)
        if args.contact_sheet:
            create_contact_sheets(items, str(args.export_root), str(args.output_dir))
        return 1 if failures else 0

    base_url = normalize_base_url(os.getenv("NINEROUTER_URL", ""))
    keys = parse_api_keys()
    if not keys:
        raise RuntimeError("Missing NINEROUTER_KEY/NINEROUTER_KEYS")
    print(f"api={base_url} keys={len(keys)}", flush=True)

    workers = max(1, min(int(args.workers), len(pending)))
    completed = 0
    failed: list[tuple[str, str]] = []
    next_idx = 0
    running: dict[Any, tuple[ArtItem, Path]] = {}

    def submit_next(executor: ThreadPoolExecutor) -> None:
        nonlocal next_idx
        if next_idx >= len(pending):
            return
        item, target_path = pending[next_idx]
        api_key = keys[next_idx % len(keys)]
        next_idx += 1
        print(f"START {item.code}", flush=True)
        future = executor.submit(
            generate_one,
            item=item,
            target_path=target_path,
            base_url=base_url,
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.timeout,
            retry_count=args.retry,
            retry_backoff=args.backoff,
            extra_note=str(args.extra_note or ""),
            save_raw=not args.no_raw,
            color_key=color_key,
            output_mode=output_mode,
            resize_enabled=resize_enabled,
        )
        running[future] = (item, target_path)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in range(workers):
            submit_next(executor)
        while running:
            done, _ = wait(running, timeout=5, return_when=FIRST_COMPLETED)
            if not done:
                print(
                    f"PROGRESS {completed}/{len(pending)} running={len(running)} "
                    f"queued={len(pending) - next_idx}",
                    flush=True,
                )
                continue
            for future in done:
                item, path = running.pop(future)
                try:
                    info = future.result()
                    completed += 1
                    print(f"OK {item.code} {info['seconds']}s -> {path}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    completed += 1
                    failed.append((item.code, str(exc)))
                    print(f"ERROR {item.code}: {exc}", flush=True)
                submit_next(executor)

    print(f"DONE ok={completed - len(failed)} failed={len(failed)} total={len(pending)}", flush=True)
    validation_failures = validate(items, str(args.export_root), output_mode)
    if args.contact_sheet:
        create_contact_sheets(items, str(args.export_root), str(args.output_dir))
    if failed:
        for code, message in failed:
            print(f"FAILED {code}: {message}", flush=True)
        return 1
    return 1 if validation_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
