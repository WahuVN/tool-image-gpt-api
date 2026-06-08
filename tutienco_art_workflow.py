"""Workflow Streamlit cho việc vẽ art game Tu Tiên Cờ.

Cho user:
- Xem danh sách art còn thiếu (đã catalog).
- Chọn nhiều item để vẽ batch.
- Tự động build prompt + payload theo từng item.
- Lưu file đúng path Unity Assets/Resources/...
- Auto post-process: nếu transparent=True thì tách nền (nếu Pillow available).
- Auto resize về size mục tiêu cuối cùng.

Module này được gọi từ nine_router_image_app.page_generate_quick khi
operation == "Vẽ art game Tu Tiên Cờ".
"""

from __future__ import annotations

import concurrent.futures
import io
import os
import random
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import streamlit as st

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore

from tutienco_art_catalog import (
    CATALOG,
    GROUP_ORDER,
    ArtItem,
    items_by_group,
    stats,
)


OLD_DEFAULT_EXPORT_ROOT = "TuTienCoArt"
DEFAULT_EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien2"
TUTIEN3_GREEN_EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien3"
TUTIEN4_PINK_EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien4"
TUTIEN5_EXPORT_ROOT = r"D:\TOOL\TOOL Anh\TuTien5"
SUPPLEMENT_20260528_GROUPS = {
    "H. System 2026-05-28",
    "J. Achievements 2026-05-28",
    "K. Quest 2026-05-28",
}
BLUE_SCREEN_PAYLOAD_FLAG = "_blue_screen_remove_background"
GREEN_SCREEN_RAW_PAYLOAD_FLAG = "_green_screen_keep_background"
CHROMA_BACKGROUND_OPTIONS = {
    "green": {
        "label": "Xanh lá",
        "rgb": (0, 255, 0),
        "rgb_text": "RGB 0,255,0",
        "name_en": "pure green",
        "avoid": "pure green details on the subject",
    },
    "blue": {
        "label": "Xanh biển",
        "rgb": (0, 0, 255),
        "rgb_text": "RGB 0,0,255",
        "name_en": "pure blue",
        "avoid": "pure blue details on the subject",
    },
    "pink": {
        "label": "Hồng",
        "rgb": (255, 0, 255),
        "rgb_text": "RGB 255,0,255",
        "name_en": "pure hot pink / magenta",
        "avoid": "pure hot-pink or magenta details on the subject",
    },
}
BACKGROUND_OUTPUT_OPTIONS = {
    "remove": "Tách nền ra PNG trong suốt",
    "keep": "Giữ nền màu trong PNG final",
}
TUTIEN_GREEN_SCREEN_RAW_PROMPT = (
    "Use a single flat pure chroma key green background (#00FF00, RGB 0,255,0) behind the asset. "
    "Do not make the background transparent and do not remove the green. The green must be uniform, untextured, "
    "evenly lit, with no gradient, no scenery, no floor, no wall, no cast shadow on the green background. "
    "Keep the subject fully inside the canvas with generous padding. Avoid pure #00FF00 on the subject itself."
)
TUTIEN_GREEN_SCREEN_RAW_NEGATIVE = (
    "transparent background, alpha channel, checkerboard, white background, black background, gray background, "
    "gradient green, uneven green, scenery background, floor, wall, cast shadow on background, pure #00FF00 subject details"
)
TUTIEN_BLUE_SCREEN_PROMPT = (
    "Use a single flat pure chroma key blue background (#0000FF, RGB 0,0,255) behind the asset. "
    "The blue must be uniform, untextured, evenly lit, with no gradient, no scenery, no floor, no wall, "
    "no cast shadow on the background. Fill every gap around and inside the silhouette with exact #0000FF. "
    "Avoid pure #0000FF on the subject itself; if blue details are required, use darker navy/cyan tones with a clear outline."
)
TUTIEN_BLUE_SCREEN_NEGATIVE = (
    "transparent background, white background, black background, gray background, checkerboard, scenery, room, wall, floor, "
    "gradient blue background, uneven blue, dark blue patches, sky background, ocean background, water background, blue spill on subject, "
    "pure #0000FF subject details"
)


# =====================================================================
# Prompt builder
# =====================================================================

def _adapt_transparent_rule(rule: str, use_blue_screen: bool) -> str:
    if not use_blue_screen:
        return rule
    adapted = rule.replace(
        "transparent background, alpha channel",
        "flat pure #0000FF chroma key background for later PNG alpha cutout",
    )
    adapted = adapted.replace("transparent background", "flat pure #0000FF chroma key background")
    adapted = adapted.replace("alpha channel", "clean isolated silhouette")
    adapted = adapted.replace("no scenery", "no scenery, only flat #0000FF outside the subject")
    return adapted

def build_item_prompt(item: ArtItem, extra_user_note: str = "", use_blue_screen: bool = True) -> str:
    """Build prompt chi tiết cho 1 art item."""
    lines: list[str] = []
    lines.append(f"Art game asset: {item.title_vi} ({item.code}).")
    lines.append(f"Description: {item.desc}.")
    lines.append(
        f"Style: {item.style_hint or 'chinese fantasy game art'}, "
        f"target output {item.size[0]}x{item.size[1]} px."
    )

    if item.transparent and use_blue_screen:
        lines.append(
            "Background workflow: generate on chroma key blue, then the app will remove blue into PNG alpha. "
            f"{TUTIEN_BLUE_SCREEN_PROMPT}"
        )
    elif item.transparent:
        lines.append(
            "MUST be on transparent background (PNG alpha=0 outside subject). "
            "No background, no scenery, no floor shadow, no environment, no extra object."
        )
    else:
        lines.append(
            "Full scene background; do NOT make it transparent."
        )

    if item.extra_rules:
        lines.append("Strict rules:")
        for rule in item.extra_rules:
            lines.append(f"- {_adapt_transparent_rule(rule, item.transparent and use_blue_screen)}")

    lines.append(
        "Quality: high detail, professional game art, clean composition, "
        "production-ready, sharp edges, no watermark, no signature, no text artifact."
    )

    extra = (extra_user_note or "").strip()
    if extra:
        lines.append(f"Extra note: {extra}")

    return "\n".join(lines)


def build_negative_prompt(item: ArtItem, use_blue_screen: bool = True) -> str:
    base = [
        "watermark", "signature", "logo error", "text artifact", "wrong text",
        "extra limbs", "deformed hand", "bad anatomy", "blurry", "low quality",
        "jpeg artifact", "cropped", "cut off", "frame border outside",
    ]
    if item.transparent and use_blue_screen:
        base.extend([part.strip() for part in TUTIEN_BLUE_SCREEN_NEGATIVE.split(",") if part.strip()])
    elif item.transparent:
        base.extend([
            "background", "scenery", "room", "landscape", "floor", "wall",
            "white background", "black background", "checker pattern",
        ])
    return ", ".join(base)

def _chroma_spec(color_key: str) -> dict[str, Any]:
    return CHROMA_BACKGROUND_OPTIONS.get(color_key, CHROMA_BACKGROUND_OPTIONS["blue"])

def build_item_prompt_chroma(
    item: ArtItem,
    extra_user_note: str = "",
    *,
    color_key: str = "blue",
    output_mode: str = "remove",
) -> str:
    """Build prompt for a flat colored background, either kept or removed locally."""
    if not item.transparent and output_mode == "remove":
        return build_item_prompt(item, extra_user_note, use_blue_screen=False)

    spec = _chroma_spec(color_key)
    color_label = str(spec["label"])
    workflow = (
        f"Background workflow: draw on a single flat {spec['name_en']} screen background ({spec['rgb_text']}). "
        "The background must be one uniform color with no gradient, no texture, no scenery, no floor, no wall, and no cast shadow. "
        "Keep the asset centered, fully inside the canvas, with generous padding. "
        f"Avoid {spec['avoid']}."
    )
    if output_mode == "remove":
        workflow += " The app will remove this colored background locally after generation and export PNG alpha."
    else:
        workflow += " Keep this colored background visible in the final PNG; do not make the output transparent."

    lines: list[str] = [
        f"Art game asset: {item.title_vi} ({item.code}).",
        f"Description: {item.desc}.",
        f"Style: {item.style_hint or 'chinese fantasy game art'}, target output {item.size[0]}x{item.size[1]} px.",
        workflow,
    ]
    if item.group == "F. Background" and output_mode == "keep":
        lines.append(
            f"This is a {color_label} screen pass: keep the flat color visible as the backing field while rendering the requested key visual cleanly over it."
        )
    if item.extra_rules:
        lines.append("Strict rules:")
        for rule in item.extra_rules:
            adapted = rule.replace("transparent background, alpha channel", f"flat {color_label} screen background")
            adapted = adapted.replace("transparent background", f"flat {color_label} screen background")
            adapted = adapted.replace("alpha channel", "clean isolated silhouette" if output_mode == "remove" else "opaque colored background")
            adapted = adapted.replace("no scenery", f"no scenery, only the flat {color_label} screen outside the subject")
            lines.append(f"- {adapted}")
    lines.append(
        "Quality: high detail, professional game art, clean composition, production-ready, sharp edges, no watermark, no signature, no text artifact."
    )
    extra = (extra_user_note or "").strip()
    if extra:
        lines.append(f"Extra note: {extra}")
    return "\n".join(lines)

def build_negative_prompt_chroma(item: ArtItem, color_key: str, output_mode: str) -> str:
    if not item.transparent and output_mode == "remove":
        return build_negative_prompt(item, use_blue_screen=False)

    spec = _chroma_spec(color_key)
    base = [
        "watermark", "signature", "logo error", "text artifact", "wrong text",
        "extra limbs", "deformed hand", "bad anatomy", "blurry", "low quality",
        "jpeg artifact", "cropped", "cut off", "frame border outside",
        "gradient colored background", "textured background", "floor", "wall", "cast shadow on background",
        str(spec["avoid"]),
    ]
    if output_mode == "keep":
        base.extend(["transparent background", "alpha channel", "checkerboard"])
    else:
        base.extend(["white background", "black background", "gray background", "scenery background"])
    return ", ".join(base)

