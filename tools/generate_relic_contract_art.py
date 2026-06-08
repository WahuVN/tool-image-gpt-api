from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nine_router_image import load_env_file, normalize_base_url
from tutienco_art_catalog import CATALOG, ArtItem
from tutienco_art_workflow import (
    BLUE_SCREEN_PAYLOAD_FLAG,
    _generate_image_with_retry_no_ui,
    build_item_prompt,
    build_negative_prompt,
    post_process_image,
    resolve_output_path,
)


EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien2"
DEFAULT_MODEL = "cx/gpt-5.4-image"
DEFAULT_OUTPUT_DIR = "outputs/relic_contract_generation"

TARGET_SUBGROUPS = {
    "B2. Liar temp": "liar",
    "B3. Three-card temp": "three-card",
}

EXTRA_PROMPT_NOTE = """
Follow this exact production spec: 256x256 transparent PNG icon, 1:1, 2D mobile game art,
cultivation fantasy poker relic, polished meme-cartoon style, thick clean outline, high contrast,
centered object, readable at 64x64, no text, no logo, no watermark, no square background.
Keep the relic fully inside the canvas with generous padding. Outside the icon silhouette must become transparent.
Use the rarity rim described in the item description as an ornamental circular/arc aura, not a filled background card.
For every three-card relic, add a tiny clean three-playing-card glyph in one corner or behind the object, with no letters or numbers.
""".strip()

NEGATIVE_EXTRA = (
    "letters, numbers, readable text, watermark, logo, signature, UI screenshot, square card background, "
    "cropped object, cut off edges, photorealistic, blurry, low contrast, cluttered scene"
)


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


def target_items() -> list[ArtItem]:
    return [item for item in CATALOG if item.subgroup in TARGET_SUBGROUPS]

def target_path_for(item: ArtItem, export_root: str) -> Path:
    return resolve_output_path(item, export_root)


def validate_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        alpha = rgba.getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        opaque_bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
        return {
            "size": rgba.size,
            "mode": rgba.mode,
            "alpha_min": int(alpha_min),
            "alpha_max": int(alpha_max),
            "has_subject": opaque_bbox is not None,
        }

def validate_contract(export_root: str) -> list[tuple[str, str, str]]:
    failures: list[tuple[str, str, str]] = []
    total = 0
    for subgroup in TARGET_SUBGROUPS:
        items = [item for item in target_items() if item.subgroup == subgroup]
        existing = 0
        for item in items:
            total += 1
            path = target_path_for(item, export_root)
            if not path.exists():
                failures.append((item.code, "missing", str(path)))
                continue
            try:
                check = validate_png(path)
            except Exception as exc:
                failures.append((item.code, f"unreadable: {exc}", str(path)))
                continue
            ok = (
                check["size"] == (256, 256)
                and check["mode"] == "RGBA"
                and check["alpha_min"] == 0
                and check["alpha_max"] > 0
                and check["has_subject"]
            )
            if ok:
                existing += 1
            else:
                failures.append((item.code, f"invalid png: {check}", str(path)))
        print(f"VALIDATE {subgroup}: {existing}/{len(items)} ok", flush=True)
    print(f"VALIDATE total={total} failures={len(failures)}", flush=True)
    for code, reason, path in failures:
        print(f"VALIDATE_FAIL {code}: {reason} -> {path}", flush=True)
    return failures

