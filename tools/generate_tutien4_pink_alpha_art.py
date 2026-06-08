from __future__ import annotations

import argparse
import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from io import BytesIO
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nine_router_image import build_headers, build_url, load_env_file, normalize_base_url
from tutienco_art_catalog import CATALOG, GROUP_ORDER, ArtItem
from tutienco_art_workflow import (
    build_item_prompt_chroma,
    build_negative_prompt_chroma,
    post_process_chroma_image,
    resolve_output_path,
    resolve_raw_background_output_path,
)

EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien4"
DEFAULT_MODEL = "cx/gpt-5.4-image"
DEFAULT_OUTPUT_DIR = "outputs/tutien4_pink_alpha_generation"
PINK_RGB = (255, 0, 255)


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


def select_items(groups: str = "", priorities: str = "", include_opaque: bool = False) -> list[ArtItem]:
    items = list(CATALOG)
    if not include_opaque:
        items = [item for item in items if item.transparent]
    if groups.strip():
        wanted = {part.strip() for part in groups.split(",") if part.strip()}
        items = [item for item in items if item.group in wanted or item.group.split(".", 1)[0] in wanted]
    if priorities.strip():
        wanted_priority = {part.strip() for part in priorities.split(",") if part.strip()}
        items = [item for item in items if item.priority in wanted_priority]
    return items


