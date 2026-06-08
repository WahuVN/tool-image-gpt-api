from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nine_router_image import build_headers, build_url, load_env_file, normalize_base_url
from tutienco_art_catalog import CATALOG, GROUP_ORDER, ArtItem
from tutienco_art_workflow import resolve_output_path


EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien3"
DEFAULT_MODEL = "cx/gpt-5.4-image"
DEFAULT_OUTPUT_DIR = "outputs/tutien3_green_generation"
GREEN_RGB = (0, 255, 0)
GREEN_RGBA = (0, 255, 0, 255)

GREEN_PROMPT_RULE = """
Background rule for this TuTien3 batch: use a single flat pure chroma key green background (#00FF00, RGB 0,255,0).
Do not make the background transparent. Do not remove the green. The final PNG should be opaque with green visible behind and around the subject.
The green must be uniform, untextured, evenly lit, with no gradient, no scenery, no floor, no wall, no cast shadow on the green.
Keep the asset centered, fully inside the canvas, with generous padding. Avoid pure #00FF00 anywhere on the subject itself.
No watermark, no logo, no signature, no unintended text.
""".strip()

NEGATIVE_PROMPT = (
    "transparent background, alpha channel, checkerboard, white background, black background, gray background, "
    "gradient green, scenery background behind subject, floor, wall, cast shadow on background, watermark, logo, "
    "signature, text artifact, cropped, cut off, blurry, low quality, jpeg artifact"
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


def select_items(groups: str = "", priorities: str = "") -> list[ArtItem]:
    items = list(CATALOG)
    if groups.strip():
        wanted = {part.strip() for part in groups.split(",") if part.strip()}
        items = [item for item in items if item.group in wanted or item.group.split(".", 1)[0] in wanted]
    if priorities.strip():
        wanted_priority = {part.strip() for part in priorities.split(",") if part.strip()}
        items = [item for item in items if item.priority in wanted_priority]
    return items


def build_prompt(item: ArtItem, extra_note: str = "") -> str:
    rules = [rule for rule in item.extra_rules]
    adapted_rules = []
    for rule in rules:
        adapted = rule.replace("transparent background, alpha channel", "opaque flat #00FF00 green background")
        adapted = adapted.replace("transparent background", "opaque flat #00FF00 green background")
        adapted = adapted.replace("alpha channel", "no alpha channel, green background remains visible")
        adapted = adapted.replace("no scenery", "no scenery except the flat #00FF00 green background")
        adapted_rules.append(adapted)

    lines = [
        f"Art game asset: {item.title_vi} ({item.code}).",
        f"Description: {item.desc}.",
        f"Style: {item.style_hint or 'chinese fantasy game art'}, target output {item.size[0]}x{item.size[1]} px, aspect {item.aspect}.",
        GREEN_PROMPT_RULE,
        "Style target: 2D mobile game, tu tien cultivation fantasy poker, polished meme-cartoon, thick clean outline, bright readable colors.",
    ]
    if item.group == "F. Background":
        lines.append(
            "Even though this is a background-scene asset, this TuTien3 export is a green-screen pass: keep #00FF00 visible as the backing color. "
            "Render the requested scene/key visual cleanly over the green field without replacing the whole canvas with a normal scenic backdrop."
        )
    if adapted_rules:
        lines.append("Strict rules:")
        lines.extend(f"- {rule}" for rule in adapted_rules)
    if extra_note.strip():
        lines.append(f"Extra note: {extra_note.strip()}")
    return "\n".join(lines)


def build_payload(item: ArtItem, model: str, extra_note: str = "") -> dict[str, Any]:
    return {
        "model": model,
        "prompt": build_prompt(item, extra_note),
        "n": 1,
        "aspect_ratio": item.aspect,
        "output_format": "png",
        "negative_prompt": NEGATIVE_PROMPT,
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


def green_screen_score(pixel: tuple[int, int, int, int]) -> float:
    r, g, b, a = pixel
    if a == 0:
        return 1.0
    max_rb = max(int(r), int(b))
    green_delta = int(g) - max_rb
    green_ratio = int(g) / max(1, max_rb)
    score = 0.0
    if int(g) >= 80:
        score += max(0.0, min(1.0, green_delta / 80.0)) * 0.7
        score += max(0.0, min(1.0, (green_ratio - 1.05) / 0.9)) * 0.3
    return max(0.0, min(1.0, score))


def normalize_green_border(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width < 2 or height < 2:
        return rgba
    pixels = list(rgba.getdata())
    mask = bytearray(1 if green_screen_score(pixel) >= 0.38 else 0 for pixel in pixels)
    visited = bytearray(width * height)
    stack: list[int] = []
    for x in range(width):
        stack.append(x)
        stack.append((height - 1) * width + x)
    for y in range(height):
        stack.append(y * width)
        stack.append(y * width + width - 1)
    while stack:
        idx = stack.pop()
        if visited[idx] or not mask[idx]:
            continue
        visited[idx] = 1
        x = idx % width
        if x > 0:
            stack.append(idx - 1)
        if x < width - 1:
            stack.append(idx + 1)
        if idx >= width:
            stack.append(idx - width)
        if idx < width * (height - 1):
            stack.append(idx + width)
    if sum(visited) < max(16, int(width * height * 0.03)):
        return rgba
    output = []
    for idx, (r, g, b, a) in enumerate(pixels):
        output.append(GREEN_RGBA if visited[idx] else (r, g, b, 255))
    out = Image.new("RGBA", rgba.size, GREEN_RGBA)
    out.putdata(output)
    return out


def process_green_png(image_bytes: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(BytesIO(image_bytes)) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGBA")
    source = normalize_green_border(source)
    target_w, target_h = size
    sw, sh = source.size
    scale = min(target_w / sw, target_h / sh)
    new_w = max(1, int(round(sw * scale)))
    new_h = max(1, int(round(sh * scale)))
    resized = source.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), GREEN_RGBA)
    offset = ((target_w - new_w) // 2, (target_h - new_h) // 2)
    canvas.alpha_composite(resized, offset)
    canvas = normalize_green_border(canvas)
    # Keep PNG simple and opaque; the green screen is the background, not alpha.
    final = Image.new("RGB", canvas.size, GREEN_RGB)
    final.paste(canvas.convert("RGB"), mask=canvas.getchannel("A"))
    out = BytesIO()
    final.save(out, format="PNG")
    return out.getvalue()


def inspect_green_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        corners = [rgb.getpixel((0, 0)), rgb.getpixel((width - 1, 0)), rgb.getpixel((0, height - 1)), rgb.getpixel((width - 1, height - 1))]
        corner_green = sum(1 for pixel in corners if pixel == GREEN_RGB)
        edge_sample = []
        step_x = max(1, width // 24)
        step_y = max(1, height // 24)
        for x in range(0, width, step_x):
            edge_sample.append(rgb.getpixel((x, 0)))
            edge_sample.append(rgb.getpixel((x, height - 1)))
        for y in range(0, height, step_y):
            edge_sample.append(rgb.getpixel((0, y)))
            edge_sample.append(rgb.getpixel((width - 1, y)))
        edge_green_ratio = sum(1 for pixel in edge_sample if pixel == GREEN_RGB) / max(1, len(edge_sample))
        return {
            "size": rgb.size,
            "mode": im.mode,
            "corner_green": corner_green,
            "edge_green_ratio": edge_green_ratio,
        }


def validate(items: list[ArtItem], export_root: str) -> list[tuple[str, str, str]]:
    failures: list[tuple[str, str, str]] = []
    by_group: dict[str, tuple[int, int]] = {}
    for item in items:
        path = resolve_output_path(item, export_root)
        ok_count, total_count = by_group.get(item.group, (0, 0))
        total_count += 1
        if not path.exists():
            failures.append((item.code, "missing", str(path)))
            by_group[item.group] = (ok_count, total_count)
            continue
        try:
            check = inspect_green_png(path)
        except Exception as exc:
            failures.append((item.code, f"unreadable: {exc}", str(path)))
            by_group[item.group] = (ok_count, total_count)
            continue
        ok = check["size"] == item.size and check["corner_green"] == 4 and check["edge_green_ratio"] >= 0.45
        if ok:
            ok_count += 1
        else:
            failures.append((item.code, f"invalid green PNG: {check}", str(path)))
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
            icon = Image.open(path).convert("RGB")
            icon.thumbnail((128, 128), Image.LANCZOS)
            bg = Image.new("RGB", (128, 128), GREEN_RGB)
            bg.paste(icon, ((128 - icon.width) // 2, (128 - icon.height) // 2))
            canvas.paste(bg, (x + 11, y + 8))
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
        out_path = out_dir / f"{slug}_green_sheet.jpg"
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
    final_bytes = process_green_png(image_bytes, item.size)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(final_bytes)
    check = inspect_green_png(target_path)
    if check["size"] != item.size or check["corner_green"] != 4:
        raise RuntimeError(f"invalid saved green png: {check}")
    return {"code": item.code, "path": str(target_path), "seconds": round(time.monotonic() - start, 1)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate TuTien3 full art catalog on opaque green-screen PNG backgrounds.")
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
    parser.add_argument("--groups", default="", help="Optional comma list, e.g. A,B or 'A. Character,B. Relics'.")
    parser.add_argument("--priorities", default="", help="Optional comma list, e.g. P0,P1.")
    parser.add_argument("--extra-note", default="")
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

    if args.validate_only:
        failures = validate(items, str(args.export_root))
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
    print(f"model={args.model} workers={args.workers} catalog_items={len(items)} pending={len(pending)} keys={len(parse_api_keys())}", flush=True)
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
                    print(f"OK {item.code} {info['seconds']}s -> {path}", flush=True)
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