def create_contact_sheets(export_root: str, output_dir: str) -> list[Path]:
    out_dir = Path(output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 12)  # type: ignore[name-defined]
    except Exception:
        font = ImageFont.load_default()  # type: ignore[name-defined]

    def checker(size: tuple[int, int], cell: int = 8) -> Image.Image:
        image = Image.new("RGBA", size, (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)  # type: ignore[name-defined]
        for y in range(0, size[1], cell):
            for x in range(0, size[0], cell):
                color = (218, 222, 228, 255) if ((x // cell + y // cell) % 2) else (246, 247, 249, 255)
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=color)
        return image

    def split_label(label: str) -> list[str]:
        parts: list[str] = []
        remaining = label
        while len(remaining) > 18:
            cut = remaining.rfind("_", 0, 18)
            if cut <= 0:
                cut = 18
            parts.append(remaining[:cut])
            remaining = remaining[cut + 1 :] if remaining[cut : cut + 1] == "_" else remaining[cut:]
        parts.append(remaining)
        return parts[:3]

    saved: list[Path] = []
    for subgroup, slug in TARGET_SUBGROUPS.items():
        items = [item for item in target_items() if item.subgroup == subgroup]
        cols = 7
        tile_w, tile_h = 150, 184
        rows = (len(items) + cols - 1) // cols
        canvas = Image.new("RGBA", (cols * tile_w, rows * tile_h), (245, 246, 248, 255))
        draw = ImageDraw.Draw(canvas)  # type: ignore[name-defined]
        for idx, item in enumerate(items):
            path = target_path_for(item, export_root)
            if not path.exists():
                continue
            x = (idx % cols) * tile_w
            y = (idx // cols) * tile_h
            tile = checker((128, 128))
            icon = Image.open(path).convert("RGBA").resize((128, 128), Image.LANCZOS)
            tile.alpha_composite(icon, (0, 0))
            canvas.alpha_composite(tile, (x + 11, y + 8))
            for line_index, line in enumerate(split_label(item.code)):
                draw.text((x + 8, y + 140 + line_index * 13), line, fill=(30, 35, 45), font=font)
        out_path = out_dir / f"{slug}_contact_sheet.jpg"
        canvas.convert("RGB").save(out_path, quality=95)
        saved.append(out_path.resolve())
        print(f"CONTACT_SHEET {out_path.resolve()}", flush=True)
    return saved


def build_payload(item: ArtItem, model: str) -> dict[str, Any]:
    prompt = build_item_prompt(item, EXTRA_PROMPT_NOTE, use_blue_screen=True)
    negative = build_negative_prompt(item, use_blue_screen=True)
    if NEGATIVE_EXTRA.lower() not in negative.lower():
        negative = f"{negative}, {NEGATIVE_EXTRA}"
    return {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": "1:1",
        "output_format": "png",
        "negative_prompt": negative,
        BLUE_SCREEN_PAYLOAD_FLAG: True,
    }


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
) -> dict[str, Any]:
    start = time.monotonic()
    payload = build_payload(item, model)
    result = _generate_image_with_retry_no_ui(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        response_format="binary",
        timeout_seconds=timeout_seconds,
        retry_count=retry_count,
        retry_backoff_seconds=retry_backoff,
    )
    if result.get("kind") not in {"binary", "b64_json"}:
        raise RuntimeError(f"response has no binary image: kind={result.get('kind')}")
    image_bytes = result.get("image_bytes", b"")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise RuntimeError("empty image response")

    final_bytes = post_process_image(item, image_bytes)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(final_bytes)

    check = validate_png(target_path)
    if check["size"] != (256, 256) or check["mode"] != "RGBA":
        raise RuntimeError(f"invalid PNG shape/mode after save: {check}")
    if check["alpha_min"] != 0 or not check["has_subject"]:
        raise RuntimeError(f"invalid alpha/subject after save: {check}")
    return {
        "code": item.code,
        "path": str(target_path),
        "seconds": round(time.monotonic() - start, 1),
        "check": check,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate missing TuTien2 relic temp contract PNGs.")
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--contact-sheet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))

    if args.validate_only:
        failures = validate_contract(str(args.export_root))
        if args.contact_sheet:
            create_contact_sheets(str(args.export_root), str(args.output_dir))
        return 1 if failures else 0

    pending: list[tuple[ArtItem, Path]] = []
    for item in target_items():
        path = target_path_for(item, str(args.export_root))
        if path.exists() and not args.overwrite:
            continue
        pending.append((item, path))
    if args.limit > 0:
        pending = pending[: args.limit]

    key_count = len(parse_api_keys())
    print(f"model={args.model} workers={args.workers} keys={key_count} pending={len(pending)}", flush=True)
    for item, path in pending:
        print(f"PENDING {item.subgroup} {item.code} -> {path}", flush=True)
    if args.dry_run:
        if args.contact_sheet:
            create_contact_sheets(str(args.export_root), str(args.output_dir))
        return 0
    if not pending:
        failures = validate_contract(str(args.export_root))
        if args.contact_sheet:
            create_contact_sheets(str(args.export_root), str(args.output_dir))
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
                    print(f"OK {item.code} {info['seconds']}s -> {path}", flush=True)
                except Exception as exc:
                    completed += 1
                    failed.append((item.code, str(exc)))
                    print(f"ERROR {item.code}: {exc}", flush=True)
                submit_next(executor)

    print(f"DONE ok={completed - len(failed)} failed={len(failed)} total={len(pending)}", flush=True)
    validation_failures = validate_contract(str(args.export_root))
    if args.contact_sheet:
        create_contact_sheets(str(args.export_root), str(args.output_dir))
    if failed:
        for code, message in failed:
            print(f"FAILED {code}: {message}", flush=True)
        return 1
    return 1 if validation_failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr, flush=True)
        raise