def build_payload(item: ArtItem, model: str, extra_note: str = "") -> dict[str, Any]:
    return {
        "model": model,
        "prompt": build_item_prompt_chroma(item, extra_note, color_key="pink", output_mode="remove"),
        "n": 1,
        "aspect_ratio": item.aspect,
        "output_format": "png",
        "negative_prompt": build_negative_prompt_chroma(item, "pink", "remove"),
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
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            delay = min(15.0, retry_backoff * (2 ** (attempt - 1)))
            print(f"RETRY attempt={attempt}/{attempts} after {delay:.1f}s error={last_error}", flush=True)
            time.sleep(delay)
    assert last_error is not None
    raise RuntimeError(str(last_error))


def raw_path_for(target_path: Path, variant_idx: int = 1) -> Path:
    return resolve_raw_background_output_path(target_path, "pink", variant_idx)


def inspect_final_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        width, height = rgba.size
        alpha = rgba.getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        hist = alpha.histogram()
        total = max(1, width * height)
        transparent_ratio = int(hist[0]) / total
        edge_width = max(1, min(8, width // 64 or 1, height // 64 or 1))
        edge_boxes = [
            (0, 0, width, edge_width),
            (0, height - edge_width, width, height),
            (0, 0, edge_width, height),
            (width - edge_width, 0, width, height),
        ]
        edge_transparent = 0
        edge_total = 0
        for box in edge_boxes:
            edge_alpha = alpha.crop(box)
            edge_hist = edge_alpha.histogram()
            edge_transparent += int(edge_hist[0])
            edge_total += max(1, edge_alpha.size[0] * edge_alpha.size[1])
        return {
            "size": rgba.size,
            "mode": im.mode,
            "alpha_min": int(alpha_min),
            "alpha_max": int(alpha_max),
            "transparent_ratio": transparent_ratio,
            "edge_transparent_ratio": edge_transparent / max(1, edge_total),
        }


def pink_score(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    min_rb = min(int(r), int(b))
    max_rb = max(int(r), int(b))
    if int(r) < 80 or int(b) < 80:
        return 0.0
    magenta_delta = min_rb - int(g)
    rb_balance = 1.0 - min(1.0, abs(int(r) - int(b)) / max(1, max_rb))
    score = max(0.0, min(1.0, magenta_delta / 85.0)) * 0.75
    score += max(0.0, min(1.0, rb_balance)) * 0.25
    return max(0.0, min(1.0, score))


def inspect_raw_pink(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        corners = [
            rgb.getpixel((0, 0)),
            rgb.getpixel((width - 1, 0)),
            rgb.getpixel((0, height - 1)),
            rgb.getpixel((width - 1, height - 1)),
        ]
        corner_pink = sum(1 for pixel in corners if pink_score(pixel) >= 0.45)
        edge_sample: list[tuple[int, int, int]] = []
        step_x = max(1, width // 24)
        step_y = max(1, height // 24)
        for x in range(0, width, step_x):
            edge_sample.append(rgb.getpixel((x, 0)))
            edge_sample.append(rgb.getpixel((x, height - 1)))
        for y in range(0, height, step_y):
            edge_sample.append(rgb.getpixel((0, y)))
            edge_sample.append(rgb.getpixel((width - 1, y)))
        edge_pink_ratio = sum(1 for pixel in edge_sample if pink_score(pixel) >= 0.45) / max(1, len(edge_sample))
        return {
            "size": rgb.size,
            "mode": im.mode,
            "corner_pink": corner_pink,
            "edge_pink_ratio": edge_pink_ratio,
        }


def validate(items: list[ArtItem], export_root: str) -> list[tuple[str, str, str]]:
    failures: list[tuple[str, str, str]] = []
    by_group: dict[str, tuple[int, int]] = {}
    for item in items:
        path = resolve_output_path(item, export_root)
        raw_path = raw_path_for(path)
        ok_count, total_count = by_group.get(item.group, (0, 0))
        total_count += 1
        if not path.exists():
            failures.append((item.code, "missing final", str(path)))
            by_group[item.group] = (ok_count, total_count)
            continue
        if not raw_path.exists():
            failures.append((item.code, "missing raw pink", str(raw_path)))
            by_group[item.group] = (ok_count, total_count)
            continue
        try:
            final_check = inspect_final_png(path)
            raw_check = inspect_raw_pink(raw_path)
        except Exception as exc:
            failures.append((item.code, f"unreadable: {exc}", str(path)))
            by_group[item.group] = (ok_count, total_count)
            continue
        final_ok = (
            final_check["size"] == item.size
            and final_check["alpha_min"] == 0
            and final_check["transparent_ratio"] >= 0.005
        )
        raw_ok = raw_check["corner_pink"] >= 2 or raw_check["edge_pink_ratio"] >= 0.20
        if final_ok and raw_ok:
            ok_count += 1
        else:
            failures.append((item.code, f"invalid final/raw: final={final_check} raw={raw_check}", str(path)))
        by_group[item.group] = (ok_count, total_count)
    for group in GROUP_ORDER:
        if group in by_group:
            ok_count, total_count = by_group[group]
            print(f"VALIDATE {group}: {ok_count}/{total_count} ok", flush=True)
    print(f"VALIDATE total={sum(total for _, total in by_group.values())} failures={len(failures)}", flush=True)
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
    except Exception:
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
                label = label[cut + 1 :] if label[cut : cut + 1] == "_" else label[cut:]
            parts.append(label)
            for line_index, line in enumerate(parts[:3]):
                draw.text((x + 8, y + 140 + line_index * 13), line, fill=(20, 24, 32), font=font)
        slug = group.split(".", 1)[0].lower() + "_" + group.split(" ", 1)[-1].lower().replace(" ", "_")
        out_path = out_dir / f"{slug}_pink_alpha_sheet.jpg"
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
) -> dict[str, Any]:
    start = time.monotonic()
    image_bytes = generate_with_retry(
        base_url=base_url,
        api_key=api_key,
        payload=build_payload(item, model, extra_note),
        timeout_seconds=timeout_seconds,
        retry_count=retry_count,
        retry_backoff=retry_backoff,
    )
    raw_path = raw_path_for(target_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(image_bytes)
    final_bytes = post_process_chroma_image(
        item,
        image_bytes,
        color_key="pink",
        output_mode="remove",
        resize_enabled=True,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(final_bytes)
    final_check = inspect_final_png(target_path)
    if final_check["size"] != item.size or final_check["alpha_min"] != 0:
        raise RuntimeError(f"invalid final transparent png: {final_check}")
    return {
        "code": item.code,
        "path": str(target_path),
        "raw_path": str(raw_path),
        "seconds": round(time.monotonic() - start, 1),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate TuTien4 transparent game assets from pink-screen raw PNGs.")
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
    parser.add_argument("--groups", default="", help="Optional comma list, e.g. A,B or 'B. Relics,E. Icon'.")
    parser.add_argument("--priorities", default="", help="Optional comma list, e.g. P0,P1.")
    parser.add_argument("--extra-note", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--contact-sheet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    items = select_items(args.groups, args.priorities, include_opaque=False)
    if args.limit > 0:
        items = items[: args.limit]

    if args.validate_only:
        failures = validate(items, str(args.export_root))
        if args.contact_sheet:
            create_contact_sheets(items, str(args.export_root), str(args.output_dir))
        return 1 if failures else 0

    pending: list[tuple[ArtItem, Path]] = []
    for item in items:
        path = resolve_output_path(item, str(args.export_root))
        raw_path = raw_path_for(path)
        if path.exists() and raw_path.exists() and not args.overwrite:
            continue
        pending.append((item, path))

    print(f"export_root={args.export_root}", flush=True)
    print(
        f"model={args.model} workers={args.workers} transparent_items={len(items)} pending={len(pending)} keys={len(parse_api_keys())}",
        flush=True,
    )
    for item, path in pending:
        print(f"PENDING {item.group} / {item.subgroup} {item.code} -> {path}", flush=True)
    if args.dry_run:
        if args.contact_sheet:
            create_contact_sheets(items, str(args.export_root), str(args.output_dir))
        return 0
    if not pending:
        failures = validate(items, str(args.export_root))
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
        )
        running[future] = (item, target_path)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in range(workers):
            submit_next(executor)
        while running:
            done, _ = wait(running, timeout=5, return_when=FIRST_COMPLETED)
            if not done:
                print(f"PROGRESS {completed}/{len(pending)} running={len(running)} queued={len(pending) - next_idx}", flush=True)
                continue
            for future in done:
                item, path = running.pop(future)
                try:
                    info = future.result()
                    completed += 1
                    print(f"OK {item.code} {info['seconds']}s -> {path} RAW {info['raw_path']}", flush=True)
                except Exception as exc:
                    completed += 1
                    failed.append((item.code, str(exc)))
                    print(f"ERROR {item.code}: {exc}", flush=True)
                submit_next(executor)

    print(f"DONE ok={completed - len(failed)} failed={len(failed)} total={len(pending)}", flush=True)
    validation_failures = validate(items, str(args.export_root))
    if args.contact_sheet:
        create_contact_sheets(items, str(args.export_root), str(args.output_dir))
    if failed:
        for code, message in failed:
            print(f"FAILED {code}: {message}", flush=True)
        return 1
    return 1 if validation_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