def build_item_prompt_green_raw(item: ArtItem, extra_user_note: str = "") -> str:
    """Build prompt for TuTien3 green-screen PNGs that keep the green background."""
    lines: list[str] = []
    lines.append(f"Art game asset: {item.title_vi} ({item.code}).")
    lines.append(f"Description: {item.desc}.")
    lines.append(
        f"Style: {item.style_hint or 'chinese fantasy game art'}, "
        f"target output {item.size[0]}x{item.size[1]} px."
    )
    lines.append(
        "Background workflow: TuTien3 green-screen export, keep the chroma key green in the final PNG. "
        f"{TUTIEN_GREEN_SCREEN_RAW_PROMPT}"
    )
    if item.group == "F. Background":
        lines.append(
            "This is still a green-screen pass: keep #00FF00 visible as the backing color. "
            "Render the requested scene/key visual cleanly over the green field instead of replacing the full canvas with a normal scenic backdrop."
        )
    if item.extra_rules:
        lines.append("Strict rules:")
        for rule in item.extra_rules:
            adapted = rule.replace("transparent background, alpha channel", "opaque flat #00FF00 green background")
            adapted = adapted.replace("transparent background", "opaque flat #00FF00 green background")
            adapted = adapted.replace("alpha channel", "no alpha channel, green background remains visible")
            adapted = adapted.replace("no scenery", "no scenery except the flat #00FF00 green background")
            lines.append(f"- {adapted}")
    lines.append(
        "Quality: high detail, professional game art, clean composition, production-ready, "
        "sharp edges, no watermark, no signature, no text artifact."
    )
    extra = (extra_user_note or "").strip()
    if extra:
        lines.append(f"Extra note: {extra}")
    return "\n".join(lines)

def build_negative_prompt_green_raw(item: ArtItem) -> str:
    base = build_negative_prompt(item, use_blue_screen=False)
    additions = [part.strip() for part in TUTIEN_GREEN_SCREEN_RAW_NEGATIVE.split(",") if part.strip()]
    existing = {part.strip().lower() for part in base.split(",") if part.strip()}
    merged = [part.strip() for part in base.split(",") if part.strip()]
    for addition in additions:
        if addition.lower() not in existing:
            merged.append(addition)
            existing.add(addition.lower())
    return ", ".join(merged)


# =====================================================================
# Output path helpers
# =====================================================================

def resolve_output_path(item: ArtItem, export_root: str) -> Path:
    """Path tuyệt đối nơi sẽ lưu file PNG cuối cùng cho item."""
    root = Path(export_root.strip() or DEFAULT_EXPORT_ROOT)
    if not root.is_absolute():
        root = Path.cwd() / root
    rel = Path(item.relpath + ".png")
    return (root / rel).resolve()


def resolve_raw_chroma_output_path(target_path: Path, variant_idx: int = 1) -> Path:
    """Path lưu bản gốc còn nền chroma trước khi tách alpha."""
    suffix = target_path.suffix or ".png"
    raw_dir = target_path.parent / "_raw_chroma"
    variant_suffix = "" if variant_idx == 1 else f"_v{variant_idx}"
    return raw_dir / f"{target_path.stem}{variant_suffix}_raw_chroma{suffix}"

def resolve_raw_background_output_path(target_path: Path, color_key: str, variant_idx: int = 1) -> Path:
    """Path lưu bản gốc nền màu trước hậu kỳ để backup."""
    suffix = target_path.suffix or ".png"
    raw_dir = target_path.parent / "_raw_background"
    variant_suffix = "" if variant_idx == 1 else f"_v{variant_idx}"
    return raw_dir / f"{target_path.stem}{variant_suffix}_{color_key}_raw{suffix}"


# =====================================================================
# Post-process: alpha + resize
# =====================================================================

def _looks_transparent_png(image_bytes: bytes) -> bool:
    """Check ảnh đã có alpha thật chưa (có pixel alpha < 255)."""
    if Image is None or not image_bytes:
        return False
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            if im.mode in ("RGBA", "LA"):
                alpha = im.split()[-1]
                extrema = alpha.getextrema()
                return bool(extrema and extrema[0] < 250)
    except Exception:
        return False
    return False


def auto_remove_white_background(image_bytes: bytes, threshold: int = 240) -> bytes:
    """Fallback đơn giản: biến vùng trắng/sáng gần biên thành alpha=0.

    Không phải remove-bg AI, nhưng giúp ảnh game asset có nền trắng / xám sáng
    chuyển sang nền trong suốt được dùng ngay. Hoạt động tốt với icon/relic vốn
    đã được prompt yêu cầu nền sạch.
    """
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGBA")
            w, h = im.size
            pixels = im.load()
            # Lấy 4 góc làm "màu nền tham chiếu".
            corners = [pixels[0, 0], pixels[w - 1, 0], pixels[0, h - 1], pixels[w - 1, h - 1]]
            # Nếu cả 4 góc đều "sáng" (mỗi kênh > threshold) thì coi là nền trắng/sáng.
            light = all(
                isinstance(c, tuple) and len(c) >= 3 and c[0] > threshold and c[1] > threshold and c[2] > threshold
                for c in corners
            )
            if not light:
                return image_bytes  # Không chắc là nền trắng, để nguyên.

            # Flood-fill 4 mép thành alpha=0 cho các pixel "sáng".
            from collections import deque
            visited = [[False] * h for _ in range(w)]
            stack: deque[tuple[int, int]] = deque()
            for x in range(w):
                stack.append((x, 0))
                stack.append((x, h - 1))
            for y in range(h):
                stack.append((0, y))
                stack.append((w - 1, y))
            while stack:
                x, y = stack.popleft()
                if x < 0 or y < 0 or x >= w or y >= h or visited[x][y]:
                    continue
                visited[x][y] = True
                px = pixels[x, y]
                if not isinstance(px, tuple) or len(px) < 3:
                    continue
                r, g, b = px[0], px[1], px[2]
                if r > threshold and g > threshold and b > threshold:
                    pixels[x, y] = (r, g, b, 0)
                    stack.append((x + 1, y))
                    stack.append((x - 1, y))
                    stack.append((x, y + 1))
                    stack.append((x, y - 1))

            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return image_bytes


def resize_to_target(image_bytes: bytes, size: tuple[int, int]) -> bytes:
    """Resize giữ tỉ lệ canvas; nếu đầu vào không vuông sẽ pad alpha."""
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGBA")
            target_w, target_h = size
            sw, sh = im.size
            if (sw, sh) == (target_w, target_h):
                return image_bytes
            # Fit-inside, giữ tỉ lệ.
            scale = min(target_w / sw, target_h / sh)
            new_w = max(1, int(round(sw * scale)))
            new_h = max(1, int(round(sh * scale)))
            resized = im.resize((new_w, new_h), Image.LANCZOS)
            canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            offset_x = (target_w - new_w) // 2
            offset_y = (target_h - new_h) // 2
            canvas.paste(resized, (offset_x, offset_y), resized)
            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return image_bytes


def post_process_image(item: ArtItem, image_bytes: bytes) -> bytes:
    """Apply alpha cleanup + resize theo cấu hình của item."""
    if not image_bytes:
        return image_bytes

    processed = image_bytes
    if item.transparent:
        try:
            from nine_router_image_app import ensure_transparent_png_rgba_bytes

            processed = ensure_transparent_png_rgba_bytes(processed, remove_blue_screen=True)
        except Exception:
            if not _looks_transparent_png(processed):
                processed = auto_remove_white_background(processed)

    processed = resize_to_target(processed, item.size)
    return processed

def post_process_green_screen_image(item: ArtItem, image_bytes: bytes) -> bytes:
    """Resize/pad onto an opaque #00FF00 canvas without removing the green background."""
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGBA")
            target_w, target_h = item.size
            sw, sh = im.size
            scale = min(target_w / sw, target_h / sh)
            new_w = max(1, int(round(sw * scale)))
            new_h = max(1, int(round(sh * scale)))
            resized = im.resize((new_w, new_h), Image.LANCZOS)
            canvas = Image.new("RGBA", (target_w, target_h), (0, 255, 0, 255))
            offset_x = (target_w - new_w) // 2
            offset_y = (target_h - new_h) // 2
            canvas.alpha_composite(resized, (offset_x, offset_y))
            final = Image.new("RGB", (target_w, target_h), (0, 255, 0))
            final.paste(canvas.convert("RGB"), mask=canvas.getchannel("A"))
            buf = io.BytesIO()
            final.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return image_bytes

def _chroma_match(pixel: tuple[int, int, int, int], target_rgb: tuple[int, int, int]) -> bool:
    r, g, b, a = pixel
    if int(a) == 0:
        return True
    tr, tg, tb = target_rgb
    distance = ((int(r) - tr) ** 2 + (int(g) - tg) ** 2 + (int(b) - tb) ** 2) ** 0.5
    if distance <= 95:
        return True
    if target_rgb == (0, 255, 0):
        return int(g) >= 80 and int(g) - max(int(r), int(b)) >= 35
    if target_rgb == (0, 0, 255):
        return int(b) >= 80 and int(b) - max(int(r), int(g)) >= 35
    if target_rgb == (255, 0, 255):
        return int(r) >= 120 and int(b) >= 120 and min(int(r), int(b)) - int(g) >= 35
    return False

def remove_chroma_background_bytes(image_bytes: bytes, color_key: str) -> bytes:
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
        target_rgb = tuple(_chroma_spec(color_key)["rgb"])  # type: ignore[arg-type]
        width, height = image.size
        if width < 2 or height < 2:
            return image_bytes
        pixels = list(image.getdata())
        mask = bytearray(1 if _chroma_match(pixel, target_rgb) else 0 for pixel in pixels)  # type: ignore[arg-type]
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
        if sum(visited) < max(16, int(width * height * 0.01)):
            return image_bytes
        out_pixels: list[tuple[int, int, int, int]] = []
        for idx, (r, g, b, a) in enumerate(pixels):
            if visited[idx]:
                out_pixels.append((r, g, b, 0))
            else:
                out_pixels.append((r, g, b, a))
        out = Image.new("RGBA", image.size, (0, 0, 0, 0))
        out.putdata(out_pixels)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes

def resize_to_target_with_canvas(
    image_bytes: bytes,
    size: tuple[int, int],
    *,
    background_rgb: tuple[int, int, int] | None,
) -> bytes:
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
        target_w, target_h = size
        sw, sh = image.size
        scale = min(target_w / sw, target_h / sh)
        new_w = max(1, int(round(sw * scale)))
        new_h = max(1, int(round(sh * scale)))
        resized = image.resize((new_w, new_h), Image.LANCZOS)
        if background_rgb is None:
            canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            canvas.alpha_composite(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            return buf.getvalue()
        canvas = Image.new("RGBA", (target_w, target_h), (*background_rgb, 255))
        canvas.alpha_composite(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        final = Image.new("RGB", (target_w, target_h), background_rgb)
        final.paste(canvas.convert("RGB"), mask=canvas.getchannel("A"))
        buf = io.BytesIO()
        final.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes

def resize_scene_to_target_bytes(image_bytes: bytes, size: tuple[int, int]) -> bytes:
    """Resize opaque backgrounds with center-crop so 16:9 scenes fill the canvas."""
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
        target_w, target_h = size
        sw, sh = image.size
        scale = max(target_w / sw, target_h / sh)
        new_w = max(1, int(round(sw * scale)))
        new_h = max(1, int(round(sh * scale)))
        resized = image.resize((new_w, new_h), Image.LANCZOS)
        left = max(0, (new_w - target_w) // 2)
        top = max(0, (new_h - target_h) // 2)
        cropped = resized.crop((left, top, left + target_w, top + target_h))
        final = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        final.paste(cropped.convert("RGB"), mask=cropped.getchannel("A"))
        buf = io.BytesIO()
        final.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes

def flatten_to_background_bytes(image_bytes: bytes, background_rgb: tuple[int, int, int]) -> bytes:
    if Image is None or not image_bytes:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
        final = Image.new("RGB", image.size, background_rgb)
        final.paste(image.convert("RGB"), mask=image.getchannel("A"))
        buf = io.BytesIO()
        final.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes

def post_process_chroma_image(
    item: ArtItem,
    image_bytes: bytes,
    *,
    color_key: str,
    output_mode: str,
    resize_enabled: bool,
) -> bytes:
    processed = image_bytes
    if not item.transparent and output_mode == "remove":
        if resize_enabled:
            return resize_scene_to_target_bytes(processed, item.size)
        return flatten_to_background_bytes(processed, (0, 0, 0))

    target_rgb = tuple(_chroma_spec(color_key)["rgb"])  # type: ignore[arg-type]
    if output_mode == "remove":
        processed = remove_chroma_background_bytes(processed, color_key)
        if resize_enabled:
            processed = resize_to_target_with_canvas(processed, item.size, background_rgb=None)
    else:
        if resize_enabled:
            processed = resize_to_target_with_canvas(processed, item.size, background_rgb=target_rgb)  # type: ignore[arg-type]
        else:
            processed = flatten_to_background_bytes(processed, target_rgb)  # type: ignore[arg-type]
    return processed


# =====================================================================
# Streamlit UI
# =====================================================================

def _ensure_state() -> None:
    st.session_state.setdefault("tutienco_export_root", DEFAULT_EXPORT_ROOT)
    if str(st.session_state.get("tutienco_export_root", "")).strip() == OLD_DEFAULT_EXPORT_ROOT:
        st.session_state.tutienco_export_root = DEFAULT_EXPORT_ROOT
    st.session_state.setdefault("tutienco_user_note", "")
    st.session_state.setdefault("tutienco_overwrite_existing", False)
    st.session_state.setdefault("tutienco_use_post_process", True)
    st.session_state.setdefault("tutienco_use_green_screen_transparent", True)
    st.session_state.setdefault("tutienco_green_screen_raw_mode", False)
    st.session_state.setdefault("tutienco_background_color", "blue")
    st.session_state.setdefault("tutienco_background_output", "remove")
    st.session_state.setdefault("tutienco_resize_output", True)
    st.session_state.setdefault("tutienco_save_raw_background", True)
    if bool(st.session_state.get("tutienco_green_screen_raw_mode", False)) and str(st.session_state.get("tutienco_export_root", "")) == TUTIEN3_GREEN_EXPORT_ROOT:
        st.session_state.tutienco_background_color = "green"
        st.session_state.tutienco_background_output = "keep"
    if st.session_state.tutienco_background_color not in CHROMA_BACKGROUND_OPTIONS:
        st.session_state.tutienco_background_color = "blue"
    if st.session_state.tutienco_background_output not in BACKGROUND_OUTPUT_OPTIONS:
        st.session_state.tutienco_background_output = "remove"
    st.session_state.setdefault("tutienco_force_transparent_api", False)
    st.session_state.setdefault("tutienco_selected_codes", [])
    st.session_state.tutienco_selected_codes = _ordered_item_ids(st.session_state.tutienco_selected_codes)
    st.session_state.setdefault("tutienco_selected_component_keys", [])
    st.session_state.setdefault("tutienco_run_status", {})
    st.session_state.setdefault("tutienco_last_run_summary", [])
    st.session_state.setdefault("tutienco_parallel_workers", 4)
    st.session_state.setdefault("tutienco_priority_filter", "Tất cả")
    for group in GROUP_ORDER:
        st.session_state.setdefault(f"tutienco_group_open__{group}", False)


def _is_tutien5(item: ArtItem) -> bool:
    """TuTien5 item có relpath bắt đầu bằng 'Assets/' (catalog checklist 2026-06-06)."""
    return item.relpath.replace("\\", "/").startswith("Assets/")


def _base_catalog() -> list[ArtItem]:
    return [item for item in CATALOG if not _is_tutien5(item)]


def _tutien5_catalog() -> list[ArtItem]:
    return [item for item in CATALOG if _is_tutien5(item)]


def _filter_items(priority_filter: str, only_missing: bool, export_root: str) -> list[ArtItem]:
    # Mỗi đích chỉ hiển thị đúng bộ của nó: TuTien5 -> item Assets/...; còn lại -> item gốc.
    if str(export_root).strip() == TUTIEN5_EXPORT_ROOT:
        items = _tutien5_catalog()
    else:
        items = _base_catalog()
    if priority_filter != "Tất cả":
        items = [item for item in items if item.priority == priority_filter]
    if only_missing:
        items = [item for item in items if not resolve_output_path(item, export_root).exists()]
    return items


def _item_id(item: ArtItem) -> str:
    return item.relpath

def _item_widget_key(item: ArtItem) -> str:
    return item.relpath.replace("\\", "/").replace("/", "__").replace(" ", "_").replace(".", "_")

def _find_by_item_id(item_id: str) -> ArtItem | None:
    return next((item for item in CATALOG if _item_id(item) == item_id), None)

def _item_ids_from_values(values: set[str] | list[str] | tuple[str, ...]) -> set[str]:
    """Accept current relpath IDs and legacy code values from older session state."""
    raw_values = set(values)
    relpaths = {_item_id(item) for item in CATALOG}
    normalized = {value for value in raw_values if value in relpaths}
    legacy_codes = raw_values - normalized
    if legacy_codes:
        normalized.update(_item_id(item) for item in CATALOG if item.code in legacy_codes)
    return normalized

def _ordered_item_ids(item_ids: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    id_set = _item_ids_from_values(item_ids)
    return [_item_id(item) for item in CATALOG if _item_id(item) in id_set]

def _set_item_codes_selected(codes: list[str], selected: bool) -> None:
    current = _item_ids_from_values(st.session_state.get("tutienco_selected_codes", []))
    code_set = _item_ids_from_values(codes)
    if selected:
        current.update(code_set)
    else:
        current.difference_update(code_set)
    st.session_state.tutienco_selected_codes = _ordered_item_ids(current)
    for item in CATALOG:
        if _item_id(item) in code_set:
            st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = selected

def _clear_all_item_selection() -> None:
    st.session_state.tutienco_selected_codes = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = False

def _setup_full_redraw_tutien2() -> None:
    Path(DEFAULT_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    st.session_state.tutienco_export_root = DEFAULT_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = False
    st.session_state.tutienco_overwrite_existing = True
    st.session_state.tutienco_green_screen_raw_mode = False
    st.session_state.tutienco_use_green_screen_transparent = True
    st.session_state.tutienco_background_color = "blue"
    st.session_state.tutienco_background_output = "remove"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in _base_catalog()]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = not _is_tutien5(item)
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = False

def _setup_full_redraw_tutien3_green() -> None:
    Path(TUTIEN3_GREEN_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    st.session_state.tutienco_export_root = TUTIEN3_GREEN_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = False
    st.session_state.tutienco_overwrite_existing = True
    st.session_state.tutienco_use_post_process = True
    st.session_state.tutienco_green_screen_raw_mode = True
    st.session_state.tutienco_use_green_screen_transparent = False
    st.session_state.tutienco_background_color = "green"
    st.session_state.tutienco_background_output = "keep"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in _base_catalog()]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = not _is_tutien5(item)
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = False

def _setup_tutien3_supplement_20260528() -> None:
    Path(TUTIEN3_GREEN_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    selected_items = [item for item in CATALOG if item.group in SUPPLEMENT_20260528_GROUPS]
    st.session_state.tutienco_export_root = TUTIEN3_GREEN_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = True
    st.session_state.tutienco_overwrite_existing = False
    st.session_state.tutienco_use_post_process = True
    st.session_state.tutienco_green_screen_raw_mode = False
    st.session_state.tutienco_use_green_screen_transparent = True
    st.session_state.tutienco_background_color = "green"
    st.session_state.tutienco_background_output = "remove"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in selected_items]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    selected_ids = {_item_id(item) for item in selected_items}
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = _item_id(item) in selected_ids
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = group in SUPPLEMENT_20260528_GROUPS

def _setup_full_redraw_tutien4_pink_icons() -> None:
    Path(TUTIEN4_PINK_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    selected_items = [item for item in _base_catalog() if item.transparent]
    selected_ids = {_item_id(item) for item in selected_items}
    st.session_state.tutienco_export_root = TUTIEN4_PINK_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = False
    st.session_state.tutienco_overwrite_existing = True
    st.session_state.tutienco_use_post_process = True
    st.session_state.tutienco_green_screen_raw_mode = False
    st.session_state.tutienco_use_green_screen_transparent = True
    st.session_state.tutienco_background_color = "pink"
    st.session_state.tutienco_background_output = "remove"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in selected_items]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = _item_id(item) in selected_ids
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = any(item.group == group for item in selected_items)

def _setup_missing_tutien4_pink_icons() -> None:
    Path(TUTIEN4_PINK_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    selected_items = [
        item for item in _base_catalog()
        if item.transparent and not resolve_output_path(item, TUTIEN4_PINK_EXPORT_ROOT).exists()
    ]
    selected_ids = {_item_id(item) for item in selected_items}
    st.session_state.tutienco_export_root = TUTIEN4_PINK_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = True
    st.session_state.tutienco_overwrite_existing = False
    st.session_state.tutienco_use_post_process = True
    st.session_state.tutienco_green_screen_raw_mode = False
    st.session_state.tutienco_use_green_screen_transparent = True
    st.session_state.tutienco_background_color = "pink"
    st.session_state.tutienco_background_output = "remove"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in selected_items]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = _item_id(item) in selected_ids
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = any(item.group == group for item in selected_items)

def _apply_tutien5_selection(selected_items: list[ArtItem], *, overwrite: bool) -> None:
    """Setup chung cho TuTien5: vẽ nền hồng → tách alpha, lưu vào TuTien5."""
    Path(TUTIEN5_EXPORT_ROOT).mkdir(parents=True, exist_ok=True)
    selected_ids = {_item_id(item) for item in selected_items}
    st.session_state.tutienco_export_root = TUTIEN5_EXPORT_ROOT
    st.session_state.tutienco_priority_filter = "Tất cả"
    st.session_state.tutienco_hide_done = not overwrite
    st.session_state.tutienco_overwrite_existing = overwrite
    st.session_state.tutienco_use_post_process = True
    st.session_state.tutienco_green_screen_raw_mode = False
    st.session_state.tutienco_use_green_screen_transparent = True
    st.session_state.tutienco_background_color = "pink"
    st.session_state.tutienco_background_output = "remove"
    st.session_state.tutienco_resize_output = True
    st.session_state.tutienco_save_raw_background = True
    st.session_state.tutienco_selected_codes = [_item_id(item) for item in selected_items]
    st.session_state.tutienco_run_status = {}
    st.session_state.tutienco_last_run_summary = []
    for item in CATALOG:
        st.session_state[f"tutien_pick__{_item_widget_key(item)}"] = _item_id(item) in selected_ids
    for group in GROUP_ORDER:
        st.session_state[f"tutienco_group_open__{group}"] = any(item.group == group for item in selected_items)

def _setup_missing_tutien5() -> None:
    selected_items = [
        item for item in _tutien5_catalog()
        if not resolve_output_path(item, TUTIEN5_EXPORT_ROOT).exists()
    ]
    _apply_tutien5_selection(selected_items, overwrite=False)

def _setup_full_redraw_tutien5() -> None:
    _apply_tutien5_selection(_tutien5_catalog(), overwrite=True)

def _component_key(item: ArtItem) -> str:
    return f"{item.group}::{item.subgroup or 'Khác'}"

def _component_label(component_key: str) -> str:
    group, _, subgroup = component_key.partition("::")
    return f"{group} / {subgroup or 'Khác'}"

def _items_by_component(items: list[ArtItem]) -> dict[str, list[ArtItem]]:
    grouped: dict[str, list[ArtItem]] = {}
    for item in items:
        grouped.setdefault(_component_key(item), []).append(item)
    return grouped

def _component_sort_key(component_key: str) -> tuple[int, str]:
    group, _, subgroup = component_key.partition("::")
    try:
        group_index = GROUP_ORDER.index(group)
    except ValueError:
        group_index = len(GROUP_ORDER)
    return group_index, subgroup

def _selected_component_keys(component_keys: list[str]) -> list[str]:
    selected: list[str] = []
    for key in component_keys:
        if st.session_state.get(f"tutien_component_pick__{key}", False):
            selected.append(key)
    st.session_state.tutienco_selected_component_keys = selected
    return selected

def _status_label(status: str) -> str:
    labels = {
        "pending": "⏳ Chờ vẽ",
        "running": "🎨 Đang vẽ",
        "ok": "✅ Xong",
        "error": "❌ Lỗi",
        "skipped": "⏭ Bỏ qua",
        "done": "✅ Đã có file",
    }
    return labels.get(status, status or "⏳ Chờ vẽ")

def _set_run_status(
    item: ArtItem,
    status: str,
    *,
    message: str = "",
    path: str | None = None,
    files: list[str] | None = None,
) -> None:
    records = dict(st.session_state.get("tutienco_run_status", {}))
    target_path = path or str(resolve_output_path(item, str(st.session_state.get("tutienco_export_root", DEFAULT_EXPORT_ROOT))))
    records[_item_id(item)] = {
        "status": status,
        "message": message,
        "path": target_path,
        "files": files or [],
        "updated": datetime.now().strftime("%H:%M:%S"),
    }
    st.session_state.tutienco_run_status = records

def _scan_run_status(items: list[ArtItem], export_root: str) -> None:
    records: dict[str, dict[str, Any]] = {}
    now_label = datetime.now().strftime("%H:%M:%S")
    for item in items:
        path = resolve_output_path(item, export_root)
        exists = path.exists()
        records[_item_id(item)] = {
            "status": "done" if exists else "pending",
            "message": "File đã tồn tại" if exists else "Chưa có file",
            "path": str(path),
            "files": [str(path)] if exists else [],
            "updated": now_label,
        }
    st.session_state.tutienco_run_status = records

def _status_rows(items: list[ArtItem], export_root: str) -> list[dict[str, Any]]:
    records = st.session_state.get("tutienco_run_status", {})
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        target_path = resolve_output_path(item, export_root)
        record = records.get(_item_id(item), {}) if isinstance(records, dict) else {}
        status = str(record.get("status") or ("done" if target_path.exists() else "pending"))
        rows.append({
            "#": index,
            "Trạng thái": _status_label(status),
            "Code": item.code,
            "Tên": item.title_vi,
            "Nhóm": item.group,
            "Thành phần": item.subgroup or "Khác",
            "Ưu tiên": item.priority,
            "Size": f"{item.size[0]}x{item.size[1]}",
            "Cập nhật": record.get("updated", ""),
            "Ghi chú": record.get("message", "File đã tồn tại" if target_path.exists() else ""),
            "File": str(record.get("path") or target_path),
        })
    return rows

def _render_status_table(items: list[ArtItem], export_root: str, slot: Any | None = None) -> None:
    rows = _status_rows(items, export_root)
    target = slot or st
    if not rows:
        target.info("Chưa có item để kiểm tra tiến độ.")
        return
    target.dataframe(rows, hide_index=True, use_container_width=True, height=min(520, 88 + len(rows) * 34))

def _update_progress(progress: Any, value: float, text: str = "") -> None:
    value = max(0.0, min(1.0, float(value)))
    try:
        progress.progress(value, text=text)
    except TypeError:
        progress.progress(value)

def _generate_image_with_retry_no_ui(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    timeout_seconds: int,
    retry_count: int,
    retry_backoff_seconds: float,
) -> dict[str, Any]:
    """Retry image generation without Streamlit calls so it is safe inside worker threads."""
    from nine_router_image_app import (
        MAX_API_TIMEOUT_SECONDS,
        build_generate_error_hint,
        generate_image,
        is_codex_entitlement_error,
        is_codex_upgrade_required_error,
        is_retryable_generate_error,
        is_transparent_background_not_supported_error,
        is_upstream_headers_timeout_error,
        normalize_transparent_image_result,
        suggest_compat_model_fallback,
        suggest_entitlement_model_fallback,
        unique_list,
    )

    total_attempts = max(0, int(retry_count)) + 1
    timeout_base = max(30, int(timeout_seconds))
    backoff_base = max(0.0, float(retry_backoff_seconds))
    current_payload = dict(payload)
    attempted_compat_fallback = False
    attempted_models = [str(current_payload.get("model", "")).strip()]
    retry_notes: list[str] = []
    last_error: Exception | None = None

    attempt = 1
    while attempt <= total_attempts:
        timeout_now = min(int(MAX_API_TIMEOUT_SECONDS), timeout_base + (attempt - 1) * 90)
        try:
            result = generate_image(
                base_url=base_url,
                api_key=api_key,
                payload=current_payload,
                response_format=response_format,
                timeout_seconds=timeout_now,
            )
            return normalize_transparent_image_result(result, current_payload)
        except Exception as ex:
            last_error = ex
            current_model = str(current_payload.get("model", "")).strip()
            if current_model and current_model not in attempted_models:
                attempted_models.append(current_model)

            fallback_model = suggest_compat_model_fallback(current_model)
            if (
                not attempted_compat_fallback
                and fallback_model
                and fallback_model != current_model
                and is_codex_upgrade_required_error(str(ex))
            ):
                attempted_compat_fallback = True
                current_payload = dict(current_payload)
                current_payload["model"] = fallback_model
                attempted_models.append(fallback_model)
                retry_notes.append(f"Đổi model tương thích: {current_model} → {fallback_model}")
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            fallback_reason = ""
            fallback_model = ""
            if is_codex_entitlement_error(str(ex)):
                fallback_reason = "thiếu quyền/không trả ảnh"
                fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            elif is_upstream_headers_timeout_error(str(ex)):
                fallback_reason = "upstream timeout"
                fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            elif is_transparent_background_not_supported_error(str(ex)):
                fallback_reason = "không hỗ trợ transparent native"
                fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            if fallback_model:
                current_payload = dict(current_payload)
                current_payload["model"] = fallback_model
                attempted_models.append(fallback_model)
                retry_notes.append(f"Model {current_model} {fallback_reason}; thử {fallback_model}")
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            should_retry = attempt < total_attempts and is_retryable_generate_error(ex)
            if not should_retry:
                break

            delay = min(12.0, backoff_base * (2 ** max(0, attempt - 1)) + random.uniform(0.0, 0.35))
            retry_notes.append(f"Lần {attempt}/{total_attempts} lỗi: {ex}. Thử lại sau {delay:.1f}s.")
            time.sleep(delay)
            attempt += 1

    assert last_error is not None
    hint = build_generate_error_hint(str(last_error))
    tried = " → ".join(item for item in unique_list(attempted_models) if item)
    details = [str(last_error)]
    if hint:
        details.append(hint)
    if tried:
        details.append(f"Đã thử model: {tried}")
    if retry_notes:
        details.append("Retry log: " + " | ".join(retry_notes[-4:]))
    raise RuntimeError("\n".join(details))

def _generate_and_save_for_item_worker(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    item: ArtItem,
    target_path: Path,
    do_post: bool,
    request_timeout: int,
    retry_count: int,
    retry_backoff: float,
    color_key: str = "blue",
    output_mode: str = "remove",
    resize_enabled: bool = True,
    save_raw_background: bool = True,
) -> list[str]:
    """Generate and save one catalog item. Does not call Streamlit; safe for parallel workers."""
    saved_paths: list[str] = []
    n_images = max(1, int(payload.get("n", 1)))
    base_payload = dict(payload)
    base_payload["n"] = 1

    for variant_idx in range(1, n_images + 1):
        variant_payload = dict(base_payload)
        if "seed" in variant_payload:
            with suppress(Exception):
                variant_payload["seed"] = int(variant_payload["seed"]) + variant_idx
        result = _generate_image_with_retry_no_ui(
            base_url=base_url,
            api_key=api_key,
            payload=variant_payload,
            response_format="binary",
            timeout_seconds=request_timeout,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff,
        )
        if result.get("kind") not in {"binary", "b64_json"}:
            raise RuntimeError(f"Phản hồi không có ảnh nhị phân: kind={result.get('kind')}")
        image_bytes = result.get("image_bytes", b"")
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise RuntimeError("Ảnh trả về rỗng.")

        if save_raw_background:
            raw_path = resolve_raw_background_output_path(target_path, color_key, variant_idx)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(image_bytes)
            saved_paths.append(str(raw_path))

        if do_post:
            image_bytes = post_process_chroma_image(
                item,
                image_bytes,
                color_key=color_key,
                output_mode=output_mode,
                resize_enabled=resize_enabled,
            )

        if variant_idx == 1:
            out_path = target_path
        else:
            out_path = target_path.with_name(f"{target_path.stem}_v{variant_idx}{target_path.suffix}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_bytes)
        saved_paths.append(str(out_path))

    return saved_paths

def _tutien5_catalog_info() -> dict[str, Any] | None:
    """Đọc catalog TuTien5 (module riêng) và đếm số file còn thiếu."""
    try:
        import tutien5_art_catalog as t5
    except Exception:
        return None
    missing = 0
    by_group: dict[str, list[int]] = {}
    for item in t5.CATALOG:
        counts = by_group.setdefault(item.group, [0, 0])
        counts[1] += 1
        if not resolve_output_path(item, TUTIEN5_EXPORT_ROOT).exists():
            counts[0] += 1
            missing += 1
    return {
        "total": len(t5.CATALOG),
        "missing": missing,
        "groups": list(t5.GROUP_ORDER),
        "by_group": by_group,
    }


def _launch_tutien5_background(
    groups: list[str],
    priorities: list[str],
    overwrite: bool,
    model: str,
    *,
    color_key: str = "pink",
    output_mode: str = "remove",
    resize: bool = True,
    save_raw: bool = True,
    extra_note: str = "",
    workers: int = 4,
) -> tuple[Path, int]:
    """Chạy tools/generate_tutien5_art.py ở tiến trình nền, ghi log ra file."""
    root = Path(__file__).resolve().parent
    python_exe = root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    log_dir = root / "outputs" / "tutien5_generation"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"app_run_{stamp}.log"

    args: list[str] = [
        str(python_exe),
        "tools/generate_tutien5_art.py",
        "--workers", str(max(1, int(workers))),
        "--contact-sheet",
        "--color", str(color_key),
        "--output-mode", str(output_mode),
    ]
    if groups:
        args += ["--groups", ",".join(groups)]
    if priorities:
        args += ["--priorities", ",".join(priorities)]
    if str(model or "").strip():
        args += ["--model", str(model).strip()]
    if str(extra_note or "").strip():
        args += ["--extra-note", str(extra_note).strip()]
    if not resize:
        args += ["--no-resize"]
    if not save_raw:
        args += ["--no-raw"]
    if overwrite:
        args += ["--overwrite"]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 (đóng khi tiến trình kết thúc)
    process = subprocess.Popen(
        args,
        cwd=str(root),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    return log_path, process.pid


def _render_tutien5_setup(model: str) -> None:
    """Panel TuTien5: chạy CLI generator (catalog riêng 2026-06-06) ở tiến trình nền.

    Render inline (không bọc expander) để hiển thị dưới bước 'Vẽ gì'.
    """
    info = _tutien5_catalog_info()
    if info is None:
        st.error("Không nạp được `tutien5_art_catalog`. Kiểm tra file ở thư mục gốc.")
        return

    stat_total, stat_missing = st.columns(2, gap="small")
    with stat_total:
        st.metric("Tổng file", info["total"])
    with stat_missing:
        st.metric("Còn thiếu", info["missing"])
    st.caption(
        "Item trong suốt vẽ trên nền hồng rồi tự tách alpha; banner/nền giữ opaque. "
        "TuTien5 chạy riêng bằng tiến trình nền nên không dùng danh sách chọn phía dưới."
    )

    pick_groups = st.multiselect(
        "Nhóm cần vẽ (để trống = vẽ tất cả)",
        options=info["groups"],
        key="tutien5_pick_groups",
    )
    col_pri, col_over, col_model = st.columns([1.2, 1.0, 1.6], gap="medium")
    with col_pri:
        pick_priorities = st.multiselect(
            "Ưu tiên (trống = tất cả)",
            options=["P0", "P1", "P2", "P3"],
            key="tutien5_pick_priorities",
        )
    with col_over:
        overwrite = st.checkbox("Ghi đè file đã có", value=False, key="tutien5_overwrite")
    with col_model:
        t5_model = st.text_input("Model ảnh", value=str(model or "gpt-image-2"), key="tutien5_model")

    # ----- Tùy chọn nền màu & luồng vẽ (đầy đủ như các bộ khác) -----
    st.markdown("**Nền màu & luồng vẽ**")
    bg1, bg2, bg3 = st.columns([1.2, 1.6, 1.0], gap="medium")
    color_keys = list(CHROMA_BACKGROUND_OPTIONS.keys())
    with bg1:
        t5_color = st.selectbox(
            "Nền khi vẽ",
            options=color_keys,
            format_func=lambda key: CHROMA_BACKGROUND_OPTIONS[key]["label"],
            index=color_keys.index("pink") if "pink" in color_keys else 0,
            key="tutien5_background_color",
            help="AI vẽ asset trên nền màu phẳng để dễ tách hoặc giữ nền.",
        )
    with bg2:
        t5_output = st.radio(
            "Ảnh final",
            options=list(BACKGROUND_OUTPUT_OPTIONS.keys()),
            format_func=lambda key: BACKGROUND_OUTPUT_OPTIONS[key],
            key="tutien5_background_output",
            help="Tách nền ra alpha trong suốt, hoặc giữ nguyên nền màu trong ảnh final.",
        )
    with bg3:
        t5_resize = st.checkbox("Tự resize đúng size", value=True, key="tutien5_resize")
        t5_save_raw = st.checkbox("Backup ảnh raw", value=True, key="tutien5_save_raw")

    adv1, adv2 = st.columns([1.0, 2.0], gap="medium")
    with adv1:
        t5_workers = st.number_input("Luồng song song", min_value=1, max_value=60, value=4, step=1, key="tutien5_workers")
    with adv2:
        t5_note = st.text_input(
            "Note thêm (áp cho mọi item lần này)",
            value="",
            key="tutien5_note",
            placeholder="Ví dụ: ưu tiên tone vàng kim, nét sạch.",
        )

    if st.button("🚀 Bắt đầu vẽ TuTien5 (chạy nền)", type="primary", use_container_width=True, key="btn_tutien5_run_bg"):
        log_path, pid = _launch_tutien5_background(
            groups=list(pick_groups),
            priorities=list(pick_priorities),
            overwrite=bool(overwrite),
            model=t5_model,
            color_key=str(t5_color),
            output_mode=str(t5_output),
            resize=bool(t5_resize),
            save_raw=bool(t5_save_raw),
            extra_note=str(t5_note or ""),
            workers=int(t5_workers),
        )
        st.session_state.tutien5_last_log = str(log_path)
        st.success(f"Đã chạy nền (PID {pid}). Log: `{log_path}`")

    last_log = st.session_state.get("tutien5_last_log", "")
    if last_log and Path(last_log).exists():
        if st.button("🔄 Xem log mới nhất", use_container_width=True, key="btn_tutien5_refresh_log"):
            st.rerun()
        with suppress(Exception):
            tail = Path(last_log).read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            st.code("\n".join(tail) or "(log trống)", language="text")


def render_tutienco_workflow(
    *,
    base_url: str,
    api_key: str,
    model: str,
    run_payload_generation: Callable[..., None],
    timestamp_slug_fn: Callable[[], str],
    apply_character_detail_note: Callable[[str], str] | None = None,
) -> None:
    """Render workflow Vẽ art game Tu Tiên Cờ.

    `run_payload_generation` và `timestamp_slug_fn` được pass từ nine_router_image_app
    để khỏi import vòng và để tận dụng hệ thống multi-API/parallel có sẵn.
    """
    _ensure_state()

    st.markdown(
        "<div class='nr-workflow-intro'>"
        "<h3>🐉 Vẽ art game Tu Tiên Cờ</h3>"
        "<p>Đọc checklist art còn thiếu, chọn món cần vẽ, app sẽ tự build prompt, "
        "đặt tên và lưu đúng path <code>Assets/Resources/...</code> để bạn drop thẳng vào Unity.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ---------- Setup nhanh ----------
    selected_ids_now = _item_ids_from_values(st.session_state.get("tutienco_selected_codes", []))
    tutien4_items = [item for item in CATALOG if item.transparent]
    tutien4_count = len(tutien4_items)
    tutien4_missing = sum(
        1 for item in tutien4_items
        if not resolve_output_path(item, TUTIEN4_PINK_EXPORT_ROOT).exists()
    )
    tutien4_ids = {_item_id(item) for item in tutien4_items}
    is_tutien4_setup = (
        str(st.session_state.get("tutienco_export_root", "")) == TUTIEN4_PINK_EXPORT_ROOT
        and bool(selected_ids_now)
        and selected_ids_now.issubset(tutien4_ids)
    )
    supplement_items = [item for item in CATALOG if item.group in SUPPLEMENT_20260528_GROUPS]
    supplement_count = len(supplement_items)
    supplement_missing = sum(
        1 for item in supplement_items
        if not resolve_output_path(item, TUTIEN3_GREEN_EXPORT_ROOT).exists()
    )
    supplement_ids = {_item_id(item) for item in supplement_items}
    is_supplement_setup = (
        str(st.session_state.get("tutienco_export_root", "")) == TUTIEN3_GREEN_EXPORT_ROOT
        and bool(selected_ids_now)
        and selected_ids_now.issubset(supplement_ids)
    )

    st.markdown("### 1️⃣ Vẽ vào đâu?")
    dest_options = {
        "TuTien4": "TuTien4 — icon/asset trong suốt (khuyên dùng)",
        "TuTien5": "TuTien5 — checklist mới 2026-06-06",
        "TuTien3": "TuTien3 — giữ nền xanh lá",
        "TuTien2": "TuTien2 — bản đầy đủ mặc định",
    }
    dest_paths = {
        "TuTien4": TUTIEN4_PINK_EXPORT_ROOT,
        "TuTien5": TUTIEN5_EXPORT_ROOT,
        "TuTien3": TUTIEN3_GREEN_EXPORT_ROOT,
        "TuTien2": DEFAULT_EXPORT_ROOT,
    }
    dest = st.radio(
        "Chọn bộ đích",
        options=list(dest_options.keys()),
        format_func=lambda key: dest_options[key],
        horizontal=True,
        key="tutien_dest_choice",
        label_visibility="collapsed",
    )
    st.caption(f"📁 Ảnh sẽ lưu vào: `{dest_paths[dest]}\\Assets\\Resources\\...`")

    st.markdown("### 2️⃣ Vẽ gì?")

    # ----- TuTien5: vẽ inline y hệt các bộ khác, lưu vào TuTien5 -----
    if dest == "TuTien5":
        t5_items = _tutien5_catalog()
        t5_count = len(t5_items)
        t5_missing = sum(
            1 for item in t5_items
            if not resolve_output_path(item, TUTIEN5_EXPORT_ROOT).exists()
        )
        col_btn, col_stat = st.columns([2.0, 1.0], gap="medium")
        with col_btn:
            if st.button(
                f"➕ Bổ sung {t5_missing} file còn thiếu",
                type="primary",
                use_container_width=True,
                key="btn_tutien5_missing",
            ):
                _setup_missing_tutien5()
                st.success(f"Đã chọn {t5_missing} file TuTien5 còn thiếu. Kéo xuống mục 3️⃣ bấm Vẽ.")
                st.rerun()
            if st.button(
                f"🔁 Vẽ lại toàn bộ {t5_count} file",
                use_container_width=True,
                key="btn_tutien5_full",
            ):
                _setup_full_redraw_tutien5()
                st.success(f"Đã chọn toàn bộ {t5_count} file TuTien5 (bật ghi đè). Kéo xuống mục 3️⃣ bấm Vẽ.")
                st.rerun()
        with col_stat:
            st.metric("File", f"{t5_count}")
            st.caption(f"Còn thiếu: {t5_missing}/{t5_count}")
        is_t5_setup = (
            str(st.session_state.get("tutienco_export_root", "")) == TUTIEN5_EXPORT_ROOT
            and bool(selected_ids_now)
        )
        if is_t5_setup:
            st.success(f"Đang chọn {len(selected_ids_now)} món TuTien5. Kéo xuống mục 3️⃣ để bấm Vẽ.")

    # ----- TuTien4: icon/asset trong suốt (nền hồng → tách alpha) -----
    elif dest == "TuTien4":
        col_btn, col_stat = st.columns([2.0, 1.0], gap="medium")
        with col_btn:
            if st.button(
                f"➕ Bổ sung {tutien4_missing} file còn thiếu",
                type="primary",
                use_container_width=True,
                key="btn_tutien_setup_tutien4_missing_pink_icons",
            ):
                _setup_missing_tutien4_pink_icons()
                st.success(f"Đã chọn {tutien4_missing} file còn thiếu (không ghi đè file đã có).")
                st.rerun()
            if st.button(
                f"🔁 Vẽ lại toàn bộ {tutien4_count} file",
                use_container_width=True,
                key="btn_tutien_setup_tutien4_pink_icons",
            ):
                _setup_full_redraw_tutien4_pink_icons()
                st.success(f"Đã chọn toàn bộ {tutien4_count} icon/asset (bật ghi đè).")
                st.rerun()
        with col_stat:
            st.metric("Icon/asset", f"{tutien4_count}")
            st.caption(f"Còn thiếu: {tutien4_missing}/{tutien4_count}")
        if is_tutien4_setup:
            st.success(f"Đang chọn {len(selected_ids_now)}/{tutien4_count} món. Kéo xuống mục 3️⃣ để bấm Vẽ.")

    # ----- TuTien3: giữ nền xanh lá -----
    elif dest == "TuTien3":
        col_btn, col_stat = st.columns([2.0, 1.0], gap="medium")
        with col_btn:
            if st.button(
                f"➕ Bổ sung {supplement_count} ảnh hệ thống (2026-05-28)",
                type="primary",
                use_container_width=True,
                key="btn_tutien_setup_supplement_20260528",
            ):
                _setup_tutien3_supplement_20260528()
                st.success(f"Đã chọn {supplement_count} file bổ sung (còn thiếu {supplement_missing}).")
                st.rerun()
            if st.button(
                f"🔁 Vẽ lại toàn bộ {len(CATALOG)} món (nền xanh)",
                use_container_width=True,
                key="btn_tutien_setup_redraw_tutien3_green",
            ):
                _setup_full_redraw_tutien3_green()
                st.success(f"Đã chọn toàn bộ {len(CATALOG)} món, giữ nền xanh lá.")
                st.rerun()
        with col_stat:
            st.metric("Bổ sung", f"{supplement_count}")
            st.caption(f"Còn thiếu: {supplement_missing}/{supplement_count}")
        if is_supplement_setup:
            st.success(f"Đang chọn {len(selected_ids_now)}/{supplement_count} món. Kéo xuống mục 3️⃣ để bấm Vẽ.")

    # ----- TuTien2: bản đầy đủ mặc định -----
    else:
        if st.button(
            f"🔁 Vẽ lại toàn bộ {len(CATALOG)} món vào TuTien2",
            type="primary",
            use_container_width=True,
            key="btn_tutien_setup_redraw_tutien2",
        ):
            _setup_full_redraw_tutien2()
            st.success(f"Đã chọn toàn bộ {len(CATALOG)} món, bật ghi đè.")
            st.rerun()

    st.markdown("### 3️⃣ Tinh chỉnh & vẽ")
    st.caption(
        "Có thể bỏ qua phần dưới nếu đã bấm preset ở trên. "
        "Chọn thêm/bớt món, rồi bấm nút Vẽ ở cuối trang."
    )

    cfg1, cfg2, cfg3 = st.columns([2.2, 1.0, 1.0], gap="medium")
    with cfg1:
        st.text_input(
            "Thư mục thực tế sẽ lưu (tự đặt khi bấm preset ở trên, sửa tay nếu cần)",
            key="tutienco_export_root",
            help="Các nút preset ở mục 2️⃣ sẽ tự điền ô này. Chỉ sửa tay nếu muốn lưu chỗ khác.",
        )
    with cfg2:
        priority_filter = st.selectbox(
            "Lọc ưu tiên",
            options=["Tất cả", "P0", "P1", "P2"],
            key="tutienco_priority_filter",
        )
    with cfg3:
        only_missing = st.checkbox("Ẩn món đã có file", value=True, key="tutienco_hide_done")

    with st.expander("Cấu hình nền màu & hậu kỳ nâng cao", expanded=False):
        st.caption("Bình thường không cần chỉnh mục này sau khi bấm setup nhanh.")
        bg_col1, bg_col2, bg_col3, bg_col4 = st.columns([1.1, 1.35, 1.1, 1.1], gap="small")
        color_keys = list(CHROMA_BACKGROUND_OPTIONS.keys())
        with bg_col1:
            st.selectbox(
                "Nền khi vẽ",
                options=color_keys,
                format_func=lambda key: CHROMA_BACKGROUND_OPTIONS[key]["label"],
                key="tutienco_background_color",
                help="AI sẽ vẽ asset trên nền màu phẳng để dễ tách hoặc giữ nền.",
            )
        with bg_col2:
            st.radio(
                "Ảnh final",
                options=list(BACKGROUND_OUTPUT_OPTIONS.keys()),
                format_func=lambda key: BACKGROUND_OUTPUT_OPTIONS[key],
                horizontal=False,
                key="tutienco_background_output",
                help="Chọn tách nền ra alpha hoặc giữ nguyên nền màu trong ảnh final.",
            )
        with bg_col3:
            st.checkbox(
                "Tự resize đúng size",
                key="tutienco_resize_output",
                help="Fit ảnh vào kích thước catalog, pad bằng alpha hoặc màu nền tùy mode.",
            )
            st.checkbox(
                "Ghi đè file cũ",
                key="tutienco_overwrite_existing",
            )
        with bg_col4:
            st.checkbox(
                "Backup ảnh nền màu raw",
                key="tutienco_save_raw_background",
                help="Lưu bản AI trả về trước khi tách/resize vào thư mục _raw_background cạnh file final.",
            )
            st.checkbox(
                "Bật hậu kỳ local",
                key="tutienco_use_post_process",
                help="Nếu tắt, app lưu ảnh AI trả về gần như nguyên bản, chỉ vẫn có raw backup nếu bật.",
            )

    selected_color = _chroma_spec(str(st.session_state.get("tutienco_background_color", "blue")))
    selected_output = str(st.session_state.get("tutienco_background_output", "remove"))
    st.info(
        f"Mode hiện tại: vẽ nền {selected_color['label']} ({selected_color['rgb_text']}) • "
        f"final: {BACKGROUND_OUTPUT_OPTIONS.get(selected_output, selected_output)} • "
        f"resize: {'bật' if st.session_state.get('tutienco_resize_output', True) else 'tắt'} • "
        f"backup raw: {'bật' if st.session_state.get('tutienco_save_raw_background', True) else 'tắt'}."
    )

    st.text_area(
        "Note thêm (sẽ áp cho tất cả item được chọn lần này)",
        key="tutienco_user_note",
        height=72,
        placeholder="Ví dụ: ưu tiên tone vàng kim, cảm hứng phim Tây Du Ký bản 1986.",
    )

    # ---------- Danh sách & chọn ----------
    visible_items = _filter_items(
        priority_filter=str(priority_filter),
        only_missing=bool(only_missing),
        export_root=str(st.session_state.tutienco_export_root),
    )

    total_catalog = len(CATALOG)
    summary_stats = stats()
    summary_str = " • ".join(f"{g}: {n}" for g, n in summary_stats.items())
    st.caption(
        f"Tổng catalog: {total_catalog} món. Đang hiển thị: {len(visible_items)}. {summary_str}"
    )

    component_map = _items_by_component(visible_items)
    component_keys = sorted(component_map, key=_component_sort_key)
    selected_component_keys: list[str] = []
    component_codes: list[str] = []
    with st.expander("Chọn nhanh theo thành phần", expanded=False):
        st.caption("Tick Portrait/Chibi/Icon/Background/VFX... rồi bấm chọn. App sẽ tự chạy lần lượt tới khi xong.")
        if component_keys:
            comp_cols = st.columns(3)
            for idx, component_key in enumerate(component_keys):
                comp_items = component_map[component_key]
                missing_count = sum(
                    1 for item in comp_items
                    if not resolve_output_path(item, str(st.session_state.tutienco_export_root)).exists()
                )
                label = f"{_component_label(component_key)} • {len(comp_items)} món • thiếu {missing_count}"
                with comp_cols[idx % 3]:
                    st.checkbox(
                        label,
                        key=f"tutien_component_pick__{component_key}",
                    )
            selected_component_keys = _selected_component_keys(component_keys)
            component_codes = _ordered_item_ids({
                _item_id(item)
                for key in selected_component_keys
                for item in component_map.get(key, [])
            })
            action1, action2, action3, action4 = st.columns([1.1, 1.1, 1.1, 1.2], gap="small")
            with action1:
                if st.button("✅ Chọn thành phần đã tick", use_container_width=True, key="btn_tutien_select_components"):
                    _set_item_codes_selected(component_codes, True)
                    st.rerun()
            with action2:
                if st.button("⭐ Chọn P0 đang hiện", use_container_width=True, key="btn_tutien_select_p0_visible"):
                    _set_item_codes_selected([_item_id(item) for item in visible_items if item.priority == "P0"], True)
                    st.rerun()
            with action3:
                if st.button("🧹 Bỏ component đã tick", use_container_width=True, key="btn_tutien_drop_components"):
                    _set_item_codes_selected(component_codes, False)
                    st.rerun()
            with action4:
                if st.button("🔎 Kiểm tra tiến độ", use_container_width=True, key="btn_tutien_scan_progress"):
                    _scan_run_status(visible_items, str(st.session_state.tutienco_export_root))
            st.caption(f"Thành phần đã tick: {len(selected_component_keys)} • số item tương ứng: {len(component_codes)}")
        else:
            st.info("Không có thành phần nào theo bộ lọc hiện tại.")

    with st.expander("📊 Bảng tiến độ file đang hiển thị", expanded=False):
        _render_status_table(visible_items, str(st.session_state.tutienco_export_root))

    bulk1, bulk2, bulk3, bulk4 = st.columns([1.0, 1.0, 1.0, 2.0], gap="small")
    visible_codes = [_item_id(item) for item in visible_items]
    with bulk1:
        if st.button("✅ Chọn tất cả (đang hiện)", use_container_width=True, key="btn_tutien_select_all"):
            _set_item_codes_selected(visible_codes, True)
            st.rerun()
    with bulk2:
        if st.button("🚫 Bỏ chọn (đang hiện)", use_container_width=True, key="btn_tutien_unselect_visible"):
            _set_item_codes_selected(visible_codes, False)
            st.rerun()
    with bulk3:
        if st.button("🧹 Bỏ chọn tất cả", use_container_width=True, key="btn_tutien_clear_all"):
            _clear_all_item_selection()
            st.rerun()
    with bulk4:
        st.caption(
            f"Đang chọn item: {len(st.session_state.tutienco_selected_codes)} • từ thành phần tick: {len(component_codes)} • catalog: {total_catalog}."
        )

    # Group by category, then expand each.
    grouped = items_by_group()
    selected_set = _item_ids_from_values(st.session_state.tutienco_selected_codes)
    visible_set = set(visible_codes)

    for group in GROUP_ORDER:
        group_items = [item for item in grouped.get(group, []) if _item_id(item) in visible_set]
        if not group_items:
            continue
        with st.expander(f"{group} — {len(group_items)} món", expanded=False):
            # Group selection helpers.
            gcol1, gcol2, gcol3 = st.columns([1.0, 1.0, 2.0], gap="small")
            with gcol1:
                if st.button("Chọn cả nhóm", key=f"btn_tutien_pick_group_{group}", use_container_width=True):
                    _set_item_codes_selected([_item_id(item) for item in group_items], True)
                    st.rerun()
            with gcol2:
                if st.button("Bỏ nhóm", key=f"btn_tutien_drop_group_{group}", use_container_width=True):
                    _set_item_codes_selected([_item_id(item) for item in group_items], False)
                    st.rerun()
            with gcol3:
                done_count = sum(
                    1 for item in group_items
                    if resolve_output_path(item, str(st.session_state.tutienco_export_root)).exists()
                )
                st.caption(f"Đã có file: {done_count}/{len(group_items)}")

            # Sub-group rows.
            subgroups: dict[str, list[ArtItem]] = {}
            for item in group_items:
                subgroups.setdefault(item.subgroup or "—", []).append(item)

            for sub_name, sub_items in subgroups.items():
                if sub_name and sub_name != "—":
                    st.markdown(f"**{sub_name}** ({len(sub_items)})")
                cols = st.columns(2)
                for idx, item in enumerate(sub_items):
                    with cols[idx % 2]:
                        path = resolve_output_path(item, str(st.session_state.tutienco_export_root))
                        already = path.exists()
                        prefix = "✅ " if already else ""
                        label = f"{prefix}{item.title_vi}"
                        item_id = _item_id(item)
                        checked = item_id in selected_set
                        new_checked = st.checkbox(
                            label,
                            value=checked,
                            key=f"tutien_pick__{_item_widget_key(item)}",
                            help=(
                                f"Code: {item.code}\n"
                                f"Path: {path}\n"
                                f"Size: {item.size[0]}x{item.size[1]} • Aspect: {item.aspect}\n"
                                f"Transparent: {'có' if item.transparent else 'không'}\n"
                                f"Priority: {item.priority}"
                            ),
                        )
                        if new_checked and item_id not in selected_set:
                            selected_set.add(item_id)
                        if not new_checked and item_id in selected_set:
                            selected_set.discard(item_id)
                        st.caption(
                            f"`{path.relative_to(path.anchor) if path.is_absolute() else path}` • "
                            f"{item.size[0]}x{item.size[1]} • {item.priority}"
                        )

    st.session_state.tutienco_selected_codes = _ordered_item_ids(selected_set)

    run_item_set = set(selected_set).union(component_codes)
    if not run_item_set:
        st.info("Chưa chọn món nào. Tick checkbox item hoặc tick thành phần ở trên để bắt đầu.")
        return

    selected_items = [it for it in CATALOG if _item_id(it) in run_item_set]

    with st.expander("👀 Xem trước prompt của 1 món", expanded=False):
        preview_id = st.selectbox(
            "Chọn item",
            options=[_item_id(it) for it in selected_items],
            format_func=lambda item_id: (
                f"{(_find_by_item_id(item_id).code if _find_by_item_id(item_id) else item_id)} — "
                f"{(_find_by_item_id(item_id).title_vi if _find_by_item_id(item_id) else item_id)}"
            ),
            key="tutienco_preview_code",
        )
        preview_item = _find_by_item_id(preview_id)
        if preview_item:
            st.code(build_item_prompt_chroma(
                preview_item,
                st.session_state.get("tutienco_user_note", ""),
                color_key=str(st.session_state.get("tutienco_background_color", "blue")),
                output_mode=str(st.session_state.get("tutienco_background_output", "remove")),
            ))
            st.caption(
                f"Sẽ lưu vào: {resolve_output_path(preview_item, str(st.session_state.tutienco_export_root))}"
            )

    # ---------- Submit ----------
    submit_col1, submit_col2, submit_col3 = st.columns([1.25, 1.25, 2.0])
    with submit_col1:
        n_per_item = st.number_input(
            "Số ảnh / món", min_value=1, max_value=8, value=1, step=1, key="tutienco_n_per_item",
            help="Vẽ nhiều biến thể, app chỉ giữ ảnh #1 đúng tên path; các biến thể khác sẽ thêm hậu tố _vN.",
        )
    with submit_col2:
        parallel_workers = st.number_input(
            "Số luồng song song",
            min_value=1,
            max_value=30,
            value=int(st.session_state.get("tutienco_parallel_workers", 4)),
            step=1,
            key="tutienco_parallel_workers",
            help="Số item art được gọi API cùng lúc. Tăng cao sẽ nhanh hơn nhưng dễ gặp rate limit/timeout nếu provider yếu.",
        )
    with submit_col3:
        st.caption(
            f"Sẽ gửi: {len(selected_items)} món × {int(n_per_item)} ảnh = "
            f"{len(selected_items) * int(n_per_item)} ảnh. Chạy tối đa {int(parallel_workers)} item cùng lúc."
        )

    # Model riêng cho luồng vẽ art: nên là model ảnh, không phải model chat/codex.
    # Model cho luong ve art: tu chon theo nguon dang ket noi (Flow / Gemini / 9Router).
    _art_base = str(base_url or "")
    _cur_art = str(st.session_state.get("tutienco_art_model", "") or model or "")
    if "8790" in _art_base:
        if _cur_art.lower() not in ("narwhal", "flow", "flow-narwhal"):
            _cur_art = "NARWHAL"
    elif "8788" in _art_base:
        if "image" not in _cur_art.lower():
            _cur_art = "gemini-2.5-flash-image"
    else:
        if "image" not in _cur_art.lower():
            _cur_art = "cx/gpt-5.4-image"
    st.session_state["tutienco_art_model"] = _cur_art
    art_model = st.text_input(
        "Model vẽ art (nên dùng model ẢNH)",
        key="tutienco_art_model",
        help=(
            "Vẽ art nên dùng model ảnh (vd cx/gpt-5.4-image, gpt-image-2). "
            "Model chat/codex như gpt-5.5 khi đẩy vào /v1/images/generations dễ bị 401 "
            "'authentication token invalidated'. Bấm '↻ Nạp model' ở thanh trên để xem model server hỗ trợ."
        ),
    )
    if ("image" not in str(art_model).lower()) and ("8790" not in str(base_url)) and ("8788" not in str(base_url)):
        st.warning(
            f"Model '{art_model}' trông không phải model ảnh. Nếu bị lỗi 401/anh không ra, "
            "đổi sang model ảnh như `cx/gpt-5.4-image` hoặc `gpt-image-2`."
        )

    if st.button(
        f"🚀 Chạy auto tới khi xong: {len(selected_items)} món art Tu Tiên Cờ",
        type="primary",
        use_container_width=True,
        key="btn_tutien_run_batch",
    ):
        _run_tutienco_batch(
            base_url=base_url,
            api_key=api_key,
            model=str(art_model).strip() or model,
            items=selected_items,
            n_per_item=int(n_per_item),
            run_payload_generation=run_payload_generation,
            timestamp_slug_fn=timestamp_slug_fn,
            apply_character_detail_note=apply_character_detail_note,
        )


# =====================================================================
# Batch runner
# =====================================================================

def _run_tutienco_batch(
    *,
    base_url: str,
    api_key: str,
    model: str,
    items: list[ArtItem],
    n_per_item: int,
    run_payload_generation: Callable[..., None],
    timestamp_slug_fn: Callable[[], str],
    apply_character_detail_note: Callable[[str], str] | None = None,
) -> None:
    export_root = str(st.session_state.get("tutienco_export_root", DEFAULT_EXPORT_ROOT))
    overwrite = bool(st.session_state.get("tutienco_overwrite_existing", False))
    do_post = bool(st.session_state.get("tutienco_use_post_process", True))
    color_key = str(st.session_state.get("tutienco_background_color", "blue"))
    if color_key not in CHROMA_BACKGROUND_OPTIONS:
        color_key = "blue"
    output_mode = str(st.session_state.get("tutienco_background_output", "remove"))
    if output_mode not in BACKGROUND_OUTPUT_OPTIONS:
        output_mode = "remove"
    resize_enabled = bool(st.session_state.get("tutienco_resize_output", True))
    save_raw_background = bool(st.session_state.get("tutienco_save_raw_background", True))
    green_raw_mode = output_mode == "keep"
    use_blue_screen = output_mode == "remove" and color_key == "blue"
    force_api_bg = bool(st.session_state.get("tutienco_force_transparent_api", False))
    parallel_workers = max(1, min(30, int(st.session_state.get("tutienco_parallel_workers", 4))))
    user_note = str(st.session_state.get("tutienco_user_note", ""))

    try:
        from nine_router_image_app import (
            DEFAULT_API_POST_TIMEOUT_SECONDS,
            DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS,
            DEFAULT_IMAGE_RETRY_COUNT,
            parse_api_keys_pool,
            resolve_api_post_timeout_seconds,
            resolve_image_retry_backoff_seconds,
            resolve_image_retry_count,
        )

        request_timeout = resolve_api_post_timeout_seconds(
            st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS)
        )
        retry_count = resolve_image_retry_count(
            st.session_state.get("image_retry_count", DEFAULT_IMAGE_RETRY_COUNT)
        )
        retry_backoff = resolve_image_retry_backoff_seconds(
            st.session_state.get("image_retry_backoff", DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS)
        )
        key_pool = parse_api_keys_pool(str(st.session_state.get("api_keys_pool_text", "")), api_key)
    except Exception:
        request_timeout = 480
        retry_count = 1
        retry_backoff = 1.2
        key_pool = [api_key] if api_key else []
    if not key_pool:
        key_pool = [api_key]

    progress = st.progress(0.0)
    status = st.empty()
    table_slot = st.empty()
    summary: list[dict[str, Any]] = []

    total = len(items)
    st.session_state.tutienco_run_status = {}
    tasks: list[dict[str, Any]] = []
    skipped_count = 0
    for item in items:
        target_path = resolve_output_path(item, export_root)
        if target_path.exists() and not overwrite:
            _set_run_status(item, "skipped", message="File đã tồn tại, sẽ bỏ qua", path=str(target_path))
            summary.append({"item": item.code, "status": "skipped (đã tồn tại)", "path": str(target_path)})
            skipped_count += 1
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = build_item_prompt_chroma(item, user_note, color_key=color_key, output_mode=output_mode)
        if apply_character_detail_note is not None:
            with suppress(Exception):
                prompt = apply_character_detail_note(prompt)

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n_per_item),
            "aspect_ratio": item.aspect,
            "output_format": "png",
            "negative_prompt": build_negative_prompt_chroma(item, color_key, output_mode),
        }
        payload.pop("background", None)
        if item.transparent and force_api_bg and output_mode == "remove":
            payload["background"] = "transparent"

        key_for_task = key_pool[len(tasks) % max(1, len(key_pool))]
        _set_run_status(item, "pending", message="Đang chờ tới lượt", path=str(target_path))
        tasks.append({
            "item": item,
            "target_path": target_path,
            "payload": payload,
            "api_key": key_for_task,
        })

    _render_status_table(items, export_root, table_slot)

    completed_count = skipped_count
    _update_progress(progress, completed_count / max(1, total), f"Đã bỏ qua {skipped_count} file có sẵn")

    if not tasks:
        st.session_state.tutienco_last_run_summary = summary
        status.success("Hoàn tất: tất cả item đã có file hoặc đã bị bỏ qua.")
        with st.expander("📋 Tóm tắt batch", expanded=True):
            st.json(summary)
        return

    max_workers = max(1, min(parallel_workers, len(tasks)))
    status.info(
        f"🚀 Đang vẽ song song {len(tasks)} item • tối đa {max_workers} luồng • "
        f"{len(key_pool)} API key • timeout {request_timeout}s • retry {retry_count}."
    )

    next_task_index = 0
    running: dict[Any, dict[str, Any]] = {}

    def submit_next(executor: concurrent.futures.ThreadPoolExecutor) -> None:
        nonlocal next_task_index
        if next_task_index >= len(tasks):
            return
        task = tasks[next_task_index]
        next_task_index += 1
        task_item: ArtItem = task["item"]
        task_path: Path = task["target_path"]
        _set_run_status(
            task_item,
            "running",
            message=f"Đang vẽ song song ({len(running) + 1}/{max_workers} luồng)",
            path=str(task_path),
        )
        future = executor.submit(
            _generate_and_save_for_item_worker,
            base_url=base_url,
            api_key=str(task["api_key"]),
            payload=dict(task["payload"]),
            item=task_item,
            target_path=task_path,
            do_post=do_post,
            request_timeout=request_timeout,
            retry_count=retry_count,
            retry_backoff=retry_backoff,
            color_key=color_key,
            output_mode=output_mode,
            resize_enabled=resize_enabled,
            save_raw_background=save_raw_background,
        )
        running[future] = task

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _ in range(max_workers):
            submit_next(executor)
        _render_status_table(items, export_root, table_slot)

        while running:
            done, _pending = concurrent.futures.wait(
                running,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done:
                task = running.pop(future)
                item: ArtItem = task["item"]
                target_path: Path = task["target_path"]
                try:
                    saved_files = future.result()
                    summary.append({
                        "item": item.code,
                        "status": "ok",
                        "path": str(target_path),
                        "files": saved_files,
                    })
                    _set_run_status(item, "ok", message="Đã vẽ, lưu PNG final và backup raw nếu bật", path=str(target_path), files=saved_files)
                except Exception as ex:
                    summary.append({"item": item.code, "status": f"lỗi: {ex}", "path": str(target_path)})
                    _set_run_status(item, "error", message=str(ex), path=str(target_path))
                    st.error(f"Lỗi vẽ {item.code}: {ex}")

                completed_count += 1
                _update_progress(progress, completed_count / max(1, total), f"{completed_count}/{total} • xong {item.code}")
                submit_next(executor)
                _render_status_table(items, export_root, table_slot)

    st.session_state.tutienco_last_run_summary = summary
    status.success("Hoàn tất batch.")
    with st.expander("📋 Tóm tắt batch", expanded=True):
        st.json(summary)


def _generate_and_save_for_item(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    item: ArtItem,
    target_path: Path,
    do_post: bool,
    run_payload_generation: Callable[..., None],
    timestamp_slug_fn: Callable[[], str],
) -> list[str]:
    """Gọi API qua module generate_image_with_retry (tận dụng retry/timeout của app),
    rồi tự lưu ra đúng target_path (PNG, transparent, đúng size).

    Nếu Pillow chưa cài, fallback dùng run_payload_generation và caller sẽ chỉ thấy
    ảnh nằm trong outputs/history.
    """
    # Lazy import để tránh circular dependency.
    try:
        from nine_router_image_app import (
            DEFAULT_API_POST_TIMEOUT_SECONDS,
            DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS,
            DEFAULT_IMAGE_RETRY_COUNT,
            generate_image_with_retry,
            resolve_api_post_timeout_seconds,
            resolve_image_retry_backoff_seconds,
            resolve_image_retry_count,
        )
    except Exception:
        # Không lấy được helpers ⇒ fallback thuần.
        output_file = f"tutien_{item.code}_{timestamp_slug_fn()}.png"
        run_payload_generation(
            base_url, api_key, payload, "binary", output_file,
            f"Tu Tiên Art – {item.code}", False,
        )
        return []

    request_timeout = resolve_api_post_timeout_seconds(
        st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS)
    )
    retry_count = resolve_image_retry_count(
        st.session_state.get("image_retry_count", DEFAULT_IMAGE_RETRY_COUNT)
    )
    retry_backoff = resolve_image_retry_backoff_seconds(
        st.session_state.get("image_retry_backoff", DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS)
    )

    saved_paths: list[str] = []
    n_images = max(1, int(payload.get("n", 1)))
    # Gọi từng ảnh (n=1) để có thể tự đặt tên biến thể.
    base_payload = dict(payload)
    base_payload["n"] = 1

    for variant_idx in range(1, n_images + 1):
        result = generate_image_with_retry(
            base_url=base_url,
            api_key=api_key,
            payload=base_payload,
            response_format="binary",
            timeout_seconds=request_timeout,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff,
            task_label=f"TuTienArt {item.code} v{variant_idx}",
        )
        if result.get("kind") not in {"binary", "b64_json"}:
            raise RuntimeError(f"Phản hồi không có ảnh nhị phân: kind={result.get('kind')}")
        image_bytes = result.get("image_bytes", b"")
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise RuntimeError("Ảnh trả về rỗng.")

        raw_chroma_bytes = result.get("raw_chroma_image_bytes")
        if isinstance(raw_chroma_bytes, bytes) and raw_chroma_bytes:
            raw_path = resolve_raw_chroma_output_path(target_path, variant_idx)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw_chroma_bytes)

        if do_post:
            image_bytes = post_process_image(item, image_bytes)

        if variant_idx == 1:
            out_path = target_path
        else:
            out_path = target_path.with_name(f"{target_path.stem}_v{variant_idx}{target_path.suffix}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_bytes)
        saved_paths.append(str(out_path))

        with st.container():
            st.image(image_bytes, caption=f"{item.title_vi} (v{variant_idx})", width=200)
            st.caption(f"Đã lưu: {out_path}")

    return saved_paths
