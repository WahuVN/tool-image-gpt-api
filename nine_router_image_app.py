import base64
import binascii
import concurrent.futures
from contextlib import suppress
import html
import io
import json
import mimetypes
import os
import random
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import streamlit as st

try:
    from streamlit_paste_button import paste_image_button as paste_image_button
except Exception:
    paste_image_button = None

try:
    from PIL import Image, ImageDraw, ImageGrab, ImageOps
except Exception:
    Image = None
    ImageDraw = None
    ImageGrab = None
    ImageOps = None


def _patch_streamlit_width_compat(api_name: str) -> None:
    original = getattr(st, api_name, None)
    if not callable(original) or getattr(original, "_ninerouter_width_compat", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if "use_container_width" in kwargs and "width" not in kwargs:
            use_container_width = bool(kwargs.get("use_container_width"))
            migrated_kwargs = dict(kwargs)
            migrated_kwargs.pop("use_container_width", None)
            migrated_kwargs["width"] = "stretch" if use_container_width else "content"
            try:
                return original(*args, **migrated_kwargs)
            except TypeError:
                return original(*args, **kwargs)
        return original(*args, **kwargs)

    wrapped._ninerouter_width_compat = True
    setattr(st, api_name, wrapped)


for _streamlit_api in ("button", "image", "dataframe", "download_button"):
    _patch_streamlit_width_compat(_streamlit_api)


HISTORY_FILE = Path("outputs/history.jsonl")
HISTORY_DAILY_ROOT = Path("outputs/history")
LORA_HISTORY_FILE = Path("outputs/lora_jobs.jsonl")
LORA_DATASET_ROOT = Path("outputs/lora_datasets")
DEFAULT_ENV_FILE = ".env.9router"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
MODE_SINGLE_API = "Thường (1 request)"
MODE_AUTO_API = "Tự động (nhiều key = song song)"
MODE_PARALLEL_API = "Chia nhiều API (song song)"
DEFAULT_MULTI_API_MODE = MODE_AUTO_API
MULTI_API_MODES = [
    MODE_AUTO_API,
    MODE_SINGLE_API,
    MODE_PARALLEL_API,
]

QUICK_COUNT_OPTIONS = [1, 4, 8, 16, 32]
MAX_PARALLEL_WORKERS = 60
DEFAULT_API_GET_TIMEOUT_SECONDS = 180
DEFAULT_API_POST_TIMEOUT_SECONDS = 480
MIN_API_POST_TIMEOUT_SECONDS = 120
DEFAULT_IMAGE_RETRY_COUNT = 2
DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS = 1.4
MAX_IMAGE_RETRY_COUNT = 5
MAX_API_TIMEOUT_SECONDS = 900
QUICK_RATIO_OPTIONS = ["Mặc định", "1:1", "16:9", "9:16", "4:5", "3:2"]
QUICK_STYLE_OPTIONS = [
    "Mặc định",
    "Không áp phong cách",
    "Chân thực",
    "Điện ảnh",
    "Anime",
    "3D",
]
QUICK_QUALITY_OPTIONS = ["Mặc định", "Nhanh", "Cân bằng", "Chất lượng cao (HD)"]
QUICK_STYLE_NOTE_TEMPLATES = {
    "Không dùng mẫu": "",
    "Giữ khuôn mặt ảnh 1": "Giữ đúng khuôn mặt, tỉ lệ đầu và biểu cảm của ảnh 1.",
    "Giữ trang phục ảnh 1": "Giữ nguyên trang phục, phụ kiện và nhận diện nhân vật từ ảnh 1.",
    "Giữ bố cục ảnh 1": "Giữ bố cục, góc máy và vị trí chủ thể như ảnh 1.",
    "Học màu ảnh 2": "Ưu tiên học palette màu, độ tương phản và mood ánh sáng từ ảnh 2.",
    "Học nét vẽ ảnh 2": "Ưu tiên học line-art, chất liệu nét và brush style từ ảnh 2.",
    "Giữ nền sạch": "Giữ nền gọn sạch, hạn chế chi tiết rối và tránh thêm vật thể lạ.",
}
QUICK_STYLE_FOCUS_PROMPTS = {
    "Toàn diện (nét + màu + ánh sáng + bóng)": "Ưu tiên học toàn diện từ Ảnh 2: line-art, palette, ánh sáng, đổ bóng, chất liệu và không khí cảnh.",
    "Ánh sáng + đổ bóng + bokeh": "Ưu tiên học ánh sáng, đổ bóng, volumetric light, bóng lá/hoa và bokeh hậu cảnh từ Ảnh 2.",
    "Nét vẽ + chất liệu": "Ưu tiên học nét vẽ, contour, chất liệu da/tóc/vải và độ sắc cạnh chi tiết từ Ảnh 2.",
    "Màu sắc + mood": "Ưu tiên học bảng màu, nhiệt độ màu, tương phản và mood tổng thể từ Ảnh 2.",
}
QUICK_STYLE_IDENTITY_LOCK_PROMPTS = {
    "Rất chặt": "Khóa danh tính nhân vật Ảnh 1 rất chặt: giữ khuôn mặt, tóc, trang phục, phụ kiện và tỷ lệ cơ thể; không đổi người.",
    "Cân bằng": "Giữ chắc danh tính nhân vật Ảnh 1 nhưng cho phép biến tấu nhẹ biểu cảm và góc máy.",
    "Linh hoạt": "Giữ chủ thể từ Ảnh 1 ở mức tương đối, cho phép sáng tạo bố cục/phong thái nhiều hơn.",
}
QUICK_STYLE_EFFECT_PRESETS = {
    "Không dùng preset": "",
    "Ánh sáng hoa đào sắc nét": "ánh sáng dịu xuyên qua tán hoa đào, bóng cành lá đổ nhẹ lên mặt, bokeh hoa tiền cảnh và hậu cảnh",
    "Nắng ngược viền tóc": "backlight vàng nhẹ, viền sáng tóc rõ, vùng da giữ mềm và tự nhiên",
    "Điện ảnh đêm neon": "ánh sáng neon tím-xanh, tương phản cao, bloom nhẹ, hậu cảnh mờ điện ảnh",
    "Mơ màng pastel": "tone pastel sáng, highlight mềm, đổ bóng mịn, không khí mơ màng",
}
QUICK_STYLE_SCENARIO_PRESETS = {
    "Thay nhân vật ảnh 1 vào ảnh 2 (giữ cảnh ảnh 2)": {
        "focus": "Toàn diện (nét + màu + ánh sáng + bóng)",
        "lock": "Rất chặt",
        "strength": "Mạnh",
        "effect": "giữ bố cục, ánh sáng, đổ bóng và chiều sâu cảnh của Ảnh 2",
        "note": (
            "Giữ nguyên danh tính nhân vật từ Ảnh 1 (khuôn mặt, tóc, trang phục, phụ kiện). "
            "Đặt nhân vật đó vào đúng bố cục/cảnh của Ảnh 2, học toàn bộ ánh sáng, bóng, bokeh và không khí từ Ảnh 2. "
            "Không biến thành nhân vật khác, không đổi outfit chính."
        ),
    },
    "Giữ nhân vật ảnh 1, lấy pose và góc máy ảnh 2": {
        "focus": "Nét vẽ + chất liệu",
        "lock": "Rất chặt",
        "strength": "Vừa",
        "effect": "ưu tiên pose, góc máy và framing của Ảnh 2",
        "note": (
            "Giữ nguyên nhân vật Ảnh 1 nhưng chuyển pose, góc máy, crop khung hình theo Ảnh 2. "
            "Ánh sáng và đổ bóng theo Ảnh 2 ở mức vừa phải, giữ chi tiết mắt/tóc/trang phục rõ nét."
        ),
    },
    "Giữ mặt ảnh 1, mượn ánh sáng hoa/cảnh ảnh 2": {
        "focus": "Ánh sáng + đổ bóng + bokeh",
        "lock": "Rất chặt",
        "strength": "Vừa",
        "effect": "ánh sáng xuyên qua hoa/lá, bóng đổ mềm trên mặt, bokeh tiền cảnh/hậu cảnh từ Ảnh 2",
        "note": (
            "Khóa chặt khuôn mặt và nhận diện từ Ảnh 1. Mượn ánh sáng, đổ bóng, bokeh và mood cảnh từ Ảnh 2. "
            "Ưu tiên cảm giác chân thực, sắc nét, không cháy sáng và không noise."
        ),
    },
    "Remix sáng tạo: nhân vật ảnh 1 + vibe ảnh 2": {
        "focus": "Màu sắc + mood",
        "lock": "Cân bằng",
        "strength": "Mạnh",
        "effect": "vibe màu sắc và không khí tổng thể của Ảnh 2",
        "note": (
            "Giữ chủ thể chính từ Ảnh 1, cho phép biến tấu bố cục vừa phải để hòa vào vibe của Ảnh 2. "
            "Học palette, tương phản, ánh sáng và cảm xúc cảnh từ Ảnh 2."
        ),
    },
}
QUICK_STYLE_DETAILED_PROMPT_TEMPLATES = {
    "Mẫu chi tiết: Giữ mặt + đổi style mạnh": (
        "Mục tiêu: Giữ nguyên danh tính nhân vật từ Ảnh 1 (khuôn mặt, tóc, trang phục, phụ kiện), "
        "chỉ chuyển ngôn ngữ thị giác theo Ảnh 2.\n"
        "Bắt buộc:\n"
        "1) Khuôn mặt giống Ảnh 1, không đổi tuổi/giới.\n"
        "2) Bố cục chính và tư thế gần giống Ảnh 1.\n"
        "3) Học palette, ánh sáng và chất liệu nét từ Ảnh 2.\n"
        "4) Tránh lỗi tay/chân, mắt lệch, chi tiết méo.\n"
        "5) Nền sạch, không thêm vật thể lạ.\n"
        "Ngữ cảnh: [điền bối cảnh], Mood: [điền mood], Camera: [điền góc máy]."
    ),
    "Mẫu chi tiết: Chân dung điện ảnh": (
        "Tạo phiên bản chân dung điện ảnh từ Ảnh 1 với phong cách từ Ảnh 2.\n"
        "Yêu cầu chi tiết:\n"
        "- Giữ tỷ lệ khuôn mặt và thần thái của chủ thể ở Ảnh 1.\n"
        "- Ánh sáng key/fill/rim theo phong cách Ảnh 2, tương phản vừa phải.\n"
        "- Giữ texture da tự nhiên, không plastic skin, không over-sharpen.\n"
        "- Màu da trung thực, giữ chi tiết mắt/tóc.\n"
        "- Hậu cảnh mềm, ít nhiễu, không rối.\n"
        "Bổ sung: [điền màu chủ đạo], [điền tông cảm xúc], [điền crop gần/trung]."
    ),
    "Mẫu chi tiết: Sản phẩm sạch nền": (
        "Dùng Ảnh 1 làm sản phẩm chính, áp phong cách trình bày từ Ảnh 2.\n"
        "Ràng buộc:\n"
        "- Giữ hình dáng, logo, tỷ lệ thật của sản phẩm từ Ảnh 1.\n"
        "- Nền sạch, ánh sáng studio, bóng đổ mềm tự nhiên.\n"
        "- Tăng độ sắc nét ở biên sản phẩm và chất liệu bề mặt.\n"
        "- Không thêm chữ watermark, không thêm sản phẩm khác.\n"
        "- Ưu tiên bố cục thương mại rõ ràng, dễ nhìn.\n"
        "Biến thể mong muốn: [điền góc chụp], [điền tone màu], [điền mức tương phản]."
    ),
    "Mẫu chi tiết: Anime/Webtoon": (
        "Giữ nhân vật và bố cục của Ảnh 1, chuyển sang phong cách anime/webtoon từ Ảnh 2.\n"
        "Yêu cầu:\n"
        "- Đường nét sạch, rõ contour, đổ bóng cel-shading hợp lý.\n"
        "- Mắt, tóc, biểu cảm tự nhiên; không méo tay/chân.\n"
        "- Giữ trang phục và màu nhận diện của nhân vật gốc.\n"
        "- Hạn chế nền rối, ưu tiên background gọn để nổi chủ thể.\n"
        "- Chất lượng cao, không blur, không artifact.\n"
        "Chi tiết thêm: [điền bối cảnh], [điền nhịp cảm xúc], [điền mức độ stylize]."
    ),
    "Mẫu chi tiết: Kiến trúc/nội thất": (
        "Giữ layout và tỉ lệ không gian của Ảnh 1, học vật liệu và ánh sáng từ Ảnh 2.\n"
        "Tiêu chí:\n"
        "- Đường thẳng kiến trúc chuẩn, không cong méo phối cảnh.\n"
        "- Vật liệu (gỗ/kính/kim loại/vải) hiển thị rõ texture.\n"
        "- Ánh sáng tự nhiên, cân bằng trắng ổn định, không ám màu nặng.\n"
        "- Hạn chế noise và chi tiết thừa.\n"
        "- Giữ bố cục sạch, có chiều sâu không gian.\n"
        "Tùy chọn: [điền phong cách hiện đại/tối giản], [điền thời điểm sáng/chiều/đêm]."
    ),
    "Mẫu chi tiết: Nhân vật ảnh 1 + ánh sáng hoa đào ảnh 2": (
        "Giữ nguyên nhân vật từ Ảnh 1: khuôn mặt, mắt, tóc, trang phục, phụ kiện và tỷ lệ cơ thể.\n"
        "Áp ngôn ngữ thị giác từ Ảnh 2 theo hướng toàn diện, không chỉ nét và màu:\n"
        "- Học ánh sáng xuyên qua cành hoa, bóng lá/hoa đổ lên da mặt một cách tự nhiên.\n"
        "- Học bokeh tiền cảnh/hậu cảnh kiểu hoa đào, độ sâu trường ảnh mềm và trong.\n"
        "- Học chuyển sắc highlight/shadow sắc nét nhưng không cháy sáng.\n"
        "- Giữ chất lượng ảnh cao, chi tiết tóc và mắt rõ, da mịn tự nhiên.\n"
        "- Tuyệt đối không biến nhân vật thành người khác, không đổi trang phục chính.\n"
        "Bối cảnh mong muốn: [điền], góc máy: [điền], cảm xúc: [điền]."
    ),
    "Mẫu chi tiết: Thay nhân vật ảnh 1 vào bố cục ảnh 2": (
        "Nhiệm vụ: Thay nhân vật của Ảnh 2 bằng nhân vật từ Ảnh 1, nhưng vẫn giữ tổng thể khung cảnh của Ảnh 2.\n"
        "Ràng buộc cứng:\n"
        "- Giữ nguyên danh tính từ Ảnh 1: khuôn mặt, tóc, trang phục, phụ kiện, tỉ lệ cơ thể.\n"
        "- Giữ bố cục, góc máy, ánh sáng, đổ bóng, DOF và bokeh của Ảnh 2.\n"
        "- Chuyển blend tự nhiên giữa nhân vật và môi trường, không tách lớp giả.\n"
        "- Tránh lỗi anatomy (tay/chân/mắt), tránh artifact và blur.\n"
        "- Chất lượng cao, sắc nét, giữ texture tóc/da/vải tự nhiên.\n"
        "Tùy chỉnh thêm: [điền bối cảnh], [điền mood], [điền mức dramatize]."
    ),
}
QUICK_SPEED_PRESETS = {
    "Ổn định": 2,
    "Nhanh": 4,
    "Rất nhanh": 8,
    "Turbo": 30,
}
QUICK_UNIVERSAL_POWER_PRESETS = {
    "Nhanh": {"steps": 24, "guidance_scale": 6.0, "cfg_scale": 6.0, "clip_skip": 1, "image_detail": "medium"},
    "Cân bằng": {"steps": 36, "guidance_scale": 7.0, "cfg_scale": 7.0, "clip_skip": 1, "image_detail": "high"},
    "Mạnh": {"steps": 48, "guidance_scale": 7.5, "cfg_scale": 7.2, "clip_skip": 1, "image_detail": "high"},
    "Max": {"steps": 60, "guidance_scale": 8.0, "cfg_scale": 7.8, "clip_skip": 1, "image_detail": "high"},
}
QUICK_OPERATION_OPTIONS = [
    "Tạo ảnh",
    "Vẽ art game Tu Tiên Cờ",
    "Vẽ asset game (không nền)",
    "AI đa năng (copy ảnh + lệnh tự do)",
    "Làm truyện tranh",
    "Sửa ảnh nâng cao",
    "Sửa ảnh",
    "Phân tích & tách nền",
    "Xóa nền chroma",
    "Nâng cấp chất lượng",
    "Dịch ảnh",
    "Sao chép phong cách",
]

CHARACTER_DETAIL_TEMPLATES = {
    "— Tự nhập —": "",
    "Mắt sao tím": "Mắt có họa tiết ngôi sao màu tím nhạt ở tròng mắt, luôn giữ rõ cả 2 mắt, không che, không mờ.",
    "Mắt dị sắc (heterochromia)": "Một mắt xanh lá, một mắt xanh dương, viền mắt rõ, lông mi đậm tự nhiên.",
    "Nốt ruồi dưới mắt trái": "Có 1 nốt ruồi nhỏ tròn dưới mắt trái, màu nâu sẫm, không thêm nốt ruồi khác.",
    "Vết sẹo lông mày phải": "Có 1 vết sẹo dọc nhỏ chia đôi lông mày phải, mảnh và rõ.",
    "Tóc bạc lọn trắng trước trán": "Một lọn tóc bạc trắng nhỏ ngay phía trước trán, các phần còn lại giữ nguyên màu gốc.",
    "Khuyên bạc tai trái": "Đeo 1 khuyên bạc nhỏ hình tròn ở dái tai trái, tai phải để trống.",
    "Răng khểnh trái": "Có 1 chiếc răng khểnh nhẹ ở bên trái khi cười, các răng còn lại đều và trắng tự nhiên.",
    "Hình xăm cổ tay": "Có hình xăm chữ thư pháp nhỏ ở cổ tay phải, đường nét mảnh, màu đen.",
    "Vòng cổ chữ thập bạc": "Đeo dây chuyền bạc mảnh, mặt chữ thập đơn giản, luôn nằm ngoài cổ áo.",
    "Tàn nhang gò má": "Có tàn nhang nhẹ rải đều ở 2 gò má và sống mũi, màu nâu nhạt tự nhiên.",
    "Mí lót, lông mi cong": "Mí mắt lót sắc, lông mi cong tự nhiên, không quá đậm.",
    "Kính tròn gọng vàng": "Đeo kính gọng tròn mảnh màu vàng đồng, tròng kính trong suốt.",
    "Móng tay sơn đen": "Móng tay được sơn màu đen mờ, ngắn vừa phải, gọn gàng.",
    "Vết bớt cổ phải": "Có vết bớt cà phê sữa nhỏ hình giọt nước ở cổ bên phải.",
    "Lúm đồng tiền má phải": "Khi cười xuất hiện lúm đồng tiền nhẹ ở má phải.",
}

PAGE_HOME = "🏠 Tổng quan"
PAGE_DRAW = "🎨 Studio"
PAGE_TRAIN = "🧬 Train LoRA"
PAGE_MODEL = "🧠 Model"
PAGE_GALLERY = "🖼️ Thư viện"
PAGE_CONFIG = "⚙️ Cài đặt"

PAGE_OPTIONS = [
    PAGE_HOME,
    PAGE_DRAW,
    PAGE_TRAIN,
    PAGE_MODEL,
    PAGE_GALLERY,
    PAGE_CONFIG,
]



SIZE_PRESETS = {
    "Vuông 1024": "1024x1024",
    "Vuông 1536": "1536x1536",
    "Ngang 3:2": "1536x1024",
    "Ngang 16:9": "1792x1024",
    "Dọc 2:3": "1024x1536",
    "Dọc 9:16": "1024x1792",
    "Bài đăng MXH": "1080x1080",
    "Story/Reel": "1080x1920",
    "Wallpaper 4K": "3840x2160",
    "Tùy chỉnh": "",
}

ASPECT_RATIO_ORIGINAL = "Nguyên gốc theo ảnh mẫu"
ASPECT_RATIO_PRESETS = [ASPECT_RATIO_ORIGINAL, "", "1:1", "16:9", "9:16", "4:5", "5:4", "3:2", "2:3", "21:9"]
RESPONSE_FORMAT_OPTIONS = ["binary", "url", "b64_json"]
RESPONSE_FORMAT_LABELS = {
    "binary": "Ảnh trực tiếp (khuyên dùng)",
    "url": "Đường dẫn URL",
    "b64_json": "Chuỗi base64 (JSON)",
}
BACKGROUND_OPTIONS = ["", "transparent", "opaque", "blurred"]
OUTPUT_FORMAT_OPTIONS = ["", "png", "jpeg", "webp"]
IMAGE_DETAIL_OPTIONS = ["", "low", "medium", "high"]
SAMPLER_OPTIONS = ["", "euler", "euler_a", "ddim", "dpmpp_2m", "heun"]
TRANSPARENT_IMAGE_MODE = "RGBA"
TRANSPARENT_RGBA_COLOR = (0, 0, 0, 0)
TRANSPARENT_BACKGROUND_PROMPT_RULE = (
    "Required transparent background output: real PNG alpha channel, image mode RGBA, "
    "outside the subject must be fully transparent RGBA(0,0,0,0); no white background, "
    "no black background, no colored background, no checkerboard, no scenery unless explicitly requested."
)
TRANSPARENT_BACKGROUND_NEGATIVE_RULE = (
    "white background, black background, colored background, solid background, checkerboard background, "
    "opaque background, scenery background, room, wall, floor"
)
GREEN_SCREEN_RGB = (0, 255, 0)
GREEN_SCREEN_HEX = "#00FF00"
GREEN_SCREEN_PAYLOAD_FLAG = "_green_screen_remove_background"
GREEN_SCREEN_PROMPT_RULE = (
    "Use a single flat pure chroma key green background (#00FF00, RGB 0,255,0) behind the subject. "
    "The green background must be uniform, untextured, evenly lit, with no gradient, no scenery, no props, "
    "no floor, no wall, no pattern, no cast shadow on the green background. Fill every gap around and between limbs/hair/tail "
    "with the exact same flat #00FF00 green so chroma key removal can delete it. Keep the subject fully separated from the green."
)
GREEN_SCREEN_NEGATIVE_RULE = (
    "transparent background, white background, black background, gray background, checkerboard, scenery, room, wall, floor, "
    "gradient background, dark green patches, uneven green, grass, leaves, green glow spilling onto subject, green clothes unless explicitly requested"
)
BLUE_SCREEN_RGB = (0, 0, 255)
BLUE_SCREEN_HEX = "#0000FF"
BLUE_SCREEN_PAYLOAD_FLAG = "_blue_screen_remove_background"
BLUE_SCREEN_PROMPT_RULE = (
    "Use a single flat pure chroma key blue background (#0000FF, RGB 0,0,255) behind the subject. "
    "The blue background must be uniform, untextured, evenly lit, with no gradient, no scenery, no props, "
    "no floor, no wall, no pattern, no cast shadow on the blue background. Fill every gap around and between limbs/hair/tail "
    "with the exact same flat #0000FF blue so chroma key removal can delete it. Keep the subject fully separated from the blue."
)
BLUE_SCREEN_NEGATIVE_RULE = (
    "transparent background, white background, black background, gray background, checkerboard, scenery, room, wall, floor, "
    "gradient background, dark blue patches, uneven blue, sky, ocean, water, blue glow spilling onto subject, blue clothes unless explicitly requested"
)
MAGENTA_SCREEN_RGB = (255, 0, 255)
MAGENTA_SCREEN_HEX = "#FF00FF"
GPT_IMAGE_QUALITY_VALUES = {"low", "medium", "high", "auto"}
GPT_IMAGE_QUALITY_ALIASES = {
    "standard": "medium",
    "normal": "medium",
    "balanced": "medium",
    "hd": "high",
    "ultra": "high",
}
TRANSPARENT_DEFAULT_QUALITY = "medium"

QUALITY_PROFILES = {
    "Nhanh": {
        "quality": "standard",
        "steps": 20,
        "guidance_scale": 5.5,
        "cfg_scale": 5.0,
        "prompt_suffix": "clean composition",
    },
    "Cân bằng": {
        "quality": "standard",
        "steps": 30,
        "guidance_scale": 6.5,
        "cfg_scale": 6.0,
        "prompt_suffix": "high detail, refined lighting",
    },
    "Chất lượng cao (HD)": {
        "quality": "hd",
        "steps": 40,
        "guidance_scale": 7.5,
        "cfg_scale": 7.0,
        "prompt_suffix": "ultra detailed, crisp focus, cinematic texture",
    },
    "Siêu chi tiết (Ultra+)": {
        "quality": "hd",
        "steps": 55,
        "guidance_scale": 8.0,
        "cfg_scale": 7.5,
        "prompt_suffix": "masterpiece quality, intricate details, professional art direction",
    },
}

STYLE_PRESETS = {
    "Điện ảnh": {
        "style": "cinematic",
        "prompt_suffix": "cinematic lighting, dramatic contrast, film look",
        "negative_prompt": "blurry, flat lighting, low contrast",
    },
    "Chân thực": {
        "style": "photoreal",
        "prompt_suffix": "photorealistic, natural skin texture, realistic shadows",
        "negative_prompt": "plastic skin, overprocessed, uncanny face",
    },
    "Anime": {
        "style": "anime",
        "prompt_suffix": "anime style, clean line art, vivid cel shading",
        "negative_prompt": "mutated hands, distorted eyes, extra limbs",
    },
    "3D": {
        "style": "3d render",
        "prompt_suffix": "high quality 3D render, global illumination, octane style",
        "negative_prompt": "noisy mesh, low poly artifacts",
    },
    "Pixel Art": {
        "style": "pixel art",
        "prompt_suffix": "pixel art, limited palette, crisp retro aesthetic",
        "negative_prompt": "anti-aliased blur, realistic photo texture",
    },
    "Logo tối giản": {
        "style": "minimal",
        "prompt_suffix": "minimal clean design, vector-inspired, strong silhouette",
        "negative_prompt": "busy background, too many details",
    },
    "Không áp phong cách": {
        "style": "",
        "prompt_suffix": "",
        "negative_prompt": "",
    },
}










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

MODEL_RECOMMENDED = CPAB_CHAT_MODELS.copy()

MODEL_TOP_PRIORITY = CPAB_CHAT_MODELS.copy()

OPENAI_GPT_IMAGE_MODELS = {
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
    "gpt-image-2",
    "chatgpt-image-latest",
}
OPENAI_GPT_IMAGE_TRANSPARENT_MODELS = {
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
}
OPENAI_GPT_IMAGE_NO_TRANSPARENT_MODELS = {"gpt-image-2"}
DEFAULT_TRANSPARENT_NATIVE_MODEL = "gpt-image-1.5"

MODEL_COMPAT_FALLBACKS = {
    # Map of unsupported-version → newer-supported-version (Codex client too old).
    "gpt-5.5-image": "gpt-5.4-image",
}

# Do not auto-fallback to `openai/*` here. A local 9Router server may expose only
# `cx/*-image` models and return "No credentials for provider: openai" for OpenAI
# routes. Keep model selection tied to `/v1/models/image`.
MODEL_ENTITLEMENT_FALLBACKS: tuple[str, ...] = (
    "gpt-5.4-image",
    "gpt-5.3-image",
    "gpt-5.2-image",
)

DEFAULT_LORA_TRAIN_ENDPOINT = "/v1/lora/train"
DEFAULT_LORA_STATUS_ENDPOINT = "/v1/lora/train/status"
DEFAULT_LORA_LIST_ENDPOINT = "/v1/lora/list"
DEFAULT_LORA_CANCEL_ENDPOINT = "/v1/lora/train/cancel"
LORA_MAX_IMAGES = 80
LORA_DATASET_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

LORA_TRAINING_PRESETS = {
    "Nhanh thử": {
        "steps": 1200,
        "epochs": 8,
        "batch_size": 1,
        "learning_rate": 0.0001,
        "network_dim": 16,
        "network_alpha": 16,
        "resolution": 768,
        "caption_dropout": 0.0,
    },
    "Nhân vật chuẩn": {
        "steps": 2800,
        "epochs": 14,
        "batch_size": 2,
        "learning_rate": 0.00008,
        "network_dim": 32,
        "network_alpha": 16,
        "resolution": 1024,
        "caption_dropout": 0.05,
    },
    "Chi tiết cao": {
        "steps": 4200,
        "epochs": 20,
        "batch_size": 2,
        "learning_rate": 0.00006,
        "network_dim": 64,
        "network_alpha": 32,
        "resolution": 1024,
        "caption_dropout": 0.1,
    },
}

LORA_WORKFLOW_PROFILES = {
    "Train nhân vật": {
        "lora_type": "character",
        "training_preset": "Nhân vật chuẩn",
        "trigger_prefix": "char",
        "caption_prefix": "portrait character",
        "caption_suffix": "consistent identity",
        "recommended_images": "12-40 ảnh",
        "focus": "Giữ nhận diện nhân vật ổn định qua nhiều góc, trang phục, biểu cảm.",
    },
    "Train nét vẽ": {
        "lora_type": "style",
        "training_preset": "Chi tiết cao",
        "trigger_prefix": "style",
        "caption_prefix": "art style",
        "caption_suffix": "visual style consistency",
        "recommended_images": "25-80 ảnh",
        "focus": "Học phong cách màu, nét cọ, ánh sáng và chất liệu của bộ ảnh.",
    },
    "Train sản phẩm": {
        "lora_type": "product",
        "training_preset": "Nhân vật chuẩn",
        "trigger_prefix": "product",
        "caption_prefix": "product photo",
        "caption_suffix": "clean background",
        "recommended_images": "15-50 ảnh",
        "focus": "Giữ form sản phẩm, logo, chi tiết bề mặt khi đổi bối cảnh chụp.",
    },
    "Train logo/chữ": {
        "lora_type": "general",
        "training_preset": "Chi tiết cao",
        "trigger_prefix": "logo",
        "caption_prefix": "logo typography",
        "caption_suffix": "clean vector-like edges",
        "recommended_images": "20-60 ảnh",
        "focus": "Học kiểu chữ, đường nét logo, độ sắc cạnh và bố cục ký tự.",
    },
    "Train concept chung": {
        "lora_type": "general",
        "training_preset": "Nhanh thử",
        "trigger_prefix": "concept",
        "caption_prefix": "visual concept",
        "caption_suffix": "cohesive concept",
        "recommended_images": "20-100 ảnh",
        "focus": "Học concept tổng quát (mood, chất liệu, bối cảnh) thay vì 1 chủ thể cố định.",
    },
}



TRANSLATE_LANG_OPTIONS = [
    "Tiếng Việt",
    "Tiếng Anh",
    "Tiếng Nhật",
    "Tiếng Hàn",
    "Tiếng Trung",
    "Tiếng Pháp",
    "Tiếng Đức",
    "Tiếng Tây Ban Nha",
]

COMIC_STYLE_OPTIONS = [
    "Anime",
    "Manga đen trắng",
    "Webtoon màu",
    "Chibi",
    "Semi-realistic",
]

COMIC_STYLE_PROMPTS = {
    "Anime": "anime sharp lineart, vibrant cel shading, expressive face, dynamic composition",
    "Manga đen trắng": "black and white manga, screentone texture, high contrast ink lines",
    "Webtoon màu": "colorful webtoon style, clean digital lines, vertical storytelling composition",
    "Chibi": "cute chibi proportions, oversized expressive eyes, soft playful colors",
    "Semi-realistic": "semi-realistic illustration, natural anatomy, cinematic lighting, detailed textures",
}


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


def save_env_file(env_file: Path, base_url: str, api_key: str, api_keys_pool_text: str = "") -> None:
    pool_text = str(api_keys_pool_text or "").strip()
    content = (
        "# 9Router config\n"
        "# Example: NINEROUTER_URL=http://localhost:20128\n"
        f"NINEROUTER_URL={base_url.strip()}\n\n"
        "# If auth is enabled, set key below\n"
        f"NINEROUTER_KEY={api_key.strip()}\n"
    )
    if pool_text:
        content += (
            "\n# Multiple API keys for parallel generation (one per line or separated by comma)\n"
            f"NINEROUTER_KEYS={pool_text}\n"
        )
    env_file.write_text(content, encoding="utf-8")


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("NINEROUTER_URL đang trống.")
    if not normalized.startswith("http://") and not normalized.startswith("https://"):
        raise ValueError("NINEROUTER_URL phải bắt đầu bằng http:// hoặc https://")
    return normalized


def build_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    normalized_base = str(base_url or "").strip().rstrip("/")
    normalized_path = path if str(path).startswith("/") else f"/{path}"
    if normalized_base.endswith("/v1") and normalized_path.startswith("/v1/"):
        normalized_path = normalized_path[len("/v1"):]
    url = f"{normalized_base}{normalized_path}"
    if not query:
        return url
    return f"{url}?{parse.urlencode(query)}"


def resolve_api_url(base_url: str, path_or_url: str) -> str:
    raw = (path_or_url or "").strip()
    if not raw:
        raise ValueError("Endpoint đang trống.")
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    normalized = raw if raw.startswith("/") else f"/{raw}"
    return f"{base_url}{normalized}"


def append_query_params(url: str, query: dict[str, Any]) -> str:
    clean = {k: v for k, v in query.items() if v is not None and str(v).strip() != ""}
    if not clean:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{parse.urlencode(clean)}"


def build_headers(api_key: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "curl/8.13.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def resolve_api_get_timeout_seconds(value: Any | None = None) -> int:
    fallback = st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS)
    source = fallback if value is None else value
    return _clamp_int(source, 30, MAX_API_TIMEOUT_SECONDS)


def resolve_api_post_timeout_seconds(value: Any | None = None) -> int:
    fallback = st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS)
    source = fallback if value is None else value
    return _clamp_int(source, MIN_API_POST_TIMEOUT_SECONDS, MAX_API_TIMEOUT_SECONDS)

def ensure_runtime_timeout_defaults() -> None:
    current_timeout = st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS)
    if _clamp_int(current_timeout, 0, MAX_API_TIMEOUT_SECONDS) < MIN_API_POST_TIMEOUT_SECONDS:
        st.session_state.api_request_timeout = DEFAULT_API_POST_TIMEOUT_SECONDS


def resolve_image_retry_count(value: Any | None = None) -> int:
    fallback = st.session_state.get("image_retry_count", DEFAULT_IMAGE_RETRY_COUNT)
    source = fallback if value is None else value
    return _clamp_int(source, 0, MAX_IMAGE_RETRY_COUNT)


def resolve_image_retry_backoff_seconds(value: Any | None = None) -> float:
    fallback = st.session_state.get("image_retry_backoff", DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS)
    source = fallback if value is None else value
    return _clamp_float(source, 0.2, 15.0)


def parse_http_status_code(error_text: str) -> int | None:
    matched = re.search(r"\[(\d{3})\]", str(error_text or ""))
    if not matched:
        return None
    with suppress(Exception):
        return int(matched.group(1))
    return None


def is_codex_upgrade_required_error(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    signals = [
        "requires a newer version of codex",
        "please upgrade to the latest",
        "please upgrade to the lates",
    ]
    return any(signal in lowered for signal in signals)


def is_codex_entitlement_error(error_text: str) -> bool:
    """Detect Codex/ChatGPT account entitlement errors (Plus/Pro required).

    These are server-side 502 with text like:
      "Codex did not return an image. Account may not be entitled (Plus/Pro required)."
    Retrying never fixes them — fail fast with actionable hint instead.
    """
    lowered = str(error_text or "").lower()
    signals = [
        "may not be entitled",
        "plus/pro required",
        "plus / pro required",
        "codex did not return an image",
    ]
    return any(signal in lowered for signal in signals)


def is_upstream_headers_timeout_error(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    signals = [
        "und_err_headers_timeout",
        "headers timeout error",
        "headers timeout",
    ]
    return any(signal in lowered for signal in signals)


def is_transparent_background_not_supported_error(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    signals = [
        "transparent background is not supported",
        "background=transparent is not supported",
        "background transparent is not supported",
    ]
    return any(signal in lowered for signal in signals)


def suggest_compat_model_fallback(model_id: str) -> str:
    clean = str(model_id or "").strip()
    if not clean:
        return ""

    lowered = clean.lower()
    for source_suffix, fallback_suffix in MODEL_COMPAT_FALLBACKS.items():
        source = source_suffix.lower()
        if source not in lowered:
            continue
        source_idx = lowered.find(source)
        if source_idx < 0:
            continue
        return f"{clean[:source_idx]}{fallback_suffix}"
    return clean


def model_provider_prefix(model_id: str) -> str:
    clean = str(model_id or "").strip()
    if "/" not in clean:
        return ""
    return clean.rsplit("/", 1)[0] + "/"


def model_suffix(model_id: str) -> str:
    return str(model_id or "").strip().rsplit("/", 1)[-1].lower()


def is_cpab_base_url(base_url: str) -> bool:
    return "cpab.hiennq.dev" in str(base_url or "").lower()


def is_cpab_image_model(model_id: str) -> bool:
    clean = str(model_id or "").strip().lower()
    return clean in {item.lower() for item in CPAB_IMAGE_MODELS}


def is_cpab_chat_model(model_id: str) -> bool:
    clean = str(model_id or "").strip().lower()
    return clean in {item.lower() for item in CPAB_CHAT_MODELS}


def is_image_endpoint_model_unsupported_error(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    return (
        "not supported on /v1/images/generations" in lowered
        or "not supported on /v1/images/edits" in lowered
    )


def is_openai_gpt_image_model(model_id: str) -> bool:
    return model_suffix(model_id) in OPENAI_GPT_IMAGE_MODELS


def is_openai_transparent_supported_model(model_id: str) -> bool:
    return model_suffix(model_id) in OPENAI_GPT_IMAGE_TRANSPARENT_MODELS


def is_openai_transparent_known_unsupported_model(model_id: str) -> bool:
    return model_suffix(model_id) in OPENAI_GPT_IMAGE_NO_TRANSPARENT_MODELS


def choose_transparent_native_model(current_model: Any = "") -> str:
    current = str(current_model or "").strip()
    if is_openai_transparent_supported_model(current):
        return current
    try:
        candidates = unique_list(
            [str(item).strip() for item in st.session_state.get("models", []) if str(item).strip()]
            + MODEL_TOP_PRIORITY
            + MODEL_RECOMMENDED
            + [DEFAULT_TRANSPARENT_NATIVE_MODEL]
        )
    except Exception:
        candidates = unique_list(MODEL_TOP_PRIORITY + MODEL_RECOMMENDED + [DEFAULT_TRANSPARENT_NATIVE_MODEL])
    for candidate in candidates:
        if is_openai_transparent_supported_model(candidate):
            return model_suffix(candidate)
    return DEFAULT_TRANSPARENT_NATIVE_MODEL


def get_loaded_image_models_for_fallback() -> list[str]:
    try:
        loaded = [str(item).strip() for item in st.session_state.get("models", []) if str(item).strip()]
    except Exception:
        loaded = []
    return unique_list(loaded + MODEL_TOP_PRIORITY + MODEL_RECOMMENDED)


def suggest_entitlement_model_fallback(model_id: str, attempted_models: list[str]) -> str:
    current = str(model_id or "").strip()
    if not current:
        return ""

    attempted_suffixes = {model_suffix(item) for item in attempted_models if str(item).strip()}
    current_suffix = model_suffix(current)
    available = get_loaded_image_models_for_fallback()
    available_by_suffix: dict[str, str] = {model_suffix(item): item for item in available if item}

    fallback_suffixes: list[str] = []
    if current_suffix == "gpt-5.5-image":
        fallback_suffixes.extend(MODEL_ENTITLEMENT_FALLBACKS)
    elif current_suffix == "gpt-5.4-image":
        fallback_suffixes.extend(["gpt-5.3-image", "gpt-5.2-image"])
    elif current_suffix == "gpt-5.3-image":
        fallback_suffixes.append("gpt-5.2-image")
    fallback_suffixes = [item for item in unique_list(fallback_suffixes) if item and item not in attempted_suffixes]

    prefix = model_provider_prefix(current) or "cx/"
    for fallback_suffix in fallback_suffixes:
        candidate = available_by_suffix.get(fallback_suffix, f"{prefix}{fallback_suffix}")
        if candidate and candidate != current and candidate not in attempted_models:
            return candidate
    return ""


def is_retryable_generate_error(ex: Exception) -> bool:
    message = str(ex or "")
    lowered = message.lower()

    if is_codex_upgrade_required_error(message):
        return False
    if is_codex_entitlement_error(message):
        return False
    if is_upstream_headers_timeout_error(message):
        return False
    if is_transparent_background_not_supported_error(message):
        return False

    status_code = parse_http_status_code(message)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        # 502 with entitlement message handled above; otherwise retry.
        return True

    retry_signals = [
        "timed out",
        "timeout",
        "time out",
        "temporary failure",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "try again",
        "429",
        "rate limit",
        "too many requests",
    ]
    return any(signal in lowered for signal in retry_signals)


def build_generate_error_hint(error_text: str) -> str:
    text = str(error_text or "")
    lowered = text.lower()
    if "no credentials for provider: openai" in lowered:
        return (
            "Gợi ý: server 9Router hiện chưa cấu hình provider OpenAI. "
            "Hãy dùng model có sẵn trong `/v1/models/image` (ví dụ `cx/gpt-5.4-image`) "
            "hoặc cấu hình OpenAI credentials ở phía server."
        )
    if is_codex_entitlement_error(text):
        return (
            "Gợi ý: đây là lỗi quyền tài khoản/provider, không phải lỗi prompt hay timeout. "
            "Model `cx/gpt-5.x-image` cần entitlement phù hợp ở phía server 9Router/Codex "
            "(thường là tài khoản Plus/Pro hoặc phiên đăng nhập provider còn hạn). "
            "Hãy kiểm tra quyền provider `cx`, đăng nhập lại/cập nhật token phía server, hoặc chọn model khác trong `/v1/models/image`."
        )
    if is_upstream_headers_timeout_error(text):
        return (
            "Gợi ý: đây là timeout nội bộ phía 9Router/upstream (UND_ERR_HEADERS_TIMEOUT, reset sau ~30s), "
            "không phải timeout của app Streamlit. Tăng timeout app lên 570s không sửa được nếu server 9Router tự ngắt ở 30s. "
            "Cần tăng headers/request timeout ở server 9Router hoặc giảm độ nặng request: số ảnh=1, quality=low/medium, prompt ngắn hơn, ít ảnh mẫu hơn."
        )
    if is_transparent_background_not_supported_error(text):
        return (
            "Gợi ý: model hiện tại không hỗ trợ `background=transparent` native. "
            "Muốn không nền chuẩn GPT phải dùng OpenAI Images API với `gpt-image-1.5`, `gpt-image-1` hoặc `gpt-image-1-mini` "
            "và `background=transparent`, `output_format=png`. `gpt-image-2` hiện không hỗ trợ transparent background. "
            "Nếu vẫn thấy URL `localhost:20128` thì app đang đi qua 9Router; hãy cấu hình provider OpenAI trong 9Router hoặc đổi Base URL sang `https://api.openai.com`."
        )
    if is_codex_upgrade_required_error(text):
        return "Gợi ý: model hiện tại cần Codex mới hơn. Hãy nâng cấp Codex hoặc đổi sang `cx/gpt-5.4-image`."
    if "invalid size" in lowered and "minimum pixel budget" in lowered:
        return "Gợi ý: dùng size >= 1024x1024 hoặc bỏ trường size để backend tự chọn kích thước hợp lý."
    if "[401]" in lowered or "unauthorized" in lowered:
        return "Gợi ý: kiểm tra lại API key / quyền truy cập model."
    if "[429]" in lowered or "rate limit" in lowered:
        return "Gợi ý: giảm luồng song song, tăng backoff retry hoặc chờ quota reset."
    if "timed out" in lowered or "timeout" in lowered:
        return "Gợi ý: tăng Timeout request lên 360-480s và retry 1-2 lần. Có thể giảm số ảnh/lượt nếu server chậm."
    return ""


def http_get_json(url: str, api_key: str | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
    resolved_timeout = resolve_api_get_timeout_seconds(timeout_seconds)
    req = request.Request(url=url, method="GET")
    for key, value in build_headers(api_key).items():
        req.add_header(key, value)
    try:
        with request.urlopen(req, timeout=resolved_timeout) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} thất bại [{ex.code}]\n{text}") from ex
    except TimeoutError as ex:
        raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
    except socket.timeout as ex:
        raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
    except error.URLError as ex:
        if isinstance(ex.reason, TimeoutError) or isinstance(ex.reason, socket.timeout):
            raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
        raise RuntimeError(f"Không kết nối được tới {url}: {ex.reason}") from ex
    return json.loads(body)


def http_post(
    url: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[bytes, str]:
    resolved_timeout = resolve_api_post_timeout_seconds(timeout_seconds)
    body_bytes = json.dumps(payload).encode("utf-8")
    body_size_mb = len(body_bytes) / (1024 * 1024)
    req = request.Request(url=url, data=body_bytes, method="POST")
    for key, value in build_headers(api_key).items():
        req.add_header(key, value)
    try:
        with request.urlopen(req, timeout=resolved_timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except error.HTTPError as ex:
        text = ex.read().decode("utf-8", errors="replace")
        # Surface body size for 400/413 to help diagnose oversized JSON.
        size_hint = ""
        if ex.code in (400, 413) and body_size_mb > 1.5:
            size_hint = f" • payload {body_size_mb:.1f}MB"
        raise RuntimeError(f"POST {url} thất bại [{ex.code}]{size_hint}\n{text}") from ex
    except TimeoutError as ex:
        raise RuntimeError(f"POST {url} bị timeout sau {resolved_timeout}s") from ex
    except socket.timeout as ex:
        raise RuntimeError(f"POST {url} bị timeout sau {resolved_timeout}s") from ex
    except error.URLError as ex:
        if isinstance(ex.reason, TimeoutError) or isinstance(ex.reason, socket.timeout):
            raise RuntimeError(f"POST {url} bị timeout sau {resolved_timeout}s") from ex
        raise RuntimeError(f"Không kết nối được tới {url}: {ex.reason}") from ex
    return body, content_type


def http_post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    body, _ = http_post(url, payload, api_key, timeout_seconds=timeout_seconds)
    text = body.decode("utf-8", errors="replace")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"API không trả JSON hợp lệ: {text[:700]}") from ex
    if not isinstance(loaded, dict):
        raise RuntimeError("API trả về JSON nhưng không phải object")
    return loaded


@st.cache_data(show_spinner=False, ttl=60)
def discover_models(base_url: str, api_key: str, nonce: int) -> list[str]:
    _ = nonce
    try:
        data = http_get_json(build_url(base_url, "/v1/models/image"), api_key or None)
    except Exception:
        data = http_get_json(build_url(base_url, "/v1/models"), api_key or None)
    models = data.get("data", [])
    discovered = [item.get("id", "") for item in models if item.get("id")]
    allowed = {item.lower() for item in CPAB_ALLOWED_MODELS}
    filtered = [item for item in discovered if item.lower() in allowed]
    allowed_chat = {item.lower() for item in CPAB_CHAT_MODELS}
    filtered_chat = [item for item in filtered if item.lower() in allowed_chat]
    return unique_list(filtered_chat or CPAB_CHAT_MODELS.copy())


def get_model_info(base_url: str, api_key: str, model_id: str) -> dict[str, Any]:
    return http_get_json(build_url(base_url, "/v1/models/info", {"id": model_id}), api_key or None)


def health_check(base_url: str, api_key: str) -> tuple[bool, dict[str, Any] | str]:
    try:
        data = http_get_json(build_url(base_url, "/api/health"), api_key or None)
        return bool(data.get("ok", False)), data
    except Exception as ex:
        return False, str(ex)


# Fields that 9Router/many image-gen providers don't accept; drop them on first 400.
_PAYLOAD_OPTIONAL_FIELDS = (
    "steps",
    "guidance_scale",
    "cfg_scale",
    "clip_skip",
    "strength",
    "sampler",
    "image_detail",
    "background",
    "output_format",
    "negative_prompt",
    "seed",
    "aspect_ratio",
)


def sanitize_payload_for_retry(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop optional fields that often trigger 'Invalid JSON body' on strict providers.

    Returns (cleaned_payload, removed_field_names).
    """
    cleaned = dict(payload)
    removed: list[str] = []
    for field in _PAYLOAD_OPTIONAL_FIELDS:
        if field in cleaned:
            cleaned.pop(field, None)
            removed.append(field)
    return cleaned, removed


def _payload_image_refs(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    single = payload.get("image")
    if isinstance(single, str) and single.strip():
        refs.append(single.strip())
    many = payload.get("images")
    if isinstance(many, list):
        refs.extend(str(item).strip() for item in many if str(item).strip())
    return unique_list(refs)


def build_cpab_chat_image_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "") or "").strip()
    negative = str(payload.get("negative_prompt", "") or "").strip()
    if negative:
        prompt = append_prompt_rule(prompt, f"Avoid: {negative}")

    details: list[str] = []
    for key in ("size", "aspect_ratio", "quality", "style", "background", "output_format", "image_detail"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            details.append(f"{key}: {value}")
    if details:
        prompt = append_prompt_rule(prompt, "Generation settings: " + ", ".join(details))
    if not prompt:
        prompt = "Generate an image."

    refs = _payload_image_refs(payload)
    if refs:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": ref}} for ref in refs[:12])
    else:
        content = prompt

    chat_payload: dict[str, Any] = {
        "model": str(payload.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": float(payload.get("temperature", 0.7) or 0.7),
        "max_tokens": int(payload.get("max_tokens", 500) or 500),
    }
    return chat_payload


def decode_data_image_url(url: str) -> tuple[bytes, str] | None:
    clean = str(url or "").strip()
    if not clean.lower().startswith("data:image/") or "," not in clean:
        return None
    header, encoded = clean.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "image/png"
    try:
        return base64.b64decode(encoded), content_type
    except (binascii.Error, ValueError):
        return None


def parse_cpab_chat_image_result(parsed: dict[str, Any], response_format: str) -> dict[str, Any]:
    choices = parsed.get("choices", [])
    if not choices:
        return {"kind": "json", "raw": parsed}
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    images = message.get("images", []) if isinstance(message, dict) else []
    for image_item in images:
        if not isinstance(image_item, dict):
            continue
        image_url = image_item.get("image_url", {})
        url = image_url.get("url", "") if isinstance(image_url, dict) else ""
        decoded = decode_data_image_url(str(url))
        if decoded:
            image_bytes, content_type = decoded
            kind = "binary" if response_format == "binary" else "b64_json"
            return {"kind": kind, "image_bytes": image_bytes, "content_type": content_type, "raw": parsed}
        if url:
            return {"kind": "url", "url": str(url), "raw": parsed}
        b64_json = image_item.get("b64_json")
        if isinstance(b64_json, str) and b64_json.strip():
            return {
                "kind": "binary" if response_format == "binary" else "b64_json",
                "image_bytes": base64.b64decode(b64_json),
                "content_type": "image/png",
                "raw": parsed,
            }
    return {"kind": "json", "raw": parsed}


def generate_cpab_chat_image(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    chat_payload = build_cpab_chat_image_payload(payload)
    parsed = http_post_json(
        build_url(base_url, "/v1/chat/completions"),
        chat_payload,
        api_key or None,
        timeout_seconds=timeout_seconds,
    )
    result = parse_cpab_chat_image_result(parsed, response_format)
    if result.get("kind") == "json":
        raise RuntimeError("CPAB chat completion không trả ảnh trong `message.images`.")
    return result


def generate_image(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    effective_payload = dict(payload)
    if is_cpab_base_url(base_url) and is_cpab_chat_model(str(effective_payload.get("model", ""))):
        return generate_cpab_chat_image(
            base_url=base_url,
            api_key=api_key,
            payload=effective_payload,
            response_format=response_format,
            timeout_seconds=timeout_seconds,
        )

    openai_gpt_image_json = is_openai_gpt_image_model(str(effective_payload.get("model", "")))
    request_payload = prepare_openai_gpt_image_payload(effective_payload) if openai_gpt_image_json else dict(effective_payload)
    request_payload.pop(GREEN_SCREEN_PAYLOAD_FLAG, None)
    request_payload.pop(BLUE_SCREEN_PAYLOAD_FLAG, None)

    endpoint = build_url(base_url, "/v1/images/generations")
    if response_format == "binary" and not openai_gpt_image_json:
        endpoint = build_url(base_url, "/v1/images/generations", {"response_format": "binary"})
    try:
        body, content_type = http_post(endpoint, request_payload, api_key or None, timeout_seconds=timeout_seconds)
    except RuntimeError as ex:
        # If server rejects with 400 "Invalid JSON body" or "bad_request",
        # retry once with a sanitized payload (drop optional/non-standard fields).
        msg = str(ex)
        if payload_requests_transparent_background(request_payload) and is_transparent_background_not_supported_error(msg):
            raise
        if openai_gpt_image_json:
            raise
        is_bad_request = "[400]" in msg and (
            "invalid_request_error" in msg.lower()
            or "bad_request" in msg.lower()
            or "invalid json" in msg.lower()
            or "not supported" in msg.lower()
            or "unsupported" in msg.lower()
        )
        if not is_bad_request:
            raise
        cleaned, removed = sanitize_payload_for_retry(request_payload)
        if not removed or cleaned == request_payload:
            raise
        body, content_type = http_post(endpoint, cleaned, api_key or None, timeout_seconds=timeout_seconds)

    if response_format == "binary" and not openai_gpt_image_json:
        return {"kind": "binary", "image_bytes": body, "content_type": content_type, "raw": None}

    parsed = json.loads(body.decode("utf-8"))
    data = parsed.get("data", [])
    if not data:
        return {"kind": "json", "raw": parsed}
    first = data[0]
    if first.get("url"):
        return {"kind": "url", "url": first["url"], "raw": parsed}
    if first.get("b64_json"):
        kind = "binary" if response_format == "binary" else "b64_json"
        return {"kind": kind, "image_bytes": base64.b64decode(first["b64_json"]), "content_type": "image/png", "raw": parsed}
    return {"kind": "json", "raw": parsed}


def generate_image_with_retry(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    timeout_seconds: int,
    retry_count: int,
    retry_backoff_seconds: float,
    task_label: str = "",
) -> dict[str, Any]:
    retries = resolve_image_retry_count(retry_count)
    timeout_base = resolve_api_post_timeout_seconds(timeout_seconds)
    backoff_base = resolve_image_retry_backoff_seconds(retry_backoff_seconds)
    total_attempts = retries + 1
    last_error: Exception | None = None
    current_payload = dict(payload)
    attempted_compat_fallback = False
    attempted_image_model_fallback = False
    attempted_models = [str(current_payload.get("model", "")).strip()]

    attempt = 1
    while attempt <= total_attempts:
        # Escalate timeout each retry: server may be slow on cold cache.
        timeout_now = min(MAX_API_TIMEOUT_SECONDS, timeout_base + (attempt - 1) * 90)
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
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            if (
                not attempted_image_model_fallback
                and is_cpab_base_url(base_url)
                and is_image_endpoint_model_unsupported_error(str(ex))
                and not is_cpab_image_model(current_model)
            ):
                attempted_image_model_fallback = True
                tag = f"[{task_label}] " if task_label else ""
                st.warning(
                    f"{tag}Model `{current_model}` là model chat, không dùng được cho endpoint tạo ảnh; tự dùng backend ảnh `{DEFAULT_IMAGE_MODEL}`."
                )
                current_payload = dict(current_payload)
                current_payload["model"] = DEFAULT_IMAGE_MODEL
                attempted_models.append(DEFAULT_IMAGE_MODEL)
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            entitlement_fallback_model = ""
            if is_codex_entitlement_error(str(ex)):
                entitlement_fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            if entitlement_fallback_model:
                tag = f"[{task_label}] " if task_label else ""
                st.warning(
                    f"{tag}Model `{current_model}` thiếu quyền/không trả ảnh; tự thử `{entitlement_fallback_model}`."
                )
                current_payload = dict(current_payload)
                current_payload["model"] = entitlement_fallback_model
                attempted_models.append(entitlement_fallback_model)
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            timeout_fallback_model = ""
            if is_upstream_headers_timeout_error(str(ex)):
                timeout_fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            if timeout_fallback_model:
                tag = f"[{task_label}] " if task_label else ""
                st.warning(
                    f"{tag}Model `{current_model}` bị upstream headers timeout 30s; tự thử `{timeout_fallback_model}` nhẹ hơn."
                )
                current_payload = dict(current_payload)
                current_payload["model"] = timeout_fallback_model
                attempted_models.append(timeout_fallback_model)
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            transparent_fallback_model = ""
            if is_transparent_background_not_supported_error(str(ex)):
                transparent_fallback_model = suggest_entitlement_model_fallback(current_model, attempted_models)
            if transparent_fallback_model:
                tag = f"[{task_label}] " if task_label else ""
                st.warning(
                    f"{tag}Model `{current_model}` không hỗ trợ nền trong suốt native; tự thử `{transparent_fallback_model}`."
                )
                current_payload = dict(current_payload)
                current_payload["model"] = transparent_fallback_model
                attempted_models.append(transparent_fallback_model)
                if attempt == total_attempts:
                    total_attempts += 1
                attempt += 1
                continue

            should_retry = attempt < total_attempts and is_retryable_generate_error(ex)
            if not should_retry:
                break

            jitter = random.uniform(0.0, 0.35)
            delay = min(12.0, backoff_base * (2 ** max(0, attempt - 1)) + jitter)
            tag = f"[{task_label}] " if task_label else ""
            st.warning(
                f"{tag}Lần {attempt}/{total_attempts} lỗi: {ex}. "
                f"Sẽ thử lại sau {delay:.1f}s (timeout={timeout_now}s)."
            )
            time.sleep(delay)
            attempt += 1

    assert last_error is not None
    hint = build_generate_error_hint(str(last_error))
    if (
        is_codex_entitlement_error(str(last_error))
        or is_upstream_headers_timeout_error(str(last_error))
        or is_transparent_background_not_supported_error(str(last_error))
    ) and attempted_models:
        tried = " → ".join(item for item in unique_list(attempted_models) if item)
        if tried:
            hint = f"{hint}\nĐã thử model: {tried}" if hint else f"Đã thử model: {tried}"
    if hint:
        raise RuntimeError(f"{last_error}\\n{hint}")
    raise RuntimeError(str(last_error))


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def date_slug() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def build_daily_output_path(output_path: str, workflow_name: str, fallback_ext: str = ".png") -> str:
    requested = Path(output_path)
    ext = requested.suffix or fallback_ext
    stem = safe_filename(requested.stem or workflow_name or "image")
    workflow_slug = safe_filename(workflow_name.lower().replace(" ", "_"))
    timestamp = datetime.now().strftime("%H%M%S")
    daily_dir = HISTORY_DAILY_ROOT / date_slug()
    filename = f"{timestamp}_{workflow_slug}_{stem}{ext}"
    return str((daily_dir / filename).resolve())


def infer_ext(content_type: str, fallback: str = ".png") -> str:
    ctype = (content_type or "").lower()
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "webp" in ctype:
        return ".webp"
    if "gif" in ctype:
        return ".gif"
    return fallback


def append_prompt_rule(prompt: str, rule: str) -> str:
    prompt_text = str(prompt or "").strip()
    rule_text = str(rule or "").strip()
    if not rule_text:
        return prompt_text
    if rule_text.lower() in prompt_text.lower():
        return prompt_text
    if not prompt_text:
        return rule_text
    return f"{prompt_text}\n\n{rule_text}"


def append_unique_csv_rule(text: str, additions: str) -> str:
    parts = [part.strip() for part in str(text or "").split(",") if part.strip()]
    seen = {part.lower() for part in parts}
    for item in str(additions or "").split(","):
        clean_item = item.strip()
        if clean_item and clean_item.lower() not in seen:
            parts.append(clean_item)
            seen.add(clean_item.lower())
    return ", ".join(parts)


def normalize_gpt_image_quality_for_transparent(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not clean:
        return TRANSPARENT_DEFAULT_QUALITY
    mapped = GPT_IMAGE_QUALITY_ALIASES.get(clean, clean)
    if mapped == "auto":
        return TRANSPARENT_DEFAULT_QUALITY
    if mapped in GPT_IMAGE_QUALITY_VALUES:
        return mapped
    return TRANSPARENT_DEFAULT_QUALITY


def openai_size_from_aspect_ratio(aspect_ratio: str) -> str:
    ratio = str(aspect_ratio or "").strip()
    if ratio in {"", "Mặc định", ASPECT_RATIO_ORIGINAL}:
        return ""
    if ratio == "1:1":
        return "1024x1024"
    if ratio in {"16:9", "3:2", "5:4", "21:9"}:
        return "1536x1024"
    if ratio in {"9:16", "2:3", "4:5"}:
        return "1024x1536"
    return ""


def prepare_openai_gpt_image_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(payload)
    prepared["model"] = model_suffix(prepared.get("model", "")) or str(prepared.get("model", "")).strip()

    if prepared.get("background") == "transparent" and not is_openai_transparent_supported_model(str(prepared.get("model", ""))):
        raise RuntimeError(
            f"Model `{prepared.get('model')}` không hỗ trợ `background=transparent` native theo OpenAI Images API."
        )

    if prepared.get("background") == "transparent" and ("image" in prepared or "images" in prepared):
        raise RuntimeError(
            "Luồng OpenAI Images API native transparent hiện chỉ hỗ trợ text-to-image trong app này. "
            "Hãy bỏ ảnh tham chiếu, hoặc dùng luồng sửa ảnh riêng/multipart edit khi cần image-to-image."
        )

    if "aspect_ratio" in prepared and "size" not in prepared:
        mapped_size = openai_size_from_aspect_ratio(str(prepared.get("aspect_ratio", "")))
        if mapped_size:
            prepared["size"] = mapped_size

    if "quality" in prepared:
        prepared["quality"] = normalize_gpt_image_quality_for_transparent(prepared.get("quality"))
    if prepared.get("background") == "transparent":
        prepared["output_format"] = str(prepared.get("output_format") or "png").strip() or "png"
        if prepared["output_format"] == "jpeg":
            prepared["output_format"] = "png"

    negative = str(prepared.pop("negative_prompt", "") or "").strip()
    if negative:
        prepared["prompt"] = append_prompt_rule(str(prepared.get("prompt", "")), f"Avoid: {negative}")

    unsupported_fields = {
        "aspect_ratio",
        "image",
        "images",
        "style",
        "steps",
        "guidance_scale",
        "cfg_scale",
        "clip_skip",
        "strength",
        "sampler",
        "image_detail",
        "seed",
    }
    for field in unsupported_fields:
        prepared.pop(field, None)
    return prepared


def apply_transparent_background_request(payload: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
    if not enabled:
        return payload
    payload[BLUE_SCREEN_PAYLOAD_FLAG] = True
    payload.pop("background", None)
    payload["output_format"] = "png"
    payload["prompt"] = append_prompt_rule(str(payload.get("prompt", "")), BLUE_SCREEN_PROMPT_RULE)
    payload["negative_prompt"] = append_unique_csv_rule(
        str(payload.get("negative_prompt", "")),
        BLUE_SCREEN_NEGATIVE_RULE,
    )
    return payload


def payload_requests_green_screen_removal(payload: dict[str, Any]) -> bool:
    prompt_value = str(payload.get("prompt", "")).strip().lower()
    return bool(payload.get(GREEN_SCREEN_PAYLOAD_FLAG)) or "#00ff00" in prompt_value or "chroma key green" in prompt_value


def payload_requests_blue_screen_removal(payload: dict[str, Any]) -> bool:
    prompt_value = str(payload.get("prompt", "")).strip().lower()
    return bool(payload.get(BLUE_SCREEN_PAYLOAD_FLAG)) or "#0000ff" in prompt_value or "chroma key blue" in prompt_value


def payload_requests_chroma_screen_removal(payload: dict[str, Any]) -> bool:
    return payload_requests_blue_screen_removal(payload) or payload_requests_green_screen_removal(payload)


def payload_requests_transparent_background(payload: dict[str, Any]) -> bool:
    if payload_requests_chroma_screen_removal(payload):
        return True
    background_value = str(payload.get("background", "")).strip().lower()
    output_format_value = str(payload.get("output_format", "")).strip().lower()
    prompt_value = str(payload.get("prompt", "")).strip().lower()
    if background_value == "transparent":
        return True
    if output_format_value == "png" and any(
        marker in prompt_value
        for marker in (
            "transparent background",
            "png alpha",
            "alpha channel",
            "rgba(0,0,0,0)",
            "alpha=0",
        )
    ):
        return True
    return False


def rgba_has_transparent_pixels(image: Any) -> bool:
    try:
        alpha = image.getchannel("A")
        alpha_min, _alpha_max = alpha.getextrema()
        return int(alpha_min) < 255
    except Exception:
        return False


def inspect_image_transparency(image_bytes: bytes) -> dict[str, Any]:
    check: dict[str, Any] = {
        "readable": False,
        "ok": False,
        "mode": "",
        "format": "",
        "size": "",
        "has_alpha": False,
        "alpha_min": None,
        "alpha_max": None,
        "transparent_ratio": 0.0,
        "near_transparent_ratio": 0.0,
        "edge_transparent_ratio": 0.0,
        "reason": "",
    }
    if Image is None:
        check["reason"] = "Pillow chưa khả dụng nên không kiểm tra alpha được."
        return check
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            source = ImageOps.exif_transpose(opened) if ImageOps is not None else opened
            mode = str(source.mode)
            fmt = str(opened.format or "")
            width, height = source.size
            rgba_image = source.convert(TRANSPARENT_IMAGE_MODE)
            alpha = rgba_image.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            hist = alpha.histogram()
            total = max(1, width * height)
            transparent_count = int(hist[0])
            near_transparent_count = sum(int(value) for value in hist[:8])

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

            has_alpha = mode in {"RGBA", "LA"} or "transparency" in opened.info or int(alpha_min) < 255
            transparent_ratio = transparent_count / total
            near_transparent_ratio = near_transparent_count / total
            edge_transparent_ratio = edge_transparent / max(1, edge_total)
            check.update(
                {
                    "readable": True,
                    "ok": mode == TRANSPARENT_IMAGE_MODE and int(alpha_min) == 0 and transparent_ratio >= 0.005,
                    "mode": mode,
                    "format": fmt,
                    "size": f"{width}x{height}",
                    "has_alpha": has_alpha,
                    "alpha_min": int(alpha_min),
                    "alpha_max": int(alpha_max),
                    "transparent_ratio": transparent_ratio,
                    "near_transparent_ratio": near_transparent_ratio,
                    "edge_transparent_ratio": edge_transparent_ratio,
                }
            )
            if not has_alpha:
                check["reason"] = "Ảnh không có kênh alpha, nền đang opaque."
            elif int(alpha_min) > 0:
                check["reason"] = "Có alpha nhưng chưa có pixel alpha=0 hoàn toàn."
            elif mode != TRANSPARENT_IMAGE_MODE:
                check["reason"] = f"Có alpha nhưng mode hiện là {mode}, chưa phải RGBA."
            elif transparent_ratio < 0.005:
                check["reason"] = "Có alpha=0 nhưng vùng trong suốt quá ít để coi là ảnh không nền."
            else:
                check["reason"] = "Đạt: PNG/RGBA có vùng alpha=0."
    except Exception as ex:
        check["reason"] = f"Không đọc được ảnh để kiểm tra alpha: {ex}"
    return check


def render_transparency_check(check: dict[str, Any], requested: bool = False) -> None:
    if not check or not check.get("readable"):
        if requested:
            st.warning(str(check.get("reason", "Không kiểm tra được nền trong suốt.")))
        return
    if not requested and not check.get("has_alpha"):
        return

    transparent_pct = float(check.get("transparent_ratio", 0.0)) * 100
    edge_pct = float(check.get("edge_transparent_ratio", 0.0)) * 100
    summary = (
        f"Mode `{check.get('mode')}` • format `{check.get('format') or 'unknown'}` • "
        f"alpha min/max `{check.get('alpha_min')}/{check.get('alpha_max')}` • "
        f"transparent `{transparent_pct:.2f}%` • viền transparent `{edge_pct:.1f}%`"
    )
    if check.get("ok"):
        st.success(f"Nền trong suốt: ĐẠT. {summary}")
    elif requested:
        st.warning(f"Nền trong suốt: CHƯA CHẮC/CHƯA ĐẠT. {summary}. {check.get('reason', '')}")
    else:
        st.info(f"Ảnh có alpha. {summary}")


def transparency_check_label(check: Any, requested: bool = False) -> str:
    if not isinstance(check, dict) or not check.get("readable"):
        return "⚠️ Chưa kiểm tra alpha" if requested else ""
    transparent_pct = float(check.get("transparent_ratio", 0.0)) * 100
    if check.get("ok"):
        return f"✅ Không nền chuẩn • {check.get('mode')} • alpha=0 • {transparent_pct:.1f}% trong suốt"
    if requested:
        return f"⚠️ Chưa đạt không nền • {check.get('mode')} • alpha {check.get('alpha_min')}/{check.get('alpha_max')}"
    if check.get("has_alpha"):
        return f"ℹ️ Có alpha • {check.get('mode')} • {transparent_pct:.1f}% trong suốt"
    return ""


def rgb_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return sum((int(a) - int(b)) ** 2 for a, b in zip(left, right)) ** 0.5


def average_rgb(pixels: list[tuple[int, int, int, int]]) -> tuple[int, int, int]:
    if not pixels:
        return (255, 255, 255)
    total_r = sum(int(pixel[0]) for pixel in pixels)
    total_g = sum(int(pixel[1]) for pixel in pixels)
    total_b = sum(int(pixel[2]) for pixel in pixels)
    count = max(1, len(pixels))
    return (round(total_r / count), round(total_g / count), round(total_b / count))


def green_screen_score(pixel: tuple[int, int, int, int]) -> float:
    r, g, b, a = pixel
    if int(a) == 0:
        return 1.0
    max_rb = max(int(r), int(b))
    green_delta = int(g) - max_rb
    green_ratio = int(g) / max(1, max_rb)
    saturation_gap = int(g) - min(int(r), int(b))
    score = 0.0
    if int(g) >= 70:
        score += max(0.0, min(1.0, green_delta / 85.0)) * 0.55
        score += max(0.0, min(1.0, (green_ratio - 1.05) / 0.85)) * 0.30
        score += max(0.0, min(1.0, saturation_gap / 120.0)) * 0.15
    return max(0.0, min(1.0, score))


def is_chroma_green_pixel(pixel: tuple[int, int, int, int]) -> bool:
    return green_screen_score(pixel) >= 0.42


def is_strong_chroma_green_pixel(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if int(a) == 0:
        return True
    return green_screen_score(pixel) >= 0.62 or (
        int(g) >= 90
        and int(g) - int(r) >= 30
        and int(g) - int(b) >= 25
        and int(g) >= int(max(r, b)) * 1.15
    )


def blue_screen_score(pixel: tuple[int, int, int, int]) -> float:
    r, g, b, a = pixel
    if int(a) == 0:
        return 1.0
    max_rg = max(int(r), int(g))
    blue_delta = int(b) - max_rg
    blue_ratio = int(b) / max(1, max_rg)
    saturation_gap = int(b) - min(int(r), int(g))
    score = 0.0
    if int(b) >= 70:
        score += max(0.0, min(1.0, blue_delta / 85.0)) * 0.55
        score += max(0.0, min(1.0, (blue_ratio - 1.05) / 0.85)) * 0.30
        score += max(0.0, min(1.0, saturation_gap / 120.0)) * 0.15
    return max(0.0, min(1.0, score))


def is_chroma_blue_pixel(pixel: tuple[int, int, int, int]) -> bool:
    return blue_screen_score(pixel) >= 0.42


def is_strong_chroma_blue_pixel(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if int(a) == 0:
        return True
    return blue_screen_score(pixel) >= 0.62 or (
        int(b) >= 90
        and int(b) - int(r) >= 25
        and int(b) - int(g) >= 30
        and int(b) >= int(max(r, g)) * 1.15
    )

def magenta_screen_score(pixel: tuple[int, int, int, int]) -> float:
    r, g, b, a = pixel
    if int(a) == 0:
        return 1.0
    min_rb = min(int(r), int(b))
    max_rb = max(int(r), int(b))
    magenta_delta = min_rb - int(g)
    rb_balance = 1.0 - min(1.0, abs(int(r) - int(b)) / max(1, max_rb))
    magenta_ratio = min_rb / max(1, int(g))
    score = 0.0
    if int(r) >= 70 and int(b) >= 70:
        score += max(0.0, min(1.0, magenta_delta / 85.0)) * 0.55
        score += max(0.0, min(1.0, (magenta_ratio - 1.05) / 0.85)) * 0.25
        score += max(0.0, min(1.0, rb_balance)) * 0.20
    return max(0.0, min(1.0, score))

def is_chroma_magenta_pixel(pixel: tuple[int, int, int, int]) -> bool:
    return magenta_screen_score(pixel) >= 0.42

def is_strong_chroma_magenta_pixel(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if int(a) == 0:
        return True
    return magenta_screen_score(pixel) >= 0.62 or (
        int(r) >= 90
        and int(b) >= 90
        and min(int(r), int(b)) - int(g) >= 30
        and min(int(r), int(b)) >= int(g) * 1.15
    )


def _has_neighbor(mask: bytearray, idx: int, width: int, height: int) -> bool:
    x = idx % width
    if x > 0 and mask[idx - 1]:
        return True
    if x < width - 1 and mask[idx + 1]:
        return True
    if idx >= width and mask[idx - width]:
        return True
    return bool(idx < width * (height - 1) and mask[idx + width])


def remove_green_screen_background(image: Any) -> Any:
    width, height = image.size
    if width < 2 or height < 2:
        return image

    pixels = list(image.getdata())
    green_mask = bytearray(1 if is_chroma_green_pixel(pixel) else 0 for pixel in pixels)
    strong_green_mask = bytearray(1 if is_strong_chroma_green_pixel(pixel) else 0 for pixel in pixels)
    visited = bytearray(width * height)
    stack: list[int] = []

    for x in range(width):
        top = x
        bottom = (height - 1) * width + x
        if green_mask[top]:
            stack.append(top)
        if green_mask[bottom]:
            stack.append(bottom)
    for y in range(height):
        left = y * width
        right = y * width + (width - 1)
        if green_mask[left]:
            stack.append(left)
        if green_mask[right]:
            stack.append(right)

    while stack:
        idx = stack.pop()
        if visited[idx] or not green_mask[idx]:
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

    remove_mask = bytearray(visited)
    for idx, is_strong_green in enumerate(strong_green_mask):
        if is_strong_green:
            remove_mask[idx] = 1

    for _ in range(2):
        grown = bytearray(remove_mask)
        for idx, pixel in enumerate(pixels):
            if remove_mask[idx]:
                continue
            score = green_screen_score(pixel)
            if score >= 0.30 and _has_neighbor(remove_mask, idx, width, height):
                grown[idx] = 1
        remove_mask = grown

    removed_count = sum(remove_mask)
    if removed_count < max(16, int(width * height * 0.01)):
        return image

    output_pixels: list[tuple[int, int, int, int]] = []
    for idx, (r, g, b, a) in enumerate(pixels):
        if remove_mask[idx]:
            output_pixels.append((r, g, b, 0))
            continue
        score = green_screen_score((r, g, b, a))
        if score >= 0.18 and _has_neighbor(remove_mask, idx, width, height):
            softened_alpha = max(0, min(255, round(int(a) * (1.0 - min(0.85, score * 1.25)))))
            clean_r = min(255, int(r) + round(max(0, int(g) - max(int(r), int(b))) * 0.15))
            clean_g = min(int(g), max(int(r), int(b), round(int(g) * (1.0 - score * 0.55))))
            output_pixels.append((clean_r, clean_g, b, softened_alpha))
        else:
            output_pixels.append((r, g, b, a))

    output_image = Image.new(TRANSPARENT_IMAGE_MODE, image.size, TRANSPARENT_RGBA_COLOR)
    output_image.putdata(output_pixels)
    return output_image


def remove_blue_screen_background(image: Any) -> Any:
    width, height = image.size
    if width < 2 or height < 2:
        return image

    pixels = list(image.getdata())
    blue_mask = bytearray(1 if is_chroma_blue_pixel(pixel) else 0 for pixel in pixels)
    strong_blue_mask = bytearray(1 if is_strong_chroma_blue_pixel(pixel) else 0 for pixel in pixels)
    visited = bytearray(width * height)
    stack: list[int] = []

    for x in range(width):
        top = x
        bottom = (height - 1) * width + x
        if blue_mask[top]:
            stack.append(top)
        if blue_mask[bottom]:
            stack.append(bottom)
    for y in range(height):
        left = y * width
        right = y * width + (width - 1)
        if blue_mask[left]:
            stack.append(left)
        if blue_mask[right]:
            stack.append(right)

    while stack:
        idx = stack.pop()
        if visited[idx] or not blue_mask[idx]:
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

    remove_mask = bytearray(visited)
    for idx, is_strong_blue in enumerate(strong_blue_mask):
        if is_strong_blue:
            remove_mask[idx] = 1

    for _ in range(2):
        grown = bytearray(remove_mask)
        for idx, pixel in enumerate(pixels):
            if remove_mask[idx]:
                continue
            score = blue_screen_score(pixel)
            if score >= 0.30 and _has_neighbor(remove_mask, idx, width, height):
                grown[idx] = 1
        remove_mask = grown

    removed_count = sum(remove_mask)
    if removed_count < max(16, int(width * height * 0.01)):
        return image

    output_pixels: list[tuple[int, int, int, int]] = []
    for idx, (r, g, b, a) in enumerate(pixels):
        if remove_mask[idx]:
            output_pixels.append((r, g, b, 0))
            continue
        score = blue_screen_score((r, g, b, a))
        if score >= 0.18 and _has_neighbor(remove_mask, idx, width, height):
            softened_alpha = max(0, min(255, round(int(a) * (1.0 - min(0.85, score * 1.25)))))
            blue_excess = max(0, int(b) - max(int(r), int(g)))
            clean_r = min(255, int(r) + round(blue_excess * 0.10))
            clean_g = min(255, int(g) + round(blue_excess * 0.10))
            clean_b = min(int(b), max(int(r), int(g), round(int(b) * (1.0 - score * 0.55))))
            output_pixels.append((clean_r, clean_g, clean_b, softened_alpha))
        else:
            output_pixels.append((r, g, b, a))

    output_image = Image.new(TRANSPARENT_IMAGE_MODE, image.size, TRANSPARENT_RGBA_COLOR)
    output_image.putdata(output_pixels)
    return output_image

def remove_magenta_screen_background(image: Any) -> Any:
    width, height = image.size
    if width < 2 or height < 2:
        return image

    pixels = list(image.getdata())
    magenta_mask = bytearray(1 if is_chroma_magenta_pixel(pixel) else 0 for pixel in pixels)
    strong_magenta_mask = bytearray(1 if is_strong_chroma_magenta_pixel(pixel) else 0 for pixel in pixels)
    visited = bytearray(width * height)
    stack: list[int] = []

    for x in range(width):
        top = x
        bottom = (height - 1) * width + x
        if magenta_mask[top]:
            stack.append(top)
        if magenta_mask[bottom]:
            stack.append(bottom)
    for y in range(height):
        left = y * width
        right = y * width + (width - 1)
        if magenta_mask[left]:
            stack.append(left)
        if magenta_mask[right]:
            stack.append(right)

    while stack:
        idx = stack.pop()
        if visited[idx] or not magenta_mask[idx]:
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

    remove_mask = bytearray(visited)
    for idx, is_strong_magenta in enumerate(strong_magenta_mask):
        if is_strong_magenta:
            remove_mask[idx] = 1

    for _ in range(2):
        grown = bytearray(remove_mask)
        for idx, pixel in enumerate(pixels):
            if remove_mask[idx]:
                continue
            score = magenta_screen_score(pixel)
            if score >= 0.30 and _has_neighbor(remove_mask, idx, width, height):
                grown[idx] = 1
        remove_mask = grown

    removed_count = sum(remove_mask)
    if removed_count < max(16, int(width * height * 0.01)):
        return image

    output_pixels: list[tuple[int, int, int, int]] = []
    for idx, (r, g, b, a) in enumerate(pixels):
        if remove_mask[idx]:
            output_pixels.append((r, g, b, 0))
            continue
        score = magenta_screen_score((r, g, b, a))
        if score >= 0.18 and _has_neighbor(remove_mask, idx, width, height):
            softened_alpha = max(0, min(255, round(int(a) * (1.0 - min(0.85, score * 1.25)))))
            magenta_excess = max(0, min(int(r), int(b)) - int(g))
            clean_r = max(int(g), round(int(r) * (1.0 - score * 0.45)))
            clean_g = min(255, int(g) + round(magenta_excess * 0.10))
            clean_b = max(int(g), round(int(b) * (1.0 - score * 0.45)))
            output_pixels.append((clean_r, clean_g, clean_b, softened_alpha))
        else:
            output_pixels.append((r, g, b, a))

    output_image = Image.new(TRANSPARENT_IMAGE_MODE, image.size, TRANSPARENT_RGBA_COLOR)
    output_image.putdata(output_pixels)
    return output_image


def remove_solid_corner_background(image: Any) -> Any:
    width, height = image.size
    if width < 4 or height < 4:
        return image

    sample_size = max(2, min(18, width // 28, height // 28))
    boxes = [
        (0, 0, sample_size, sample_size),
        (width - sample_size, 0, width, sample_size),
        (0, height - sample_size, sample_size, height),
        (width - sample_size, height - sample_size, width, height),
    ]
    corner_colors = [average_rgb(list(image.crop(box).getdata())) for box in boxes]
    corner_spread = max(
        rgb_distance(left, right)
        for left in corner_colors
        for right in corner_colors
    )
    if corner_spread > 42:
        return image

    background_rgb = average_rgb([(r, g, b, 255) for r, g, b in corner_colors])
    hard_threshold = 34
    soft_threshold = 62
    changed = 0
    new_pixels: list[tuple[int, int, int, int]] = []
    for r, g, b, a in image.getdata():
        dist = rgb_distance((r, g, b), background_rgb)
        if dist <= hard_threshold:
            new_pixels.append((r, g, b, TRANSPARENT_RGBA_COLOR[3]))
            changed += 1
        elif dist <= soft_threshold:
            ratio = (dist - hard_threshold) / max(1, soft_threshold - hard_threshold)
            new_pixels.append((r, g, b, max(0, min(255, round(int(a) * ratio)))))
            changed += 1
        else:
            new_pixels.append((r, g, b, a))

    if changed / max(1, width * height) < 0.08:
        return image

    output_image = Image.new(TRANSPARENT_IMAGE_MODE, image.size, TRANSPARENT_RGBA_COLOR)
    output_image.putdata(new_pixels)
    return output_image


BACKGROUND_REMOVAL_METHOD_LABELS = {
    "existing_alpha": "Ảnh đã có nền trong suốt",
    "green_chroma": f"Xóa nền xanh lá {GREEN_SCREEN_HEX}",
    "blue_chroma": f"Xóa nền xanh biển {BLUE_SCREEN_HEX}",
    "magenta_chroma": f"Xóa nền hồng {MAGENTA_SCREEN_HEX}",
    "solid_corner": "Xóa nền trơn theo màu ở 4 góc",
    "fallback": "Tự xử lý nền trơn/góc ảnh",
}

def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, int(rgb[0]))),
        max(0, min(255, int(rgb[1]))),
        max(0, min(255, int(rgb[2]))),
    )

def _sample_image_edge_pixels(image: Any, max_samples: int = 4096) -> list[tuple[int, int, int, int]]:
    width, height = image.size
    if width < 1 or height < 1:
        return []
    step = max(1, max(width, height) // 160)
    px = image.load()
    samples: list[tuple[int, int, int, int]] = []
    for x in range(0, width, step):
        samples.append(px[x, 0])
        if height > 1:
            samples.append(px[x, height - 1])
    for y in range(0, height, step):
        samples.append(px[0, y])
        if width > 1:
            samples.append(px[width - 1, y])
    if len(samples) > max_samples:
        samples = samples[::max(1, len(samples) // max_samples)]
    return samples

def _sample_image_corner_pixels(image: Any) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int]]]:
    width, height = image.size
    if width < 1 or height < 1:
        return [], []
    sample_size = max(1, min(24, max(1, width // 12), max(1, height // 12), width, height))
    boxes = [
        (0, 0, sample_size, sample_size),
        (max(0, width - sample_size), 0, width, sample_size),
        (0, max(0, height - sample_size), sample_size, height),
        (max(0, width - sample_size), max(0, height - sample_size), width, height),
    ]
    corner_pixels: list[tuple[int, int, int, int]] = []
    corner_colors: list[tuple[int, int, int]] = []
    for box in boxes:
        pixels = list(image.crop(box).getdata())
        corner_pixels.extend(pixels)
        corner_colors.append(average_rgb(pixels))
    return corner_pixels, corner_colors

def _ratio_for_score(
    pixels: list[tuple[int, int, int, int]],
    score_fn: Any,
    threshold: float = 0.42,
) -> tuple[float, float]:
    if not pixels:
        return 0.0, 0.0
    scores = [float(score_fn(pixel)) for pixel in pixels]
    ratio = sum(1 for score in scores if score >= threshold) / max(1, len(scores))
    avg_score = sum(scores) / max(1, len(scores))
    return ratio, avg_score

def analyze_background_for_removal(image_bytes: bytes, before_check: dict[str, Any] | None = None) -> dict[str, Any]:
    analysis: dict[str, Any] = {
        "readable": False,
        "reason": "",
        "method": "fallback",
        "method_label": BACKGROUND_REMOVAL_METHOD_LABELS["fallback"],
    }
    if Image is None:
        analysis["reason"] = "Pillow chưa khả dụng nên không phân tích được ảnh."
        return analysis
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            source = ImageOps.exif_transpose(opened) if ImageOps is not None else opened
            rgba_image = source.convert(TRANSPARENT_IMAGE_MODE)
    except Exception as ex:
        analysis["reason"] = f"Không đọc được ảnh: {ex}"
        return analysis

    edge_pixels = _sample_image_edge_pixels(rgba_image)
    corner_pixels, corner_colors = _sample_image_corner_pixels(rgba_image)
    edge_rgb = average_rgb(edge_pixels)
    corner_rgb = average_rgb(corner_pixels)
    corner_spread = max(
        [rgb_distance(left, right) for left in corner_colors for right in corner_colors] or [0.0]
    )
    edge_green_ratio, edge_green_score = _ratio_for_score(edge_pixels, green_screen_score)
    edge_blue_ratio, edge_blue_score = _ratio_for_score(edge_pixels, blue_screen_score)
    edge_magenta_ratio, edge_magenta_score = _ratio_for_score(edge_pixels, magenta_screen_score)
    corner_green_ratio, _corner_green_score = _ratio_for_score(corner_pixels, green_screen_score)
    corner_blue_ratio, _corner_blue_score = _ratio_for_score(corner_pixels, blue_screen_score)
    corner_magenta_ratio, _corner_magenta_score = _ratio_for_score(corner_pixels, magenta_screen_score)
    edge_solid_ratio = 0.0
    if edge_pixels:
        edge_solid_ratio = sum(
            1 for r, g, b, _a in edge_pixels
            if rgb_distance((r, g, b), corner_rgb) <= 62
        ) / max(1, len(edge_pixels))

    transparent_ratio = 0.0
    edge_transparent_ratio = 0.0
    if before_check:
        transparent_ratio = float(before_check.get("transparent_ratio", 0.0) or 0.0)
        edge_transparent_ratio = float(before_check.get("edge_transparent_ratio", 0.0) or 0.0)

    analysis.update(
        {
            "readable": True,
            "size": f"{rgba_image.size[0]}x{rgba_image.size[1]}",
            "edge_rgb": edge_rgb,
            "edge_hex": rgb_to_hex(edge_rgb),
            "corner_rgb": corner_rgb,
            "corner_hex": rgb_to_hex(corner_rgb),
            "corner_spread": round(float(corner_spread), 2),
            "edge_solid_ratio": round(edge_solid_ratio, 4),
            "edge_green_ratio": round(edge_green_ratio, 4),
            "edge_blue_ratio": round(edge_blue_ratio, 4),
            "edge_magenta_ratio": round(edge_magenta_ratio, 4),
            "edge_green_score": round(edge_green_score, 4),
            "edge_blue_score": round(edge_blue_score, 4),
            "edge_magenta_score": round(edge_magenta_score, 4),
            "corner_green_ratio": round(corner_green_ratio, 4),
            "corner_blue_ratio": round(corner_blue_ratio, 4),
            "corner_magenta_ratio": round(corner_magenta_ratio, 4),
            "transparent_ratio": round(transparent_ratio, 4),
            "edge_transparent_ratio": round(edge_transparent_ratio, 4),
        }
    )
    return analysis

def _select_background_removal_method(analysis: dict[str, Any], preferred: str = "auto") -> tuple[str, str]:
    preferred_key = str(preferred or "auto").strip().lower()
    forced_methods = {
        "green": "green_chroma",
        "blue": "blue_chroma",
        "magenta": "magenta_chroma",
        "pink": "magenta_chroma",
        "solid": "solid_corner",
        "corner": "solid_corner",
    }
    if preferred_key in forced_methods:
        method = forced_methods[preferred_key]
        return method, f"Người dùng ưu tiên: {BACKGROUND_REMOVAL_METHOD_LABELS[method]}."

    if float(analysis.get("transparent_ratio", 0.0) or 0.0) >= 0.005 and float(analysis.get("edge_transparent_ratio", 0.0) or 0.0) >= 0.25:
        return "existing_alpha", "Ảnh đã có alpha tốt ở viền, giữ nguyên PNG trong suốt."

    chroma_methods = [
        (float(analysis.get("edge_green_ratio", 0.0) or 0.0), float(analysis.get("corner_green_ratio", 0.0) or 0.0), "green_chroma"),
        (float(analysis.get("edge_blue_ratio", 0.0) or 0.0), float(analysis.get("corner_blue_ratio", 0.0) or 0.0), "blue_chroma"),
        (float(analysis.get("edge_magenta_ratio", 0.0) or 0.0), float(analysis.get("corner_magenta_ratio", 0.0) or 0.0), "magenta_chroma"),
    ]
    chroma_methods.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_edge, top_corner, top_method = chroma_methods[0]
    second_edge = chroma_methods[1][0] if len(chroma_methods) > 1 else 0.0
    corner_spread = float(analysis.get("corner_spread", 999.0) or 999.0)
    edge_solid_ratio = float(analysis.get("edge_solid_ratio", 0.0) or 0.0)

    if top_edge >= 0.38 and top_edge >= max(0.05, second_edge * 1.18):
        return top_method, f"Viền ảnh khớp chroma cao ({top_edge:.0%}), chọn {BACKGROUND_REMOVAL_METHOD_LABELS[top_method]}."
    if top_corner >= 0.62 and top_edge >= 0.18:
        return top_method, f"Các góc ảnh là màu chroma rõ ({top_corner:.0%}), chọn {BACKGROUND_REMOVAL_METHOD_LABELS[top_method]}."
    if corner_spread <= 42 and edge_solid_ratio >= 0.48:
        corner_value = analysis.get("corner_rgb", (255, 255, 255))
        return "solid_corner", f"Bốn góc gần cùng một màu ({rgb_to_hex(tuple(corner_value))}), chọn nền trơn."
    if top_edge >= 0.22:
        return top_method, f"Có dấu hiệu chroma vừa đủ ở viền ({top_edge:.0%}), thử {BACKGROUND_REMOVAL_METHOD_LABELS[top_method]} trước."
    if corner_spread <= 70 and edge_solid_ratio >= 0.34:
        return "solid_corner", "Không thấy chroma rõ, nhưng nền viền/góc khá đồng màu nên dùng tách nền trơn."
    return "solid_corner", "Không nhận diện được chroma rõ; thử tách theo màu nền ở 4 góc."

def _ordered_background_removal_candidates(selected_method: str, analysis: dict[str, Any], preferred: str = "auto") -> list[str]:
    methods: list[str] = []

    def add(method: str) -> None:
        if method not in {"", "existing_alpha"} and method not in methods:
            methods.append(method)

    add(selected_method)
    chroma_methods = [
        (float(analysis.get("edge_green_ratio", 0.0) or 0.0), "green_chroma"),
        (float(analysis.get("edge_blue_ratio", 0.0) or 0.0), "blue_chroma"),
        (float(analysis.get("edge_magenta_ratio", 0.0) or 0.0), "magenta_chroma"),
    ]
    for ratio, method in sorted(chroma_methods, reverse=True):
        if ratio >= 0.12 or str(preferred or "auto").lower() != "auto":
            add(method)
    add("solid_corner")
    return methods

def _apply_background_removal_method(image: Any, method: str) -> Any:
    if method == "green_chroma":
        return remove_green_screen_background(image.copy())
    if method == "blue_chroma":
        return remove_blue_screen_background(image.copy())
    if method == "magenta_chroma":
        return remove_magenta_screen_background(image.copy())
    if method == "solid_corner":
        return remove_solid_corner_background(image.copy())
    return image.copy()

def _rgba_image_to_png_bytes(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def auto_remove_analyzed_background(image_bytes: bytes, preferred: str = "auto") -> tuple[bytes, dict[str, Any]]:
    before_check = inspect_image_transparency(image_bytes)
    analysis = analyze_background_for_removal(image_bytes, before_check)
    analysis["before_check"] = before_check
    if Image is None or not analysis.get("readable"):
        analysis["after_check"] = before_check
        return image_bytes, analysis

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            source = ImageOps.exif_transpose(opened) if ImageOps is not None else opened
            rgba_image = source.convert(TRANSPARENT_IMAGE_MODE)
    except Exception as ex:
        analysis["reason"] = f"Không đọc được ảnh để tách nền: {ex}"
        analysis["after_check"] = before_check
        return image_bytes, analysis

    selected_method, select_reason = _select_background_removal_method(analysis, preferred)
    analysis["selected_method"] = selected_method
    analysis["selected_method_label"] = BACKGROUND_REMOVAL_METHOD_LABELS.get(selected_method, selected_method)
    analysis["reason"] = select_reason

    if selected_method == "existing_alpha":
        output_bytes = _rgba_image_to_png_bytes(rgba_image)
        after_check = inspect_image_transparency(output_bytes)
        analysis["method"] = selected_method
        analysis["method_label"] = BACKGROUND_REMOVAL_METHOD_LABELS[selected_method]
        analysis["after_check"] = after_check
        analysis["attempts"] = []
        return output_bytes, analysis

    original_bytes = _rgba_image_to_png_bytes(rgba_image)
    best_bytes = original_bytes
    best_method = "fallback"
    best_check = inspect_image_transparency(original_bytes)
    best_score = float(best_check.get("transparent_ratio", 0.0) or 0.0) + float(best_check.get("edge_transparent_ratio", 0.0) or 0.0) * 0.75
    attempts: list[dict[str, Any]] = []

    for method in _ordered_background_removal_candidates(selected_method, analysis, preferred):
        processed_image = _apply_background_removal_method(rgba_image, method)
        processed_bytes = _rgba_image_to_png_bytes(processed_image)
        check = inspect_image_transparency(processed_bytes)
        transparent_ratio = float(check.get("transparent_ratio", 0.0) or 0.0)
        edge_transparent_ratio = float(check.get("edge_transparent_ratio", 0.0) or 0.0)
        score = transparent_ratio + edge_transparent_ratio * 0.75
        if check.get("ok"):
            score += 2.0
        attempts.append(
            {
                "method": method,
                "label": BACKGROUND_REMOVAL_METHOD_LABELS.get(method, method),
                "transparent_ratio": round(transparent_ratio, 4),
                "edge_transparent_ratio": round(edge_transparent_ratio, 4),
                "ok": bool(check.get("ok")),
            }
        )
        if score > best_score:
            best_score = score
            best_bytes = processed_bytes
            best_method = method
            best_check = check
        if check.get("ok") and method == selected_method:
            break

    analysis["attempts"] = attempts
    analysis["method"] = best_method
    analysis["method_label"] = BACKGROUND_REMOVAL_METHOD_LABELS.get(best_method, best_method)
    analysis["after_check"] = best_check
    if best_method != selected_method:
        analysis["reason"] = f"{select_reason} Kết quả tốt nhất sau thử fallback: {analysis['method_label']}."
    return best_bytes, analysis

def ensure_transparent_png_rgba_bytes(
    image_bytes: bytes,
    remove_green_screen: bool = False,
    remove_blue_screen: bool = False,
) -> bytes:
    if Image is None:
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            source = ImageOps.exif_transpose(opened) if ImageOps is not None else opened
            rgba_image = source.convert(TRANSPARENT_IMAGE_MODE)
        if remove_blue_screen:
            rgba_image = remove_blue_screen_background(rgba_image)
        if remove_green_screen:
            rgba_image = remove_green_screen_background(rgba_image)
        if not rgba_has_transparent_pixels(rgba_image):
            rgba_image = remove_solid_corner_background(rgba_image)
        buffer = io.BytesIO()
        rgba_image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return image_bytes


def normalize_transparent_image_result(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not payload_requests_transparent_background(payload):
        return result
    if result.get("kind") not in {"binary", "b64_json"}:
        return result
    image_bytes = result.get("image_bytes")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        return result
    normalized = dict(result)
    before_check = inspect_image_transparency(image_bytes)
    keep_raw_chroma = payload_requests_chroma_screen_removal(payload)
    normalized_bytes = ensure_transparent_png_rgba_bytes(
        image_bytes,
        remove_green_screen=payload_requests_green_screen_removal(payload),
        remove_blue_screen=payload_requests_blue_screen_removal(payload),
    )
    after_check = inspect_image_transparency(normalized_bytes)
    normalized["image_bytes"] = normalized_bytes
    normalized["content_type"] = "image/png"
    normalized["transparent_requested"] = True
    normalized["transparent_check_before"] = before_check
    normalized["transparent_check"] = after_check
    normalized["transparent_postprocessed"] = bool(before_check.get("readable")) and before_check != after_check
    if keep_raw_chroma:
        normalized["raw_chroma_image_bytes"] = image_bytes
        normalized["raw_chroma_content_type"] = result.get("content_type", "image/png")
    return normalized


def build_raw_chroma_output_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    suffix = path.suffix or ".png"
    return path.with_name("_raw_chroma") / f"{path.stem}_raw_chroma{suffix}"


def save_image(image_bytes: bytes, output_path: str) -> Path:
    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path.resolve()


def append_history(record: dict[str, Any]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_history(limit: int = 300) -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    records = records[-limit:]
    records.reverse()
    return records


def parse_api_keys_pool(raw_text: str, fallback_key: str = "") -> list[str]:
    def _extract(text: str) -> list[str]:
        clean_text = str(text or "").strip()
        if not clean_text:
            return []

        sk_matches = re.findall(r"sk-[A-Za-z0-9_-]+", clean_text)
        if sk_matches:
            return unique_list([item.strip() for item in sk_matches if item.strip()])

        chunks = re.split(r"[\s,;]+", clean_text)
        return unique_list([item.strip() for item in chunks if item.strip()])

    base_keys = _extract(raw_text)
    fallback_keys = _extract(fallback_key)
    return unique_list(fallback_keys + base_keys)


def mask_api_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if len(key) <= 12:
        return key
    return f"{key[:8]}...{key[-4:]}"


def build_key_schedule(total_images: int, api_keys: list[str]) -> list[str]:
    if total_images <= 0:
        return []
    if not api_keys:
        return []
    schedule: list[str] = []
    for idx in range(total_images):
        schedule.append(api_keys[idx % len(api_keys)])
    return schedule


def should_split_batch_requests(mode: str, requested_count: int, key_pool_count: int) -> bool:
    if requested_count <= 1 or key_pool_count <= 0:
        return False
    if mode == MODE_PARALLEL_API:
        return True
    if mode == MODE_AUTO_API:
        return key_pool_count > 1
    return False


def resolve_parallel_workers(mode: str, requested_count: int, key_pool_count: int, max_parallel: int) -> int:
    requested = max(1, int(requested_count))
    configured = max(1, min(int(max_parallel), MAX_PARALLEL_WORKERS))
    workers = min(configured, requested)
    if mode == MODE_AUTO_API:
        workers = min(workers, max(1, int(key_pool_count)))
    return max(1, workers)


def build_batch_error_summary(errors: list[str]) -> tuple[str, str]:
    if not errors:
        return "", ""

    status_counts: dict[int, int] = {}
    lowered_errors = "\n".join(str(item) for item in errors).lower()
    for item in errors:
        status_code = parse_http_status_code(str(item))
        if status_code is None:
            continue
        status_counts[status_code] = status_counts.get(status_code, 0) + 1

    status_note = ""
    if status_counts:
        ranked = sorted(status_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        status_note = " • ".join([f"[{code}] x{count}" for code, count in ranked[:4]])

    if is_codex_entitlement_error(lowered_errors):
        hint = (
            "Tài khoản/provider `cx` phía server thiếu quyền hoặc session hết hạn. "
            "Đăng nhập lại/cập nhật provider ở 9Router, hoặc chọn model khác đang có trong `/v1/models/image`."
        )
    elif is_upstream_headers_timeout_error(lowered_errors):
        hint = (
            "9Router/upstream đang tự ngắt headers timeout khoảng 30s. "
            "Tăng timeout trong app không đủ; cần tăng timeout server 9Router hoặc giảm request còn 1 ảnh, quality low/medium, ít ảnh mẫu hơn."
        )
    elif is_transparent_background_not_supported_error(lowered_errors):
        hint = (
            "Model đang dùng không hỗ trợ `background=transparent` native. "
            "Không nền chuẩn cần dùng OpenAI Images API với `gpt-image-1.5`, `gpt-image-1` hoặc `gpt-image-1-mini`; "
            "`gpt-image-2` hiện không hỗ trợ transparent background."
        )
    elif is_codex_upgrade_required_error(lowered_errors):
        hint = "Model yêu cầu bản Codex mới hơn. Hãy nâng cấp Codex hoặc đổi model sang gpt-5.4-image."
    elif 401 in status_counts:
        hint = "Phát hiện [401]: kiểm tra lại API key trong pool (có thể lẫn key cũ/sai)."
    elif 429 in status_counts:
        hint = "Phát hiện [429]: giảm luồng song song hoặc tăng retry/backoff để tránh rate limit."
    elif any(code in status_counts for code in [500, 502, 503, 504]):
        hint = "Phát hiện lỗi server tạm thời (5xx): giữ retry 1-2 lần và backoff >= 1.2s."
    elif "minimum pixel budget" in lowered_errors or "invalid size" in lowered_errors:
        hint = "Kích thước ảnh có thể không hợp lệ với model hiện tại. Thử size >= 1024x1024 hoặc bỏ size."
    elif "timeout" in lowered_errors or "timed out" in lowered_errors:
        hint = "Đã có timeout: tăng Timeout request lên 360-480s, retry 1-2 lần."
    else:
        hint = "Bật Debug mode để xem đầy đủ payload/phản hồi, rồi thử lại với 1 ảnh để khoanh vùng lỗi."

    return status_note, hint


def append_lora_history(record: dict[str, Any]) -> None:
    LORA_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LORA_HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_lora_history(limit: int = 300) -> list[dict[str, Any]]:
    if not LORA_HISTORY_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in LORA_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
            if isinstance(loaded, dict):
                records.append(loaded)
        except Exception:
            continue
    records = records[-limit:]
    records.reverse()
    return records


def unique_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def suggest_top_model(loaded_models: list[str], current_model: str = "") -> str:
    image_models = [item for item in loaded_models if str(item).strip()]
    current = str(current_model or "").strip()
    pool = unique_list(([current] if current else []) + image_models + [DEFAULT_MODEL])
    for preferred in MODEL_TOP_PRIORITY:
        preferred_suffix = preferred.strip().lower().split("/", 1)[-1]
        if not preferred_suffix:
            continue
        for candidate in pool:
            candidate_suffix = candidate.strip().lower().split("/", 1)[-1]
            if candidate_suffix == preferred_suffix:
                return candidate
    return pool[0] if pool else DEFAULT_MODEL


def get_quick_model_choices() -> list[str]:
    current = str(st.session_state.get("manual_model", DEFAULT_MODEL)).strip()
    cached = [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)]
    current_safe = [current] if current and current in cached else []
    choices = unique_list([suggest_top_model(cached, current)] + MODEL_TOP_PRIORITY + MODEL_RECOMMENDED + cached + current_safe)
    return choices[:10]


def load_models_into_state(base_url: str, api_key: str, enforce_top_model: bool = False) -> tuple[bool, str]:
    st.session_state.model_nonce = int(st.session_state.get("model_nonce", 0)) + 1
    try:
        discovered = discover_models(base_url, api_key, st.session_state.model_nonce)
    except Exception as ex:
        return False, str(ex)

    st.session_state.models = unique_list(discovered)
    top_model = suggest_top_model(st.session_state.models, str(st.session_state.get("manual_model", "")))
    current_model = str(st.session_state.get("manual_model", "")).strip()
    if enforce_top_model or not current_model or (st.session_state.models and current_model not in st.session_state.models):
        st.session_state.manual_model = top_model
    return True, f"Đã nạp {len(st.session_state.models)} model"


def apply_everyday_studio_defaults() -> None:
    st.session_state.manual_model = suggest_top_model(
        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
        str(st.session_state.get("manual_model", "")),
    )
    st.session_state.quick_style = "Không áp phong cách"
    st.session_state.quick_quality_profile = "Cân bằng"
    st.session_state.quick_aspect_ratio = "1:1"
    st.session_state.quick_size_preset = "Vuông 1024"
    st.session_state.quick_subject = ""
    st.session_state.studio_count = 1
    st.session_state.studio_response_format = "binary"


def parse_json_object(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("JSON phải là object")
    return loaded


def safe_filename(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]", "_", name or "image")
    clean = clean.strip("._")
    return clean or "image"


def guess_mime_type(filename: str, provided: str = "") -> str:
    if provided:
        return provided
    guessed, _ = mimetypes.guess_type(filename)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"


def image_bytes_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


# Soft cap on encoded reference image size. Above this we attempt to re-encode
# via Pillow (downscale long-side + JPEG quality reduction) so the API request
# stays under typical 4MB JSON body limits even with multiple ref images.
_REF_IMAGE_MAX_BYTES = 2_300_000  # ~2.2 MB raw before base64 inflation
_REF_IMAGE_MAX_LONG_SIDE = 1536


def compress_image_for_ref(image_bytes: bytes, mime_type: str = "") -> tuple[bytes, str]:
    """Return (bytes, mime) suitable for embedding as a reference image.

    If Pillow is missing or the image is already small enough, returns the
    original bytes unchanged. Otherwise re-encodes as JPEG (or PNG when alpha
    is needed) capped at _REF_IMAGE_MAX_LONG_SIDE pixels on the long side and
    iteratively reduces quality until under _REF_IMAGE_MAX_BYTES.
    """
    if not image_bytes:
        return image_bytes, mime_type or "image/png"
    mime_lower = (mime_type or "").lower()
    if Image is None:
        return image_bytes, mime_type or "image/png"
    if len(image_bytes) <= _REF_IMAGE_MAX_BYTES and "gif" not in mime_lower:
        # Small enough already.
        return image_bytes, mime_type or "image/png"
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            has_alpha = img.mode in {"RGBA", "LA"} or (
                img.mode == "P" and "transparency" in img.info
            )
            target = img.convert("RGBA" if has_alpha else "RGB")
            long_side = max(target.size)
            if long_side > _REF_IMAGE_MAX_LONG_SIDE:
                scale = _REF_IMAGE_MAX_LONG_SIDE / long_side
                new_size = (int(target.size[0] * scale), int(target.size[1] * scale))
                target = target.resize(new_size, Image.LANCZOS)
            if has_alpha:
                buffer = io.BytesIO()
                target.save(buffer, format="PNG", optimize=True)
                return buffer.getvalue(), "image/png"
            for quality in (88, 80, 72, 64, 55):
                buffer = io.BytesIO()
                target.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                data = buffer.getvalue()
                if len(data) <= _REF_IMAGE_MAX_BYTES:
                    return data, "image/jpeg"
            buffer = io.BytesIO()
            target.save(buffer, format="JPEG", quality=50, optimize=True, progressive=True)
            return buffer.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, mime_type or "image/png"


def safe_image_to_data_url(image_bytes: bytes, mime_type: str = "") -> str:
    """Compress + base64-encode an image for use as an API reference."""
    data, mime = compress_image_for_ref(image_bytes, mime_type)
    return image_bytes_to_data_url(data, mime or "image/png")


def decode_data_image_ref(ref: str) -> bytes | None:
    text = str(ref or "").strip()
    if not text.lower().startswith("data:image/"):
        return None
    if "," not in text:
        return None
    meta, encoded = text.split(",", 1)
    if ";base64" not in meta.lower():
        return None
    try:
        return base64.b64decode(encoded, validate=False)
    except Exception:
        return None


def normalize_local_folder_input(raw_path: str) -> Path:
    clean = str(raw_path or "").strip().strip("\"").strip("'")
    if not clean:
        raise ValueError("Đường dẫn thư mục đang trống.")

    if clean.lower().startswith("file://"):
        parsed = parse.urlsplit(clean)
        decoded_path = parse.unquote(parsed.path or "")
        if parsed.netloc:
            decoded_path = f"//{parsed.netloc}{decoded_path}"
        if re.match(r"^/[a-zA-Z]:", decoded_path):
            decoded_path = decoded_path[1:]
        clean = decoded_path or parse.unquote(clean[7:])

    folder = Path(clean).expanduser()
    try:
        return folder.resolve(strict=False)
    except Exception:
        return folder


def collect_images_from_local_folder(folder_input: str, recursive: bool = True, max_images: int = LORA_MAX_IMAGES) -> tuple[list[dict[str, Any]], str]:
    raw = str(folder_input or "").strip()
    if not raw:
        return [], ""

    try:
        folder = normalize_local_folder_input(raw)
    except Exception as ex:
        return [], str(ex)

    if not folder.exists():
        return [], f"Không tìm thấy thư mục: {folder}"
    if not folder.is_dir():
        return [], f"Đường dẫn không phải thư mục: {folder}"

    path_iter = folder.rglob("*") if recursive else folder.glob("*")
    image_paths: list[Path] = []
    for path in path_iter:
        if not path.is_file():
            continue
        if path.suffix.lower() not in LORA_DATASET_IMAGE_EXTS:
            continue
        image_paths.append(path)

    image_paths = sorted(image_paths, key=lambda item: str(item).lower())
    if not image_paths:
        return [], "Không tìm thấy file ảnh hợp lệ trong thư mục."

    if len(image_paths) > max_images:
        image_paths = image_paths[:max_images]

    entries: list[dict[str, Any]] = []
    for image_path in image_paths:
        try:
            image_bytes = image_path.read_bytes()
        except Exception:
            continue
        if not image_bytes:
            continue
        mime_type = guess_mime_type(image_path.name)
        entries.append(
            {
                "filename": image_path.name,
                "source_path": str(image_path),
                "mime_type": mime_type,
                "image_bytes": image_bytes,
            }
        )

    if not entries:
        return [], "Đã quét thư mục nhưng không đọc được ảnh nào."

    return entries, ""


def parse_pasted_image_refs(raw_text: str) -> list[str]:
    refs: list[str] = []
    if not raw_text.strip():
        return refs

    direct_refs = re.findall(r"https?://\S+|data:image/\S+", raw_text, flags=re.IGNORECASE)
    refs.extend([item.strip() for item in direct_refs if item.strip()])

    for raw_line in re.split(r"[\r\n]+", raw_text):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("http://", "https://", "data:image/")):
            refs.append(line)
            continue
        normalized = line.replace(" ", "")
        try:
            decoded = base64.b64decode(normalized, validate=True)
            refs.append(safe_image_to_data_url(decoded, "image/png"))
        except (binascii.Error, ValueError):
            continue
    return unique_list(refs)


def grab_clipboard_image_data_url() -> tuple[str | None, str]:
    if ImageGrab is None:
        return None, "Không có PIL.ImageGrab để đọc clipboard hệ thống."
    try:
        clip_obj = ImageGrab.grabclipboard()
    except Exception as ex:
        return None, f"Không đọc được clipboard: {ex}"

    if clip_obj is None:
        return None, "Clipboard hiện chưa có ảnh."

    if hasattr(clip_obj, "save"):
        try:
            buffer = io.BytesIO()
            clip_obj.save(buffer, format="PNG")
            return safe_image_to_data_url(buffer.getvalue(), "image/png"), ""
        except Exception as ex:
            return None, f"Không chuyển đổi ảnh clipboard được: {ex}"

    if isinstance(clip_obj, list):
        for raw_path in clip_obj:
            try:
                file_path = Path(str(raw_path))
                if not file_path.exists() or not file_path.is_file():
                    continue
                ext = file_path.suffix.lower()
                if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                    continue
                data = file_path.read_bytes()
                mime = guess_mime_type(file_path.name)
                return safe_image_to_data_url(data, mime), ""
            except Exception:
                continue

    return None, "Clipboard không phải ảnh hợp lệ."


def save_uploaded_input_copy(content: bytes, original_name: str, section_key: str, index: int) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(original_name).suffix or ".png"
    filename = f"{timestamp}_{section_key}_{index}_{safe_filename(Path(original_name).stem)}{ext}"
    path = Path("outputs") / "inputs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path.resolve())


def collect_reference_images(section_key: str, allow_multiple: bool, compact_mode: bool) -> tuple[list[str], list[bytes], list[str]]:
    st.markdown("**Nguồn ảnh tham chiếu**")
    upload_tab, paste_tab = st.tabs(["Tải ảnh", "Dán nhanh"])
    paste_height = 78 if compact_mode else 96
    preview_cols_count = 4 if compact_mode else 3

    uploaded: Any
    with upload_tab:
        uploaded = st.file_uploader(
            "Tải ảnh (PNG/JPG/WEBP)",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=allow_multiple,
            key=f"{section_key}_uploader",
        )

    with paste_tab:
        pasted = st.text_area(
            "Dán URL ảnh hoặc base64",
            key=f"{section_key}_pasted",
            height=paste_height,
            placeholder="Mỗi dòng 1 ảnh",
        )

    save_inputs = False
    if True:
        with st.expander("Tùy chọn ảnh tham chiếu", expanded=False):
            save_inputs = st.checkbox(
                "Lưu bản sao ảnh tải lên vào outputs/inputs",
                value=False,
                key=f"{section_key}_save_input_copy",
            )

    uploaded_files: list[Any]
    if allow_multiple:
        uploaded_files = uploaded or []
    else:
        uploaded_files = [uploaded] if uploaded is not None else []

    refs: list[str] = []
    preview_bytes: list[bytes] = []
    saved_paths: list[str] = []

    for idx, up in enumerate(uploaded_files, start=1):
        content = up.getvalue()
        mime_type = guess_mime_type(getattr(up, "name", "image.png"), getattr(up, "type", ""))
        refs.append(safe_image_to_data_url(content, mime_type))
        preview_bytes.append(content)
        if save_inputs:
            saved_paths.append(save_uploaded_input_copy(content, getattr(up, "name", f"img_{idx}.png"), section_key, idx))

    refs.extend(parse_pasted_image_refs(pasted or ""))
    refs = unique_list(refs)

    if preview_bytes:
        with st.expander(f"Xem trước {len(preview_bytes)} ảnh nguồn", expanded=False):
            cols = st.columns(min(preview_cols_count, len(preview_bytes)))
            for idx, img_bytes in enumerate(preview_bytes):
                with cols[idx % len(cols)]:
                    st.image(img_bytes, use_container_width=True)

    if saved_paths:
        with st.expander("Đường dẫn ảnh đã lưu", expanded=False):
            for path in saved_paths:
                st.code(path)

    if refs and len(preview_bytes) == 0:
        st.caption(f"Đã nạp {len(refs)} nguồn ảnh từ dán URL/base64")

    return refs, preview_bytes, saved_paths


def extract_job_id(response: dict[str, Any]) -> str:
    direct_keys = ["job_id", "id", "task_id", "train_id", "run_id"]
    for key in direct_keys:
        value = response.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    data_node = response.get("data")
    if isinstance(data_node, dict):
        for key in direct_keys:
            value = data_node.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def apply_lora_training_preset(preset_name: str) -> None:
    preset = LORA_TRAINING_PRESETS.get(preset_name)
    if not preset:
        return
    st.session_state.lora_steps = int(preset["steps"])
    st.session_state.lora_epochs = int(preset["epochs"])
    st.session_state.lora_batch_size = int(preset["batch_size"])
    st.session_state.lora_learning_rate = float(preset["learning_rate"])
    st.session_state.lora_network_dim = int(preset["network_dim"])
    st.session_state.lora_network_alpha = int(preset["network_alpha"])
    st.session_state.lora_resolution = int(preset["resolution"])
    st.session_state.lora_caption_dropout = float(preset["caption_dropout"])


def apply_lora_workflow_profile(profile_name: str, keep_manual_fields: bool = True) -> None:
    profile = LORA_WORKFLOW_PROFILES.get(profile_name)
    if not profile:
        return

    st.session_state.lora_type = str(profile.get("lora_type", st.session_state.get("lora_type", "general")))
    training_preset = str(profile.get("training_preset", st.session_state.get("lora_training_preset", "Nhanh thử")))
    if training_preset in LORA_TRAINING_PRESETS:
        st.session_state.lora_training_preset = training_preset
        apply_lora_training_preset(training_preset)

    trigger_now = str(st.session_state.get("lora_trigger_word", "")).strip()
    name_now = str(st.session_state.get("lora_name", "lora_model")).strip() or "lora_model"
    name_stub = safe_filename(name_now).lower()[:18]
    trigger_prefix = safe_filename(str(profile.get("trigger_prefix", "token"))).lower() or "token"
    auto_trigger = f"{trigger_prefix}_{name_stub}"

    if (not trigger_now) or (not keep_manual_fields):
        st.session_state.lora_trigger_word = auto_trigger

    caption_prefix = str(profile.get("caption_prefix", "")).strip()
    caption_suffix = str(profile.get("caption_suffix", "")).strip()

    if (not str(st.session_state.get("lora_caption_prefix", "")).strip()) or (not keep_manual_fields):
        st.session_state.lora_caption_prefix = caption_prefix
    if (not str(st.session_state.get("lora_caption_suffix", "")).strip()) or (not keep_manual_fields):
        st.session_state.lora_caption_suffix = caption_suffix


def export_lora_dataset_bundle(dataset_name: str, entries: list[dict[str, Any]], train_payload_preview: dict[str, Any]) -> Path:
    slug = safe_filename(dataset_name or "lora_dataset")
    bundle_dir = LORA_DATASET_ROOT / date_slug() / f"{timestamp_slug()}_{slug}"
    image_dir = bundle_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    metadata_records: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        original_name = str(entry.get("filename", f"img_{idx}.png"))
        content = entry.get("image_bytes", b"")
        if not isinstance(content, bytes) or not content:
            continue

        stem = safe_filename(Path(original_name).stem)
        ext = Path(original_name).suffix or infer_ext(str(entry.get("mime_type", "")), ".png")
        if not ext.startswith("."):
            ext = f".{ext}"

        saved_name = f"{idx:03d}_{stem}{ext}"
        saved_path = image_dir / saved_name
        saved_path.write_bytes(content)

        caption = str(entry.get("caption", "")).strip()
        if caption:
            (image_dir / f"{Path(saved_name).stem}.txt").write_text(caption, encoding="utf-8")

        metadata_records.append(
            {
                "index": idx,
                "file": str(saved_path.relative_to(bundle_dir).as_posix()),
                "caption": caption,
                "original_name": original_name,
            }
        )

    (bundle_dir / "metadata.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in metadata_records),
        encoding="utf-8",
    )

    preview_payload = dict(train_payload_preview)
    preview_payload.pop("dataset", None)
    manifest = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "dataset_name": dataset_name,
        "image_count": len(metadata_records),
        "train_payload_preview": preview_payload,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle_dir.resolve()


def run_payload_generation(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    output_file: str,
    workflow_name: str,
    show_inline_preview: bool = True,
) -> None:
    st.session_state.last_payload = payload
    if True:
        with st.expander("Payload sẽ gửi", expanded=False):
            st.json(payload)

    prompt = str(payload.get("prompt", ""))
    model = str(payload.get("model", ""))
    requested_count = max(1, int(payload.get("n", 1)))
    mode = str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE))
    key_pool_raw = str(st.session_state.get("api_keys_pool_text", ""))
    key_pool = parse_api_keys_pool(key_pool_raw, api_key)
    request_timeout = resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS))
    retry_count = resolve_image_retry_count(st.session_state.get("image_retry_count", DEFAULT_IMAGE_RETRY_COUNT))
    retry_backoff = resolve_image_retry_backoff_seconds(
        st.session_state.get("image_retry_backoff", DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS)
    )

    use_multi_api = should_split_batch_requests(
        mode=mode,
        requested_count=requested_count,
        key_pool_count=len(key_pool),
    )
    if not use_multi_api:
        with st.spinner("Đang gọi 9Router..."):
            try:
                result = generate_image_with_retry(
                    base_url=base_url,
                    api_key=api_key,
                    payload=payload,
                    response_format=response_format,
                    timeout_seconds=request_timeout,
                    retry_count=retry_count,
                    retry_backoff_seconds=retry_backoff,
                    task_label=workflow_name,
                )
            except Exception as ex:
                st.error(str(ex))
                return

        dated_output_file = build_daily_output_path(output_file, workflow_name)
        render_generate_result(
            result,
            model=model,
            prompt=f"[{workflow_name}] {prompt}",
            response_format=response_format,
            output_file=dated_output_file,
            show_inline_preview=show_inline_preview,
        )
        return

    schedule = build_key_schedule(requested_count, key_pool)
    max_parallel = int(st.session_state.get("multi_api_max_parallel", len(key_pool) or 1))
    max_workers = resolve_parallel_workers(
        mode=mode,
        requested_count=len(schedule),
        key_pool_count=len(key_pool),
        max_parallel=max_parallel,
    )
    key_summary: dict[str, int] = {}
    for key in schedule:
        key_summary[key] = key_summary.get(key, 0) + 1

    mode_note = "auto" if mode == MODE_AUTO_API else "parallel"
    st.info(
        f"Đang chia {requested_count} ảnh qua {len(key_pool)} API • mode {mode_note} • chạy song song {max_workers} luồng."
    )
    if True:
        st.caption(
            "Phân bổ key: "
            + " • ".join([f"{mask_api_key(k)}: {v}" for k, v in key_summary.items()])
        )
        st.caption(
            f"Timeout/request: {request_timeout}s • retry: {retry_count} • backoff cơ bản: {retry_backoff:.1f}s"
        )

    base_payload = dict(payload)
    base_payload["n"] = 1
    progress = st.progress(0.0)
    success_count = 0
    fail_count = 0
    errors: list[str] = []

    base_output_path = Path(output_file)
    base_ext = base_output_path.suffix or ".png"
    base_stem = base_output_path.stem or "out"

    # Live grid: tạo placeholder ngay, mỗi ảnh xong là cập nhật vào ô của nó.
    # Luôn hiện trong nhánh song song để người dùng thấy ảnh ngay khi xong.
    st.markdown(f"##### Kết quả live ({workflow_name})")
    live_grid_cols = min(4, max(1, requested_count))
    live_columns = st.columns(live_grid_cols)
    live_placeholders: dict[int, Any] = {}
    for idx in range(1, requested_count + 1):
        with live_columns[(idx - 1) % live_grid_cols]:
            live_placeholders[idx] = st.empty()
            with live_placeholders[idx].container():
                st.markdown(
                    f"<div class='panel-card' style='min-height:180px;display:grid;"
                    f"place-items:center;text-align:center;opacity:0.7;'>"
                    f"<div>⏳<br><small>Ảnh #{idx} đang vẽ…</small></div></div>",
                    unsafe_allow_html=True,
                )

    def _render_live_tile(image_idx: int, result_dict: dict[str, Any], saved_path_str: str) -> None:
        placeholder = live_placeholders.get(image_idx)
        if placeholder is None:
            return
        kind = result_dict.get("kind")
        with placeholder.container():
            try:
                if kind in {"binary", "b64_json"}:
                    img_bytes = result_dict.get("image_bytes", b"")
                    if isinstance(img_bytes, bytes) and img_bytes:
                        st.image(img_bytes, use_container_width=True)
                        download_key = f"live_dl_{workflow_name}_{image_idx}_{timestamp_slug()}"
                        st.download_button(
                            f"⬇ Tải ảnh #{image_idx}",
                            data=img_bytes,
                            file_name=Path(saved_path_str).name if saved_path_str else f"img_{image_idx}.png",
                            mime="image/png",
                            key=download_key,
                            use_container_width=True,
                        )
                    elif saved_path_str and Path(saved_path_str).exists():
                        st.image(saved_path_str, use_container_width=True)
                elif kind == "url":
                    url_val = str(result_dict.get("url", "")).strip()
                    if url_val:
                        st.image(url_val, use_container_width=True)
                        st.caption(url_val)
                else:
                    st.warning(f"Ảnh #{image_idx}: phản hồi không có dữ liệu ảnh.")
                st.caption(f"#{image_idx}")
            except Exception as render_ex:
                st.warning(f"Ảnh #{image_idx}: không thể hiển thị ({render_ex}).")

    def _render_live_error(image_idx: int, key_used: str, err_msg: str) -> None:
        placeholder = live_placeholders.get(image_idx)
        if placeholder is None:
            return
        with placeholder.container():
            st.error(f"Ảnh #{image_idx} lỗi")
            st.caption(f"{mask_api_key(key_used)}")
            with st.expander("Chi tiết", expanded=False):
                st.code(err_msg or "(không có chi tiết)")

    def _worker(image_idx: int, key_used: str) -> tuple[int, str, dict[str, Any] | None, str | None]:
        task_payload = dict(base_payload)
        if "seed" in task_payload:
            with suppress(Exception):
                task_payload["seed"] = int(task_payload["seed"]) + image_idx
        try:
            generated = generate_image_with_retry(
                base_url=base_url,
                api_key=key_used,
                payload=task_payload,
                response_format=response_format,
                timeout_seconds=request_timeout,
                retry_count=retry_count,
                retry_backoff_seconds=retry_backoff,
                task_label=f"{workflow_name}#{image_idx}",
            )
            return image_idx, key_used, generated, None
        except Exception as ex:
            return image_idx, key_used, None, str(ex)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_worker, idx, api_key_item)
            for idx, api_key_item in enumerate(schedule, start=1)
        ]
        done_total = 0
        for future in concurrent.futures.as_completed(futures):
            done_total += 1
            image_idx, key_used, result, err = future.result()
            if err is not None or result is None:
                fail_count += 1
                errors.append(f"Ảnh #{image_idx} ({mask_api_key(key_used)}): {err}")
                _render_live_error(image_idx, key_used, err or "")
                progress.progress(done_total / len(futures))
                continue

            success_count += 1
            output_i = str(base_output_path.with_name(f"{base_stem}_{image_idx}{base_ext}"))
            dated_output_file = build_daily_output_path(output_i, f"{workflow_name}_{image_idx}")
            render_generate_result(
                result,
                model=model,
                prompt=f"[{workflow_name} #{image_idx}] {prompt}",
                response_format=response_format,
                output_file=dated_output_file,
                show_inline_preview=False,
                download_key_suffix=f"{workflow_name}_{image_idx}_{timestamp_slug()}",
            )
            # Tìm path đã lưu từ recent_outputs (mục mới nhất khớp prompt).
            saved_path_for_tile = ""
            try:
                for entry in st.session_state.get("recent_outputs", []):
                    if isinstance(entry, dict) and str(entry.get("prompt", "")).startswith(
                        f"[{workflow_name} #{image_idx}] "
                    ):
                        saved_path_for_tile = str(entry.get("local_path", ""))
                        break
            except Exception:
                saved_path_for_tile = ""
            _render_live_tile(image_idx, result, saved_path_for_tile)
            progress.progress(done_total / len(futures))

    if success_count > 0:
        st.success(f"Hoàn tất batch: thành công {success_count}/{requested_count} ảnh.")
    if fail_count > 0:
        st.warning(f"Có {fail_count} ảnh lỗi trong batch.")
        status_note, hint = build_batch_error_summary(errors)
        if status_note:
            st.caption(f"Thống kê mã lỗi: {status_note}")
        if hint:
            st.info(hint)

        # Hành động cứu nhanh khi có lỗi timeout/rate limit.
        joined_errors = "\n".join(str(item) for item in errors).lower()
        timeout_present = ("timeout" in joined_errors) or ("timed out" in joined_errors)
        rate_limit_present = ("rate limit" in joined_errors) or ("429" in joined_errors)
        if timeout_present or rate_limit_present:
            st.markdown("**Đề xuất khắc phục nhanh:**")
            cur_timeout = int(st.session_state.get("api_request_timeout", DEFAULT_API_POST_TIMEOUT_SECONDS))
            cur_count = int(st.session_state.get("studio_count", 1))
            cur_workers = int(st.session_state.get("multi_api_max_parallel", 1))
            colf1, colf2, colf3 = st.columns(3)
            with colf1:
                if timeout_present and st.button(
                    f"⏱ Tăng timeout +120s (hiện {cur_timeout}s)",
                    key=f"btn_bump_timeout_{timestamp_slug()}_{success_count}_{fail_count}",
                    use_container_width=True,
                ):
                    st.session_state.api_request_timeout = min(MAX_API_TIMEOUT_SECONDS, cur_timeout + 120)
                    st.toast(f"Timeout đã tăng lên {st.session_state.api_request_timeout}s.")
                    st.rerun()
            with colf2:
                new_count = max(1, cur_count // 2) if cur_count > 1 else 1
                if cur_count > 1 and st.button(
                    f"🪄 Giảm số ảnh xuống {new_count}",
                    key=f"btn_reduce_count_{timestamp_slug()}_{success_count}_{fail_count}",
                    use_container_width=True,
                ):
                    st.session_state.studio_count = new_count
                    st.session_state.gen_count = new_count
                    st.toast(f"Đã chỉnh số ảnh / lượt = {new_count}.")
                    st.rerun()
            with colf3:
                new_workers = max(1, cur_workers // 2) if cur_workers > 1 else 1
                if rate_limit_present and cur_workers > 1 and st.button(
                    f"🐢 Giảm luồng song song xuống {new_workers}",
                    key=f"btn_reduce_workers_{timestamp_slug()}_{success_count}_{fail_count}",
                    use_container_width=True,
                ):
                    st.session_state.multi_api_max_parallel = new_workers
                    st.toast(f"Đã chỉnh luồng song song = {new_workers}.")
                    st.rerun()

        with st.expander("Chi tiết lỗi batch", expanded=False):
            for item in errors[:20]:
                st.code(item)


def build_translate_prompt(src_lang: str, target_lang: str, note: str) -> str:
    base = (
        f"Hãy thay toàn bộ chữ {src_lang} trong ảnh sang {target_lang}. "
        "Giữ nguyên bố cục, font, màu, logo, phong cách; chỉ thay nội dung chữ."
    )
    if note.strip():
        base += f" Ghi chú thêm: {note.strip()}"
    return base


def build_storyboard_prompts(topic: str, character: str, style: str, panels: int) -> list[str]:
    prompts: list[str] = []
    for idx in range(panels):
        panel_no = idx + 1
        prompts.append(
            f"Khung truyện {panel_no}/{panels}: chủ đề '{topic}', nhân vật chính '{character}', "
            f"phong cách {style}, bố cục rõ ràng, mạch truyện liền mạch, chất lượng cao"
        )
    return prompts


def new_story_item_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%H%M%S%f')}_{random.randint(100, 999)}"


def make_default_story_character(index: int) -> dict[str, Any]:
    return {
        "id": new_story_item_id("char"),
        "name": f"Nhân vật {index}",
        "appearance": "",
        "refs": [],
    }


def make_default_story_panel(index: int) -> dict[str, Any]:
    return {
        "id": new_story_item_id("panel"),
        "title": f"Trang/Khung {index}",
        "scene_prompt": "",
        "dialogue_1": "",
        "dialogue_2": "",
        "narration": "",
        "character_ids": [],
    }


def ensure_story_builder_state() -> None:
    if "story_characters_state" not in st.session_state:
        st.session_state.story_characters_state = [
            make_default_story_character(1),
            make_default_story_character(2),
        ]
    if "story_panels_state" not in st.session_state:
        st.session_state.story_panels_state = [make_default_story_panel(i) for i in range(1, 5)]
    if "story_generated_panels" not in st.session_state:
        st.session_state.story_generated_panels = []
    if "story_keep_characters_consistent" not in st.session_state:
        st.session_state.story_keep_characters_consistent = True
    if "story_export_cols" not in st.session_state:
        st.session_state.story_export_cols = 2
    if "story_export_rows" not in st.session_state:
        st.session_state.story_export_rows = 2
    if "story_refs_per_character" not in st.session_state:
        st.session_state.story_refs_per_character = 2


def build_story_panel_prompt(
    panel_index: int,
    total_panels: int,
    panel: dict[str, Any],
    panel_characters: list[dict[str, Any]],
    style_name: str,
    story_beat: str,
    keep_consistent: bool,
) -> str:
    style_directive = COMIC_STYLE_PROMPTS.get(style_name, style_name)
    character_lines: list[str] = []
    for idx, char in enumerate(panel_characters, start=1):
        char_name = str(char.get("name", f"Nhân vật {idx}")).strip() or f"Nhân vật {idx}"
        appearance = str(char.get("appearance", "")).strip()
        line = f"- Nhân vật {idx} ({char_name})"
        if appearance:
            line += f": {appearance}"
        character_lines.append(line)

    dialogue_1 = str(panel.get("dialogue_1", "")).strip()
    dialogue_2 = str(panel.get("dialogue_2", "")).strip()
    narration = str(panel.get("narration", "")).strip()

    dialogue_lines: list[str] = []
    if dialogue_1:
        dialogue_lines.append(f"- Bong bóng thoại nhân vật 1: \"{dialogue_1}\"")
    if dialogue_2:
        dialogue_lines.append(f"- Bong bóng thoại nhân vật 2: \"{dialogue_2}\"")
    if narration:
        dialogue_lines.append(f"- Chữ dẫn truyện: \"{narration}\"")

    consistency_note = (
        "Giữ nhất quán khuôn mặt, tóc, trang phục, màu chủ đạo và phong cách các nhân vật giữa các trang."
        if keep_consistent
        else "Cho phép biến tấu nhẹ về biểu cảm và góc máy giữa các trang."
    )

    scene_prompt = str(panel.get("scene_prompt", "")).strip()
    panel_title = str(panel.get("title", f"Trang/Khung {panel_index}")).strip() or f"Trang/Khung {panel_index}"

    prompt_parts = [
        f"Bạn đang vẽ truyện tranh nhiều khung phong cách {style_name}.",
        f"Style visual: {style_directive}.",
        f"Nhịp truyện: {story_beat}.",
        consistency_note,
        f"Khung hiện tại: {panel_index}/{total_panels} - {panel_title}.",
    ]

    if character_lines:
        prompt_parts.append("Thông tin nhân vật xuất hiện:")
        prompt_parts.extend(character_lines)

    if scene_prompt:
        prompt_parts.append(f"Mô tả khung: {scene_prompt}")

    if dialogue_lines:
        prompt_parts.append("Nội dung thoại/chữ:")
        prompt_parts.extend(dialogue_lines)

    prompt_parts.append(
        "Bố cục rõ ràng, có khung truyện và bong bóng thoại dễ đọc, tránh lỗi tay/chân, giữ độ sắc nét cao."
    )

    return "\n".join(prompt_parts)


def compose_story_pages(panel_images: list[bytes], cols: int, rows: int, gutter: int = 24) -> list[Any]:
    if Image is None or ImageOps is None:
        raise RuntimeError("Thiếu Pillow để ghép trang PNG/PDF.")

    parsed_images: list[Any] = []
    for raw in panel_images:
        if not isinstance(raw, bytes) or not raw:
            continue
        try:
            parsed_images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
        except Exception:
            continue

    if not parsed_images:
        return []

    cols = max(1, int(cols))
    rows = max(1, int(rows))
    per_page = max(1, cols * rows)
    cell_w = max(img.width for img in parsed_images)
    cell_h = max(img.height for img in parsed_images)
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS

    pages: list[Any] = []
    for start in range(0, len(parsed_images), per_page):
        chunk = parsed_images[start : start + per_page]
        page_w = cols * cell_w + (cols + 1) * gutter
        page_h = rows * cell_h + (rows + 1) * gutter
        canvas = Image.new("RGB", (page_w, page_h), color="white")
        draw = ImageDraw.Draw(canvas) if ImageDraw is not None else None

        for idx, img in enumerate(chunk):
            r = idx // cols
            c = idx % cols
            x = gutter + c * (cell_w + gutter)
            y = gutter + r * (cell_h + gutter)
            fitted = ImageOps.fit(img, (cell_w, cell_h), method=resample)
            canvas.paste(fitted, (x, y))
            if draw is not None:
                badge = f"{start + idx + 1}"
                draw.rectangle((x + 8, y + 8, x + 56, y + 40), fill=(0, 0, 0))
                draw.text((x + 22, y + 14), badge, fill=(255, 255, 255))

        pages.append(canvas)

    return pages


def encode_story_pages_png(pages: list[Any], page_gap: int = 28) -> bytes:
    if Image is None:
        raise RuntimeError("Thiếu Pillow để xuất PNG.")
    if not pages:
        return b""

    if len(pages) == 1:
        buffer = io.BytesIO()
        pages[0].save(buffer, format="PNG")
        return buffer.getvalue()

    total_w = max(page.width for page in pages)
    total_h = sum(page.height for page in pages) + page_gap * (len(pages) - 1)
    merged = Image.new("RGB", (total_w, total_h), color="white")
    offset_y = 0
    for page in pages:
        x = max(0, (total_w - page.width) // 2)
        merged.paste(page, (x, offset_y))
        offset_y += page.height + page_gap

    buffer = io.BytesIO()
    merged.save(buffer, format="PNG")
    return buffer.getvalue()


def encode_story_pages_pdf(pages: list[Any]) -> bytes:
    if Image is None:
        raise RuntimeError("Thiếu Pillow để xuất PDF.")
    if not pages:
        return b""

    converted = [img.convert("RGB") for img in pages]
    buffer = io.BytesIO()
    converted[0].save(buffer, format="PDF", save_all=True, append_images=converted[1:])
    return buffer.getvalue()


def extract_model_option_hints(info: dict[str, Any], target_key: str) -> list[str]:
    result: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() == target_key.lower():
                    if isinstance(value, list):
                        result.extend([str(v) for v in value if isinstance(v, (str, int, float, bool))])
                    elif isinstance(value, (str, int, float, bool)):
                        result.append(str(value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(info)
    return unique_list(result)


def apply_quality_profile_to_state() -> None:
    profile = QUALITY_PROFILES.get(st.session_state.gen_quality_profile, {})
    st.session_state.gen_steps = int(profile.get("steps", st.session_state.gen_steps))
    st.session_state.gen_guidance_scale = float(profile.get("guidance_scale", st.session_state.gen_guidance_scale))
    st.session_state.gen_cfg_scale = float(profile.get("cfg_scale", st.session_state.gen_cfg_scale))
    if not st.session_state.gen_quality_override:
        st.session_state.gen_quality_override = str(profile.get("quality", ""))


def render_css() -> None:
    compact_mode = bool(st.session_state.get("ui_compact_mode", True))
    container_pad_x = ".55rem" if compact_mode else ".95rem"
    container_pad_y_top = ".4rem" if compact_mode else ".7rem"
    container_pad_y_bot = ".55rem" if compact_mode else ".95rem"
    vert_gap = ".4rem" if compact_mode else ".6rem"
    horz_gap = ".42rem" if compact_mode else ".7rem"
    control_h = "34px" if compact_mode else "40px"
    action_h = "44px" if compact_mode else "52px"
    sidebar_w = "208px" if compact_mode else "236px"

    st.markdown(
        f"""
        <style>
          /* ============================================================
             Wahu Image Studio - Desktop AI Image Generator
             Dark futuristic, purple-cyan, glassmorphism, neon glow.
             ============================================================ */
          :root {{
            --nr-bg-0: #070a17;
            --nr-bg-1: #0b1020;
            --nr-bg-2: #121a2b;
            --nr-bg-3: #1a2440;
            --nr-panel:        rgba(18, 26, 43, 0.72);
            --nr-panel-strong: rgba(18, 26, 43, 0.92);
            --nr-line:   rgba(255, 255, 255, 0.08);
            --nr-line-2: rgba(255, 255, 255, 0.14);
            --nr-text:        #f1f5fc;
            --nr-text-soft:   #c7d0e3;
            --nr-text-mute:   rgba(226, 232, 240, 0.62);
            --nr-primary: #7B61FF;
            --nr-primary-2: #38BDF8;
            --nr-success: #34d399;
            --nr-warn:    #fbbf24;
            --nr-danger:  #f87171;
            --nr-glow-purple: 0 0 28px rgba(123, 97, 255, 0.30);
            --nr-glow-cyan:   0 0 28px rgba( 56, 189, 248, 0.22);
            --nr-shadow-sm: 0 1px 3px rgba(2, 6, 23, 0.40);
            --nr-shadow-md: 0 10px 28px rgba(2, 6, 23, 0.40);
            --nr-shadow-lg: 0 22px 60px rgba(2, 6, 23, 0.55);
          }}

          /* ----- Typography (Vietnamese-friendly) ----- */
          html, body, [data-testid="stAppViewContainer"] {{
            font-family: "Inter", "SF Pro Display", "Segoe UI",
              "Roboto", "Helvetica Neue", Arial,
              "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji", sans-serif;
            color: var(--nr-text);
            letter-spacing: 0.1px;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: optimizeLegibility;
          }}
          [data-testid="stAppViewContainer"] *,
          section[data-testid="stSidebar"] * {{
            line-height: 1.5;
          }}
          h1, h2, h3, h4, h5, h6,
          [data-testid="stWidgetLabel"] p,
          .stMarkdown p,
          [data-testid="stCaptionContainer"] p {{
            overflow: visible !important;
            text-overflow: initial !important;
            white-space: normal !important;
          }}
          h1 {{ font-size: 1.55rem !important; font-weight: 800 !important; }}
          h2 {{ font-size: 1.22rem !important; font-weight: 700 !important; }}
          h3 {{ font-size: 1.06rem !important; font-weight: 700 !important; }}
          h4 {{ font-size: .96rem  !important; font-weight: 700 !important; }}

          /* ----- App background ----- */
          [data-testid="stAppViewContainer"] {{
            background:
              radial-gradient(900px 540px at 18% -8%,  rgba(123, 97, 255, 0.22), transparent 62%),
              radial-gradient(820px 480px at 84% 6%,   rgba( 56, 189, 248, 0.18), transparent 60%),
              linear-gradient(180deg, #0B1020 0%, #090d1a 50%, #060912 100%);
          }}
          [data-testid="stHeader"],
          [data-testid="stToolbar"],
          [data-testid="stDecoration"],
          [data-testid="stStatusWidget"],
          [data-testid="stMainMenu"],
          .stDeployButton,
          [data-testid="stDeployButton"],
          header[data-testid="stHeader"] {{
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            width: 0 !important;
            min-height: 0 !important;
          }}
          /* Some Streamlit versions render the Deploy/menu in a floating toolbar */
          div[data-testid="stToolbarActions"],
          div[data-testid="stMainMenuPopover"],
          [class*="viewerBadge"] {{
            display: none !important;
          }}
          /* Reclaim the top space the hidden header used to take */
          section[data-testid="stMain"] > div:first-child,
          section[data-testid="stMain"] > div[data-testid="stMainBlockContainer"] {{
            padding-top: .55rem !important;
          }}
          footer {{ display: none !important; }}

          /* ----- Sidebar ----- */
          section[data-testid="stSidebar"] {{
            width: {sidebar_w} !important;
            min-width: {sidebar_w} !important;
            background:
              linear-gradient(180deg, rgba(18,26,43,.92) 0%, rgba(10,15,30,.94) 100%);
            border-right: 1px solid var(--nr-line);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            box-shadow: 14px 0 44px rgba(0,0,0,.18);
          }}
          section[data-testid="stSidebar"] > div {{
            padding: 1rem .85rem !important;
          }}
          section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
          section[data-testid="stSidebar"] .stMarkdown p {{
            color: var(--nr-text-soft);
          }}

          /* Sidebar brand block */
          .nr-brand {{
            display: flex;
            align-items: center;
            gap: .65rem;
            padding: .35rem .25rem .85rem;
            border-bottom: 1px solid var(--nr-line);
            margin-bottom: .8rem;
          }}
          .nr-brand-logo {{
            width: 40px; height: 40px;
            display: grid; place-items: center;
            border-radius: 12px;
            background: linear-gradient(135deg, #7B61FF, #38BDF8);
            color: #fff;
            font-weight: 800;
            font-size: .96rem;
            letter-spacing: .4px;
            box-shadow: 0 0 22px rgba(123, 97, 255, .42);
          }}
          .nr-brand-title {{
            font-size: 1rem;
            font-weight: 800;
            color: #fff;
            line-height: 1.1;
          }}
          .nr-brand-sub {{
            font-size: .74rem;
            color: var(--nr-text-mute);
            margin-top: 2px;
          }}
          .nr-sidebar-divider {{
            height: 1px;
            background: var(--nr-line);
            margin: .6rem 0 .55rem;
          }}

          /* Sidebar nav radio → chip list */
          section[data-testid="stSidebar"] div[role="radiogroup"] {{
            display: flex;
            flex-direction: column;
            gap: .32rem;
          }}
          section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
            border: 1px solid var(--nr-line);
            background: rgba(255, 255, 255, .025);
            border-radius: 12px;
            padding: .45rem .7rem !important;
            transition: all .18s ease;
          }}
          section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {{
            border-color: rgba(123, 97, 255, .55);
            background: rgba(123, 97, 255, .08);
            transform: translateX(2px);
          }}
          section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
            border-color: rgba(123, 97, 255, .65);
            background: linear-gradient(135deg, rgba(123,97,255,.22) 0%, rgba(56,189,248,.10) 100%);
            box-shadow: var(--nr-glow-purple);
          }}
          section[data-testid="stSidebar"] div[role="radiogroup"] > label p {{
            font-weight: 600;
            color: var(--nr-text) !important;
            font-size: .92rem !important;
          }}
          section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {{
            display: none !important;
          }}

          /* ----- Main container ----- */
          section[data-testid="stMain"] > div[data-testid="stMainBlockContainer"],
          .block-container {{
            max-width: 100% !important;
            padding-left:  {container_pad_x} !important;
            padding-right: {container_pad_x} !important;
            padding-top:    {container_pad_y_top} !important;
            padding-bottom: {container_pad_y_bot} !important;
          }}
          [data-testid="stVerticalBlock"] {{ gap: {vert_gap} !important; }}
          [data-testid="stHorizontalBlock"] {{ gap: {horz_gap} !important; }}

          div[data-testid="stWidgetLabel"] p {{
            margin-bottom: .22rem !important;
            font-size: .85rem !important;
            font-weight: 600 !important;
            color: var(--nr-text-soft) !important;
            letter-spacing: .15px;
          }}
          [data-testid="stCaptionContainer"] p {{
            margin: .1rem 0 .25rem !important;
            color: var(--nr-text-mute) !important;
            line-height: 1.4 !important;
            overflow-wrap: anywhere !important;
            word-break: break-word !important;
          }}
          .stMarkdown p {{ margin-bottom: .25rem; }}

          /* ----- Inputs (glass) ----- */
          .stTextInput input,
          .stTextArea textarea,
          .stSelectbox [data-baseweb="select"] > div,
          .stMultiSelect [data-baseweb="select"] > div,
          .stNumberInput input,
          .stDateInput input {{
            border-radius: 12px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: rgba(255,255,255,.04) !important;
            color: var(--nr-text) !important;
            min-height: {control_h} !important;
            transition: border-color .18s ease, box-shadow .18s ease, background .18s ease !important;
          }}
          .stTextArea textarea {{
            min-height: 96px !important;
            line-height: 1.5 !important;
            padding: .55rem .7rem !important;
          }}
          .stTextInput input:hover,
          .stTextArea textarea:hover,
          .stSelectbox [data-baseweb="select"] > div:hover,
          .stMultiSelect [data-baseweb="select"] > div:hover,
          .stNumberInput input:hover {{
            border-color: rgba(123, 97, 255, .55) !important;
          }}
          .stTextInput input:focus,
          .stTextArea textarea:focus,
          .stNumberInput input:focus,
          .stSelectbox [data-baseweb="select"] > div:focus-within,
          .stMultiSelect [data-baseweb="select"] > div:focus-within {{
            border-color: rgba(123, 97, 255, .85) !important;
            box-shadow: 0 0 0 3px rgba(123, 97, 255, .18) !important;
            outline: none !important;
          }}
          .stTextArea textarea::placeholder,
          .stTextInput input::placeholder {{
            color: var(--nr-text-mute) !important;
          }}

          /* Featured prompt textarea */
          .st-key-quick_subject textarea {{
            min-height: 160px !important;
            border: 1px solid rgba(123, 97, 255, .55) !important;
            background: rgba(8, 14, 28, .85) !important;
            box-shadow: inset 0 0 0 1px rgba(123, 97, 255, .14),
                        0 6px 22px rgba(123, 97, 255, .10) !important;
            font-size: .94rem !important;
          }}

          /* Compact file uploader drop zone */
          [data-testid="stFileUploaderDropzone"] {{
            min-height: 60px !important;
            padding: .35rem .6rem !important;
            border-radius: 12px !important;
            border: 1px dashed var(--nr-line-2) !important;
            background: rgba(255, 255, 255, .03) !important;
          }}
          [data-testid="stFileUploaderDropzone"] section {{
            padding: 0 !important;
          }}
          [data-testid="stFileUploaderDropzoneInstructions"] span {{
            font-size: .8rem !important;
          }}
          [data-testid="stFileUploaderDropzoneInstructions"] small {{
            font-size: .72rem !important;
            color: var(--nr-text-mute) !important;
          }}

          /* ----- Buttons ----- */
          .stButton > button {{
            min-height: {control_h} !important;
            padding: .12rem .85rem !important;
            border-radius: 11px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: linear-gradient(180deg, rgba(255,255,255,.05) 0%, rgba(255,255,255,.02) 100%) !important;
            color: var(--nr-text) !important;
            font-weight: 600 !important;
            font-size: .88rem !important;
            box-shadow: var(--nr-shadow-sm) !important;
            transition: transform .15s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease !important;
          }}
          .stButton > button:hover {{
            border-color: rgba(123, 97, 255, .65) !important;
            background: linear-gradient(180deg, rgba(123,97,255,.16) 0%, rgba(56,189,248,.06) 100%) !important;
            transform: translateY(-1px);
          }}
          .stButton > button:active {{ transform: translateY(0); }}
          .stButton > button:focus-visible {{
            outline: none !important;
            box-shadow: 0 0 0 3px rgba(123, 97, 255, .32), var(--nr-shadow-md) !important;
          }}

          /* Primary buttons (gradient + glow) */
          .stButton > button[kind="primary"],
          .stButton > button[data-kind="primary"] {{
            border: 0 !important;
            background: linear-gradient(135deg, #7B61FF 0%, #38BDF8 100%) !important;
            color: #fff !important;
            font-weight: 800 !important;
            font-size: .94rem !important;
            box-shadow: 0 0 26px rgba(123, 97, 255, .34),
                        0 12px 28px rgba(2, 6, 23, .35) !important;
          }}
          .stButton > button[kind="primary"]:hover,
          .stButton > button[data-kind="primary"]:hover {{
            transform: translateY(-1px) scale(1.02);
            background: linear-gradient(135deg, #8e7aff 0%, #67d8fd 100%) !important;
          }}

          /* Highlighted action buttons */
          .st-key-btn_quick_generate button,
          .st-key-btn_quick_edit_submit button,
          .st-key-btn_quick_upscale_submit button,
          .st-key-btn_quick_translate_submit button,
          .st-key-btn_quick_style_transfer button,
          .st-key-btn_quick_universal_submit button,
          .st-key-btn_quick_remix_submit button,
          .st-key-btn_create_image button,
          .st-key-btn_story_generate_comic button {{
            min-height: {action_h} !important;
            font-size: 1rem !important;
            font-weight: 800 !important;
            border: 0 !important;
            background: linear-gradient(135deg, #7B61FF 0%, #38BDF8 100%) !important;
            color: #fff !important;
            letter-spacing: .25px !important;
            box-shadow: 0 0 30px rgba(123, 97, 255, .38),
                        0 12px 30px rgba(2, 6, 23, .40) !important;
            transition: transform .15s ease, box-shadow .18s ease, background .25s ease !important;
          }}
          .st-key-btn_quick_generate button:hover,
          .st-key-btn_quick_edit_submit button:hover,
          .st-key-btn_quick_upscale_submit button:hover,
          .st-key-btn_quick_translate_submit button:hover,
          .st-key-btn_quick_style_transfer button:hover,
          .st-key-btn_quick_universal_submit button:hover,
          .st-key-btn_quick_remix_submit button:hover,
          .st-key-btn_create_image button:hover,
          .st-key-btn_story_generate_comic button:hover {{
            transform: translateY(-1px) scale(1.01);
            box-shadow: 0 0 38px rgba(123, 97, 255, .50),
                        0 14px 32px rgba(2, 6, 23, .45) !important;
            background: linear-gradient(135deg, #8e7aff 0%, #67d8fd 100%) !important;
          }}

          /* Secondary tints */
          .st-key-btn_studio_load_models button,
          .st-key-btn_quick_load_models button,
          .st-key-btn_studio_apply_preset button,
          .st-key-btn_apply_lora_preset button,
          .st-key-btn_lora_use_studio_model button,
          .st-key-btn_load_edit_preset button,
          .st-key-btn_load_compose_preset button,
          .st-key-btn_sidebar_open_config_api button,
          .st-key-btn_sidebar_load_env button,
          .st-key-btn_sidebar_save_env button,
          .st-key-btn_open_config_from_quick_keys button,
          .st-key-btn_open_config_from_studio_keys button {{
            border: 1px solid rgba(56, 189, 248, .42) !important;
            background: linear-gradient(180deg, rgba(56,189,248,.16) 0%, rgba(56,189,248,.05) 100%) !important;
            color: #ecfeff !important;
          }}

          .st-key-btn_apply_lora_workflow button,
          .st-key-btn_train_lora button,
          .st-key-btn_sidebar_open_train_lora button,
          .st-key-btn_quick_open_train_lora button {{
            border: 0 !important;
            background: linear-gradient(135deg, #a78bfa 0%, #6d28d9 100%) !important;
            color: #fff !important;
            box-shadow: 0 0 24px rgba(167,139,250,.32),
                        0 10px 24px rgba(91,33,182,.32) !important;
          }}

          .st-key-btn_lora_status button,
          .st-key-btn_lora_list button {{
            border: 1px solid rgba(45, 212, 191, .45) !important;
            background: linear-gradient(180deg, rgba(45,212,191,.16) 0%, rgba(45,212,191,.04) 100%) !important;
            color: #ecfdf5 !important;
          }}

          .st-key-btn_quick_prompt_os_clipboard button,
          .st-key-btn_quick_edit_clipboard button,
          .st-key-btn_quick_upscale_clipboard button,
          .st-key-btn_quick_translate_clipboard button {{
            border: 1px solid rgba(251, 191, 36, .55) !important;
            background: linear-gradient(180deg, rgba(251,191,36,.18) 0%, rgba(251,191,36,.04) 100%) !important;
            color: #fffbeb !important;
            font-weight: 700 !important;
          }}
          .st-key-btn_clear_quick_prompt_clip button,
          .st-key-btn_clear_quick_edit_clip button,
          .st-key-btn_clear_quick_upscale_clip button,
          .st-key-btn_clear_quick_translate_clip button {{
            border: 1px solid rgba(248, 113, 113, .5) !important;
            color: #fecaca !important;
          }}
          .st-key-btn_clear_lora_log button,
          .st-key-btn_lora_cancel button,
          .st-key-btn_create_reset button {{
            border: 1px solid rgba(248, 113, 113, .55) !important;
            background: linear-gradient(180deg, rgba(248,113,113,.16) 0%, rgba(248,113,113,.04) 100%) !important;
            color: #fee2e2 !important;
          }}

          [class*="st-key-btn_recent_view_"] button,
          [class*="st-key-btn_recent_del_"] button {{
            min-height: 28px !important;
            padding: .04rem .42rem !important;
            font-size: .76rem !important;
            border-radius: 8px !important;
          }}

          .stDownloadButton > button {{
            border-radius: 11px !important;
            border: 0 !important;
            background: linear-gradient(135deg, #6366f1 0%, #4338ca 100%) !important;
            color: #eef2ff !important;
            font-weight: 700 !important;
            box-shadow: 0 10px 24px rgba(67, 56, 202, .32) !important;
          }}
          .stDownloadButton > button:hover {{
            transform: translateY(-1px);
            background: linear-gradient(135deg, #818cf8 0%, #4f46e5 100%) !important;
          }}

          /* ----- Expanders / panels (glass cards) ----- */
          [data-testid="stExpander"] {{
            border: 1px solid var(--nr-line) !important;
            border-radius: 14px !important;
            background:
              radial-gradient(380px 220px at 0% 0%, rgba(123, 97, 255, .10), transparent 70%),
              linear-gradient(150deg, var(--nr-panel) 0%, rgba(10, 15, 30, .62) 100%) !important;
            box-shadow: var(--nr-shadow-sm) !important;
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            overflow: hidden;
          }}
          [data-testid="stExpander"] summary {{
            padding: .4rem .7rem !important;
            font-weight: 600 !important;
            color: var(--nr-text) !important;
            min-height: unset !important;
          }}
          [data-testid="stExpander"] summary:hover {{
            background: rgba(123, 97, 255, .08);
          }}
          [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
            padding: .5rem .75rem .65rem !important;
          }}

          /* ----- Panel cards (custom HTML) ----- */
          .panel-card {{
            border: 1px solid var(--nr-line);
            border-radius: 16px;
            padding: .8rem 1rem;
            background:
              radial-gradient(380px 220px at 0% 0%, rgba(123, 97, 255, .10), transparent 70%),
              linear-gradient(150deg, var(--nr-panel) 0%, rgba(10, 15, 30, .62) 100%);
            box-shadow: var(--nr-shadow-md);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            margin-bottom: .55rem;
          }}
          .panel-card h4 {{
            margin: 0;
            font-size: .98rem;
            color: var(--nr-text);
            font-weight: 700;
          }}
          .panel-card p {{
            margin: .26rem 0 0;
            font-size: .85rem;
            color: var(--nr-text-soft);
          }}

          /* ----- Hero (home page) ----- */
          .hero {{
            position: relative;
            padding: .85rem 1.1rem;
            border-radius: 18px;
            border: 1px solid var(--nr-line-2);
            background:
              radial-gradient(520px 240px at 0% 0%,   rgba(123, 97, 255, .26), transparent 60%),
              radial-gradient(520px 240px at 100% 100%, rgba( 56, 189, 248, .22), transparent 60%),
              linear-gradient(135deg, rgba(18, 26, 43, .92) 0%, rgba(11, 16, 32, .92) 100%);
            box-shadow: var(--nr-shadow-md), var(--nr-glow-purple);
            margin-bottom: .65rem;
            overflow: hidden;
          }}
          .hero::after {{
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, transparent 30%, rgba(255,255,255,.04) 50%, transparent 70%);
            pointer-events: none;
          }}
          .hero-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: .7rem;
          }}
          .hero-title {{ flex: 1 1 320px; min-width: 240px; }}
          .hero h1 {{
            margin: 0;
            font-size: 1.3rem;
            font-weight: 800;
            background: linear-gradient(120deg, #ffffff 0%, #c4b5fd 55%, #38BDF8 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            letter-spacing: .3px;
          }}
          .hero p {{
            margin: .18rem 0 0;
            color: var(--nr-text-soft);
            font-size: .82rem;
          }}
          .hero-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: .42rem;
            align-items: center;
          }}
          .hero-chip {{
            display: inline-flex;
            align-items: center;
            gap: .32rem;
            padding: .22rem .62rem;
            border-radius: 999px;
            border: 1px solid var(--nr-line-2);
            background: rgba(123, 97, 255, .10);
            color: #e0e7ff;
            font-size: .76rem;
            font-weight: 600;
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
          }}

          /* ----- Pills / chip selectors ----- */
          .st-key-draw_active_flow div[role="radiogroup"] {{
            display: flex;
            flex-wrap: wrap;
            gap: .5rem;
          }}
          .st-key-draw_active_flow div[role="radiogroup"] > label,
          .st-key-studio_model_mode div[role="radiogroup"] > label,
          .st-key-create_reference_mode div[role="radiogroup"] > label {{
            border-radius: 999px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: rgba(255, 255, 255, .035) !important;
            padding: .26rem .9rem !important;
            margin-right: 0 !important;
            transition: all .18s ease;
          }}
          .st-key-draw_active_flow div[role="radiogroup"] > label:hover,
          .st-key-studio_model_mode div[role="radiogroup"] > label:hover,
          .st-key-create_reference_mode div[role="radiogroup"] > label:hover {{
            border-color: rgba(123, 97, 255, .6) !important;
            background: rgba(123, 97, 255, .10) !important;
          }}
          .st-key-draw_active_flow div[role="radiogroup"] > label:has(input:checked),
          .st-key-studio_model_mode div[role="radiogroup"] > label:has(input:checked),
          .st-key-create_reference_mode div[role="radiogroup"] > label:has(input:checked) {{
            border: 0 !important;
            background: linear-gradient(135deg, #7B61FF 0%, #38BDF8 100%) !important;
            box-shadow: var(--nr-glow-purple);
          }}
          .st-key-draw_active_flow div[role="radiogroup"] > label:has(input:checked) p,
          .st-key-studio_model_mode div[role="radiogroup"] > label:has(input:checked) p,
          .st-key-create_reference_mode div[role="radiogroup"] > label:has(input:checked) p {{
            color: #fff !important;
            font-weight: 700 !important;
          }}
          .st-key-draw_active_flow div[role="radiogroup"] > label p,
          .st-key-studio_model_mode div[role="radiogroup"] > label p,
          .st-key-create_reference_mode div[role="radiogroup"] > label p {{
            color: var(--nr-text-soft) !important;
            font-weight: 600 !important;
          }}

          div[data-testid="stPills"] button {{
            border-radius: 999px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: rgba(255, 255, 255, .035) !important;
            color: var(--nr-text-soft) !important;
            font-weight: 600 !important;
            transition: all .15s ease;
          }}
          div[data-testid="stPills"] button:hover {{
            border-color: rgba(123, 97, 255, .6) !important;
            background: rgba(123, 97, 255, .10) !important;
            color: var(--nr-text) !important;
          }}
          div[data-testid="stPills"] button[aria-selected="true"],
          div[data-testid="stPills"] button[aria-checked="true"],
          div[data-testid="stPills"] button[aria-pressed="true"] {{
            border: 0 !important;
            background: linear-gradient(135deg, #7B61FF 0%, #38BDF8 100%) !important;
            color: #fff !important;
            box-shadow: var(--nr-glow-purple);
          }}

          /* ----- Tabs ----- */
          .stTabs [data-baseweb="tab-list"] {{
            gap: .42rem;
            margin-bottom: .35rem;
            border-bottom: 1px solid var(--nr-line);
            padding-bottom: .25rem;
          }}
          .stTabs [role="tab"] {{
            border-radius: 999px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: rgba(255, 255, 255, .035) !important;
            padding: .25rem 1rem !important;
            color: var(--nr-text-soft) !important;
            min-height: {control_h} !important;
            transition: all .18s ease !important;
          }}
          .stTabs [role="tab"]:hover {{
            border-color: rgba(123, 97, 255, .55) !important;
            color: var(--nr-text) !important;
          }}
          .stTabs [role="tab"][aria-selected="true"] {{
            border: 0 !important;
            background: linear-gradient(135deg, rgba(123,97,255,.78), rgba(56,189,248,.4)) !important;
            color: #fff !important;
            box-shadow: var(--nr-glow-purple);
          }}

          /* ----- Toggles / checkboxes ----- */
          .stCheckbox label, .stToggle label {{ color: var(--nr-text-soft); }}

          /* ----- Misc ----- */
          hr {{
            border: none !important;
            border-top: 1px solid var(--nr-line) !important;
            margin: .6rem 0 !important;
          }}
          .stAlert {{
            border-radius: 14px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: rgba(18, 26, 43, .65) !important;
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
          }}
          [data-testid="stImage"] img {{
            border-radius: 14px;
            border: 1px solid var(--nr-line);
            box-shadow: 0 14px 36px rgba(0, 0, 0, .32);
            transition: transform .2s ease, box-shadow .2s ease, filter .2s ease;
          }}
          [data-testid="stImage"] img:hover {{
            transform: translateY(-2px) scale(1.015);
            box-shadow: 0 18px 44px rgba(0, 0, 0, .42), var(--nr-glow-purple);
            filter: brightness(1.05);
          }}

          /* ----- Metric cards ----- */
          [data-testid="stMetric"] {{
            padding: .68rem .85rem !important;
            border: 1px solid var(--nr-line) !important;
            border-radius: 14px !important;
            background:
              radial-gradient(220px 100px at 0% 0%, rgba(123, 97, 255, .14), transparent 70%),
              linear-gradient(180deg, rgba(18, 26, 43, .75) 0%, rgba(11, 18, 36, .55) 100%) !important;
            box-shadow: var(--nr-shadow-sm) !important;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: border-color .18s ease, transform .18s ease;
          }}
          [data-testid="stMetric"]:hover {{
            border-color: rgba(123, 97, 255, .45) !important;
            transform: translateY(-2px);
          }}
          [data-testid="stMetric"] label {{
            margin-bottom: .18rem !important;
            color: var(--nr-text-mute) !important;
            font-size: .76rem !important;
            text-transform: uppercase;
            letter-spacing: .8px;
            font-weight: 700;
          }}
          [data-testid="stMetricValue"] {{
            font-weight: 800 !important;
            color: var(--nr-text) !important;
          }}

          /* ----- Compact override on action layout columns ----- */
          .st-key-btn_create_reset button,
          .st-key-btn_create_image button,
          .st-key-btn_create_auto button,
          .st-key-btn_studio_load_models button,
          .st-key-btn_studio_apply_preset button,
          .st-key-btn_studio_everyday_defaults button,
          .st-key-btn_load_edit_preset button,
          .st-key-btn_load_compose_preset button {{
            margin-top: 1.46rem !important;
          }}

          /* ----- Auxiliary text classes ----- */
          .studio-prompt-tip {{
            margin-top: .22rem;
            font-size: .85rem;
            color: var(--nr-text-soft);
          }}
          .studio-status-chip {{
            margin: .35rem 0 .45rem;
            display: inline-flex;
            align-items: center;
            gap: .35rem;
            padding: .26rem .8rem;
            border-radius: 999px;
            border: 1px solid var(--nr-line-2);
            background: linear-gradient(135deg, rgba(123,97,255,.18), rgba(56,189,248,.08));
            color: #e0e7ff;
            font-size: .82rem;
            font-weight: 600;
          }}
          .prompt-preview-box {{
            margin-top: .3rem;
            border: 1px solid var(--nr-line-2);
            background: rgba(11, 18, 36, .72);
            border-radius: 12px;
            padding: .58rem .8rem;
            font-size: .88rem;
            color: #e2e8f0;
            line-height: 1.5;
            max-height: 130px;
            overflow: auto;
            box-shadow: var(--nr-shadow-sm);
          }}
          .studio-grid-note {{
            margin: .3rem 0 .6rem;
            color: #c4b5fd;
            font-size: .86rem;
            font-weight: 500;
          }}
          .tier-note {{
            margin: .25rem 0 .55rem;
            color: var(--nr-text-soft);
            font-size: .87rem;
          }}
          .compact-note {{
            font-size: .85rem;
            color: var(--nr-text-soft);
          }}

          /* ----- Workflow intro (lightweight inline header) ----- */
          .workflow-intro {{
            display: flex;
            align-items: baseline;
            flex-wrap: wrap;
            gap: .55rem;
            padding: .35rem .65rem;
            margin: .15rem 0 .45rem;
            border-left: 3px solid var(--nr-primary);
            background: rgba(123, 97, 255, .08);
            border-radius: 0 10px 10px 0;
          }}
          .workflow-intro strong {{
            color: var(--nr-text);
            font-size: .94rem;
            font-weight: 700;
          }}
          .workflow-intro .workflow-intro-desc {{
            color: var(--nr-text-soft);
            font-size: .82rem;
          }}

          /* ----- Command preview panel ("Lệnh sẽ gửi") ----- */
          .cmd-panel {{
            border: 1px solid var(--nr-line-2);
            border-radius: 14px;
            padding: .65rem .8rem .55rem;
            background:
              radial-gradient(360px 200px at 0% 0%, rgba(123, 97, 255, .12), transparent 70%),
              linear-gradient(180deg, rgba(15, 23, 42, .86) 0%, rgba(11, 18, 36, .68) 100%);
            box-shadow: var(--nr-shadow-sm);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
          }}
          .cmd-panel-head {{
            display: flex;
            flex-wrap: wrap;
            gap: .4rem;
            margin-bottom: .42rem;
          }}
          .cmd-tag {{
            display: inline-flex;
            align-items: center;
            padding: .15rem .55rem;
            border-radius: 999px;
            background: linear-gradient(135deg, #7B61FF 0%, #38BDF8 100%);
            color: #fff;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .25px;
          }}
          .cmd-tag-soft {{
            background: rgba(123, 97, 255, .14);
            color: #c7d0e3;
            border: 1px solid var(--nr-line-2);
          }}
          .cmd-panel-prompt {{
            margin-bottom: .5rem;
            padding: .42rem .55rem;
            border-radius: 9px;
            border: 1px dashed rgba(123, 97, 255, .35);
            background: rgba(11, 18, 36, .58);
            font-size: .82rem;
            line-height: 1.4;
            color: #e2e8f0;
            max-height: 110px;
            overflow: auto;
            white-space: pre-wrap;
            word-break: break-word;
          }}
          .cmd-panel-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: .28rem .42rem;
          }}
          .cmd-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .4rem;
            padding: .22rem .5rem;
            background: rgba(255, 255, 255, .03);
            border-radius: 8px;
            border: 1px solid var(--nr-line);
          }}
          .cmd-key {{
            color: var(--nr-text-mute);
            font-size: .72rem;
            font-weight: 600;
            letter-spacing: .25px;
            text-transform: uppercase;
          }}
          .cmd-val {{
            color: var(--nr-text);
            font-size: .82rem;
            font-weight: 600;
            text-align: right;
            max-width: 60%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }}

          /* ----- Comic banner ----- */
          .comic-banner {{
            border: 1px solid var(--nr-line-2);
            border-radius: 18px;
            padding: .9rem 1.05rem;
            background:
              radial-gradient(360px 200px at 0% 0%,   rgba(14, 116, 144, .26), transparent 60%),
              radial-gradient(360px 200px at 100% 100%, rgba(123,  97, 255, .26), transparent 60%),
              linear-gradient(135deg, rgba(13, 20, 38, .88) 0%, rgba(17, 24, 39, .88) 100%);
            box-shadow: var(--nr-shadow-md);
            margin: .25rem 0 .65rem;
          }}
          .comic-banner h4 {{
            margin: 0;
            font-size: 1.05rem;
            color: #e0f2fe;
            font-weight: 800;
            letter-spacing: .25px;
          }}
          .comic-banner p {{
            margin: .32rem 0 0;
            font-size: .88rem;
            color: var(--nr-text-soft);
          }}
          .comic-chip-row {{
            margin-top: .5rem;
            display: flex;
            gap: .42rem;
            flex-wrap: wrap;
          }}
          .comic-chip {{
            display: inline-block;
            border-radius: 999px;
            border: 1px solid var(--nr-line-2);
            background: rgba(123, 97, 255, .12);
            color: #e0e7ff;
            font-size: .78rem;
            font-weight: 600;
            padding: .2rem .68rem;
          }}
          .comic-title {{
            margin: .14rem 0 .14rem;
            font-size: .96rem;
            color: #c7d2fe;
            font-weight: 700;
          }}
          .comic-note {{
            font-size: .85rem;
            color: var(--nr-text-soft);
            margin-bottom: .3rem;
          }}

          /* ----- Canvas studio (Generate page) ----- */
          /* Marker-driven card: the next 3-column row after .nr-studio-row-marker becomes 3 glass cards */
          [data-testid="stVerticalBlock"]:has(> [data-testid="stMarkdownContainer"] > .nr-studio-row-marker) > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{
            border: 1px solid var(--nr-line) !important;
            border-radius: 16px !important;
            padding: .8rem .9rem !important;
            background:
              radial-gradient(420px 220px at 0% 0%, rgba(123, 97, 255, .07), transparent 70%),
              linear-gradient(155deg, rgba(18,26,43,.62) 0%, rgba(10,15,30,.62) 100%) !important;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            box-shadow: var(--nr-shadow-md) !important;
            min-height: 100% !important;
          }}
          .nr-studio-row-marker {{ display: none; }}
          .nr-card-header {{
            display: flex;
            align-items: center;
            gap: .5rem;
            margin: 0 0 .5rem;
            padding-bottom: .35rem;
            border-bottom: 1px solid var(--nr-line);
            color: var(--nr-text);
            font-weight: 800;
            font-size: .82rem;
            letter-spacing: .8px;
            text-transform: uppercase;
          }}
          .nr-card-divider {{
            height: 1px;
            background: var(--nr-line);
            margin: .65rem 0 .55rem;
          }}
          .nr-card-divider-strong {{
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(123,97,255,.45), transparent);
            margin: .85rem 0 .5rem;
          }}

          .nr-gallery-head {{
            display: flex;
            align-items: center;
            gap: .55rem;
            padding: .15rem 0 .55rem;
            margin-bottom: .55rem;
            border-bottom: 1px solid var(--nr-line);
          }}
          .nr-gallery-title {{
            font-weight: 800;
            font-size: 1.08rem;
            letter-spacing: .2px;
            color: var(--nr-text);
          }}
          .nr-gallery-count {{
            padding: .12rem .58rem;
            border-radius: 999px;
            border: 1px solid var(--nr-line-2);
            background: linear-gradient(135deg, rgba(123,97,255,.18), rgba(56,189,248,.10));
            color: #e0e7ff;
            font-size: .78rem;
            font-weight: 700;
          }}

          /* Bordered containers (st.container(border=True)) — kept tidy */
          [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {{
            gap: .35rem !important;
          }}
          .stMain [data-testid="stVerticalBlockBorderWrapper"] {{
            border: 1px solid var(--nr-line) !important;
            border-radius: 14px !important;
            padding: .65rem .8rem !important;
            background:
              radial-gradient(360px 200px at 0% 0%, rgba(123,97,255,.06), transparent 70%),
              linear-gradient(155deg, rgba(18,26,43,.55) 0%, rgba(10,15,30,.55) 100%) !important;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            box-shadow: var(--nr-shadow-sm) !important;
            margin-bottom: .35rem;
          }}

          .canvas-gallery-empty {{
            display: grid;
            place-items: center;
            min-height: 460px;
            text-align: center;
            color: var(--nr-text-mute);
            border: 1px dashed var(--nr-line-2);
            border-radius: 14px;
            background:
              radial-gradient(420px 220px at 50% 0%, rgba(123,97,255,.07), transparent 60%),
              rgba(255,255,255,.015);
          }}
          .canvas-gallery-empty .canvas-gallery-empty-icon {{
            font-size: 2.8rem;
            margin-bottom: .3rem;
            filter: drop-shadow(0 0 18px rgba(123,97,255,.45));
          }}
          .canvas-gallery-empty .canvas-gallery-empty-title {{
            font-weight: 700;
            color: var(--nr-text-soft);
            font-size: 1.05rem;
            margin-bottom: .4rem;
          }}
          .canvas-gallery-empty .canvas-gallery-empty-sub {{
            font-size: .88rem;
            line-height: 1.55;
            max-width: 440px;
          }}
          .canvas-status-chip {{
            margin-top: .35rem;
            display: inline-flex;
            align-items: center;
            gap: .35rem;
            padding: .26rem .68rem;
            border-radius: 10px;
            border: 1px solid rgba(56, 189, 248, .42);
            background: linear-gradient(180deg, rgba(56,189,248,.14), rgba(56,189,248,.04));
            color: #e0f2fe;
            font-size: .8rem;
            font-weight: 600;
          }}
          .canvas-status-chip-warn {{
            border-color: rgba(251, 191, 36, .55) !important;
            background: linear-gradient(180deg, rgba(251,191,36,.15), rgba(251,191,36,.04)) !important;
            color: #fef3c7 !important;
          }}
          .canvas-meta {{
            display: grid;
            gap: .38rem;
            padding: .6rem .7rem;
            border: 1px solid var(--nr-line);
            border-radius: 10px;
            background: rgba(255,255,255,.025);
            margin-bottom: .35rem;
          }}
          .canvas-meta .canvas-meta-row {{
            font-size: .82rem;
            color: var(--nr-text-soft);
            line-height: 1.45;
            word-break: break-word;
          }}
          .canvas-meta .canvas-meta-row b {{
            color: var(--nr-text-mute);
            font-weight: 700;
            text-transform: uppercase;
            font-size: .68rem;
            letter-spacing: .8px;
            margin-right: .35rem;
          }}
          .canvas-meta .canvas-meta-row code {{
            color: #c4b5fd;
            background: rgba(123, 97, 255, .12);
            padding: .04rem .35rem;
            border-radius: 6px;
            font-size: .76rem;
          }}

          /* ----- Scrollbars (dark sleek) ----- */
          *::-webkit-scrollbar {{ width: 10px; height: 10px; }}
          *::-webkit-scrollbar-track {{
            background: rgba(7, 10, 23, 0.4);
            border-radius: 8px;
          }}
          *::-webkit-scrollbar-thumb {{
            background: linear-gradient(180deg, rgba(123, 97, 255, .55), rgba(56, 189, 248, .35));
            border-radius: 8px;
            border: 2px solid rgba(7, 10, 23, 0.4);
          }}
          *::-webkit-scrollbar-thumb:hover {{
            background: linear-gradient(180deg, rgba(123, 97, 255, .85), rgba(56, 189, 248, .65));
          }}
          * {{
            scrollbar-color: rgba(123, 97, 255, .55) rgba(7, 10, 23, 0.4);
            scrollbar-width: thin;
          }}

          /* ----- Subtle hero shine sweep ----- */
          @keyframes nrHeroShine {{
            0%   {{ transform: translateX(-30%); opacity: 0; }}
            50%  {{ opacity: .9; }}
            100% {{ transform: translateX(130%); opacity: 0; }}
          }}
          .hero::before {{
            content: "";
            position: absolute;
            top: -40%;
            left: 0;
            width: 28%;
            height: 180%;
            background: linear-gradient(115deg, transparent 0%, rgba(255,255,255,.05) 45%, rgba(255,255,255,.10) 50%, rgba(255,255,255,.05) 55%, transparent 100%);
            transform: translateX(-30%);
            pointer-events: none;
            animation: nrHeroShine 7.5s ease-in-out infinite;
          }}

          /* ----- Sidebar status footer ----- */
          .nr-sidebar-status {{
            margin-top: .9rem;
            padding: .6rem .65rem;
            border-radius: 12px;
            border: 1px solid var(--nr-line);
            background:
              radial-gradient(220px 100px at 0% 0%, rgba(123,97,255,.10), transparent 70%),
              linear-gradient(160deg, rgba(18,26,43,.8) 0%, rgba(10,15,30,.65) 100%);
            box-shadow: var(--nr-shadow-sm);
          }}
          .nr-sidebar-status .nr-st-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .35rem;
            font-size: .78rem;
            color: var(--nr-text-soft);
            padding: .12rem 0;
          }}
          .nr-sidebar-status .nr-st-row b {{
            color: var(--nr-text);
            font-weight: 700;
          }}
          .nr-sidebar-status .nr-st-dot {{
            display: inline-block;
            width: 6px; height: 6px; border-radius: 50%;
            box-shadow: 0 0 10px currentColor;
            margin-right: .35rem;
          }}
          .nr-sidebar-status .nr-st-ok    {{ color: var(--nr-success); }}
          .nr-sidebar-status .nr-st-warn  {{ color: var(--nr-warn); }}
          .nr-sidebar-status .nr-st-err   {{ color: var(--nr-danger); }}

          /* ----- Quick action chips on home page ----- */
          .nr-home-actions {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: .55rem;
            margin: .25rem 0 .55rem;
          }}

          /* ----- Dashboard tile (grouped metrics) ----- */
          .nr-dash-tile {{
            border: 1px solid var(--nr-line);
            border-radius: 14px;
            padding: .7rem .85rem;
            background:
              radial-gradient(260px 130px at 0% 0%, rgba(123,97,255,.10), transparent 70%),
              linear-gradient(155deg, rgba(18,26,43,.7) 0%, rgba(10,15,30,.55) 100%);
            box-shadow: var(--nr-shadow-sm);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: border-color .18s ease, transform .18s ease;
          }}
          .nr-dash-tile:hover {{
            border-color: rgba(123,97,255,.5);
            transform: translateY(-1px);
          }}
          .nr-dash-tile .nr-dash-label {{
            color: var(--nr-text-mute);
            font-size: .72rem;
            text-transform: uppercase;
            letter-spacing: .8px;
            font-weight: 700;
          }}
          .nr-dash-tile .nr-dash-value {{
            margin-top: .15rem;
            font-size: 1.2rem;
            font-weight: 800;
            color: var(--nr-text);
          }}
          .nr-dash-tile .nr-dash-sub {{
            margin-top: .15rem;
            font-size: .76rem;
            color: var(--nr-text-soft);
          }}
          .nr-dash-bar {{
            margin-top: .42rem;
            height: 6px;
            border-radius: 999px;
            background: rgba(255,255,255,.05);
            overflow: hidden;
          }}
          .nr-dash-bar > span {{
            display: block;
            height: 100%;
            background: linear-gradient(90deg, #7B61FF 0%, #38BDF8 100%);
            box-shadow: 0 0 10px rgba(123,97,255,.5);
          }}

          /* ----- Spinner ----- */
          [data-testid="stSpinner"] > div > div {{
            border-top-color: var(--nr-primary) !important;
            border-right-color: var(--nr-primary-2) !important;
          }}

          /* ----- Toast / Snackbar polish ----- */
          [data-testid="stToast"] {{
            border-radius: 12px !important;
            border: 1px solid var(--nr-line-2) !important;
            background: linear-gradient(135deg, rgba(18,26,43,.95), rgba(11,16,32,.95)) !important;
            box-shadow: var(--nr-shadow-md), var(--nr-glow-purple) !important;
          }}

          /* ----- Code blocks ----- */
          .stCodeBlock {{
            border-radius: 12px !important;
            border: 1px solid var(--nr-line) !important;
            box-shadow: var(--nr-shadow-sm) !important;
          }}

          /* ----- Slider polish ----- */
          .stSlider [data-baseweb="slider"] [role="slider"] {{
            background: linear-gradient(135deg, #7B61FF, #38BDF8) !important;
            border: 0 !important;
            box-shadow: 0 0 14px rgba(123,97,255,.5) !important;
          }}

          /* ----- DataFrame polish ----- */
          [data-testid="stDataFrame"] {{
            border-radius: 12px !important;
            border: 1px solid var(--nr-line) !important;
            overflow: hidden;
            box-shadow: var(--nr-shadow-sm) !important;
          }}

          /* ----- Responsive ----- */
          @media (max-width: 1180px) {{
            section[data-testid="stSidebar"] {{
              width: 220px !important;
              min-width: 220px !important;
            }}
          }}
          @media (max-width: 720px) {{
            .hero h1 {{ font-size: 1.1rem !important; }}
            .hero p {{ font-size: .76rem !important; }}
            .hero-chip {{ font-size: .7rem; padding: .18rem .5rem; }}
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    base_url = str(st.session_state.get("base_url", "")).strip()
    has_api = bool(base_url)
    api_state_label = "API sẵn sàng" if has_api else "Chưa cấu hình API"
    api_state_dot = "🟢" if has_api else "🟡"
    model_label = str(st.session_state.get("manual_model", DEFAULT_MODEL))
    today_label = datetime.now().strftime("%d/%m/%Y • %H:%M")

    key_count = len(
        parse_api_keys_pool(
            st.session_state.get("api_keys_pool_text", ""),
            st.session_state.get("api_key", ""),
        )
    )
    today_slug = date_slug()
    try:
        history_today = sum(
            1
            for item in load_history(limit=600)
            if str(item.get("time", "")).startswith(today_slug)
        )
    except Exception:
        history_today = 0

    chips = [f"{api_state_dot} {html.escape(api_state_label)}"]
    short_model = model_label.split("/")[-1] if "/" in model_label else model_label
    chips.append(f"🧠 {html.escape(short_model)}")
    chips.append(f"🔑 {key_count} key" + (" pool" if key_count > 1 else ""))
    chips.append(f"⚡ {history_today} ảnh hôm nay")
    chips.append(f"📅 {html.escape(today_label)}")

    chip_html = "".join(f'<span class="hero-chip">{c}</span>' for c in chips)
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-row">
            <div class="hero-title">
              <h1>Wahu Image Studio</h1>
              <p>Tạo / sửa ảnh và train LoRA — gọn, nhanh, đẹp.</p>
            </div>
            <div class="hero-meta">{chip_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "app_initialized" in st.session_state:
        ensure_state_defaults()
        return

    load_env_file(Path(DEFAULT_ENV_FILE))
    st.session_state.env_file = DEFAULT_ENV_FILE
    st.session_state.base_url = os.getenv("NINEROUTER_URL", "")
    st.session_state.api_key = os.getenv("NINEROUTER_KEY", "")
    st.session_state.api_keys_pool_text = os.getenv("NINEROUTER_KEYS", "")
    st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
    st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
    st.session_state.config_api_keys_pool_text = st.session_state.api_keys_pool_text
    st.session_state.multi_api_mode = DEFAULT_MULTI_API_MODE
    st.session_state.multi_api_max_parallel = 5
    st.session_state.api_request_timeout = DEFAULT_API_POST_TIMEOUT_SECONDS
    st.session_state.image_retry_count = DEFAULT_IMAGE_RETRY_COUNT
    st.session_state.image_retry_backoff = DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS
    st.session_state.page_name = PAGE_DRAW
    st.session_state.page_name_selector = PAGE_DRAW
    st.session_state.ui_compact_mode = True

    st.session_state.models = []
    st.session_state.model_nonce = 0
    st.session_state.manual_model = DEFAULT_MODEL
    st.session_state.quick_subject = ""
    st.session_state.quick_style = "Không áp phong cách"
    st.session_state.quick_quality_profile = "Cân bằng"
    st.session_state.quick_size_preset = "Vuông 1024"
    st.session_state.quick_aspect_ratio = "1:1"
    st.session_state.quick_response_format = "binary"
    st.session_state.quick_count = 1
    st.session_state.quick_simple_transparent_bg = False
    st.session_state.quick_universal_transparent_bg = False
    st.session_state.quick_remix_transparent_bg = False
    st.session_state.quick_edit_transparent_bg = False

    st.session_state.gen_prompt = ""
    st.session_state.gen_negative_prompt = ""
    st.session_state.gen_style = "Không áp phong cách"
    st.session_state.gen_quality_profile = "Cân bằng"
    st.session_state.gen_size_preset = "Vuông 1024"
    st.session_state.gen_custom_size = ""
    st.session_state.gen_aspect_ratio = "1:1"
    st.session_state.gen_count = 1
    st.session_state.gen_response_format = "binary"
    st.session_state.gen_output_file = f"outputs/out_{timestamp_slug()}.png"
    st.session_state.gen_quality_override = ""
    st.session_state.gen_style_override = ""
    st.session_state.gen_transparent_background = False
    st.session_state.gen_background = ""
    st.session_state.gen_output_format = ""
    st.session_state.gen_image_detail = ""
    st.session_state.gen_sampler = ""
    st.session_state.gen_steps = 40
    st.session_state.gen_guidance_scale = 7.5
    st.session_state.gen_cfg_scale = 7.0
    st.session_state.gen_strength = 0.75
    st.session_state.gen_clip_skip = 1
    st.session_state.gen_seed = ""
    st.session_state.gen_extra_json = "{}"
    st.session_state.studio_top_model = DEFAULT_MODEL
    st.session_state.auto_save_outputs = True
    st.session_state.recent_outputs = []
    st.session_state.recent_view_output_id = ""

    st.session_state.lora_name = f"character_{date_slug().replace('-', '')}"
    st.session_state.lora_trigger_word = "char_token"
    st.session_state.lora_workflow_mode = "Train nhân vật"
    st.session_state.lora_type = "character"
    st.session_state.lora_base_model = DEFAULT_MODEL
    st.session_state.lora_training_preset = "Nhân vật chuẩn"
    st.session_state.lora_steps = 2800
    st.session_state.lora_epochs = 14
    st.session_state.lora_batch_size = 2
    st.session_state.lora_learning_rate = 0.00008
    st.session_state.lora_network_dim = 32
    st.session_state.lora_network_alpha = 16
    st.session_state.lora_resolution = 1024
    st.session_state.lora_caption_dropout = 0.05
    st.session_state.lora_repeats = 12
    st.session_state.lora_seed = 42
    st.session_state.lora_scheduler = "cosine"
    st.session_state.lora_optimizer = "adamw8bit"
    st.session_state.lora_caption_prefix = ""
    st.session_state.lora_caption_suffix = ""
    st.session_state.lora_save_inputs = True
    st.session_state.lora_export_dataset = True
    st.session_state.lora_dataset_source_mode = "Upload ảnh"
    st.session_state.lora_dataset_folder_path = ""
    st.session_state.lora_dataset_scan_recursive = True
    st.session_state.lora_extra_json = "{}"
    st.session_state.lora_train_endpoint = DEFAULT_LORA_TRAIN_ENDPOINT
    st.session_state.lora_status_endpoint = DEFAULT_LORA_STATUS_ENDPOINT
    st.session_state.lora_list_endpoint = DEFAULT_LORA_LIST_ENDPOINT
    st.session_state.lora_cancel_endpoint = DEFAULT_LORA_CANCEL_ENDPOINT
    st.session_state.lora_last_job_id = ""

    st.session_state.last_payload = {}
    st.session_state.last_model_info = {}
    st.session_state.app_initialized = True
    ensure_state_defaults()


def ensure_state_defaults() -> None:
    """Guarantee all session-state keys this app reads exist.

    Called on every run so old browser sessions that were initialized
    by an earlier version of the code don't crash with AttributeError.
    """
    load_env_file(Path(st.session_state.get("env_file", DEFAULT_ENV_FILE)))
    defaults: dict[str, Any] = {
        "env_file": DEFAULT_ENV_FILE,
        "base_url": os.getenv("NINEROUTER_URL", ""),
        "api_key": os.getenv("NINEROUTER_KEY", ""),
        "api_keys_pool_text": os.getenv("NINEROUTER_KEYS", ""),
        "quick_api_keys_pool_text": "",
        "studio_api_keys_pool_text": "",
        "config_api_keys_pool_text": "",
        "multi_api_mode": DEFAULT_MULTI_API_MODE,
        "multi_api_max_parallel": 5,
        "api_request_timeout": DEFAULT_API_POST_TIMEOUT_SECONDS,
        "image_retry_count": DEFAULT_IMAGE_RETRY_COUNT,
        "image_retry_backoff": DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS,
        "page_name": PAGE_DRAW,
        "page_name_selector": PAGE_DRAW,
        "ui_compact_mode": True,
        "models": [],
        "model_nonce": 0,
        "manual_model": DEFAULT_MODEL,
        "studio_top_model": DEFAULT_MODEL,
        "studio_response_format": "binary",
        "studio_count": 1,
        "studio_output_prefix": "outputs/result",
        "auto_save_outputs": True,
        "recent_outputs": [],
        "recent_view_output_id": "",
        "quick_subject": "",
        "quick_style": "Không áp phong cách",
        "quick_quality_profile": "Cân bằng",
        "quick_size_preset": "Vuông 1024",
        "quick_aspect_ratio": "1:1",
        "quick_response_format": "binary",
        "quick_count": 1,
        "quick_simple_transparent_bg": False,
        "quick_universal_transparent_bg": False,
        "quick_remix_transparent_bg": False,
        "quick_edit_transparent_bg": False,
        "gen_prompt": "",
        "gen_negative_prompt": "",
        "gen_style": "Không áp phong cách",
        "gen_quality_profile": "Cân bằng",
        "gen_size_preset": "Vuông 1024",
        "gen_custom_size": "",
        "gen_aspect_ratio": "1:1",
        "gen_count": 1,
        "gen_response_format": "binary",
        "gen_quality_override": "",
        "gen_style_override": "",
        "gen_transparent_background": False,
        "gen_background": "",
        "gen_output_format": "",
        "gen_image_detail": "",
        "gen_sampler": "",
        "gen_steps": 40,
        "gen_guidance_scale": 7.5,
        "gen_cfg_scale": 7.0,
        "gen_strength": 0.75,
        "gen_clip_skip": 1,
        "gen_seed": "",
        "gen_extra_json": "{}",
        "lora_name": f"character_{date_slug().replace('-', '')}",
        "lora_trigger_word": "char_token",
        "lora_workflow_mode": "Train nhân vật",
        "lora_type": "character",
        "lora_base_model": DEFAULT_MODEL,
        "lora_training_preset": "Nhân vật chuẩn",
        "lora_steps": 2800,
        "lora_epochs": 14,
        "lora_batch_size": 2,
        "lora_learning_rate": 0.00008,
        "lora_network_dim": 32,
        "lora_network_alpha": 16,
        "lora_resolution": 1024,
        "lora_caption_dropout": 0.05,
        "lora_repeats": 12,
        "lora_seed": 42,
        "lora_scheduler": "cosine",
        "lora_optimizer": "adamw8bit",
        "lora_caption_prefix": "",
        "lora_caption_suffix": "",
        "lora_save_inputs": True,
        "lora_export_dataset": True,
        "lora_dataset_source_mode": "Upload ảnh",
        "lora_dataset_folder_path": "",
        "lora_dataset_scan_recursive": True,
        "lora_extra_json": "{}",
        "lora_train_endpoint": DEFAULT_LORA_TRAIN_ENDPOINT,
        "lora_status_endpoint": DEFAULT_LORA_STATUS_ENDPOINT,
        "lora_list_endpoint": DEFAULT_LORA_LIST_ENDPOINT,
        "lora_cancel_endpoint": DEFAULT_LORA_CANCEL_ENDPOINT,
        "lora_last_job_id": "",
        "last_payload": {},
        "last_model_info": {},
    }
    if "gen_output_file" not in st.session_state:
        defaults["gen_output_file"] = f"outputs/out_{timestamp_slug()}.png"
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    env_base_url = os.getenv("NINEROUTER_URL", "").strip()
    env_api_key = os.getenv("NINEROUTER_KEY", "").strip()
    env_key_pool = os.getenv("NINEROUTER_KEYS", "").strip()
    current_base_url = str(st.session_state.get("base_url", "")).strip()
    if env_base_url and (
        not current_base_url
        or current_base_url.startswith("http://localhost:20128")
        or (is_cpab_base_url(env_base_url) and not is_cpab_base_url(current_base_url))
    ):
        st.session_state.base_url = env_base_url
        st.session_state.config_base_url = env_base_url
    if env_api_key and st.session_state.get("api_key") != env_api_key:
        st.session_state.api_key = env_api_key
        st.session_state.config_api_key = env_api_key
    if env_key_pool and st.session_state.get("api_keys_pool_text") != env_key_pool:
        st.session_state.api_keys_pool_text = env_key_pool
        st.session_state.quick_api_keys_pool_text = env_key_pool
        st.session_state.studio_api_keys_pool_text = env_key_pool
        st.session_state.config_api_keys_pool_text = env_key_pool

    if is_cpab_base_url(str(st.session_state.get("base_url", ""))):
        allowed_chat = {item.lower() for item in CPAB_CHAT_MODELS}
        for model_key in ("manual_model", "studio_top_model"):
            if str(st.session_state.get(model_key, "")).strip().lower() not in allowed_chat:
                st.session_state[model_key] = DEFAULT_MODEL
        st.session_state.models = CPAB_CHAT_MODELS.copy()

    if not st.session_state.quick_api_keys_pool_text:
        st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
    if not st.session_state.studio_api_keys_pool_text:
        st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
    if not st.session_state.config_api_keys_pool_text:
        st.session_state.config_api_keys_pool_text = st.session_state.api_keys_pool_text


def navigate_to_page(page_name: str) -> None:
    st.session_state.page_name = page_name
    st.rerun()


# ===== Flow / Provider switcher (được thêm tự động) =====
FLOW_PROXY_PORT = 8790
FLOW_PROXY_URL = "http://localhost:8790"
FLOW_PROXY_BAT = r"D:\TOOL\TOOL Anh\run_flow_proxy.bat"

PROVIDERS = {
    "flow": {
        "label": "\U0001F30A Flow (Veo \u00B7 Nano Banana)",
        "base_url": FLOW_PROXY_URL,
        "default_model": "NARWHAL",
        "desc": "Google Labs Flow qua Brave (proxy n\u1ED9i b\u1ED9 c\u1ED5ng 8790).",
    },
    "gemini": {
        "label": "\U0001F537 Gemini (ch\u00EDnh th\u1EE9c)",
        "base_url": "http://localhost:8788",
        "default_model": "gemini-2.5-flash-image",
        "desc": "Gemini API ch\u00EDnh th\u1EE9c qua proxy (c\u1ED5ng 8788).",
    },
    "9router": {
        "label": "\U0001F7E3 9Router / OpenAI",
        "base_url": os.getenv("NINEROUTER_URL", "http://localhost:20128") or "http://localhost:20128",
        "default_model": "gpt-image-2",
        "desc": "Ngu\u1ED3n OpenAI-compatible m\u1EB7c \u0111\u1ECBnh.",
    },
}


def detect_provider(base_url: str) -> str:
    u = str(base_url or "").strip().lower()
    if "8790" in u:
        return "flow"
    if "8788" in u:
        return "gemini"
    return "9router"


def flow_proxy_running() -> bool:
    try:
        with request.urlopen(f"{FLOW_PROXY_URL}/api/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def start_flow_proxy() -> bool:
    if flow_proxy_running():
        return True
    if not os.path.exists(FLOW_PROXY_BAT):
        return False
    try:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen([FLOW_PROXY_BAT], creationflags=flags)
        return True
    except Exception:
        return False


def connect_provider(key: str) -> tuple[bool, str]:
    cfg = PROVIDERS.get(key)
    if not cfg:
        return False, "Provider kh\u00F4ng h\u1EE3p l\u1EC7"
    st.session_state.base_url = cfg["base_url"]
    st.session_state.config_base_url = cfg["base_url"]
    try:
        ok, msg = load_models_into_state(cfg["base_url"], st.session_state.get("api_key", ""))
    except Exception as ex:
        return False, str(ex)
    models = [m for m in st.session_state.get("models", []) if isinstance(m, str)]
    dm = cfg.get("default_model")
    if dm and dm in models:
        st.session_state.manual_model = dm
    elif models:
        st.session_state.manual_model = models[0]
    elif dm:
        st.session_state.manual_model = dm
    return ok, msg


def _on_provider_change() -> None:
    key = st.session_state.get("provider_choice")
    cfg = PROVIDERS.get(key)
    if not cfg:
        return
    st.session_state.base_url = cfg["base_url"]
    st.session_state.config_base_url = cfg["base_url"]
    dm = cfg.get("default_model")
    if dm:
        st.session_state.manual_model = dm
    # Dong bo model ve art theo nguon
    if key == "flow":
        st.session_state["tutienco_art_model"] = "NARWHAL"
    elif key == "gemini":
        st.session_state["tutienco_art_model"] = "gemini-2.5-flash-image"
    else:
        st.session_state["tutienco_art_model"] = "cx/gpt-5.4-image"
    # Thu nap model (khong chan neu nguon chua san sang)
    try:
        load_models_into_state(cfg["base_url"], st.session_state.get("api_key", ""))
    except Exception:
        pass


def sidebar_settings() -> tuple[str, str]:
    with st.sidebar:
        page_options = list(PAGE_OPTIONS)
        if st.session_state.page_name not in page_options:
            st.session_state.page_name = PAGE_DRAW
        if st.session_state.get("page_name_selector") not in page_options:
            st.session_state.page_name_selector = st.session_state.page_name

        nav_label_map = {
            PAGE_DRAW: "🎨  Tạo ảnh",
            PAGE_HOME: "🏠  Tổng quan",
            PAGE_GALLERY: "🖼️  Thư viện",
            PAGE_TRAIN: "🧬  Train LoRA",
            PAGE_MODEL: "🧠  Model",
            PAGE_CONFIG: "⚙️  Cài đặt",
        }
        ordered_pages = [PAGE_DRAW, PAGE_HOME, PAGE_GALLERY, PAGE_TRAIN, PAGE_MODEL, PAGE_CONFIG]
        menu_options = [item for item in ordered_pages if item in page_options]
        if st.session_state.get("page_name_selector") not in menu_options:
            st.session_state.page_name_selector = (
                st.session_state.page_name if st.session_state.page_name in menu_options else menu_options[0]
            )

        st.markdown(
            """
            <div class="nr-brand">
              <div class="nr-brand-logo">W</div>
              <div class="nr-brand-text">
                <div class="nr-brand-title">Wahu Studio</div>
                <div class="nr-brand-sub">AI Image Generator</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_page = st.radio(
            "Điều hướng",
            options=menu_options,
            key="page_name_selector",
            label_visibility="collapsed",
            format_func=lambda value: nav_label_map.get(value, value),
        )
        if selected_page != st.session_state.page_name:
            st.session_state.page_name = selected_page

        st.markdown("<div class='nr-sidebar-divider'></div>", unsafe_allow_html=True)
        st.toggle(
            "Giao diện gọn",
            key="ui_compact_mode",
            help="Bật chế độ compact để giảm khoảng cách giữa các thành phần.",
        )

        configured = "🟢 Đã cấu hình" if str(st.session_state.base_url).strip() else "🟡 Chưa cấu hình"
        st.caption(f"API: {configured}")
        current_model = str(st.session_state.get("manual_model", DEFAULT_MODEL)).strip()
        if current_model:
            short_model = current_model.split("/")[-1] if "/" in current_model else current_model
            st.caption(f"Model: `{short_model}`")

        with st.expander("Cấu hình API nhanh", expanded=False):
            st.text_input("Tệp env", key="env_file")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Nạp", use_container_width=True, key="btn_sidebar_load_env"):
                    load_env_file(Path(st.session_state.env_file))
                    st.session_state.base_url = os.getenv("NINEROUTER_URL", "")
                    st.session_state.api_key = os.getenv("NINEROUTER_KEY", "")
                    st.session_state.api_keys_pool_text = os.getenv(
                        "NINEROUTER_KEYS", st.session_state.get("api_keys_pool_text", "")
                    )
                    st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
                    st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
                    st.session_state.config_api_keys_pool_text = st.session_state.api_keys_pool_text
                    st.success("Đã nạp env")
            with c2:
                if st.button("Lưu", use_container_width=True, key="btn_sidebar_save_env"):
                    save_env_file(
                        Path(st.session_state.env_file),
                        st.session_state.base_url,
                        st.session_state.api_key,
                        st.session_state.get("api_keys_pool_text", ""),
                    )
                    st.success("Đã lưu env")

            key_count = len(
                parse_api_keys_pool(
                    st.session_state.get("api_keys_pool_text", ""),
                    st.session_state.get("api_key", ""),
                )
            )
            st.caption(f"Tổng số key: {key_count}")
            if st.button("Mở Cài đặt đầy đủ", use_container_width=True, key="btn_sidebar_open_config_api"):
                navigate_to_page(PAGE_CONFIG)

        # ----- Provider switcher (Ngu\u1ED3n \u1EA3nh AI) -----
        _cur_prov = detect_provider(st.session_state.get("base_url", ""))
        _prov_keys = list(PROVIDERS.keys())
        with st.expander(f"\U0001F50C Ngu\u1ED3n \u1EA3nh AI \u00B7 {PROVIDERS[_cur_prov]['label']}", expanded=False):
            _sel = st.radio(
                "Ch\u1ECDn ngu\u1ED3n \u1EA3nh",
                options=_prov_keys,
                index=_prov_keys.index(_cur_prov),
                format_func=lambda k: PROVIDERS[k]["label"],
                key="provider_choice",
                on_change=_on_provider_change,
                label_visibility="collapsed",
            )
            st.caption(PROVIDERS[_sel]["desc"])

            if _sel == "flow":
                if flow_proxy_running():
                    st.markdown("<div style='color:#16a34a;font-weight:600;margin:2px 0'>\U0001F7E2 Flow proxy \u0111ang ch\u1EA1y</div>", unsafe_allow_html=True)
                    _b1, _b2 = st.columns(2)
                    if _b1.button("D\u00F9ng Flow", use_container_width=True, key="btn_prov_use_flow"):
                        _ok, _msg = connect_provider("flow")
                        (st.success if _ok else st.error)(_msg)
                    if _b2.button("\u21BB N\u1EA1p model", use_container_width=True, key="btn_prov_flow_reload"):
                        _ok, _msg = load_models_into_state(FLOW_PROXY_URL, "")
                        (st.success if _ok else st.error)(_msg)
                else:
                    st.markdown("<div style='color:#dc2626;font-weight:600;margin:2px 0'>\U0001F534 Flow proxy ch\u01B0a ch\u1EA1y</div>", unsafe_allow_html=True)
                    if st.button("\U0001F680 B\u1EADt Flow & m\u1EDF Brave", type="primary", use_container_width=True, key="btn_prov_start_flow"):
                        if start_flow_proxy():
                            st.session_state.base_url = FLOW_PROXY_URL
                            st.session_state.manual_model = "NARWHAL"
                            st.info("\u0110ang b\u1EADt Flow + m\u1EDF Brave (~20s). Khi proxy s\u1EB5n s\u00E0ng b\u1EA5m 'D\u00F9ng Flow' r\u1ED3i '\u21BB N\u1EA1p model'.")
                        else:
                            st.error("Kh\u00F4ng b\u1EADt \u0111\u01B0\u1EE3c proxy (ki\u1EC3m tra run_flow_proxy.bat).")
            else:
                st.caption(f"Base URL: `{PROVIDERS[_sel]['base_url']}`")
                if st.button("K\u1EBFt n\u1ED1i", type="primary", use_container_width=True, key=f"btn_prov_connect_{_sel}"):
                    _ok, _msg = connect_provider(_sel)
                    (st.success if _ok else st.error)(_msg)

            _models = [m for m in st.session_state.get("models", []) if isinstance(m, str)]
            if _models:
                st.markdown(
                    "<div style='margin-top:6px;font-size:0.82rem;color:#475569'>\u2705 <b>"
                    + str(len(_models)) + "</b> model: " + ", ".join(_models[:10]) + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Ch\u01B0a n\u1EA1p model \u2014 b\u1EA5m K\u1EBFt n\u1ED1i / N\u1EA1p model.")

        # ----- Live status footer -----
        try:
            today_slug = date_slug()
            today_count = sum(
                1
                for item in load_history(limit=600)
                if str(item.get("time", "")).startswith(today_slug)
            )
        except Exception:
            today_count = 0
        try:
            outputs_dir = Path("outputs")
            outputs_size = 0
            if outputs_dir.exists():
                for p in outputs_dir.rglob("*"):
                    if p.is_file():
                        try:
                            outputs_size += p.stat().st_size
                        except Exception:
                            continue
            if outputs_size >= 1024 ** 3:
                outputs_label = f"{outputs_size / (1024 ** 3):.2f} GB"
            elif outputs_size >= 1024 ** 2:
                outputs_label = f"{outputs_size / (1024 ** 2):.0f} MB"
            elif outputs_size >= 1024:
                outputs_label = f"{outputs_size / 1024:.0f} KB"
            else:
                outputs_label = f"{outputs_size} B"
        except Exception:
            outputs_label = "—"

        api_pool_text = st.session_state.get("api_keys_pool_text", "")
        pool_count = len(parse_api_keys_pool(api_pool_text, st.session_state.get("api_key", "")))
        api_dot_class = "nr-st-ok" if str(st.session_state.base_url).strip() else "nr-st-warn"
        api_dot_label = "Online" if str(st.session_state.base_url).strip() else "Chưa nối"
        st.markdown(
            f"""
            <div class="nr-sidebar-status">
              <div class="nr-st-row">
                <span><span class="nr-st-dot {api_dot_class}"></span>API</span>
                <b>{html.escape(api_dot_label)}</b>
              </div>
              <div class="nr-st-row"><span>🔑 Key pool</span><b>{pool_count}</b></div>
              <div class="nr-st-row"><span>⚡ Ảnh hôm nay</span><b>{today_count}</b></div>
              <div class="nr-st-row"><span>💽 Outputs</span><b>{outputs_label}</b></div>
              <div class="nr-st-row"><span>🕒</span><b>{datetime.now().strftime("%H:%M")}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return st.session_state.page_name, st.session_state.base_url


def selected_model_widget(prefix: str) -> str:
    models = unique_list(st.session_state.models)
    mode_col, search_col = st.columns([1.15, 1.85], gap="medium")
    with mode_col:
        model_mode = st.radio(
            "Chọn model",
            options=["Gợi ý", "Danh sách đầy đủ", "Nhập tay"],
            horizontal=True,
            key=f"{prefix}_model_mode",
        )

    if model_mode == "Nhập tay":
        model = st.text_input("Mã model", value=st.session_state.manual_model, key=f"{prefix}_manual_model")
        st.session_state.manual_model = model
        return model

    if model_mode == "Gợi ý":
        source = unique_list(MODEL_TOP_PRIORITY + MODEL_RECOMMENDED + models)
    else:
        source = models

    with search_col:
        search = st.text_input(
            "Lọc model",
            value="",
            key=f"{prefix}_model_search",
            placeholder="Ví dụ: gpt-5.4-image",
        )
    if search.strip():
        term = search.strip().lower()
        source = [item for item in source if term in item.lower()]

    if not source:
        st.warning("Không có model phù hợp bộ lọc, hãy đổi từ khóa hoặc chuyển sang Nhập tay.")
        model = st.text_input("Mã model", value=st.session_state.manual_model, key=f"{prefix}_manual_fallback")
        st.session_state.manual_model = model
        return model

    index = 0
    if st.session_state.manual_model in source:
        index = source.index(st.session_state.manual_model)
    model = st.selectbox("Model", options=source, index=index, key=f"{prefix}_model")
    st.session_state.manual_model = model
    return model


def response_format_widget(label: str, key: str, index: int = 0) -> str:
    return st.selectbox(
        label,
        options=RESPONSE_FORMAT_OPTIONS,
        index=index,
        key=key,
        format_func=lambda value: RESPONSE_FORMAT_LABELS.get(value, value),
    )


def pill_single_select(label: str, options: list[str], key: str, default: str | None = None) -> str:
    selected_default = default if default in options else (options[0] if options else "")
    if hasattr(st, "pills"):
        if key in st.session_state and st.session_state.get(key) not in options:
            st.session_state[key] = selected_default
        pill_kwargs: dict[str, Any] = {
            "options": options,
            "selection_mode": "single",
            "key": key,
        }
        if key not in st.session_state:
            pill_kwargs["default"] = selected_default
        selected = st.pills(label, **pill_kwargs)
        if isinstance(selected, str):
            return selected
        return selected_default
    index = options.index(selected_default) if selected_default in options else 0
    return st.radio(label, options=options, index=index, horizontal=True, key=key)


def pill_multi_select(label: str, options: list[str], key: str, default: list[str] | None = None) -> list[str]:
    picked_default = [item for item in (default or []) if item in options]
    if hasattr(st, "pills"):
        if key in st.session_state:
            current_value = st.session_state.get(key)
            if isinstance(current_value, list):
                st.session_state[key] = [item for item in current_value if item in options]
        pill_kwargs: dict[str, Any] = {
            "options": options,
            "selection_mode": "multi",
            "key": key,
        }
        if key not in st.session_state:
            pill_kwargs["default"] = picked_default
        selected = st.pills(label, **pill_kwargs)
        if isinstance(selected, list):
            return [item for item in selected if item in options]
        return picked_default
    return st.multiselect(label, options=options, default=picked_default, key=key)


def resolve_size() -> str:
    if st.session_state.gen_size_preset == "Tùy chỉnh":
        return st.session_state.gen_custom_size.strip()
    return SIZE_PRESETS.get(st.session_state.gen_size_preset, "").strip()


def build_payload(model: str, prompt: str, include_advanced: bool, response_format: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model.strip(), "prompt": prompt.strip(), "n": int(st.session_state.gen_count)}
    size = resolve_size()
    if size:
        payload["size"] = size

    quality_value = st.session_state.gen_quality_override.strip() or str(
        QUALITY_PROFILES.get(st.session_state.gen_quality_profile, {}).get("quality", "")
    ).strip()
    if quality_value:
        payload["quality"] = quality_value

    style_value = st.session_state.gen_style_override.strip() or str(
        STYLE_PRESETS.get(st.session_state.gen_style, {}).get("style", "")
    ).strip()
    if style_value:
        payload["style"] = style_value

    if response_format in {"url", "b64_json"}:
        payload["response_format"] = response_format

    negative = st.session_state.gen_negative_prompt.strip()
    if st.session_state.quick_auto_negative and not negative:
        negative = str(STYLE_PRESETS.get(st.session_state.gen_style, {}).get("negative_prompt", "")).strip()
    if negative:
        payload["negative_prompt"] = negative

    aspect_ratio_value = st.session_state.gen_aspect_ratio.strip()
    if aspect_ratio_value and aspect_ratio_value != ASPECT_RATIO_ORIGINAL:
        payload["aspect_ratio"] = aspect_ratio_value

    if include_advanced:
        if st.session_state.gen_seed.strip():
            payload["seed"] = int(st.session_state.gen_seed.strip())
        payload["steps"] = int(st.session_state.gen_steps)
        payload["guidance_scale"] = float(st.session_state.gen_guidance_scale)
        payload["cfg_scale"] = float(st.session_state.gen_cfg_scale)
        payload["strength"] = float(st.session_state.gen_strength)
        payload["clip_skip"] = int(st.session_state.gen_clip_skip)
        if st.session_state.gen_background:
            payload["background"] = st.session_state.gen_background
        if st.session_state.gen_output_format:
            payload["output_format"] = st.session_state.gen_output_format
        if st.session_state.gen_image_detail:
            payload["image_detail"] = st.session_state.gen_image_detail
        if st.session_state.gen_sampler:
            payload["sampler"] = st.session_state.gen_sampler

    extra = parse_json_object(st.session_state.gen_extra_json)
    payload.update(extra)
    apply_transparent_background_request(payload, bool(st.session_state.get("gen_transparent_background", False)))
    return payload


def add_recent_output(item: dict[str, Any]) -> None:
    recent = [entry for entry in st.session_state.get("recent_outputs", []) if isinstance(entry, dict)]
    item_id = str(item.get("id", "")).strip() or f"out_{timestamp_slug()}_{random.randint(1000, 9999)}"
    existing_ids = {str(entry.get("id", "")).strip() for entry in recent}
    while item_id in existing_ids:
        item_id = f"out_{timestamp_slug()}_{random.randint(1000, 9999)}"
    item["id"] = item_id
    recent = [entry for entry in recent if str(entry.get("id", "")) != item_id]
    recent.insert(0, item)
    st.session_state.recent_outputs = recent[:24]


def remove_recent_output(item_id: str) -> bool:
    target = str(item_id).strip()
    if not target:
        return False
    removed = False
    kept: list[dict[str, Any]] = []
    for entry in st.session_state.get("recent_outputs", []):
        if not isinstance(entry, dict):
            continue
        current_id = str(entry.get("id", "")).strip()
        if current_id != target:
            kept.append(entry)
            continue
        removed = True
        local_path = str(entry.get("local_path", "")).strip()
        if local_path:
            path = Path(local_path)
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
    st.session_state.recent_outputs = kept
    if st.session_state.get("recent_view_output_id", "") == target:
        st.session_state.recent_view_output_id = ""
    return removed


def render_recent_outputs_strip() -> None:
    recent = [entry for entry in st.session_state.get("recent_outputs", []) if isinstance(entry, dict)]
    st.markdown("#### Kết quả gần đây")

    if not recent:
        st.markdown(
            """
            <div class="panel-card" style="min-height: 220px; display: grid; place-items: center; text-align: center;">
              <div>
                <h4>Chưa có ảnh nào</h4>
                <p>Kết quả tạo ảnh sẽ xuất hiện ở đây sau khi bạn nhấn Tạo ảnh.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    show_items = recent[:12]
    cols = st.columns(2, gap="medium")
    for idx, entry in enumerate(show_items):
        entry_id = str(entry.get("id", "")).strip() or f"idx_{idx}"
        widget_id = f"{entry_id}_{idx}"
        with cols[idx % 2]:
            local_path = str(entry.get("local_path", "")).strip()
            url = str(entry.get("url", "")).strip()
            image_bytes = entry.get("image_bytes", b"")

            if local_path and Path(local_path).exists():
                st.image(local_path, use_container_width=True)
            elif isinstance(image_bytes, bytes) and image_bytes:
                st.image(image_bytes, use_container_width=True)
            elif url:
                st.image(url, use_container_width=True)
            else:
                st.markdown("<div class='panel-card'>Không có preview</div>", unsafe_allow_html=True)

            alpha_label = transparency_check_label(
                entry.get("transparent_check"),
                requested=bool(entry.get("transparent_requested")),
            )
            if alpha_label:
                st.caption(alpha_label)

            stamp = str(entry.get("time", ""))[-8:]
            model_name = str(entry.get("model", ""))
            st.caption(f"{model_name} • {stamp}")
            view_col, open_col = st.columns(2)
            with view_col:
                if st.button("🔍 Phóng to", key=f"btn_recent_view_{widget_id}", use_container_width=True):
                    st.session_state.recent_view_output_id = entry_id
            with open_col:
                if local_path and Path(local_path).exists():
                    if st.button("📂 Mở", key=f"btn_recent_open_{widget_id}", use_container_width=True, help="Mở thư mục chứa ảnh"):
                        try:
                            folder = Path(local_path).parent
                            if sys.platform.startswith("win"):
                                os.startfile(str(folder))  # type: ignore[attr-defined]
                            else:
                                subprocess.Popen(["xdg-open", str(folder)])
                            st.toast(f"Đã mở: {folder}")
                        except Exception as ex:
                            st.warning(f"Không mở được: {ex}")

    view_id = str(st.session_state.get("recent_view_output_id", "")).strip()
    if not view_id:
        return

    selected = next((item for item in recent if str(item.get("id", "")).strip() == view_id), None)
    if not selected:
        return

    with st.expander("Xem ảnh lớn", expanded=True):
        local_path = str(selected.get("local_path", "")).strip()
        url = str(selected.get("url", "")).strip()
        image_bytes = selected.get("image_bytes", b"")
        if local_path and Path(local_path).exists():
            st.image(local_path, use_container_width=True)
        elif isinstance(image_bytes, bytes) and image_bytes:
            st.image(image_bytes, use_container_width=True)
        elif url:
            st.image(url, use_container_width=True)
        alpha_label = transparency_check_label(
            selected.get("transparent_check"),
            requested=bool(selected.get("transparent_requested")),
        )
        if alpha_label:
            st.caption(alpha_label)
        prompt_text = str(selected.get("prompt", "")).strip()
        if prompt_text:
            st.code(prompt_text)
        if st.button("Đóng", key=f"btn_recent_close_{view_id}"):
            st.session_state.recent_view_output_id = ""


def render_generate_result(
    result: dict[str, Any],
    model: str,
    prompt: str,
    response_format: str,
    output_file: str,
    show_inline_preview: bool = True,
    download_key_suffix: str = "",
) -> None:
    history = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "prompt": prompt,
        "response_format": response_format,
        "result_kind": result.get("kind", "unknown"),
    }

    if result["kind"] in {"binary", "b64_json"}:
        image_bytes: bytes = result["image_bytes"]
        transparent_check = result.get("transparent_check")
        if not isinstance(transparent_check, dict):
            transparent_check = inspect_image_transparency(image_bytes)
        transparent_requested = bool(result.get("transparent_requested"))
        saved_path = ""
        raw_chroma_path = ""
        if bool(st.session_state.get("auto_save_outputs", True)):
            final_file = output_file
            if Path(final_file).suffix == "":
                final_file += infer_ext(result.get("content_type", ""))
            saved = save_image(image_bytes, final_file)
            saved_path = str(saved)
            raw_chroma_bytes = result.get("raw_chroma_image_bytes")
            if isinstance(raw_chroma_bytes, bytes) and raw_chroma_bytes:
                raw_saved = save_image(raw_chroma_bytes, build_raw_chroma_output_path(final_file))
                raw_chroma_path = str(raw_saved)
            if show_inline_preview:
                st.success(f"Đã lưu ảnh: {saved}")
                if raw_chroma_path:
                    st.caption(f"Đã lưu bản gốc nền chroma: {raw_chroma_path}")
            history["local_path"] = saved_path
            if raw_chroma_path:
                history["raw_chroma_path"] = raw_chroma_path
        elif show_inline_preview:
            st.info("Ảnh chưa lưu vào máy (đang tắt lưu tự động).")

        if show_inline_preview:
            st.image(image_bytes, caption="Ảnh vừa tạo (thumbnail)", width=260)
            render_transparency_check(transparent_check, requested=transparent_requested)
            with st.expander("Xem ảnh lớn", expanded=False):
                st.image(image_bytes, use_container_width=True)

            download_name = Path(saved_path).name if saved_path else f"generated_{timestamp_slug()}.png"
            download_key = f"download_img_{download_key_suffix}" if download_key_suffix else None
            st.download_button("Tải ảnh xuống", data=image_bytes, file_name=download_name, mime="image/png", key=download_key)

        add_recent_output(
            {
                "time": history["time"],
                "model": model,
                "prompt": prompt,
                "kind": "binary",
                "local_path": saved_path,
                "raw_chroma_path": raw_chroma_path,
                "url": "",
                "image_bytes": b"" if saved_path else image_bytes,
                "transparent_check": transparent_check,
                "transparent_requested": transparent_requested,
            }
        )
    elif result["kind"] == "url":
        url = result["url"]
        if show_inline_preview:
            st.image(url, caption="Ảnh từ URL (thumbnail)", width=260)
            with st.expander("Xem ảnh lớn", expanded=False):
                st.image(url, use_container_width=True)
            st.code(url)
        history["url"] = url
        add_recent_output(
            {
                "time": history["time"],
                "model": model,
                "prompt": prompt,
                "kind": "url",
                "local_path": "",
                "url": url,
                "image_bytes": b"",
            }
        )
    else:
        st.warning("Phản hồi không có dữ liệu ảnh rõ ràng. Hiển thị JSON thô.")

    if result.get("raw") is not None and True:
        with st.expander("Xem JSON phản hồi"):
            st.json(result["raw"])

    append_history(history)


def trigger_generate(base_url: str, api_key: str, model: str, prompt: str, response_format: str, output_file: str, include_advanced: bool) -> None:
    if not model.strip():
        st.error("Model đang trống.")
        return
    if not prompt.strip():
        st.error("Prompt đang trống.")
        return

    try:
        payload = build_payload(model=model, prompt=prompt, include_advanced=include_advanced, response_format=response_format)
    except Exception as ex:
        st.error(f"Payload không hợp lệ: {ex}")
        return

    st.session_state.last_payload = payload
    if True:
        with st.expander("Payload sẽ gửi"):
            st.json(payload)

    with st.spinner("Đang gọi 9Router tạo ảnh..."):
        try:
            result = generate_image_with_retry(
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                response_format=response_format,
                timeout_seconds=resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout")),
                retry_count=resolve_image_retry_count(st.session_state.get("image_retry_count")),
                retry_backoff_seconds=resolve_image_retry_backoff_seconds(st.session_state.get("image_retry_backoff")),
                task_label="Trigger generate",
            )
        except Exception as ex:
            st.error(str(ex))
            return

    render_generate_result(result, model, prompt, response_format, output_file)


def page_home(base_url: str, api_key: str) -> None:
    compact_mode = bool(st.session_state.get("ui_compact_mode", True))
    ok, health_data = health_check(base_url, api_key)
    history = load_history(limit=600)
    lora_history = load_lora_history(limit=600)
    today = date_slug()
    total_jobs = len(history)
    local_jobs = len([item for item in history if item.get("local_path")])
    today_jobs = len([item for item in history if str(item.get("time", "")).startswith(today)])
    unique_models = len({str(item.get("model", "")) for item in history if str(item.get("model", "")).strip()})
    lora_jobs = len([item for item in lora_history if str(item.get("action", "")) == "submit"])

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("API", "Hoạt động" if ok else "Lỗi")
    with m2:
        st.metric("Ảnh hôm nay", str(today_jobs))
    with m3:
        st.metric("Ảnh đã lưu", str(local_jobs))
    with m4:
        st.metric("Model đã dùng", str(unique_models if unique_models else total_jobs))
    with m5:
        st.metric("Job LoRA", str(lora_jobs))

    if not ok:
        with st.expander("Chi tiết lỗi kết nối", expanded=False):
            st.code(str(health_data))

    # ----- 7-day activity sparkline -----
    try:
        from collections import Counter

        day_counts: Counter = Counter()
        for item in history:
            day = str(item.get("time", ""))[:10]
            if day:
                day_counts[day] += 1
        recent_days: list[str] = []
        from datetime import timedelta as _td

        base_day = datetime.now()
        for offset in range(6, -1, -1):
            recent_days.append((base_day - _td(days=offset)).strftime("%Y-%m-%d"))
        if any(day_counts.get(d, 0) for d in recent_days):
            max_val = max(day_counts.get(d, 0) for d in recent_days) or 1
            bars_html = []
            for d in recent_days:
                v = day_counts.get(d, 0)
                pct = int(round(v / max_val * 100))
                short = d[5:]
                bars_html.append(
                    f"""
                    <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:.18rem;">
                      <div style="height:54px;width:18px;background:rgba(255,255,255,.04);border-radius:6px;display:flex;align-items:flex-end;overflow:hidden;border:1px solid var(--nr-line);">
                        <div style="width:100%;height:{pct}%;background:linear-gradient(180deg,#7B61FF 0%,#38BDF8 100%);box-shadow:0 0 8px rgba(123,97,255,.5);"></div>
                      </div>
                      <div style="font-size:.66rem;color:var(--nr-text-mute);">{short}</div>
                      <div style="font-size:.74rem;color:var(--nr-text-soft);font-weight:700;">{v}</div>
                    </div>
                    """
                )
            st.markdown(
                """
                <div class="nr-dash-tile" style="margin-top:.4rem;">
                  <div class="nr-dash-label">Hoạt động 7 ngày</div>
                  <div style="display:flex;align-items:flex-end;gap:.42rem;margin-top:.5rem;">
                """
                + "".join(bars_html)
                + "</div></div>",
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # Cảnh báo dung lượng outputs nếu lớn (>2GB).
    try:
        outputs_dir = Path("outputs")
        if outputs_dir.exists():
            total_bytes = 0
            for p in outputs_dir.rglob("*"):
                if p.is_file():
                    total_bytes += p.stat().st_size
            size_gb = total_bytes / (1024 ** 3)
            if size_gb >= 2.0:
                st.warning(
                    f"Thư mục `outputs/` đang dùng {size_gb:.2f} GB. Dùng nút 'Mở thư mục' trong Thư viện để dọn nếu cần."
                )
    except Exception:
        pass

    # Nút bắt đầu nhanh — dẫn thẳng vào Studio với tác vụ tương ứng.
    st.markdown("#### Bắt đầu nhanh")
    quick_actions = [
        ("🖌 Tạo ảnh", "Tạo ảnh"),
        ("⚡ AI đa năng", "AI đa năng (copy ảnh + lệnh tự do)"),
        ("📚 Làm truyện", "Làm truyện tranh"),
        ("🛠 Sửa ảnh", "Sửa ảnh"),
        ("🧠 Tách nền auto", "Phân tích & tách nền"),
        ("🟩 Xóa nền xanh", "Xóa nền chroma"),
        ("✨ Nâng cấp", "Nâng cấp chất lượng"),
        ("🌐 Dịch ảnh", "Dịch ảnh"),
        ("🎨 Sao chép phong cách", "Sao chép phong cách"),
        ("🎮 Asset game", "Vẽ asset game (không nền)"),
        ("🐉 Art Tu Tiên Cờ", "Vẽ art game Tu Tiên Cờ"),
    ]
    quick_cols = st.columns(4)
    for idx, (label, op_value) in enumerate(quick_actions):
        with quick_cols[idx % 4]:
            if st.button(label, use_container_width=True, key=f"btn_home_quick_{idx}"):
                st.session_state.quick_operation = op_value
                navigate_to_page(PAGE_DRAW)

    # ----- Top models used (this week) -----
    try:
        from collections import Counter as _C

        from datetime import timedelta as _td2

        week_floor = (datetime.now() - _td2(days=7)).strftime("%Y-%m-%d")
        week_models = _C(
            str(item.get("model", ""))
            for item in history
            if str(item.get("time", ""))[:10] >= week_floor and str(item.get("model", "")).strip()
        )
        top_models = week_models.most_common(5)
        if top_models:
            st.markdown("#### Model dùng nhiều (7 ngày)")
            cols = st.columns(min(5, len(top_models)))
            total_w = sum(v for _, v in top_models) or 1
            for i, (mname, count) in enumerate(top_models):
                pct = int(round(count / total_w * 100))
                short = mname.split("/")[-1]
                with cols[i]:
                    st.markdown(
                        f"""
                        <div class="nr-dash-tile">
                          <div class="nr-dash-label">{html.escape(short)}</div>
                          <div class="nr-dash-value">{count}</div>
                          <div class="nr-dash-sub">{pct}% tuần này</div>
                          <div class="nr-dash-bar"><span style="width:{pct}%"></span></div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
    except Exception:
        pass

    st.markdown("#### Ảnh gần đây")
    local_items = [item for item in history if item.get("local_path")]
    if not local_items:
        st.info("Chưa có ảnh đã lưu. Hãy vào Studio để tạo ảnh đầu tiên.")
        return

    gallery_cols = 8 if compact_mode else 6
    preview_width = 126 if compact_mode else 150
    cols = st.columns(gallery_cols)
    shown = 0
    for item in local_items:
        path = Path(str(item.get("local_path", "")))
        if not path.exists():
            continue
        with cols[shown % gallery_cols]:
            st.image(str(path), width=preview_width)
            st.caption(f"{item.get('time', '')} • {item.get('model', '')}")
        shown += 1
        if shown >= 8:
            break


def page_lora_trainer(base_url: str, api_key: str) -> None:
    st.subheader("Train LoRA từ nhiều ảnh")
    st.caption("Tạo LoRA nhân vật/phong cách với luồng gọn: nhập dữ liệu → cấu hình → submit → theo dõi.")

    lora_history = load_lora_history(limit=600)
    completed_states = {"done", "completed", "success", "succeeded", "finished"}
    completed_jobs = len(
        [
            item
            for item in lora_history
            if str(item.get("status", "")).strip().lower() in completed_states
            or str(item.get("action", "")).strip().lower() == "completed"
        ]
    )
    dataset_dirs = list(LORA_DATASET_ROOT.glob("*/*")) if LORA_DATASET_ROOT.exists() else []

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Job log", str(len(lora_history)))
    with m2:
        st.metric("Job hoàn tất", str(completed_jobs))
    with m3:
        st.metric("Dataset local", str(len(dataset_dirs)))
    with m4:
        st.metric("Job ID gần nhất", st.session_state.lora_last_job_id or "-")

    tab_train, tab_monitor, tab_log = st.tabs(["Huấn luyện", "Theo dõi job", "Lịch sử train"])

    with tab_train:
        is_debug_mode = True

        workflow_options = list(LORA_WORKFLOW_PROFILES.keys())
        if st.session_state.get("lora_workflow_mode") not in workflow_options:
            st.session_state.lora_workflow_mode = workflow_options[0]

        wf1, wf2 = st.columns([1.45, 0.95], gap="medium")
        with wf1:
            st.selectbox("Chức năng train LoRA", options=workflow_options, key="lora_workflow_mode")
        with wf2:
            if st.button("Áp cơ chế train", use_container_width=True, key="btn_apply_lora_workflow"):
                apply_lora_workflow_profile(st.session_state.lora_workflow_mode, keep_manual_fields=False)
                st.session_state.lora_workflow_mode_applied = st.session_state.lora_workflow_mode
                st.success("Đã áp cơ chế train theo chức năng đã chọn.")

        selected_profile = LORA_WORKFLOW_PROFILES.get(st.session_state.lora_workflow_mode, {})
        auto_applied = str(st.session_state.get("lora_workflow_mode_applied", ""))
        if auto_applied != str(st.session_state.lora_workflow_mode):
            apply_lora_workflow_profile(st.session_state.lora_workflow_mode, keep_manual_fields=True)
            st.session_state.lora_workflow_mode_applied = st.session_state.lora_workflow_mode

        if selected_profile:
            st.markdown(
                (
                    f"<div class='studio-status-chip'>"
                    f"{st.session_state.lora_workflow_mode} • "
                    f"Loại: <b>{selected_profile.get('lora_type', '')}</b> • "
                    f"Preset gợi ý: <b>{selected_profile.get('training_preset', '')}</b> • "
                    f"Dataset nên có: <b>{selected_profile.get('recommended_images', '')}</b>"
                    f"</div>"
                ),
                unsafe_allow_html=True,
            )
            st.caption(str(selected_profile.get("focus", "")))

        with st.expander("Cơ chế train (ghi rõ)", expanded=False):
            st.markdown(
                "\n".join(
                    [
                        "1) Chọn đúng chức năng train: nhân vật / nét vẽ / sản phẩm / logo-chữ / concept.",
                        "2) Nạp dataset bằng Upload hoặc Thư mục local (app tự đọc toàn bộ ảnh hợp lệ).",
                        "3) Với mỗi ảnh: app tạo caption mặc định từ trigger + prefix/suffix + tên file.",
                        "4) App đóng gói payload gồm config train + dataset ảnh(base64) + caption từng ảnh.",
                        "5) Gửi tới endpoint train LoRA, lưu log job, có thể theo dõi/huỷ ở tab Theo dõi job.",
                        "6) Khi dùng LoRA: thêm trigger token vào prompt để gọi đúng nhân vật/nét đã train.",
                    ]
                )
            )

        t1, t2, t3 = st.columns([1.2, 0.9, 1.2], gap="medium")
        with t1:
            model_choices = get_quick_model_choices()
            if st.session_state.lora_base_model not in model_choices:
                model_choices = unique_list([st.session_state.lora_base_model] + model_choices)
            st.selectbox("Base model", options=model_choices, key="lora_base_model")
            if st.button("Dùng model đang vẽ", use_container_width=True, key="btn_lora_use_studio_model"):
                st.session_state.lora_base_model = st.session_state.manual_model
                st.rerun()
        with t2:
            st.selectbox("Loại LoRA", options=["character", "style", "product", "general"], key="lora_type")
        with t3:
            st.selectbox("Preset huấn luyện", options=list(LORA_TRAINING_PRESETS.keys()), key="lora_training_preset")
            if st.button("Áp preset train", use_container_width=True, key="btn_apply_lora_preset"):
                apply_lora_training_preset(st.session_state.lora_training_preset)
                st.success("Đã áp preset train")

        i1, i2 = st.columns([1.1, 0.9], gap="medium")
        with i1:
            st.text_input("Tên LoRA", key="lora_name", placeholder="vd: char_anh_a")
        with i2:
            st.text_input("Trigger token", key="lora_trigger_word", placeholder="vd: anhA_token")

        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Caption prefix (tùy chọn)", key="lora_caption_prefix", placeholder="vd: cinematic portrait")
        with c2:
            st.text_input("Caption suffix (tùy chọn)", key="lora_caption_suffix", placeholder="vd: highly detailed")

        with st.expander("Thông số train nâng cao", expanded=is_debug_mode):
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                st.number_input("Steps", min_value=200, max_value=50000, step=100, key="lora_steps")
                st.number_input("Epochs", min_value=1, max_value=200, step=1, key="lora_epochs")
            with p2:
                st.number_input("Batch size", min_value=1, max_value=16, step=1, key="lora_batch_size")
                st.number_input("Repeats", min_value=1, max_value=100, step=1, key="lora_repeats")
            with p3:
                st.number_input("Network dim", min_value=4, max_value=256, step=4, key="lora_network_dim")
                st.number_input("Network alpha", min_value=1, max_value=256, step=1, key="lora_network_alpha")
            with p4:
                st.number_input("Resolution", min_value=256, max_value=2048, step=64, key="lora_resolution")
                st.number_input("Seed", min_value=0, max_value=2_147_483_647, step=1, key="lora_seed")

            p5, p6, p7 = st.columns([1, 1, 1.2])
            with p5:
                st.number_input("Learning rate", min_value=0.000001, max_value=0.01, step=0.000001, format="%.6f", key="lora_learning_rate")
            with p6:
                st.slider("Caption dropout", min_value=0.0, max_value=0.6, step=0.01, key="lora_caption_dropout")
            with p7:
                st.selectbox("Optimizer", options=["adamw8bit", "adamw", "lion", "prodigy"], key="lora_optimizer")
                st.selectbox("Scheduler", options=["cosine", "constant", "linear", "cosine_with_restarts"], key="lora_scheduler")

        if is_debug_mode:
            with st.expander("Endpoint API train/monitor", expanded=False):
                e1, e2 = st.columns(2)
                with e1:
                    st.text_input("Train endpoint", key="lora_train_endpoint")
                    st.text_input("Status endpoint", key="lora_status_endpoint")
                with e2:
                    st.text_input("List endpoint", key="lora_list_endpoint")
                    st.text_input("Cancel endpoint", key="lora_cancel_endpoint")

        st.markdown("#### Dataset ảnh nhân vật / nét vẽ")
        source_mode = st.radio(
            "Nguồn dataset",
            options=["Upload ảnh", "Thư mục local"],
            horizontal=True,
            key="lora_dataset_source_mode",
        )

        source_images: list[dict[str, Any]] = []
        if source_mode == "Upload ảnh":
            uploaded_images = st.file_uploader(
                "Tải nhiều ảnh (PNG/JPG/WEBP)",
                type=["png", "jpg", "jpeg", "webp", "bmp", "gif"],
                accept_multiple_files=True,
                key="lora_dataset_upload",
            )
            if uploaded_images:
                if len(uploaded_images) > LORA_MAX_IMAGES:
                    st.warning(f"Chỉ lấy tối đa {LORA_MAX_IMAGES} ảnh đầu tiên để tránh quá tải.")
                selected_images = uploaded_images[:LORA_MAX_IMAGES]
                source_images = [
                    {
                        "filename": getattr(item, "name", "image.png"),
                        "mime_type": guess_mime_type(getattr(item, "name", "image.png"), getattr(item, "type", "")),
                        "image_bytes": item.getvalue(),
                    }
                    for item in selected_images
                ]
        else:
            st.text_input(
                "Đường dẫn thư mục ảnh",
                key="lora_dataset_folder_path",
                placeholder=r"Ví dụ: D:\dataset\character_a hoặc file:///D:/dataset/character_a",
            )
            st.checkbox("Quét cả thư mục con", key="lora_dataset_scan_recursive")

            folder_entries, folder_error = collect_images_from_local_folder(
                folder_input=str(st.session_state.get("lora_dataset_folder_path", "")),
                recursive=bool(st.session_state.get("lora_dataset_scan_recursive", True)),
                max_images=LORA_MAX_IMAGES,
            )
            if folder_error:
                st.warning(folder_error)
            else:
                source_images = folder_entries
                if source_images:
                    st.caption(
                        f"Đã đọc {len(source_images)} ảnh từ thư mục. Hệ thống tự dùng toàn bộ ảnh để train LoRA."
                    )

        st.checkbox("Lưu ảnh gốc vào outputs/inputs", value=True, key="lora_save_inputs")
        st.checkbox("Xuất dataset local khi submit", value=True, key="lora_export_dataset")

        dataset_entries: list[dict[str, Any]] = []
        if source_images:
            st.caption(f"Đã nạp {len(source_images)} ảnh. Có thể chỉnh caption cho từng ảnh bên dưới.")
            preview_cols = st.columns(3)
            for idx, image_item in enumerate(source_images, start=1):
                image_bytes = image_item.get("image_bytes", b"")
                if not isinstance(image_bytes, bytes) or not image_bytes:
                    continue

                filename = str(image_item.get("filename", f"img_{idx}.png"))
                mime_type = str(image_item.get("mime_type", guess_mime_type(filename)))
                trigger = st.session_state.lora_trigger_word.strip()
                prefix = st.session_state.lora_caption_prefix.strip()
                suffix = st.session_state.lora_caption_suffix.strip()
                stem_hint = Path(filename).stem.replace("_", " ").replace("-", " ")
                default_caption = ", ".join(unique_list([trigger, prefix, stem_hint, suffix]))

                with preview_cols[(idx - 1) % 3]:
                    st.image(image_bytes, use_container_width=True)
                    source_path = str(image_item.get("source_path", "")).strip()
                    if source_path:
                        source_name = Path(source_path).name or source_path
                        st.caption(f"Nguồn: {source_name}")
                    caption_key = f"lora_caption_{safe_filename(filename)}_{idx}"
                    caption_value = st.text_input(f"Caption ảnh {idx}", value=default_caption, key=caption_key)

                dataset_entries.append(
                    {
                        "filename": filename,
                        "mime_type": mime_type,
                        "image_bytes": image_bytes,
                        "caption": caption_value.strip() or default_caption,
                        "source_path": str(image_item.get("source_path", "")),
                    }
                )

            local_source_paths = [
                str(item.get("source_path", "")).strip()
                for item in dataset_entries
                if str(item.get("source_path", "")).strip()
            ]
            if local_source_paths:
                with st.expander("Xem đầy đủ đường dẫn ảnh nguồn", expanded=False):
                    for local_path in local_source_paths:
                        st.code(local_path)

        st.text_area("Extra JSON (gửi thêm cho backend)", key="lora_extra_json", height=96)

        def _build_lora_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
            dataset_payload = [
                {
                    "filename": str(item.get("filename", "")),
                    "caption": str(item.get("caption", "")).strip(),
                    "image": image_bytes_to_data_url(item["image_bytes"], str(item.get("mime_type", "image/png"))),
                }
                for item in entries
                if isinstance(item.get("image_bytes"), bytes) and item.get("image_bytes")
            ]

            payload: dict[str, Any] = {
                "task": "train_lora",
                "name": st.session_state.lora_name.strip(),
                "trigger_word": st.session_state.lora_trigger_word.strip(),
                "type": st.session_state.lora_type,
                "model": st.session_state.lora_base_model,
                "base_model": st.session_state.lora_base_model,
                "config": {
                    "steps": int(st.session_state.lora_steps),
                    "epochs": int(st.session_state.lora_epochs),
                    "batch_size": int(st.session_state.lora_batch_size),
                    "repeats": int(st.session_state.lora_repeats),
                    "learning_rate": float(st.session_state.lora_learning_rate),
                    "network_dim": int(st.session_state.lora_network_dim),
                    "network_alpha": int(st.session_state.lora_network_alpha),
                    "resolution": int(st.session_state.lora_resolution),
                    "caption_dropout": float(st.session_state.lora_caption_dropout),
                    "optimizer": st.session_state.lora_optimizer,
                    "scheduler": st.session_state.lora_scheduler,
                    "seed": int(st.session_state.lora_seed),
                },
                "dataset": dataset_payload,
            }
            extra = parse_json_object(st.session_state.lora_extra_json)
            payload.update(extra)
            return payload

        p_btn1, p_btn2 = st.columns([1, 1])
        with p_btn1:
            export_clicked = st.button("Xuất dataset local", use_container_width=True, key="btn_export_lora_dataset")
        with p_btn2:
            train_clicked = st.button("Bắt đầu train LoRA", type="primary", use_container_width=True, key="btn_train_lora")

        if dataset_entries and is_debug_mode:
            try:
                payload_preview = _build_lora_payload(dataset_entries)
                compact_preview = dict(payload_preview)
                compact_preview["dataset_count"] = len(payload_preview.get("dataset", []))
                compact_preview["dataset"] = [
                    {"filename": item.get("filename", ""), "caption": item.get("caption", "")}
                    for item in payload_preview.get("dataset", [])[:3]
                ]
                with st.expander("Xem payload train (rút gọn)", expanded=False):
                    st.json(compact_preview)
            except Exception as ex:
                st.error(f"Payload train chưa hợp lệ: {ex}")

        if export_clicked:
            if not dataset_entries:
                st.error("Cần ít nhất 1 ảnh để xuất dataset.")
            else:
                try:
                    payload_preview = _build_lora_payload(dataset_entries)
                    export_dir = export_lora_dataset_bundle(st.session_state.lora_name.strip() or "lora_dataset", dataset_entries, payload_preview)
                    st.success(f"Đã xuất dataset: {export_dir}")
                except Exception as ex:
                    st.error(f"Không thể xuất dataset: {ex}")

        if train_clicked:
            if not dataset_entries:
                st.error("Cần nạp ảnh dataset (upload hoặc thư mục local) trước khi train.")
            elif len(dataset_entries) < 4:
                st.warning("Nên dùng từ 4 ảnh trở lên để LoRA ổn định hơn.")
            try:
                payload = _build_lora_payload(dataset_entries)
            except Exception as ex:
                st.error(f"Payload train không hợp lệ: {ex}")
                return

            if not payload.get("name"):
                st.error("Tên LoRA đang trống.")
                return
            if not payload.get("trigger_word"):
                st.error("Trigger token đang trống.")
                return

            if st.session_state.lora_save_inputs:
                for idx, item in enumerate(dataset_entries, start=1):
                    try:
                        save_uploaded_input_copy(item["image_bytes"], str(item.get("filename", f"img_{idx}.png")), "lora_dataset", idx)
                    except Exception:
                        continue

            if st.session_state.lora_export_dataset:
                try:
                    export_dir = export_lora_dataset_bundle(st.session_state.lora_name.strip() or "lora_dataset", dataset_entries, payload)
                    st.info(f"Đã lưu dataset local: {export_dir}")
                except Exception as ex:
                    st.warning(f"Không thể xuất dataset local: {ex}")

            endpoint = resolve_api_url(base_url, st.session_state.lora_train_endpoint)
            lora_timeout = resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout"))
            with st.spinner("Đang gửi job train LoRA..."):
                try:
                    response = http_post_json(endpoint, payload, api_key or None, timeout_seconds=lora_timeout)
                except Exception as ex:
                    st.error(str(ex))
                    append_lora_history(
                        {
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "action": "submit_failed",
                            "endpoint": endpoint,
                            "name": payload.get("name", ""),
                            "trigger_word": payload.get("trigger_word", ""),
                            "images": len(payload.get("dataset", [])),
                            "error": str(ex),
                        }
                    )
                    return

            job_id = extract_job_id(response)
            if job_id:
                st.session_state.lora_last_job_id = job_id
                st.success(f"Đã gửi job train. Job ID: {job_id}")
            else:
                st.success("Đã gửi job train. Backend không trả job_id rõ ràng.")

            st.json(response)
            append_lora_history(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "action": "submit",
                    "endpoint": endpoint,
                    "job_id": job_id,
                    "name": payload.get("name", ""),
                    "trigger_word": payload.get("trigger_word", ""),
                    "model": payload.get("base_model", ""),
                    "images": len(payload.get("dataset", [])),
                    "status": str(response.get("status", response.get("state", "submitted"))),
                }
            )

    with tab_monitor:
        st.text_input("Job ID", key="lora_last_job_id", placeholder="Dán job id để theo dõi")
        action1, action2, action3 = st.columns(3)
        with action1:
            check_clicked = st.button("Kiểm tra trạng thái", use_container_width=True, key="btn_lora_status")
        with action2:
            cancel_clicked = st.button("Huỷ job", use_container_width=True, key="btn_lora_cancel")
        with action3:
            list_clicked = st.button("Danh sách LoRA", use_container_width=True, key="btn_lora_list")

        job_id = st.session_state.lora_last_job_id.strip()

        if check_clicked:
            if not job_id:
                st.error("Cần nhập Job ID.")
            else:
                status_endpoint = resolve_api_url(base_url, st.session_state.lora_status_endpoint)
                try:
                    status_data = http_get_json(
                        append_query_params(status_endpoint, {"job_id": job_id}),
                        api_key or None,
                        timeout_seconds=resolve_api_get_timeout_seconds(st.session_state.get("api_request_timeout")),
                    )
                except Exception:
                    try:
                        status_data = http_get_json(
                            append_query_params(status_endpoint, {"id": job_id}),
                            api_key or None,
                            timeout_seconds=resolve_api_get_timeout_seconds(st.session_state.get("api_request_timeout")),
                        )
                    except Exception as ex:
                        st.error(str(ex))
                        status_data = {}

                if not status_data:
                    return

                state = str(status_data.get("status", status_data.get("state", ""))).strip() or "unknown"
                st.info(f"Trạng thái hiện tại: {state}")
                st.json(status_data)
                append_lora_history(
                    {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "action": "status_check",
                        "job_id": job_id,
                        "status": state,
                    }
                )

        if cancel_clicked:
            if not job_id:
                st.error("Cần nhập Job ID để huỷ.")
            else:
                cancel_endpoint = resolve_api_url(base_url, st.session_state.lora_cancel_endpoint)
                payload = {"job_id": job_id}
                try:
                    cancel_resp = http_post_json(
                        cancel_endpoint,
                        payload,
                        api_key or None,
                        timeout_seconds=resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout")),
                    )
                except Exception as ex:
                    st.error(str(ex))
                else:
                    st.success("Đã gửi yêu cầu huỷ job.")
                    st.json(cancel_resp)
                    append_lora_history(
                        {
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "action": "cancel",
                            "job_id": job_id,
                            "status": str(cancel_resp.get("status", "cancel_requested")),
                        }
                    )

        if list_clicked:
            list_endpoint = resolve_api_url(base_url, st.session_state.lora_list_endpoint)
            try:
                list_resp = http_get_json(
                    list_endpoint,
                    api_key or None,
                    timeout_seconds=resolve_api_get_timeout_seconds(st.session_state.get("api_request_timeout")),
                )
            except Exception as ex:
                st.error(str(ex))
            else:
                data = list_resp.get("data", list_resp)
                if isinstance(data, list) and data:
                    st.dataframe(data, use_container_width=True)
                else:
                    st.json(list_resp)

    with tab_log:
        c1, c2 = st.columns([1, 1])
        with c1:
            keyword = st.text_input("Lọc theo tên/job/status", value="", key="lora_log_keyword")
        with c2:
            if st.button("Xóa log train local", use_container_width=True, key="btn_clear_lora_log"):
                if LORA_HISTORY_FILE.exists():
                    LORA_HISTORY_FILE.unlink()
                st.success("Đã xóa log train local")

        logs = load_lora_history(limit=800)
        if keyword.strip():
            term = keyword.strip().lower()
            logs = [
                item
                for item in logs
                if term in str(item.get("name", "")).lower()
                or term in str(item.get("job_id", "")).lower()
                or term in str(item.get("status", "")).lower()
                or term in str(item.get("action", "")).lower()
            ]

        st.caption(f"Tổng log hiển thị: {len(logs)}")
        if not logs:
            st.info("Chưa có log train LoRA.")
        else:
            st.dataframe(logs, use_container_width=True)


def page_model_explorer(base_url: str, api_key: str) -> None:
    st.subheader("Khám phá model")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Tìm model", use_container_width=True):
            ok_load, load_msg = load_models_into_state(base_url, api_key)
            if ok_load:
                st.success(load_msg.replace("Đã nạp", "Tìm thấy"))
            else:
                st.error(load_msg)
    with c2:
        keyword = st.text_input("Lọc theo từ khóa", value="")

    models = st.session_state.models
    if keyword.strip():
        models = [m for m in models if keyword.strip().lower() in m.lower()]
    if models:
        st.code("\n".join(models))
    else:
        st.info("Chưa có model trong bộ nhớ. Hãy bấm Tìm model.")

    st.divider()
    model_id = st.text_input("Mã model cần xem thông tin", value=(models[0] if models else st.session_state.manual_model))
    if st.button("Xem thông tin model", use_container_width=True):
        if not model_id.strip():
            st.error("Mã model đang trống")
            return
        try:
            info = get_model_info(base_url, api_key, model_id.strip())
            st.session_state.last_model_info = info
            st.json(info)
        except Exception as ex:
            st.error(str(ex))

    if st.session_state.last_model_info:
        st.markdown("### Gợi ý tham số trích từ thông tin model")
        st.json(
            {
                "size": extract_model_option_hints(st.session_state.last_model_info, "size"),
                "quality": extract_model_option_hints(st.session_state.last_model_info, "quality"),
                "style": extract_model_option_hints(st.session_state.last_model_info, "style"),
                "output_format": extract_model_option_hints(st.session_state.last_model_info, "output_format"),
            }
        )


def render_workflow_intro(title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="workflow-intro">
          <strong>{title}</strong>
          <span class="workflow-intro-desc">{description}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_story_workflow(base_url: str, api_key: str, model: str) -> None:
    ensure_story_builder_state()
    render_workflow_intro(
        "Vẽ truyện tranh nhiều trang",
        "Tải ảnh nhân vật, nhập lệnh từng khung, thêm thoại và tạo truyện tranh giữ nhân vật nhất quán.",
    )
    st.markdown(
        """
        <div class="comic-banner">
          <h4>🎬 Comic Builder • Multi-panel</h4>
          <p>Giao diện kéo xuống theo luồng: nhân vật → kịch bản khung → tạo ảnh → xuất PNG/PDF.</p>
          <div class="comic-chip-row">
            <span class="comic-chip">Nhân vật nhất quán</span>
            <span class="comic-chip">Thoại bong bóng</span>
            <span class="comic-chip">Sắp xếp panel</span>
            <span class="comic-chip">Xuất PNG / PDF</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top1, top2, top3 = st.columns([1.25, 1.05, 1.1], gap="medium")
    with top1:
        story_topic = st.text_input(
            "Chủ đề truyện",
            value="Hành trình đi học của hai bạn trẻ",
            key="story_topic",
        )
        story_outline = st.text_area(
            "Nội dung truyện tổng quát",
            value="Giới thiệu bối cảnh, xung đột nhỏ, cao trào và kết thúc tích cực.",
            height=96,
            key="story_outline",
        )
    with top2:
        story_style = st.selectbox("Phong cách vẽ", options=COMIC_STYLE_OPTIONS, key="story_style")
        story_beat = st.selectbox("Nhịp truyện", options=["Mở đầu -> Cao trào -> Kết", "Hành trình nhân vật", "Quảng bá sản phẩm", "Minh họa kiến thức"], key="story_beat")
    with top3:
        story_ratio = st.selectbox("Tỉ lệ khung hình", options=["1:1", "16:9", "9:16", "3:2"], index=1, key="story_ratio")
        st.number_input(
            "Ảnh mẫu tối đa mỗi nhân vật",
            min_value=1,
            max_value=4,
            step=1,
            key="story_refs_per_character",
        )

    keep1, keep2 = st.columns([1.2, 1.0], gap="small")
    with keep1:
        st.toggle("Giữ nhân vật giống nhau", key="story_keep_characters_consistent")
    with keep2:
        st.number_input("Seed truyện (tùy chọn)", min_value=0, max_value=99999999, step=1, value=2026, key="story_consistency_seed")

    with st.expander("JSON bổ sung", expanded=False):
        st.text_area("JSON bổ sung (tùy chọn)", value="{}", height=84, key="story_extra_json")

    st.subheader("1) Nhân vật")
    st.caption("Thêm nhân vật 1, 2, 3... rồi tải ảnh mẫu riêng để giữ mặt, tóc, trang phục và phong cách.")
    st.write("")

    characters: list[dict[str, Any]] = [
        item for item in st.session_state.get("story_characters_state", []) if isinstance(item, dict)
    ]
    char_ops_left, char_ops_right = st.columns([1.0, 3.2], gap="small")
    with char_ops_left:
        if st.button("➕ Thêm nhân vật", key="btn_story_add_character", use_container_width=True):
            next_index = len(characters) + 1
            characters.append(make_default_story_character(next_index))
            st.session_state.story_characters_state = characters
            st.rerun()
    with char_ops_right:
        q1, q2 = st.columns([1.35, 1.1], gap="small")
        with q1:
            st.caption(f"Đang có {len(characters)} nhân vật.")
        with q2:
            if st.button("⚡ Dùng mẫu 2 nhân vật / 4 khung", key="btn_story_quick_template", use_container_width=True):
                st.session_state.story_characters_state = [
                    make_default_story_character(1),
                    make_default_story_character(2),
                ]
                st.session_state.story_panels_state = [make_default_story_panel(i) for i in range(1, 5)]
                st.session_state.story_generated_panels = []
                st.rerun()

    show_all_characters = bool(st.session_state.get("story_show_all_characters", False))
    active_char_id = ""
    if characters:
        char_focus_labels: list[str] = []
        char_focus_map: dict[str, str] = {}
        for idx, char in enumerate(characters, start=1):
            char_id_now = str(char.get("id", "")).strip() or new_story_item_id("char")
            char["id"] = char_id_now
            char_name_now = str(char.get("name", f"Nhân vật {idx}")).strip() or f"Nhân vật {idx}"
            label = f"Nhân vật {idx} • {char_name_now}"
            char_focus_labels.append(label)
            char_focus_map[label] = char_id_now

        focus_col1, focus_col2 = st.columns([1.6, 1.1], gap="small")
        with focus_col1:
            if st.session_state.get("story_active_character_label") not in char_focus_labels:
                st.session_state.story_active_character_label = char_focus_labels[0]
            picked_char_label = st.selectbox(
                "Đang chỉnh nhân vật",
                options=char_focus_labels,
                key="story_active_character_label",
            )
            active_char_id = char_focus_map.get(picked_char_label, "")
        with focus_col2:
            st.toggle("Hiện tất cả nhân vật", key="story_show_all_characters")
            show_all_characters = bool(st.session_state.get("story_show_all_characters", False))
        st.caption("Mẹo: để giao diện gọn, chỉ chỉnh 1 nhân vật rồi chuyển sang nhân vật kế tiếp.")

    for idx, char in enumerate(characters, start=1):
        char_id = str(char.get("id", "")).strip() or new_story_item_id("char")
        char["id"] = char_id
        if not show_all_characters and active_char_id and char_id != active_char_id:
            continue
        default_name = str(char.get("name", f"Nhân vật {idx}")).strip() or f"Nhân vật {idx}"
        exp_title = f"Nhân vật {idx}: {default_name}"
        with st.expander(exp_title, expanded=True):
            c1, c2 = st.columns([1.8, 0.9], gap="small")
            with c1:
                char["name"] = st.text_input(
                    f"Tên nhân vật {idx}",
                    value=default_name,
                    key=f"story_char_name_{char_id}",
                )
            with c2:
                if st.button("🗑 Xóa nhân vật", key=f"btn_story_remove_char_{char_id}", use_container_width=True):
                    if len(characters) <= 1:
                        st.warning("Cần giữ ít nhất 1 nhân vật.")
                    else:
                        characters = [item for item in characters if str(item.get("id", "")) != char_id]
                        st.session_state.story_characters_state = characters
                        st.rerun()

            char["appearance"] = st.text_area(
                f"Mô tả nhận diện nhân vật {idx}",
                value=str(char.get("appearance", "")),
                height=74,
                key=f"story_char_appearance_{char_id}",
                placeholder="Ví dụ: tóc ngắn màu nâu, áo đồng phục xanh, đeo kính tròn.",
            )

            clip_state_key = f"story_char_clip_refs_{char_id}"
            if clip_state_key not in st.session_state:
                st.session_state[clip_state_key] = []

            uploaded_refs: Any = []
            pasted_refs = ""
            tab_upload, tab_paste = st.tabs(["Tải ảnh mẫu", "Dán nhanh / Clipboard"])
            with tab_upload:
                uploaded_refs = st.file_uploader(
                    f"Ảnh mẫu nhân vật {idx}",
                    type=["png", "jpg", "jpeg", "webp", "bmp"],
                    accept_multiple_files=True,
                    key=f"story_char_upload_{char_id}",
                )
            with tab_paste:
                cb1, cb2, cb3 = st.columns([1.2, 0.9, 2.0], gap="small")
                with cb1:
                    if st.button("📋 Lấy từ Clipboard", key=f"btn_story_char_clip_{char_id}", use_container_width=True):
                        data_url, err = grab_clipboard_image_data_url()
                        if data_url:
                            current = [
                                item
                                for item in st.session_state.get(clip_state_key, [])
                                if isinstance(item, str) and item.strip()
                            ]
                            st.session_state[clip_state_key] = unique_list(current + [data_url])
                            st.success(f"Đã dán ảnh clipboard vào nhân vật {idx}.")
                        else:
                            st.warning(err)
                with cb2:
                    if st.button("🧹 Xóa ảnh dán", key=f"btn_story_char_clip_clear_{char_id}", use_container_width=True):
                        st.session_state[clip_state_key] = []
                with cb3:
                    st.caption("Copy ảnh rồi bấm nút Clipboard. Nếu không được, dán URL/data:image ở ô dưới.")

                pasted_refs = st.text_area(
                    f"Dán URL/base64 ảnh mẫu nhân vật {idx}",
                    value="",
                    height=72,
                    key=f"story_char_paste_{char_id}",
                    placeholder="Mỗi dòng 1 URL hoặc data:image/base64.",
                )

            refs: list[str] = []
            previews: list[bytes] = []
            for up_idx, up in enumerate(uploaded_refs or [], start=1):
                content = up.getvalue()
                if not content:
                    continue
                mime_type = guess_mime_type(getattr(up, "name", f"char_{idx}_{up_idx}.png"), getattr(up, "type", ""))
                refs.append(safe_image_to_data_url(content, mime_type))
                previews.append(content)

            clip_refs = [
                item for item in st.session_state.get(clip_state_key, []) if isinstance(item, str) and item.strip()
            ]
            refs.extend(clip_refs)
            refs.extend(parse_pasted_image_refs(pasted_refs or ""))
            refs = unique_list(refs)
            char["refs"] = refs

            for ref in refs:
                decoded = decode_data_image_ref(ref)
                if isinstance(decoded, bytes) and decoded:
                    previews.append(decoded)

            if previews:
                preview_cols = st.columns(min(4, len(previews)))
                for p_idx, img_bytes in enumerate(previews):
                    with preview_cols[p_idx % len(preview_cols)]:
                        st.image(img_bytes, width=110)
            st.caption(f"Đã nhận {len(refs)} ảnh mẫu cho nhân vật {idx} (upload/clipboard/dán URL-base64).")

    st.session_state.story_characters_state = characters

    st.subheader("2) Trang/Khung truyện")
    st.caption("Thêm/xóa trang, đổi thứ tự panel và nhập lệnh riêng cho từng khung.")
    st.write("")

    panels: list[dict[str, Any]] = [
        item for item in st.session_state.get("story_panels_state", []) if isinstance(item, dict)
    ]
    pctrl1, pctrl2 = st.columns([1.0, 3.0], gap="small")
    with pctrl1:
        if st.button("➕ Thêm trang", key="btn_story_add_panel", use_container_width=True):
            panels.append(make_default_story_panel(len(panels) + 1))
            st.session_state.story_panels_state = panels
            st.rerun()
    with pctrl2:
        if st.button("➖ Xóa trang cuối", key="btn_story_remove_last_panel", use_container_width=False):
            if len(panels) <= 1:
                st.warning("Cần giữ ít nhất 1 trang/khung.")
            else:
                panels.pop()
                st.session_state.story_panels_state = panels
                st.rerun()

    show_all_panels = bool(st.session_state.get("story_show_all_panels", False))
    active_panel_id = ""
    if panels:
        panel_focus_labels: list[str] = []
        panel_focus_map: dict[str, str] = {}
        for idx, panel in enumerate(panels, start=1):
            panel_id_now = str(panel.get("id", "")).strip() or new_story_item_id("panel")
            panel["id"] = panel_id_now
            title_now = str(panel.get("title", f"Trang/Khung {idx}")).strip() or f"Trang/Khung {idx}"
            label = f"Khung {idx} • {title_now}"
            panel_focus_labels.append(label)
            panel_focus_map[label] = panel_id_now

        pf1, pf2 = st.columns([1.6, 1.1], gap="small")
        with pf1:
            if st.session_state.get("story_active_panel_label") not in panel_focus_labels:
                st.session_state.story_active_panel_label = panel_focus_labels[0]
            picked_panel_label = st.selectbox(
                "Đang chỉnh khung",
                options=panel_focus_labels,
                key="story_active_panel_label",
            )
            active_panel_id = panel_focus_map.get(picked_panel_label, "")
        with pf2:
            st.toggle("Hiện tất cả khung", key="story_show_all_panels")
            show_all_panels = bool(st.session_state.get("story_show_all_panels", False))
        st.caption("Mẹo: chỉnh từng khung theo thứ tự 1 → 2 → 3 để đỡ rối.")

    panel_move_action: tuple[int, int] | None = None
    panel_delete_index: int | None = None

    character_ids = [str(char.get("id", "")) for char in characters if str(char.get("id", "")).strip()]
    character_labels: dict[str, str] = {}
    for idx, char in enumerate(characters, start=1):
        char_id = str(char.get("id", "")).strip()
        if not char_id:
            continue
        char_name = str(char.get("name", f"Nhân vật {idx}")).strip() or f"Nhân vật {idx}"
        character_labels[char_id] = f"Nhân vật {idx} • {char_name}"

    for idx, panel in enumerate(panels, start=1):
        panel_id = str(panel.get("id", "")).strip() or new_story_item_id("panel")
        panel["id"] = panel_id
        if not show_all_panels and active_panel_id and panel_id != active_panel_id:
            continue

        default_title = str(panel.get("title", f"Trang/Khung {idx}")).strip() or f"Trang/Khung {idx}"
        with st.expander(f"Trang/Khung {idx}: {default_title}", expanded=True):
            t1, t2, t3, t4 = st.columns([2.3, 0.8, 0.8, 0.9], gap="small")
            with t1:
                panel["title"] = st.text_input(
                    f"Tiêu đề trang/khung {idx}",
                    value=default_title,
                    key=f"story_panel_title_{panel_id}",
                )
            with t2:
                if st.button("⬆ Lên", key=f"btn_story_panel_up_{panel_id}", use_container_width=True) and idx > 1:
                    panel_move_action = (idx - 1, idx - 2)
            with t3:
                if st.button("⬇ Xuống", key=f"btn_story_panel_down_{panel_id}", use_container_width=True) and idx < len(panels):
                    panel_move_action = (idx - 1, idx)
            with t4:
                if st.button("🗑 Xóa", key=f"btn_story_panel_del_{panel_id}", use_container_width=True):
                    panel_delete_index = idx - 1

            panel["scene_prompt"] = st.text_area(
                f"Lệnh cho khung {idx}",
                value=str(panel.get("scene_prompt", "")),
                height=110,
                key=f"story_panel_scene_{panel_id}",
                placeholder="Ví dụ: Nhân vật 1 đứng bên trái, nhân vật 2 đứng bên phải, đang nói chuyện trong lớp học, phong cách anime sắc nét.",
            )

            selected_ids_default = [
                item
                for item in panel.get("character_ids", [])
                if isinstance(item, str) and item in character_labels
            ]
            if not selected_ids_default and character_ids:
                selected_ids_default = character_ids[:2]

            label_options = [character_labels[char_id] for char_id in character_ids if char_id in character_labels]
            default_labels = [character_labels[char_id] for char_id in selected_ids_default if char_id in character_labels]
            picked_labels = st.multiselect(
                f"Nhân vật xuất hiện trong khung {idx}",
                options=label_options,
                default=default_labels,
                key=f"story_panel_chars_{panel_id}",
            )

            picked_ids: list[str] = []
            label_to_id = {label: char_id for char_id, label in character_labels.items()}
            for label in picked_labels:
                char_id = label_to_id.get(label)
                if char_id:
                    picked_ids.append(char_id)
            panel["character_ids"] = unique_list(picked_ids)

            char1_label = character_labels.get(character_ids[0], "Nhân vật 1") if character_ids else "Nhân vật 1"
            char2_label = character_labels.get(character_ids[1], "Nhân vật 2") if len(character_ids) > 1 else "Nhân vật 2"
            d1, d2 = st.columns(2, gap="small")
            with d1:
                panel["dialogue_1"] = st.text_input(
                    f"Bong bóng thoại {char1_label}",
                    value=str(panel.get("dialogue_1", "")),
                    key=f"story_panel_dialogue1_{panel_id}",
                )
            with d2:
                panel["dialogue_2"] = st.text_input(
                    f"Bong bóng thoại {char2_label}",
                    value=str(panel.get("dialogue_2", "")),
                    key=f"story_panel_dialogue2_{panel_id}",
                )

            panel["narration"] = st.text_input(
                "Chữ dẫn truyện",
                value=str(panel.get("narration", "")),
                key=f"story_panel_narration_{panel_id}",
                placeholder="Ví dụ: Buổi sáng đầu tiên của học kỳ mới.",
            )

    if panel_delete_index is not None:
        if len(panels) <= 1:
            st.warning("Cần giữ ít nhất 1 trang/khung.")
        else:
            panels.pop(panel_delete_index)
            st.session_state.story_panels_state = panels
            st.rerun()

    if panel_move_action is not None:
        src, dst = panel_move_action
        if 0 <= src < len(panels) and 0 <= dst < len(panels):
            panels[src], panels[dst] = panels[dst], panels[src]
            st.session_state.story_panels_state = panels
            st.rerun()

    st.session_state.story_panels_state = panels

    with st.expander("🧠 Xem prompt preview từng khung", expanded=False):
        for idx, panel in enumerate(panels, start=1):
            picked_ids = [item for item in panel.get("character_ids", []) if isinstance(item, str)]
            panel_chars = [char for char in characters if str(char.get("id", "")) in picked_ids]
            prompt_preview = build_story_panel_prompt(
                panel_index=idx,
                total_panels=len(panels),
                panel=panel,
                panel_characters=panel_chars,
                style_name=story_style,
                story_beat=story_beat,
                keep_consistent=bool(st.session_state.get("story_keep_characters_consistent", True)),
            )
            st.markdown(f"**Khung {idx}**")
            st.code(prompt_preview)

    st.subheader("3) Tạo ảnh truyện")
    action1, action2 = st.columns([1.4, 1.0], gap="medium")
    with action1:
        generate_clicked = st.button("Tạo ảnh truyện", type="primary", use_container_width=True, key="btn_story_generate_comic")
    with action2:
        if st.button("Xóa kết quả truyện", use_container_width=True, key="btn_story_clear_result"):
            st.session_state.story_generated_panels = []
            st.rerun()

    if generate_clicked:
        if not panels:
            st.error("Chưa có khung nào trong truyện. Hãy thêm ít nhất 1 khung trước khi tạo.")
            return
        empty_panels = [
            idx for idx, panel in enumerate(panels, start=1)
            if not str(panel.get("prompt", "") or "").strip()
        ]
        if empty_panels:
            st.warning(
                "Một số khung chưa có lệnh: "
                + ", ".join(f"#{i}" for i in empty_panels)
                + ". Hãy nhập mô tả để tránh bị tạo lệch."
            )
            return
        try:
            extra = parse_json_object(str(st.session_state.get("story_extra_json", "{}")))
        except Exception as ex:
            st.error(f"JSON bổ sung không hợp lệ: {ex}")
            return

        keep_consistent = bool(st.session_state.get("story_keep_characters_consistent", True))
        seed_value = int(st.session_state.get("story_consistency_seed", 2026))
        ref_limit = max(1, int(st.session_state.get("story_refs_per_character", 2)))

        progress = st.progress(0.0)
        generated: list[dict[str, Any]] = []
        batch_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

        for idx, panel in enumerate(panels, start=1):
            picked_ids = [item for item in panel.get("character_ids", []) if isinstance(item, str)]
            panel_chars = [char for char in characters if str(char.get("id", "")) in picked_ids]

            prompt = build_story_panel_prompt(
                panel_index=idx,
                total_panels=len(panels),
                panel=panel,
                panel_characters=panel_chars,
                style_name=story_style,
                story_beat=story_beat,
                keep_consistent=keep_consistent,
            )

            if story_topic.strip():
                prompt = f"Chủ đề tổng thể: {story_topic.strip()}\n" + prompt
            if story_outline.strip():
                prompt += f"\nTóm tắt nội dung truyện: {story_outline.strip()}"

            payload: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "aspect_ratio": story_ratio,
            }

            panel_refs: list[str] = []
            for char in panel_chars:
                refs = [str(item) for item in char.get("refs", []) if isinstance(item, str) and str(item).strip()]
                panel_refs.extend(refs[:ref_limit])
            panel_refs = unique_list(panel_refs)

            if panel_refs:
                if len(panel_refs) == 1:
                    payload["image"] = panel_refs[0]
                else:
                    payload["images"] = panel_refs[:12]

            if keep_consistent:
                payload["seed"] = seed_value

            payload.update(extra)

            with st.spinner(f"Đang tạo khung {idx}/{len(panels)}..."):
                try:
                    result = generate_image_with_retry(
                        base_url=base_url,
                        api_key=api_key,
                        payload=payload,
                        response_format="binary",
                        timeout_seconds=resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout")),
                        retry_count=resolve_image_retry_count(st.session_state.get("image_retry_count")),
                        retry_backoff_seconds=resolve_image_retry_backoff_seconds(st.session_state.get("image_retry_backoff")),
                        task_label=f"Story panel {idx}",
                    )
                except Exception as ex:
                    st.error(f"Khung {idx} lỗi: {ex}")
                    generated.append({"index": idx, "image_bytes": None, "saved_path": "", "prompt": prompt})
                    progress.progress(idx / len(panels))
                    continue

            image_bytes: bytes | None = None
            saved_path = ""
            if result.get("kind") == "binary":
                image_bytes = result.get("image_bytes")
                if isinstance(image_bytes, bytes) and image_bytes and bool(st.session_state.get("auto_save_outputs", True)):
                    panel_file = build_daily_output_path(
                        f"{st.session_state.studio_output_prefix}_comic_{batch_slug}_panel_{idx}.png",
                        workflow_name=f"comic_panel_{idx}",
                    )
                    saved_path = str(save_image(image_bytes, panel_file))

                history_item = {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "model": model,
                    "prompt": f"[Truyện tranh] {prompt}",
                    "response_format": "binary",
                    "result_kind": "binary",
                }
                if saved_path:
                    history_item["local_path"] = saved_path
                append_history(history_item)

                add_recent_output(
                    {
                        "time": history_item["time"],
                        "model": model,
                        "prompt": history_item["prompt"],
                        "kind": "binary",
                        "local_path": saved_path,
                        "url": "",
                        "image_bytes": b"" if saved_path else (image_bytes or b""),
                    }
                )

            generated.append(
                {
                    "index": idx,
                    "panel_id": str(panel.get("id", "")),
                    "title": str(panel.get("title", f"Trang/Khung {idx}")),
                    "prompt": prompt,
                    "image_bytes": image_bytes,
                    "saved_path": saved_path,
                }
            )
            progress.progress(idx / len(panels))

        st.session_state.story_generated_panels = generated
        ok_count = len([item for item in generated if isinstance(item.get("image_bytes"), bytes) and item.get("image_bytes")])
        st.success(f"Đã tạo xong truyện tranh: {ok_count}/{len(panels)} khung thành công.")

    generated_panels: list[dict[str, Any]] = [
        item for item in st.session_state.get("story_generated_panels", []) if isinstance(item, dict)
    ]
    if not generated_panels:
        return

    st.subheader("4) Kết quả & xuất truyện")
    grid_cols = st.columns(4)
    for item in generated_panels:
        idx = int(item.get("index", 0) or 0)
        img_bytes = item.get("image_bytes")
        saved_path = str(item.get("saved_path", ""))
        with grid_cols[(idx - 1) % len(grid_cols) if idx > 0 else 0]:
            st.markdown(f"**Khung {idx}**")
            if isinstance(img_bytes, bytes) and img_bytes:
                st.image(img_bytes, width=180)
                with st.expander(f"Xem lớn khung {idx}", expanded=False):
                    st.image(img_bytes, use_container_width=True)
            else:
                st.warning("Khung này chưa có ảnh")
            if saved_path:
                st.caption(saved_path)

    image_bytes_list = [
        item.get("image_bytes")
        for item in generated_panels
        if isinstance(item.get("image_bytes"), bytes) and item.get("image_bytes")
    ]
    if not image_bytes_list:
        st.warning("Chưa có ảnh hợp lệ để xuất file PNG/PDF.")
        return

    ex1, ex2, ex3 = st.columns([1.0, 1.0, 2.2], gap="small")
    with ex1:
        st.number_input("Panel mỗi hàng", min_value=1, max_value=4, step=1, key="story_export_cols")
    with ex2:
        st.number_input("Số hàng mỗi trang", min_value=1, max_value=4, step=1, key="story_export_rows")
    with ex3:
        st.caption("Xuất PNG: ghép toàn bộ trang thành 1 ảnh dài. Xuất PDF: nhiều trang trong cùng 1 file.")

    try:
        pages = compose_story_pages(
            panel_images=image_bytes_list,
            cols=int(st.session_state.get("story_export_cols", 2)),
            rows=int(st.session_state.get("story_export_rows", 2)),
        )
    except Exception as ex:
        st.error(f"Không thể ghép trang truyện: {ex}")
        return

    if not pages:
        st.warning("Không tạo được trang truyện để xuất.")
        return

    png_bytes = encode_story_pages_png(pages)
    pdf_bytes = encode_story_pages_pdf(pages)
    export_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

    dl1, dl2 = st.columns(2, gap="small")
    with dl1:
        st.download_button(
            "Xuất ảnh truyện PNG",
            data=png_bytes,
            file_name=f"comic_story_{export_slug}.png",
            mime="image/png",
            use_container_width=True,
            key=f"btn_story_download_png_{export_slug}",
        )
    with dl2:
        st.download_button(
            "Xuất ảnh truyện PDF",
            data=pdf_bytes,
            file_name=f"comic_story_{export_slug}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"btn_story_download_pdf_{export_slug}",
        )

    if bool(st.session_state.get("auto_save_outputs", True)):
        export_png_path = Path(build_daily_output_path(f"comic_story_{export_slug}.png", "comic_story_export"))
        export_png_path.write_bytes(png_bytes)
        export_pdf_path = Path(build_daily_output_path(f"comic_story_{export_slug}.pdf", "comic_story_export", fallback_ext=".pdf"))
        export_pdf_path.write_bytes(pdf_bytes)
        st.caption(f"Đã lưu export: {export_png_path} • {export_pdf_path}")


def _normalize_quick_choice(value: str, options: list[str]) -> str:
    clean = str(value or "").strip()
    if clean in options:
        return clean
    legacy_map = {"Xóa nền xanh": "Xóa nền chroma"}
    mapped = legacy_map.get(clean)
    if mapped in options:
        return mapped
    return options[0] if options else ""


def render_quick_payload_explainer(
    payload: dict[str, Any],
    count: int,
    mode_choice: str,
    speed_choice: str,
    ref_count: int,
    key_pool_count: int,
) -> None:
    notes: list[str] = []
    notes.append(f"- Số ảnh `{count}` → gửi `n={count}`.")

    if mode_choice in {MODE_AUTO_API, MODE_PARALLEL_API} and count > 1:
        if should_split_batch_requests(mode_choice, count, key_pool_count):
            preview_workers = resolve_parallel_workers(
                mode=mode_choice,
                requested_count=count,
                key_pool_count=key_pool_count,
                max_parallel=int(st.session_state.get("multi_api_max_parallel", 1)),
            )
            notes.append(f"- Chế độ `{mode_choice}` → tách thành `{count}` request, mỗi request `n=1`.")
            notes.append(
                f"- Tốc độ `{speed_choice}` → chạy tối đa `{preview_workers}` luồng (giới hạn cấu hình `{MAX_PARALLEL_WORKERS}`)."
            )
        else:
            notes.append(
                f"- Chế độ `{mode_choice}` đang bật nhưng chỉ có `{key_pool_count}` key khả dụng → hệ thống fallback về 1 request."
            )
    else:
        notes.append(f"- Chế độ `{mode_choice}` → gửi một request duy nhất.")

    ratio_value = str(payload.get("aspect_ratio", "")).strip()
    if ratio_value:
        notes.append(f"- Tỷ lệ đã chọn → thêm `aspect_ratio={ratio_value}`.")
    else:
        notes.append("- Tỷ lệ `Mặc định` → không thêm `aspect_ratio`.")

    style_value = str(payload.get("style", "")).strip()
    if style_value:
        notes.append(f"- Phong cách đã chọn → thêm `style={style_value}`.")
    else:
        notes.append("- Phong cách `Mặc định`/`Không áp phong cách` → không thêm `style`.")

    quality_value = str(payload.get("quality", "")).strip()
    if quality_value:
        notes.append(f"- Chất lượng đã chọn → thêm `quality={quality_value}`.")
    else:
        notes.append("- Chất lượng `Mặc định` → không thêm `quality`.")

    if ref_count <= 0:
        notes.append("- Không dùng ảnh mẫu → không gửi `image`/`images`.")
    elif ref_count == 1 and "image" in payload:
        notes.append("- Có 1 ảnh mẫu → gửi trường `image`.")
    else:
        notes.append(f"- Có `{ref_count}` ảnh mẫu → gửi trường `images`.")

    notes.append(
        f"- Mạng/API: timeout `{int(st.session_state.get('api_request_timeout', DEFAULT_API_POST_TIMEOUT_SECONDS))}s`, retry `{int(st.session_state.get('image_retry_count', DEFAULT_IMAGE_RETRY_COUNT))}` lần."
    )

    st.markdown("\n".join(notes))


def _payload_command_preview(payload: dict[str, Any], char_limit: int = 220) -> str:
    """Return the user prompt extracted from a payload, trimmed for preview."""
    text = str(payload.get("prompt", "")).strip()
    if len(text) > char_limit:
        return f"{text[:char_limit]}…"
    return text


def render_payload_command_panel(
    payload: dict[str, Any],
    *,
    workflow_label: str,
    count: int,
    ref_count: int,
    mode_choice: str,
    speed_choice: str,
    key_pool_count: int,
    user_command: str = "",
    extra_rows: list[tuple[str, str]] | None = None,
) -> None:
    """Render a clean 'lệnh sẽ gửi' panel showing inputs and core parameters.

    Replaces the raw JSON dump for end users while keeping the JSON expander
    available below for power users.
    """
    user_text = (user_command or _payload_command_preview(payload)).strip()
    base_rows: list[tuple[str, str]] = [
        ("Tác vụ", workflow_label),
        ("Model", str(payload.get("model", "—"))),
        ("Số ảnh", str(count)),
        ("Ảnh nguồn", "không" if ref_count <= 0 else f"{ref_count} ảnh"),
        ("Chế độ API", mode_choice),
        ("Tốc độ", speed_choice),
        ("Key khả dụng", str(key_pool_count)),
    ]

    aspect_value = str(payload.get("aspect_ratio", "")).strip()
    if aspect_value:
        base_rows.append(("Tỷ lệ", aspect_value))
    style_value = str(payload.get("style", "")).strip()
    if style_value:
        base_rows.append(("Phong cách", style_value))
    quality_value = str(payload.get("quality", "")).strip()
    if quality_value:
        base_rows.append(("Chất lượng", quality_value))
    detail_value = str(payload.get("image_detail", "")).strip()
    if detail_value:
        base_rows.append(("Image detail", detail_value))
    bg_value = str(payload.get("background", "")).strip()
    if bg_value:
        base_rows.append(("Background", bg_value))
    format_value = str(payload.get("output_format", "")).strip()
    if format_value:
        base_rows.append(("Output", format_value))
    if payload_requests_green_screen_removal(payload):
        base_rows.append(("Không nền", "Vẽ nền xanh #00FF00 → tự xóa"))
    sampler_value = str(payload.get("sampler", "")).strip()
    if sampler_value:
        base_rows.append(("Sampler", sampler_value))
    if "strength" in payload:
        base_rows.append(("Strength", f"{float(payload['strength']):.2f}"))
    if "steps" in payload:
        base_rows.append(("Steps", str(int(payload["steps"]))))
    if "guidance_scale" in payload:
        base_rows.append(("Guidance", f"{float(payload['guidance_scale']):.1f}"))
    if "cfg_scale" in payload:
        base_rows.append(("CFG", f"{float(payload['cfg_scale']):.1f}"))
    if "seed" in payload:
        base_rows.append(("Seed", str(payload["seed"])))
    negative_value = str(payload.get("negative_prompt", "")).strip()
    if negative_value:
        snippet = negative_value if len(negative_value) <= 90 else f"{negative_value[:90]}…"
        base_rows.append(("Negative", snippet))

    if extra_rows:
        base_rows.extend(extra_rows)

    rows_html = "".join(
        f"<div class='cmd-row'><span class='cmd-key'>{html.escape(str(label))}</span>"
        f"<span class='cmd-val'>{html.escape(str(value))}</span></div>"
        for label, value in base_rows
        if str(value).strip()
    )
    safe_user_text = html.escape(user_text or "(chưa có mô tả)")
    api_endpoint = "POST /v1/images/generations"

    st.markdown(
        f"""
        <div class='cmd-panel'>
          <div class='cmd-panel-head'>
            <span class='cmd-tag'>📡 {html.escape(api_endpoint)}</span>
            <span class='cmd-tag cmd-tag-soft'>{html.escape(workflow_label)}</span>
          </div>
          <div class='cmd-panel-prompt'>{safe_user_text}</div>
          <div class='cmd-panel-grid'>{rows_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_generate_quick(base_url: str, api_key: str, compact_mode: bool) -> None:
    def _normalize_prompt_text(raw_text: str) -> str:
        return re.sub(r"https?://\S+|data:image/\S+", " ", raw_text or "", flags=re.IGNORECASE).strip()

    def _uploaded_to_refs(uploaded: Any) -> list[str]:
        if uploaded is None:
            return []
        files = uploaded if isinstance(uploaded, list) else [uploaded]

        refs_local: list[str] = []
        for idx, up in enumerate(files, start=1):
            try:
                content = up.getvalue()
                mime_type = guess_mime_type(getattr(up, "name", f"img_{idx}.png"), getattr(up, "type", ""))
                refs_local.append(safe_image_to_data_url(content, mime_type))
            except Exception:
                continue
        return unique_list(refs_local)

    def _render_small_refs(title: str, refs: list[str]) -> None:
        if not refs:
            return
        show_items = refs[:8]
        st.caption(f"{title}: {len(refs)} ảnh")
        cols = st.columns(min(8, len(show_items)))
        for idx, ref in enumerate(show_items):
            preview_source: Any = ref
            if str(ref).startswith("data:image/"):
                try:
                    preview_source = base64.b64decode(str(ref).split(",", 1)[1])
                except Exception:
                    preview_source = None
            with cols[idx % len(cols)]:
                if preview_source is not None:
                    st.image(preview_source, width=96)
                else:
                    st.caption("Không preview được")

    pose_command_presets = [
        "Đứng tựa tường, kéo nhẹ cổ áo, ánh mắt nửa buồn ngủ",
        "Ngồi trên ghế sofa, áo oversized lệch vai nhẹ, chân bắt chéo",
        "Soi gương vuốt tóc, môi hé nhẹ, biểu cảm mơ màng",
        "Vừa thức dậy trên giường, tóc rối nhẹ, áo rộng",
        "Nằm nghiêng chống cằm, ánh mắt trêu đùa",
        "Đứng trước quạt gió, váy áo bay nhẹ, cười nhạt",
        "Cởi bớt áo khoác ngoài, nhìn sang bên cạnh",
        "Tựa cửa sổ ban đêm, tay chạm môi, ánh mắt cô đơn",
        "Đang thay khuyên tai trước gương, cổ áo hơi trễ",
        "Vén tóc sau tai, nhìn camera bằng ánh mắt quyến rũ",
        "Ngồi trên bàn học, áo sơ mi hơi rộng, lười biếng",
        "Nằm dài trên sofa chơi điện thoại, chân trần",
        "Chống tay lên bàn, cúi người nhẹ, ánh mắt khiêu khích",
        "Lau tóc sau khi tắm, tóc ướt, áo mỏng nhẹ",
        "Ngồi uống cà phê sáng, áo len rộng che một phần tay",
        "Đứng cạnh cửa kính trời mưa, biểu cảm buồn nhẹ",
        "Kéo nhẹ dây áo vai, nhìn sang hướng khác",
        "Dựa lan can ban công, gió thổi tóc bay",
        "Cười nửa miệng, tay đút túi áo khoác",
        "Nằm trên giường đọc sách, chân co nhẹ tự nhiên",
        "Áo sơ mi cài hờ vài nút trên, phong cách casual sexy",
        "Quỳ trên ghế nhìn ra ngoài cửa sổ",
        "Tựa đầu lên tay, ánh mắt mệt mỏi quyến rũ",
        "Đang trang điểm trước gương, môi hơi hé",
        "Đứng dưới ánh đèn vàng mờ, váy ôm nhẹ cơ thể",
    ]

    def _parse_batch_commands(raw_text: str) -> list[str]:
        return [line.strip(" -\t") for line in str(raw_text or "").splitlines() if line.strip(" -\t")]

    def _merge_base_prompt_with_command(base_prompt: str, command: str) -> str:
        clean_base = _normalize_prompt_text(base_prompt)
        clean_command = _normalize_prompt_text(command)
        if clean_base and clean_command:
            return f"{clean_base}, {clean_command}"
        return clean_command or clean_base

    def _apply_character_detail_note(prompt: str) -> str:
        note = str(st.session_state.get("quick_character_detail_note", "")).strip()
        clean_prompt = str(prompt or "").strip()
        if not note:
            return clean_prompt
        detail_text = (
            "Lưu ý chi tiết nhân vật bắt buộc: "
            f"{note}. Giữ đúng chi tiết này rõ ràng, không bỏ sót, không làm mờ."
        )
        if clean_prompt:
            return f"{clean_prompt}\n\n{detail_text}"
        return detail_text

    def _get_batch_commands(scope_key: str = "quick") -> list[str]:
        enabled_key = f"{scope_key}_batch_use_commands"
        all_key = f"{scope_key}_batch_use_all_presets"
        text_key = f"{scope_key}_batch_commands_text"
        if not bool(st.session_state.get(enabled_key, False)):
            return []
        if bool(st.session_state.get(all_key, False)):
            return list(pose_command_presets)
        return _parse_batch_commands(str(st.session_state.get(text_key, "")))

    def _run_command_batch(
        *,
        base_payload: dict[str, Any],
        base_prompt: str,
        commands: list[str],
        output_prefix: str,
        workflow_label: str,
        refs_available: bool = False,
    ) -> bool:
        if not commands:
            return False
        progress = st.progress(0.0)
        st.info(f"Đang chạy batch {len(commands)} lệnh × {base_payload.get('n', 1)} ảnh/lệnh.")
        for command_idx, command_text in enumerate(commands, start=1):
            batch_prompt = _merge_base_prompt_with_command(base_prompt, command_text)
            batch_prompt = _apply_character_detail_note(batch_prompt)
            if not batch_prompt.strip() and not refs_available:
                continue
            batch_payload = dict(base_payload)
            batch_payload["prompt"] = batch_prompt
            output_file = f"{st.session_state.studio_output_prefix}_{output_prefix}_{command_idx}_{timestamp_slug()}.png"
            run_payload_generation(
                base_url,
                api_key,
                batch_payload,
                "binary",
                output_file,
                f"{workflow_label} {command_idx}/{len(commands)}",
                show_inline_preview=False,
            )
            progress.progress(command_idx / len(commands))
        st.success("Đã chạy xong batch lệnh mẫu.")
        return True

    if "quick_operation" not in st.session_state:
        st.session_state.quick_operation = QUICK_OPERATION_OPTIONS[0]
    if "quick_simple_mode" not in st.session_state:
        st.session_state.quick_simple_mode = str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE))
    if "quick_simple_speed" not in st.session_state:
        st.session_state.quick_simple_speed = list(QUICK_SPEED_PRESETS.keys())[0]
    if "quick_simple_count" not in st.session_state:
        base_count = int(st.session_state.get("studio_count", QUICK_COUNT_OPTIONS[0]))
        st.session_state.quick_simple_count = str(base_count if base_count in QUICK_COUNT_OPTIONS else QUICK_COUNT_OPTIONS[0])
    if "quick_simple_ratio" not in st.session_state:
        st.session_state.quick_simple_ratio = QUICK_RATIO_OPTIONS[0]
    if "quick_simple_style" not in st.session_state:
        st.session_state.quick_simple_style = QUICK_STYLE_OPTIONS[0]
    if "quick_simple_quality" not in st.session_state:
        st.session_state.quick_simple_quality = QUICK_QUALITY_OPTIONS[0]
    if "quick_simple_use_reference" not in st.session_state:
        st.session_state.quick_simple_use_reference = False
    if "quick_simple_ref_mode" not in st.session_state:
        st.session_state.quick_simple_ref_mode = "1 ảnh"
    if "quick_api_keys_pool_text" not in st.session_state:
        st.session_state.quick_api_keys_pool_text = str(st.session_state.get("api_keys_pool_text", ""))
    if "quick_prompt_clip_refs" not in st.session_state:
        st.session_state.quick_prompt_clip_refs = []
    if "quick_edit_clip_refs" not in st.session_state:
        st.session_state.quick_edit_clip_refs = []
    if "quick_upscale_clip_refs" not in st.session_state:
        st.session_state.quick_upscale_clip_refs = []
    if "quick_translate_clip_refs" not in st.session_state:
        st.session_state.quick_translate_clip_refs = []
    if "quick_remix_clip_refs" not in st.session_state:
        st.session_state.quick_remix_clip_refs = []
    if "quick_universal_clip_refs" not in st.session_state:
        st.session_state.quick_universal_clip_refs = []
    if "quick_green_clip_refs" not in st.session_state:
        st.session_state.quick_green_clip_refs = []
    if "quick_analyze_bg_clip_refs" not in st.session_state:
        st.session_state.quick_analyze_bg_clip_refs = []
    if "quick_batch_commands_text" not in st.session_state:
        st.session_state.quick_batch_commands_text = "\n".join(pose_command_presets[:5])
    if "quick_batch_use_commands" not in st.session_state:
        st.session_state.quick_batch_use_commands = False
    if "quick_batch_use_all_presets" not in st.session_state:
        st.session_state.quick_batch_use_all_presets = False
    if "quick_character_detail_note" not in st.session_state:
        st.session_state.quick_character_detail_note = ""
    for scope in ("quick", "quick_universal", "quick_remix", "quick_edit", "quick_upscale", "quick_translate", "quick_style"):
        st.session_state.setdefault(f"{scope}_batch_use_commands", False)
        st.session_state.setdefault(f"{scope}_batch_use_all_presets", False)
        st.session_state.setdefault(f"{scope}_batch_commands_text", "\n".join(pose_command_presets[:5]))

    quick_models = get_quick_model_choices()
    if st.session_state.get("studio_top_model") not in quick_models:
        st.session_state.studio_top_model = suggest_top_model(
            [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
            st.session_state.manual_model,
        )

    # Compact toolbar: model + operation + utilities on a single tight row.
    def _reset_quick_studio_defaults() -> None:
        apply_everyday_studio_defaults()
        st.session_state.quick_operation = QUICK_OPERATION_OPTIONS[0]
        st.session_state.quick_simple_count = str(QUICK_COUNT_OPTIONS[0])
        st.session_state.quick_simple_ratio = QUICK_RATIO_OPTIONS[0]
        st.session_state.quick_simple_style = QUICK_STYLE_OPTIONS[0]
        st.session_state.quick_simple_quality = QUICK_QUALITY_OPTIONS[0]
        st.session_state.quick_simple_use_reference = False
        st.session_state.quick_simple_ref_mode = "1 ảnh"
        st.session_state.quick_simple_mode = DEFAULT_MULTI_API_MODE
        st.session_state.quick_simple_speed = list(QUICK_SPEED_PRESETS.keys())[0]
        st.session_state.quick_prompt_clip_refs = []
        st.session_state.quick_edit_clip_refs = []
        st.session_state.quick_upscale_clip_refs = []
        st.session_state.quick_translate_clip_refs = []
        st.session_state.quick_remix_clip_refs = []
        st.session_state.quick_universal_clip_refs = []
        st.session_state.quick_green_clip_refs = []
        st.session_state.quick_analyze_bg_clip_refs = []
        st.session_state.quick_character_detail_note = ""
        for scope in ("quick", "quick_universal", "quick_remix", "quick_edit", "quick_upscale", "quick_translate", "quick_style"):
            st.session_state[f"{scope}_batch_use_commands"] = False
            st.session_state[f"{scope}_batch_use_all_presets"] = False
        # Reset các slider Advanced về mặc định để không "ma"
        st.session_state.gen_cfg_scale = 7.0
        st.session_state.gen_steps = 40
        st.session_state.gen_strength = 0.75
        st.session_state.gen_clip_skip = 1
        st.session_state.gen_seed = ""
        st.session_state.gen_sampler = ""
        st.session_state.gen_negative_prompt = ""
        st.session_state["_quick_reset_notice"] = True

    bar_model, bar_op, bar_util = st.columns([1.6, 2.4, 1.0], gap="small")
    with bar_model:
        selected_top = pill_single_select(
            "Model AI",
            options=quick_models,
            key="studio_top_model",
            default=st.session_state.studio_top_model,
        )
        if selected_top and selected_top != st.session_state.manual_model:
            st.session_state.manual_model = selected_top
    with bar_op:
        operation = pill_single_select(
            "Tác vụ",
            options=QUICK_OPERATION_OPTIONS,
            key="quick_operation",
            default=_normalize_quick_choice(
                str(st.session_state.get("quick_operation", QUICK_OPERATION_OPTIONS[0])),
                QUICK_OPERATION_OPTIONS,
            ),
        )
    with bar_util:
        util1, util2 = st.columns(2, gap="small")
        with util1:
            if st.button("↻ Nạp model", use_container_width=True, key="btn_quick_load_models"):
                ok_load, load_msg = load_models_into_state(base_url, api_key)
                if ok_load:
                    st.session_state.studio_top_model = suggest_top_model(st.session_state.models, st.session_state.manual_model)
                    st.success(load_msg)
                else:
                    st.error(load_msg)
        with util2:
            st.button(
                "⟲ Reset",
                use_container_width=True,
                key="btn_quick_clean_defaults",
                on_click=_reset_quick_studio_defaults,
            )
    if st.session_state.pop("_quick_reset_notice", False):
        st.success("Đã đưa giao diện về mặc định.")

    model = suggest_top_model(
        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
        str(st.session_state.manual_model).strip(),
    )
    st.session_state.manual_model = model

    with st.expander("🎯 Lưu ý chi tiết nhân vật", expanded=False):
        tpl_col, btn_col, clr_col = st.columns([2.4, 1.0, 0.7], gap="small")
        with tpl_col:
            char_template = st.selectbox(
                "Mẫu chi tiết",
                options=list(CHARACTER_DETAIL_TEMPLATES.keys()),
                key="quick_character_detail_template",
                label_visibility="collapsed",
            )
        with btn_col:
            if st.button("➕ Chèn mẫu", use_container_width=True, key="btn_quick_character_detail_use"):
                tpl_text = CHARACTER_DETAIL_TEMPLATES.get(char_template, "")
                if tpl_text:
                    current_note = str(st.session_state.get("quick_character_detail_note", "")).strip()
                    st.session_state.quick_character_detail_note = (
                        f"{current_note} {tpl_text}".strip() if current_note else tpl_text
                    )
                    st.success("Đã chèn chi tiết.")
        with clr_col:
            if st.button("🧹 Xóa", use_container_width=True, key="btn_quick_character_detail_clear"):
                st.session_state.quick_character_detail_note = ""
        st.text_area(
            "Chi tiết cần giữ cố định (ví dụ: họa tiết mắt, nốt ruồi, kiểu tóc, phụ kiện...)",
            key="quick_character_detail_note",
            height=90,
            placeholder="Ví dụ: Mắt có họa tiết ngôi sao màu tím ở tròng mắt, luôn giữ rõ cả 2 mắt.",
        )

    if operation not in {"Tạo ảnh", "Làm truyện tranh"}:
        with st.expander("🧩 Vẽ theo lệnh mẫu (batch)", expanded=False):
            st.toggle("Bật chế độ batch theo lệnh", key="quick_batch_use_commands")
            st.checkbox("Dùng toàn bộ 25 lệnh mẫu", key="quick_batch_use_all_presets")
            st.text_area(
                "Danh sách lệnh (mỗi dòng 1 lệnh)",
                key="quick_batch_commands_text",
                height=200,
                placeholder="Dán thêm lệnh mới, mỗi dòng 1 lệnh...",
            )
            batch_preview_count = len(pose_command_presets) if bool(st.session_state.get("quick_batch_use_all_presets", False)) else len(
                _parse_batch_commands(str(st.session_state.get("quick_batch_commands_text", "")))
            )
            st.caption(f"Sẵn sàng batch: {batch_preview_count} lệnh")

    if operation == "Làm truyện tranh":
        render_story_workflow(base_url, api_key, model)
        return

    if operation == "Vẽ art game Tu Tiên Cờ":
        from tutienco_art_workflow import render_tutienco_workflow

        render_tutienco_workflow(
            base_url=base_url,
            api_key=api_key,
            model=model,
            run_payload_generation=run_payload_generation,
            timestamp_slug_fn=timestamp_slug,
            apply_character_detail_note=_apply_character_detail_note,
        )
        render_recent_outputs_strip()
        return

    if operation == "Tạo ảnh":
        # ============= Pre-compute settings & payload (so action button stays at top) =============
        count_options = [str(item) for item in QUICK_COUNT_OPTIONS]
        count_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_count", "")), count_options)
        mode_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_mode", "")), MULTI_API_MODES)
        speed_options = list(QUICK_SPEED_PRESETS.keys())
        speed_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_speed", "")), speed_options)
        ratio_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_ratio", "")), QUICK_RATIO_OPTIONS)
        style_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_style", "")), QUICK_STYLE_OPTIONS)
        quality_default = _normalize_quick_choice(str(st.session_state.get("quick_simple_quality", "")), QUICK_QUALITY_OPTIONS)

        ratio_choice = ratio_default
        count_choice = count_default
        style_choice = style_default
        quality_choice = quality_default
        speed_choice = speed_default
        mode_choice = mode_default

        # Marker so CSS can style this specific 3-col block as glass cards.
        st.markdown("<div class='nr-studio-row-marker'></div>", unsafe_allow_html=True)
        left_col, center_col, right_col = st.columns([1.0, 2.5, 0.95], gap="medium")

        # ============================ LEFT COLUMN — Prompt + Settings ============================
        with left_col:
            st.markdown("<div class='nr-card-header'>📝 PROMPT</div>", unsafe_allow_html=True)
            prompt_input = st.text_area(
                "Prompt chính",
                key="quick_subject",
                height=170,
                placeholder="Ví dụ: lâu đài cổ tích trên đỉnh núi, phong cảnh huyền ảo, mây trôi, ánh sáng hoàng hôn, chi tiết cao",
                label_visibility="collapsed",
            )
            st.caption(f"Số ký tự: {len(prompt_input or '')}")

            prompt_refs = parse_pasted_image_refs(prompt_input or "")
            clip_refs: list[str] = [item for item in st.session_state.get("quick_prompt_clip_refs", []) if isinstance(item, str)]
            dropped_refs: list[str] = []

            with st.expander("📎 Tham chiếu ảnh (upload / clipboard)", expanded=False):
                dropped_quick_files = st.file_uploader(
                    "Kéo / thả ảnh vào đây",
                    type=["png", "jpg", "jpeg", "webp", "bmp"],
                    accept_multiple_files=True,
                    key="quick_prompt_drop_upload",
                    label_visibility="collapsed",
                )
                dropped_refs = _uploaded_to_refs(dropped_quick_files)

                p1, p2 = st.columns([1.3, 0.7], gap="small")
                with p1:
                    if st.button("📋 Dán Clipboard", key="btn_quick_prompt_os_clipboard", use_container_width=True):
                        data_url, err = grab_clipboard_image_data_url()
                        if data_url:
                            before_len = len(clip_refs)
                            clip_refs = unique_list(clip_refs + [data_url])
                            st.session_state.quick_prompt_clip_refs = clip_refs
                            if len(clip_refs) > before_len:
                                st.success("Đã nhận ảnh clipboard.")
                        else:
                            st.warning(err)
                with p2:
                    if st.button("🧹 Xóa", key="btn_clear_quick_prompt_clip", use_container_width=True):
                        st.session_state.quick_prompt_clip_refs = []
                        clip_refs = []

                if False:  # legacy enable_paste_component removed
                    pasted_clip = paste_image_button("Dán ảnh", key="quick_prompt_paste_button")
                    clip_image = getattr(pasted_clip, "image_data", None)
                    if clip_image is not None:
                        buffer = io.BytesIO()
                        clip_image.save(buffer, format="PNG")
                        clip_data_url = safe_image_to_data_url(buffer.getvalue(), "image/png")
                        before_len = len(clip_refs)
                        clip_refs = unique_list(clip_refs + [clip_data_url])
                        st.session_state.quick_prompt_clip_refs = clip_refs
                        if len(clip_refs) > before_len:
                            st.success("Đã nhận ảnh từ component dán.")

            prompt_refs = unique_list(prompt_refs + clip_refs + dropped_refs)
            _render_small_refs("Ảnh tham chiếu", prompt_refs)

            st.markdown("<div class='nr-card-divider'></div>", unsafe_allow_html=True)
            st.markdown("<div class='nr-card-header'>🎨 STYLE &amp; ĐẦU RA</div>", unsafe_allow_html=True)

            ratio_choice = pill_single_select(
                "Tỷ lệ khung",
                options=QUICK_RATIO_OPTIONS,
                key="quick_simple_ratio",
                default=ratio_default,
            )
            count_choice = pill_single_select(
                "Số ảnh / lần",
                options=count_options,
                key="quick_simple_count",
                default=count_default,
            )
            style_choice = pill_single_select(
                "Phong cách",
                options=QUICK_STYLE_OPTIONS,
                key="quick_simple_style",
                default=style_default,
            )
            quality_choice = pill_single_select(
                "Chất lượng",
                options=QUICK_QUALITY_OPTIONS,
                key="quick_simple_quality",
                default=quality_default,
            )
            transparent_bg = st.toggle(
                "Nền trong suốt PNG",
                value=bool(st.session_state.get("quick_simple_transparent_bg", False)),
                key="quick_simple_transparent_bg",
                help="Bật để AI vẽ nền xanh lá #00FF00 một màu, sau đó app tự xóa nền xanh và lưu PNG RGBA.",
            )
            if transparent_bg:
                st.caption("Dùng cho nhân vật, item, icon, sticker. Tắt nếu cần cảnh nền.")

            st.markdown("<div class='nr-card-divider'></div>", unsafe_allow_html=True)
            st.markdown("<div class='nr-card-header'>⚡ API &amp; TỐC ĐỘ</div>", unsafe_allow_html=True)
            speed_choice = pill_single_select(
                "Tốc độ",
                options=speed_options,
                key="quick_simple_speed",
                default=speed_default,
            )
            mode_choice = st.selectbox(
                "Chế độ gọi API",
                options=MULTI_API_MODES,
                index=MULTI_API_MODES.index(mode_default),
                key="quick_simple_mode",
            )
            with st.expander("Ổn định mạng / timeout", expanded=False):
                n1, n2 = st.columns(2, gap="small")
                with n1:
                    st.number_input(
                        "Timeout (giây)",
                        min_value=MIN_API_POST_TIMEOUT_SECONDS,
                        max_value=MAX_API_TIMEOUT_SECONDS,
                        step=10,
                        key="api_request_timeout",
                    )
                with n2:
                    st.number_input(
                        "Retry",
                        min_value=0,
                        max_value=MAX_IMAGE_RETRY_COUNT,
                        step=1,
                        key="image_retry_count",
                    )
                st.number_input(
                    "Backoff (giây)",
                    min_value=0.2,
                    max_value=10.0,
                    step=0.1,
                    key="image_retry_backoff",
                )
                st.caption("Hay timeout → tăng timeout 360-480s và retry 1-2 lần.")
            with st.expander("🧩 Vẽ theo lệnh mẫu (batch)", expanded=False):
                st.toggle("Bật chế độ batch theo lệnh", key="quick_batch_use_commands")
                st.checkbox("Dùng toàn bộ 25 lệnh mẫu", key="quick_batch_use_all_presets")
                st.text_area(
                    "Danh sách lệnh (mỗi dòng 1 lệnh)",
                    key="quick_batch_commands_text",
                    height=220,
                    placeholder="Dán thêm lệnh mới, mỗi dòng 1 lệnh...",
                )
                batch_preview_count = len(pose_command_presets) if bool(st.session_state.get("quick_batch_use_all_presets", False)) else len(
                    _parse_batch_commands(str(st.session_state.get("quick_batch_commands_text", "")))
                )
                st.caption(f"Sẵn sàng batch: {batch_preview_count} lệnh")

        # ============================ COMPUTE PAYLOAD ============================
        refs: list[str] = list(prompt_refs)
        ref_count = len(refs)
        if refs:
            with left_col:
                st.markdown("<div class='nr-card-divider'></div>", unsafe_allow_html=True)
                st.markdown("<div class='nr-card-header'>🖼️ ÁP ẢNH THAM CHIẾU</div>", unsafe_allow_html=True)
                ref_apply_mode = pill_single_select(
                    "Cách áp",
                    options=["Tự động", "Chỉ ảnh đầu tiên"],
                    key="quick_ref_apply_mode",
                    default=_normalize_quick_choice(str(st.session_state.get("quick_ref_apply_mode", "Tự động")), ["Tự động", "Chỉ ảnh đầu tiên"]),
                )
                if ref_apply_mode == "Chỉ ảnh đầu tiên":
                    refs = refs[:1]
                    ref_count = 1

        final_prompt = _normalize_prompt_text(prompt_input) or ("ảnh mẫu tham chiếu" if refs else "")
        final_prompt = _apply_character_detail_note(final_prompt)
        try:
            selected_count = int(str(count_choice).strip())
        except Exception:
            selected_count = QUICK_COUNT_OPTIONS[0]
        if selected_count not in QUICK_COUNT_OPTIONS:
            selected_count = QUICK_COUNT_OPTIONS[0]

        payload: dict[str, Any] = {
            "model": model,
            "prompt": final_prompt,
            "n": selected_count,
        }
        if ratio_choice != QUICK_RATIO_OPTIONS[0]:
            payload["aspect_ratio"] = ratio_choice

        style_value = ""
        if style_choice not in {"Mặc định", "Không áp phong cách"}:
            style_value = str(STYLE_PRESETS.get(style_choice, {}).get("style", "")).strip()
        if style_value:
            payload["style"] = style_value

        quality_value = ""
        if quality_choice != "Mặc định":
            quality_value = str(QUALITY_PROFILES.get(quality_choice, {}).get("quality", "")).strip()
        if quality_value:
            payload["quality"] = quality_value

        apply_transparent_background_request(payload, bool(transparent_bg))

        if refs:
            if len(refs) == 1:
                payload["image"] = refs[0]
            else:
                payload["images"] = refs

        # Đọc các tham số Advanced từ cột phải (CFG / Steps / Detail / Sampler / Seed / Clip Skip / Negative).
        # Chỉ đẩy vào payload khi user thực sự thay đổi khác mặc định.
        negative_text = str(st.session_state.get("gen_negative_prompt", "") or "").strip()
        if negative_text:
            payload["negative_prompt"] = negative_text
        try:
            cfg_val = float(st.session_state.get("gen_cfg_scale", 7.0))
            if abs(cfg_val - 7.0) > 1e-3:
                payload["cfg_scale"] = cfg_val
                payload["guidance_scale"] = cfg_val
        except Exception:
            pass
        try:
            steps_val = int(st.session_state.get("gen_steps", 40))
            if steps_val != 40:
                payload["steps"] = steps_val
        except Exception:
            pass
        try:
            detail_val = float(st.session_state.get("gen_strength", 0.75))
            if abs(detail_val - 0.75) > 1e-3:
                payload["strength"] = detail_val
        except Exception:
            pass
        sampler_val = str(st.session_state.get("gen_sampler", "") or "").strip()
        if sampler_val:
            payload["sampler"] = sampler_val
        seed_text = str(st.session_state.get("gen_seed", "") or "").strip()
        if seed_text:
            try:
                payload["seed"] = int(seed_text)
            except Exception:
                payload["seed"] = seed_text
        try:
            clip_val = int(st.session_state.get("gen_clip_skip", 1))
            if clip_val != 1:
                payload["clip_skip"] = clip_val
        except Exception:
            pass

        speed_parallel = int(QUICK_SPEED_PRESETS.get(speed_choice, QUICK_SPEED_PRESETS[list(QUICK_SPEED_PRESETS.keys())[0]]))
        st.session_state.multi_api_max_parallel = speed_parallel
        st.session_state.multi_api_mode = mode_choice
        st.session_state.studio_count = selected_count
        st.session_state.gen_count = selected_count
        st.session_state.studio_response_format = "binary"
        st.session_state.gen_response_format = "binary"

        if not str(st.session_state.get("quick_api_keys_pool_text", "")).strip():
            st.session_state.quick_api_keys_pool_text = str(st.session_state.get("api_keys_pool_text", ""))

        keys_raw = str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", ""))
        key_pool = parse_api_keys_pool(keys_raw, st.session_state.api_key)
        key_pool_count = len(key_pool)

        # Big primary "Generate" button at the end of the left column.
        with left_col:
            st.markdown("<div class='nr-card-divider-strong'></div>", unsafe_allow_html=True)
            generate_clicked = st.button("✨ Tạo ảnh AI", type="primary", use_container_width=True, key="btn_quick_generate")
            tg1, tg2 = st.columns([1, 1], gap="small")
            with tg1:
                st.toggle("💾 Lưu máy", key="auto_save_outputs")
            with tg2:
                if mode_choice != MODE_SINGLE_API:
                    can_split = should_split_batch_requests(mode_choice, selected_count, key_pool_count)
                    if can_split:
                        preview_workers = resolve_parallel_workers(
                            mode=mode_choice,
                            requested_count=selected_count,
                            key_pool_count=key_pool_count,
                            max_parallel=speed_parallel,
                        )
                        st.caption(f"🔑 {key_pool_count} key · {preview_workers} luồng")
                    else:
                        st.caption("⚠️ Fallback 1 request")

        if generate_clicked:
            batch_commands: list[str] = []
            batch_commands = _get_batch_commands("quick")

            if batch_commands:
                with center_col:
                    _run_command_batch(
                        base_payload=payload,
                        base_prompt=prompt_input,
                        commands=batch_commands,
                        output_prefix="quick_cmd",
                        workflow_label="Lệnh mẫu",
                        refs_available=bool(refs),
                    )
            elif not final_prompt.strip() and not refs:
                with center_col:
                    st.error("Hãy nhập prompt hoặc thêm ảnh mẫu để tránh lạc đề.")
            else:
                output_file = f"{st.session_state.studio_output_prefix}_quick_{timestamp_slug()}.png"
                run_payload_generation(
                    base_url,
                    api_key,
                    payload,
                    "binary",
                    output_file,
                    "Quick Studio",
                    show_inline_preview=False,
                )

        # ============================ RIGHT COLUMN — Image Info + Advanced ============================
        with right_col:
            st.markdown("<div class='nr-card-header'>📊 IMAGE INFO</div>", unsafe_allow_html=True)
            info_lines = [
                f"<b>Model</b><br><code>{html.escape(model)}</code>",
                f"<b>Số ảnh</b> · {selected_count}",
                f"<b>Tỷ lệ</b> · {ratio_choice}",
                f"<b>Phong cách</b> · {style_choice}",
                f"<b>Chất lượng</b> · {quality_choice}",
                f"<b>Nền</b> · {'Trong suốt PNG/RGBA' if transparent_bg else 'Tự động'}",
                f"<b>Tốc độ</b> · {speed_choice}",
            ]
            st.markdown(
                "<div class='canvas-meta'>" + "<div class='canvas-meta-row'>" + "</div><div class='canvas-meta-row'>".join(info_lines) + "</div></div>",
                unsafe_allow_html=True,
            )

            st.markdown("<div class='nr-card-divider'></div>", unsafe_allow_html=True)
            st.markdown("<div class='nr-card-header'>🎚️ ADVANCED</div>", unsafe_allow_html=True)
            st.slider("CFG Scale", min_value=1.0, max_value=20.0, step=0.1, key="gen_cfg_scale")
            st.slider("Steps", min_value=1, max_value=100, step=1, key="gen_steps")
            st.slider("Detail", min_value=0.1, max_value=1.0, step=0.05, key="gen_strength")
            with st.expander("Sampler / Seed / Clip Skip", expanded=False):
                st.selectbox("Sampler", options=SAMPLER_OPTIONS, key="gen_sampler")
                st.text_input("Seed (trống = random)", key="gen_seed")
                st.slider("Clip Skip", min_value=1, max_value=4, step=1, key="gen_clip_skip")

            st.markdown("<div class='nr-card-divider'></div>", unsafe_allow_html=True)
            st.markdown("<div class='nr-card-header'>🚫 NEGATIVE PROMPT</div>", unsafe_allow_html=True)
            st.text_area(
                "Loại trừ",
                key="gen_negative_prompt",
                height=86,
                placeholder="low quality, blurry, watermark, extra fingers, deformed anatomy",
                label_visibility="collapsed",
            )

            with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
                render_payload_command_panel(
                    payload=payload,
                    workflow_label="Tạo ảnh",
                    count=selected_count,
                    ref_count=ref_count,
                    mode_choice=mode_choice,
                    speed_choice=speed_choice,
                    key_pool_count=key_pool_count,
                    user_command=prompt_input,
                )
                with st.expander("Xem JSON payload thô", expanded=False):
                    payload_preview = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"image", "images"}
                    }
                    if "prompt" in payload_preview:
                        prompt_text = str(payload_preview.get("prompt", ""))
                        if len(prompt_text) > 260:
                            payload_preview["prompt"] = f"{prompt_text[:260]}..."
                    if "negative_prompt" in payload_preview:
                        negative_text = str(payload_preview.get("negative_prompt", ""))
                        if len(negative_text) > 220:
                            payload_preview["negative_prompt"] = f"{negative_text[:220]}..."
                    if ref_count > 0:
                        payload_preview["image_sources"] = f"{ref_count} ảnh tham chiếu (đã ẩn dữ liệu ảnh/base64)"
                    st.json(payload_preview)

        # ============================ CENTER COLUMN — Gallery ============================
        with center_col:
            recent_outputs = [
                entry for entry in st.session_state.get("recent_outputs", []) if isinstance(entry, dict)
            ]
            head_l, head_r = st.columns([2.5, 1.0], gap="small")
            with head_l:
                st.markdown(
                    "<div class='nr-gallery-head'>"
                    "<span class='nr-gallery-title'>🖼️ Generated Images</span>"
                    f"<span class='nr-gallery-count'>{len(recent_outputs)}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with head_r:
                st.caption(f"⏱ {datetime.now().strftime('%H:%M')} • {model.split('/')[-1] if '/' in model else model}")

            if recent_outputs:
                show_items = recent_outputs[:8]
                cols_per_row = 2
                rows = [show_items[i:i + cols_per_row] for i in range(0, len(show_items), cols_per_row)]
                for row_items in rows:
                    cols = st.columns(cols_per_row, gap="small")
                    for col, entry in zip(cols, row_items):
                        with col:
                            local_path = str(entry.get("local_path", "")).strip()
                            url = str(entry.get("url", "")).strip()
                            image_bytes = entry.get("image_bytes", b"")
                            if local_path and Path(local_path).exists():
                                st.image(local_path, use_container_width=True)
                            elif isinstance(image_bytes, bytes) and image_bytes:
                                st.image(image_bytes, use_container_width=True)
                            elif url:
                                st.image(url, use_container_width=True)
                            else:
                                st.caption("Không có preview")
                            alpha_label = transparency_check_label(
                                entry.get("transparent_check"),
                                requested=bool(entry.get("transparent_requested")),
                            )
                            if alpha_label:
                                st.caption(alpha_label)
                            entry_id = str(entry.get("id", "")).strip() or f"recent_{recent_outputs.index(entry)}"
                            mini1, mini2 = st.columns([1, 1], gap="small")
                            with mini1:
                                if st.button("👁 Xem", key=f"btn_recent_view_{entry_id}", use_container_width=True):
                                    st.session_state.recent_view_output_id = entry_id
                            with mini2:
                                if st.button("🗑 Xóa", key=f"btn_recent_del_{entry_id}", use_container_width=True):
                                    if remove_recent_output(entry_id):
                                        st.success("Đã xóa.")
                                    st.rerun()
            else:
                st.markdown(
                    """
                    <div class='canvas-gallery-empty'>
                      <div>
                        <div class='canvas-gallery-empty-icon'>✨</div>
                        <div class='canvas-gallery-empty-title'>Chưa có ảnh nào</div>
                        <div class='canvas-gallery-empty-sub'>Nhập prompt bên trái và bấm <b>✨ Tạo ảnh AI</b> để bắt đầu.<br>Ảnh tạo ra sẽ hiển thị thành lưới 2 cột tại đây.</div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            view_id = str(st.session_state.get("recent_view_output_id", "")).strip()
            if view_id:
                selected_output = next(
                    (item for item in recent_outputs if str(item.get("id", "")).strip() == view_id),
                    None,
                )
                if selected_output:
                    with st.expander("Xem ảnh đã chọn (full size)", expanded=True):
                        local_path = str(selected_output.get("local_path", "")).strip()
                        url = str(selected_output.get("url", "")).strip()
                        image_bytes = selected_output.get("image_bytes", b"")
                        if local_path and Path(local_path).exists():
                            st.image(local_path, use_container_width=True)
                        elif isinstance(image_bytes, bytes) and image_bytes:
                            st.image(image_bytes, use_container_width=True)
                        elif url:
                            st.image(url, use_container_width=True)
                        alpha_label = transparency_check_label(
                            selected_output.get("transparent_check"),
                            requested=bool(selected_output.get("transparent_requested")),
                        )
                        if alpha_label:
                            st.caption(alpha_label)
                        st.code(str(selected_output.get("prompt", "")))

        if True:
            with st.expander("Payload debug", expanded=False):
                st.json(payload)

    elif operation == "AI đa năng (copy ảnh + lệnh tự do)":
        render_workflow_intro(
            "⚡ AI đa năng (copy ảnh + lệnh tự do)",
            "Dán/copy nhiều ảnh + gõ lệnh tự do. Hệ thống tự hiểu vai trò ảnh và render mạnh.",
        )

        universal_instruction = st.text_area(
            "Lệnh tự do",
            key="quick_universal_instruction",
            height=150,
            placeholder="Ví dụ: thay nhân vật ảnh 1 vào bố cục ảnh 2, giữ ánh sáng hoa đào, bóng lá trên mặt, bokeh tiền cảnh, ảnh sắc nét chân thực.",
        )
        prompt_refs = parse_pasted_image_refs(universal_instruction or "")
        universal_clip_refs: list[str] = [
            item for item in st.session_state.get("quick_universal_clip_refs", []) if isinstance(item, str)
        ]

        universal_upload = st.file_uploader(
            "Kéo/thả ảnh (hỗ trợ nhiều ảnh)",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=True,
            key="quick_universal_upload",
        )

        u1, u2, u3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with u1:
            if st.button("📋 Clipboard", key="btn_quick_universal_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    universal_clip_refs = unique_list(universal_clip_refs + [data_url])
                    st.session_state.quick_universal_clip_refs = universal_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with u2:
            if st.button("🧹 Xóa", key="btn_clear_quick_universal_clip", use_container_width=True):
                st.session_state.quick_universal_clip_refs = []
                universal_clip_refs = []
        with u3:
            st.caption("Copy ảnh rồi bấm Clipboard, hoặc kéo/thả nhiều ảnh vào uploader.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(universal_upload) + universal_clip_refs)
        _render_small_refs("Ảnh đã nạp", refs)

        c1, c2, c3 = st.columns([1.0, 1.2, 1.1], gap="medium")
        with c1:
            count_universal = pill_single_select(
                "Số ảnh xuất",
                options=["1", "2", "4", "8", "16", "32"],
                key="quick_universal_count",
                default=_normalize_quick_choice(str(st.session_state.get("quick_universal_count", "1")), ["1", "2", "4", "8", "16", "32"]),
            )
        with c2:
            mode_default = _normalize_quick_choice(str(st.session_state.get("quick_universal_mode", "")), MULTI_API_MODES)
            mode_choice = st.selectbox(
                "Chế độ gọi API",
                options=MULTI_API_MODES,
                index=MULTI_API_MODES.index(mode_default),
                key="quick_universal_mode",
            )
        with c3:
            speed_options = list(QUICK_SPEED_PRESETS.keys())
            speed_default = _normalize_quick_choice(str(st.session_state.get("quick_universal_speed", "")), speed_options)
            speed_choice = pill_single_select(
                "Tốc độ",
                options=speed_options,
                key="quick_universal_speed",
                default=speed_default,
            )

        p1, p2, p3 = st.columns([1.2, 1.0, 1.0], gap="small")
        with p1:
            power_options = list(QUICK_UNIVERSAL_POWER_PRESETS.keys())
            power_choice = pill_single_select(
                "Sức mạnh render",
                options=power_options,
                key="quick_universal_power",
                default=_normalize_quick_choice(str(st.session_state.get("quick_universal_power", "Cân bằng")), power_options),
            )
        with p2:
            ratio_choice = pill_single_select(
                "Tỷ lệ",
                options=QUICK_RATIO_OPTIONS,
                key="quick_universal_ratio",
                default=_normalize_quick_choice(str(st.session_state.get("quick_universal_ratio", QUICK_RATIO_OPTIONS[0])), QUICK_RATIO_OPTIONS),
            )
        with p3:
            quality_choice = pill_single_select(
                "Chất lượng",
                options=QUICK_QUALITY_OPTIONS,
                key="quick_universal_quality",
                default=_normalize_quick_choice(str(st.session_state.get("quick_universal_quality", QUICK_QUALITY_OPTIONS[0])), QUICK_QUALITY_OPTIONS),
            )

        lock1, lock2, lock3 = st.columns([1.0, 1.1, 1.0], gap="small")
        with lock1:
            lock_identity = st.toggle(
                "Khóa nhân vật ảnh 1",
                value=bool(st.session_state.get("quick_universal_lock_identity", True)),
                key="quick_universal_lock_identity",
            )
        with lock2:
            prioritize_scene = st.toggle(
                "Ưu tiên cảnh ảnh 2",
                value=bool(st.session_state.get("quick_universal_prioritize_scene", False)),
                key="quick_universal_prioritize_scene",
            )
        with lock3:
            transparent_bg = st.toggle(
                "Nền trong suốt PNG",
                value=bool(st.session_state.get("quick_universal_transparent_bg", False)),
                key="quick_universal_transparent_bg",
                help="AI vẽ nền xanh lá #00FF00 rồi app tự xóa xanh thành nền trong suốt.",
            )

        with st.expander("Tùy chỉnh nâng cao", expanded=False):
            style_choice = pill_single_select(
                "Phong cách",
                options=QUICK_STYLE_OPTIONS,
                key="quick_universal_style",
                default=_normalize_quick_choice(str(st.session_state.get("quick_universal_style", QUICK_STYLE_OPTIONS[0])), QUICK_STYLE_OPTIONS),
            )
            negative_prompt = st.text_area(
                "Negative prompt",
                value="",
                height=78,
                key="quick_universal_negative_prompt",
                placeholder="Ví dụ: blurry, lowres, bad anatomy, extra fingers, noisy background",
            )

            adv1, adv2, adv3 = st.columns(3, gap="small")
            with adv1:
                use_seed = st.toggle("Khóa seed", value=False, key="quick_universal_use_seed")
                seed_value = st.number_input(
                    "Seed",
                    min_value=0,
                    max_value=99999999,
                    step=1,
                    value=2026,
                    key="quick_universal_seed",
                    disabled=not use_seed,
                )
            with adv2:
                sampler_value = st.selectbox("Sampler", options=SAMPLER_OPTIONS, key="quick_universal_sampler")
                output_format_value = st.selectbox("Output format", options=OUTPUT_FORMAT_OPTIONS, key="quick_universal_output_format")
            with adv3:
                background_value = st.selectbox("Background", options=BACKGROUND_OPTIONS, key="quick_universal_background")
                image_detail_override = st.selectbox("Image detail", options=IMAGE_DETAIL_OPTIONS, key="quick_universal_image_detail")

            universal_extra_json = st.text_area("JSON bổ sung", value="{}", height=90, key="quick_universal_extra_json")

        free_command = _normalize_prompt_text(universal_instruction)
        command_core = free_command if free_command else "Xử lý ảnh theo ngữ cảnh tốt nhất, kết quả sắc nét và tự nhiên."

        assistant_rules: list[str] = [
            "Bạn là trợ lý xử lý ảnh đa năng, ưu tiên làm đúng lệnh tự do của người dùng.",
            "Nếu có nhiều ảnh: mặc định Ảnh 1 là chủ thể chính; các ảnh còn lại là tham chiếu style/cảnh, trừ khi lệnh ghi rõ khác.",
        ]
        if lock_identity:
            assistant_rules.append(
                "Khóa danh tính nhân vật/chủ thể từ Ảnh 1: giữ khuôn mặt, tóc, trang phục, phụ kiện và tỷ lệ cơ thể; không đổi người."
            )
        if prioritize_scene:
            assistant_rules.append(
                "Ưu tiên học bố cục, ánh sáng, đổ bóng và chiều sâu không gian từ Ảnh 2 nếu có."
            )

        final_prompt = "\n".join(assistant_rules) + f"\n\nYêu cầu người dùng:\n{command_core}"
        final_prompt = _apply_character_detail_note(final_prompt)

        power_profile = QUICK_UNIVERSAL_POWER_PRESETS.get(power_choice, QUICK_UNIVERSAL_POWER_PRESETS["Cân bằng"])
        try:
            selected_count = int(str(count_universal).strip())
        except Exception:
            selected_count = 1
        selected_count = max(1, min(32, selected_count))

        payload: dict[str, Any] = {
            "model": model,
            "prompt": final_prompt,
            "n": selected_count,
            "steps": int(power_profile.get("steps", 36)),
            "guidance_scale": float(power_profile.get("guidance_scale", 7.0)),
            "cfg_scale": float(power_profile.get("cfg_scale", 7.0)),
            "clip_skip": int(power_profile.get("clip_skip", 1)),
        }

        quality_value = ""
        if quality_choice != "Mặc định":
            quality_value = str(QUALITY_PROFILES.get(quality_choice, {}).get("quality", "")).strip()
        if quality_value:
            payload["quality"] = quality_value

        style_value = ""
        if style_choice not in {"Mặc định", "Không áp phong cách"}:
            style_value = str(STYLE_PRESETS.get(style_choice, {}).get("style", "")).strip()
        if style_value:
            payload["style"] = style_value

        if ratio_choice != QUICK_RATIO_OPTIONS[0]:
            payload["aspect_ratio"] = ratio_choice

        image_detail_final = str(image_detail_override).strip() or str(power_profile.get("image_detail", "")).strip()
        if image_detail_final:
            payload["image_detail"] = image_detail_final

        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if sampler_value:
            payload["sampler"] = sampler_value
        if output_format_value:
            payload["output_format"] = output_format_value
        if background_value:
            payload["background"] = background_value
        if bool(use_seed):
            payload["seed"] = int(seed_value)

        apply_transparent_background_request(payload, bool(transparent_bg))

        if refs:
            if len(refs) == 1:
                payload["image"] = refs[0]
            else:
                payload["images"] = refs[:12]

        speed_parallel = int(QUICK_SPEED_PRESETS.get(speed_choice, QUICK_SPEED_PRESETS[list(QUICK_SPEED_PRESETS.keys())[0]]))
        st.session_state.multi_api_max_parallel = speed_parallel
        st.session_state.multi_api_mode = mode_choice
        st.session_state.studio_count = selected_count
        st.session_state.gen_count = selected_count
        st.session_state.studio_response_format = "binary"
        st.session_state.gen_response_format = "binary"

        keys_raw = str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", ""))
        key_pool = parse_api_keys_pool(keys_raw, st.session_state.api_key)
        key_pool_count = len(key_pool)
        if mode_choice != MODE_SINGLE_API:
            can_split = should_split_batch_requests(mode_choice, selected_count, key_pool_count)
            if can_split:
                preview_workers = resolve_parallel_workers(
                    mode=mode_choice,
                    requested_count=selected_count,
                    key_pool_count=key_pool_count,
                    max_parallel=speed_parallel,
                )
                st.caption(
                    f"Đã nhận {key_pool_count} key • batch {selected_count} ảnh • chạy tối đa {preview_workers} luồng."
                )
            else:
                st.caption(
                    f"Chế độ `{mode_choice}` hiện chưa đủ điều kiện tách batch, hệ thống sẽ fallback về 1 request thường."
                )

        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=payload,
                workflow_label="AI đa năng",
                count=selected_count,
                ref_count=len(refs),
                mode_choice=mode_choice,
                speed_choice=speed_choice,
                key_pool_count=key_pool_count,
                user_command=command_core,
            )
            with st.expander("Xem JSON payload thô", expanded=False):
                payload_preview = {key: value for key, value in payload.items() if key not in {"image", "images"}}
                if "prompt" in payload_preview:
                    prompt_text = str(payload_preview.get("prompt", ""))
                    if len(prompt_text) > 260:
                        payload_preview["prompt"] = f"{prompt_text[:260]}..."
                if refs:
                    payload_preview["image_sources"] = f"{len(refs)} ảnh nguồn (đã ẩn dữ liệu ảnh/base64)"
                st.json(payload_preview)

        with st.expander("Ổn định mạng / timeout", expanded=False):
            n1, n2, n3 = st.columns([1.0, 1.0, 1.2], gap="small")
            with n1:
                st.number_input(
                    "Timeout request (giây)",
                    min_value=MIN_API_POST_TIMEOUT_SECONDS,
                    max_value=MAX_API_TIMEOUT_SECONDS,
                    step=10,
                    key="api_request_timeout",
                )
            with n2:
                st.number_input(
                    "Retry khi timeout",
                    min_value=0,
                    max_value=MAX_IMAGE_RETRY_COUNT,
                    step=1,
                    key="image_retry_count",
                )
            with n3:
                st.number_input(
                    "Backoff retry cơ bản (giây)",
                    min_value=0.2,
                    max_value=10.0,
                    step=0.1,
                    key="image_retry_backoff",
                )
            st.caption("Nếu hay timeout: tăng timeout lên 360-480s và retry 1-2 lần.")
        action1, action2 = st.columns([1.35, 0.95], gap="medium")
        with action1:
            if st.button("🚀 Chạy AI đa năng", type="primary", use_container_width=True, key="btn_quick_universal_submit"):
                if not command_core.strip() and not refs:
                    st.error("Hãy nhập lệnh tự do hoặc thêm ảnh để AI có dữ liệu xử lý.")
                else:
                    try:
                        payload_run = dict(payload)
                        payload_run.update(parse_json_object(universal_extra_json))
                    except Exception as ex:
                        st.error(f"JSON bổ sung không hợp lệ: {ex}")
                    else:
                        batch_commands = _get_batch_commands("quick")
                        if batch_commands:
                            _run_command_batch(
                                base_payload=payload_run,
                                base_prompt=command_core,
                                commands=batch_commands,
                                output_prefix="quick_universal_cmd",
                                workflow_label="Quick AI đa năng",
                                refs_available=bool(refs),
                            )
                        else:
                            output_file = f"{st.session_state.studio_output_prefix}_quick_universal_{timestamp_slug()}.png"
                            run_payload_generation(
                                base_url,
                                api_key,
                                payload_run,
                                "binary",
                                output_file,
                                "Quick AI đa năng",
                                show_inline_preview=False,
                            )
        with action2:
            st.toggle("Lưu ảnh ra máy", key="auto_save_outputs")
        st.caption("Tip: ảnh 1 nên là chủ thể, ảnh 2 trở đi là style/cảnh để AI hiểu đúng nhất.")

    elif operation == "Sửa ảnh nâng cao":
        render_workflow_intro(
            "🚀 Sửa ảnh nâng cao",
            "Nạp ảnh mẫu rồi tinh chỉnh sâu: style, quality, strength, seed, sampler, steps, multi-API.",
        )

        remix_prompt_text = st.text_area(
            "Mô tả mục tiêu chỉnh ảnh",
            key="quick_remix_prompt_input",
            height=130,
            placeholder="Ví dụ: giữ bố cục nhân vật chính, nâng chi tiết da và tóc, ánh sáng điện ảnh, nền sạch hơn.",
        )
        prompt_refs = parse_pasted_image_refs(remix_prompt_text or "")
        remix_clip_refs: list[str] = [item for item in st.session_state.get("quick_remix_clip_refs", []) if isinstance(item, str)]

        remix_upload = st.file_uploader(
            "Kéo/thả ảnh mẫu để chỉnh (hỗ trợ nhiều ảnh)",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=True,
            key="quick_remix_upload",
        )

        r1, r2, r3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with r1:
            if st.button("📋 Clipboard", key="btn_quick_remix_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    remix_clip_refs = unique_list(remix_clip_refs + [data_url])
                    st.session_state.quick_remix_clip_refs = remix_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with r2:
            if st.button("🧹 Xóa", key="btn_clear_quick_remix_clip", use_container_width=True):
                st.session_state.quick_remix_clip_refs = []
                remix_clip_refs = []
        with r3:
            st.caption("Bạn có thể dán URL/data:image vào ô mô tả hoặc kéo/thả nhiều ảnh mẫu vào uploader.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(remix_upload) + remix_clip_refs)
        _render_small_refs("Ảnh mẫu", refs)

        ref_count = len(refs)
        if refs:
            ref_apply_mode = pill_single_select(
                "Áp ảnh mẫu",
                options=["Tự động (nhiều ảnh)", "Chỉ ảnh đầu tiên"],
                key="quick_remix_ref_apply_mode",
                default=_normalize_quick_choice(
                    str(st.session_state.get("quick_remix_ref_apply_mode", "Tự động (nhiều ảnh)")),
                    ["Tự động (nhiều ảnh)", "Chỉ ảnh đầu tiên"],
                ),
            )
            if ref_apply_mode == "Chỉ ảnh đầu tiên":
                refs = refs[:1]
                ref_count = 1

        c1, c2, c3 = st.columns([1.0, 1.25, 1.1], gap="medium")
        with c1:
            count_remix = pill_single_select(
                "Số biến thể",
                options=["1", "2", "4", "8"],
                key="quick_remix_count",
                default=_normalize_quick_choice(str(st.session_state.get("quick_remix_count", "1")), ["1", "2", "4", "8"]),
            )
        with c2:
            mode_default = _normalize_quick_choice(str(st.session_state.get("quick_remix_mode", "")), MULTI_API_MODES)
            mode_choice = st.selectbox(
                "Chế độ gọi API",
                options=MULTI_API_MODES,
                index=MULTI_API_MODES.index(mode_default),
                key="quick_remix_mode",
            )
        with c3:
            speed_options = list(QUICK_SPEED_PRESETS.keys())
            speed_default = _normalize_quick_choice(str(st.session_state.get("quick_remix_speed", "")), speed_options)
            speed_choice = pill_single_select(
                "Tốc độ",
                options=speed_options,
                key="quick_remix_speed",
                default=speed_default,
            )

        with st.expander("Ổn định mạng / timeout", expanded=False):
            n1, n2, n3 = st.columns([1.0, 1.0, 1.2], gap="small")
            with n1:
                st.number_input(
                    "Timeout request (giây)",
                    min_value=MIN_API_POST_TIMEOUT_SECONDS,
                    max_value=MAX_API_TIMEOUT_SECONDS,
                    step=10,
                    key="api_request_timeout",
                )
            with n2:
                st.number_input(
                    "Retry khi timeout",
                    min_value=0,
                    max_value=MAX_IMAGE_RETRY_COUNT,
                    step=1,
                    key="image_retry_count",
                )
            with n3:
                st.number_input(
                    "Backoff retry cơ bản (giây)",
                    min_value=0.2,
                    max_value=10.0,
                    step=0.1,
                    key="image_retry_backoff",
                )
            st.caption("Nếu hay timeout: tăng timeout lên 360-480s và retry 1-2 lần.")

        p1, p2, p3 = st.columns(3, gap="medium")
        with p1:
            ratio_choice = pill_single_select(
                "Tỷ lệ",
                options=QUICK_RATIO_OPTIONS,
                key="quick_remix_ratio",
                default=_normalize_quick_choice(str(st.session_state.get("quick_remix_ratio", QUICK_RATIO_OPTIONS[0])), QUICK_RATIO_OPTIONS),
            )
        with p2:
            style_choice = pill_single_select(
                "Phong cách",
                options=QUICK_STYLE_OPTIONS,
                key="quick_remix_style",
                default=_normalize_quick_choice(str(st.session_state.get("quick_remix_style", QUICK_STYLE_OPTIONS[0])), QUICK_STYLE_OPTIONS),
            )
        with p3:
            quality_choice = pill_single_select(
                "Chất lượng",
                options=QUICK_QUALITY_OPTIONS,
                key="quick_remix_quality",
                default=_normalize_quick_choice(str(st.session_state.get("quick_remix_quality", QUICK_QUALITY_OPTIONS[0])), QUICK_QUALITY_OPTIONS),
            )

        strength_map = {"Nhẹ": 0.35, "Vừa": 0.65, "Mạnh": 0.9}
        s1, s2, s3 = st.columns([1.0, 1.8, 1.0], gap="small")
        with s1:
            strength_preset = pill_single_select(
                "Mức chỉnh",
                options=list(strength_map.keys()),
                key="quick_remix_strength_preset",
                default=_normalize_quick_choice(str(st.session_state.get("quick_remix_strength_preset", "Vừa")), list(strength_map.keys())),
            )
        with s2:
            strength_value = st.slider(
                "Strength",
                min_value=0.1,
                max_value=1.0,
                step=0.05,
                value=float(strength_map[strength_preset]),
                key="quick_remix_strength_exact",
            )
        with s3:
            transparent_bg = st.toggle(
                "Nền trong suốt PNG",
                value=bool(st.session_state.get("quick_remix_transparent_bg", False)),
                key="quick_remix_transparent_bg",
                help="AI vẽ nền xanh lá #00FF00 rồi app tự xóa xanh thành PNG nền trong suốt.",
            )

        with st.expander("Tùy chỉnh nâng cao", expanded=False):
            negative_prompt = st.text_area(
                "Negative prompt",
                value="",
                height=78,
                key="quick_remix_negative_prompt",
                placeholder="Ví dụ: blurry, lowres, deformed hands, noisy texture",
            )

            adv_seed_col, adv_bg_col = st.columns([1.0, 1.2], gap="small")
            with adv_seed_col:
                use_seed = st.toggle("Khóa seed", value=False, key="quick_remix_use_seed")
                seed_value = st.number_input(
                    "Seed",
                    min_value=0,
                    max_value=99999999,
                    step=1,
                    value=2026,
                    key="quick_remix_seed",
                    disabled=not use_seed,
                )
            with adv_bg_col:
                bg_value = st.selectbox("Background", options=BACKGROUND_OPTIONS, key="quick_remix_background")

            adv1, adv2, adv3 = st.columns(3, gap="small")
            with adv1:
                steps_value = st.number_input("Steps", min_value=10, max_value=120, step=1, value=40, key="quick_remix_steps")
                clip_skip_value = st.number_input("Clip skip", min_value=1, max_value=4, step=1, value=1, key="quick_remix_clip_skip")
            with adv2:
                guidance_value = st.number_input(
                    "Guidance scale",
                    min_value=1.0,
                    max_value=20.0,
                    step=0.1,
                    value=7.5,
                    key="quick_remix_guidance_scale",
                )
                cfg_value = st.number_input(
                    "CFG scale",
                    min_value=1.0,
                    max_value=20.0,
                    step=0.1,
                    value=7.0,
                    key="quick_remix_cfg_scale",
                )
            with adv3:
                sampler_value = st.selectbox("Sampler", options=SAMPLER_OPTIONS, key="quick_remix_sampler")
                output_format_value = st.selectbox("Output format", options=OUTPUT_FORMAT_OPTIONS, key="quick_remix_output_format")
                image_detail_value = st.selectbox("Image detail", options=IMAGE_DETAIL_OPTIONS, key="quick_remix_image_detail")

            remix_extra_json = st.text_area("JSON bổ sung", value="{}", height=90, key="quick_remix_extra_json")

        final_prompt = _normalize_prompt_text(remix_prompt_text) or ("Chỉnh ảnh mẫu giữ bố cục chính, tăng chất lượng tổng thể." if refs else "")
        final_prompt = _apply_character_detail_note(final_prompt)
        try:
            selected_count = int(str(count_remix).strip())
        except Exception:
            selected_count = 1
        selected_count = max(1, min(8, selected_count))

        payload = {
            "model": model,
            "prompt": final_prompt,
            "n": selected_count,
            "strength": float(strength_value),
            "steps": int(steps_value),
            "guidance_scale": float(guidance_value),
            "cfg_scale": float(cfg_value),
            "clip_skip": int(clip_skip_value),
        }

        if ratio_choice != QUICK_RATIO_OPTIONS[0]:
            payload["aspect_ratio"] = ratio_choice

        style_value = ""
        if style_choice not in {"Mặc định", "Không áp phong cách"}:
            style_value = str(STYLE_PRESETS.get(style_choice, {}).get("style", "")).strip()
        if style_value:
            payload["style"] = style_value

        quality_value = ""
        if quality_choice != "Mặc định":
            quality_value = str(QUALITY_PROFILES.get(quality_choice, {}).get("quality", "")).strip()
        if quality_value:
            payload["quality"] = quality_value

        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        if bg_value:
            payload["background"] = bg_value
        if sampler_value:
            payload["sampler"] = sampler_value
        if output_format_value:
            payload["output_format"] = output_format_value
        if image_detail_value:
            payload["image_detail"] = image_detail_value

        if bool(use_seed):
            payload["seed"] = int(seed_value)

        apply_transparent_background_request(payload, bool(transparent_bg))

        if refs:
            if len(refs) == 1:
                payload["image"] = refs[0]
            else:
                payload["images"] = refs[:12]

        speed_parallel = int(QUICK_SPEED_PRESETS.get(speed_choice, QUICK_SPEED_PRESETS[list(QUICK_SPEED_PRESETS.keys())[0]]))
        st.session_state.multi_api_max_parallel = speed_parallel
        st.session_state.multi_api_mode = mode_choice
        st.session_state.studio_count = selected_count
        st.session_state.gen_count = selected_count
        st.session_state.studio_response_format = "binary"
        st.session_state.gen_response_format = "binary"

        keys_raw = str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", ""))
        key_pool = parse_api_keys_pool(keys_raw, st.session_state.api_key)
        key_pool_count = len(key_pool)
        if mode_choice != MODE_SINGLE_API:
            can_split = should_split_batch_requests(mode_choice, selected_count, key_pool_count)
            if can_split:
                preview_workers = resolve_parallel_workers(
                    mode=mode_choice,
                    requested_count=selected_count,
                    key_pool_count=key_pool_count,
                    max_parallel=speed_parallel,
                )
                st.caption(
                    f"Đã nhận {key_pool_count} key • batch {selected_count} ảnh • chạy tối đa {preview_workers} luồng."
                )
            else:
                st.caption(
                    f"Chế độ `{mode_choice}` hiện chưa đủ điều kiện tách batch, hệ thống sẽ fallback về 1 request thường."
                )

        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=payload,
                workflow_label="Sửa ảnh nâng cao",
                count=selected_count,
                ref_count=ref_count,
                mode_choice=mode_choice,
                speed_choice=speed_choice,
                key_pool_count=key_pool_count,
                user_command=remix_prompt_text,
            )
            with st.expander("Xem JSON payload thô", expanded=False):
                payload_preview = {key: value for key, value in payload.items() if key not in {"image", "images"}}
                if "prompt" in payload_preview:
                    prompt_text = str(payload_preview.get("prompt", ""))
                    if len(prompt_text) > 260:
                        payload_preview["prompt"] = f"{prompt_text[:260]}..."
                if ref_count > 0:
                    payload_preview["image_sources"] = f"{ref_count} ảnh mẫu (đã ẩn dữ liệu ảnh/base64)"
                st.json(payload_preview)

        action1, action2 = st.columns([1.35, 0.95], gap="medium")
        with action1:
            if st.button("🚀 Tạo từ ảnh mẫu (Pro)", type="primary", use_container_width=True, key="btn_quick_remix_submit"):
                if not refs:
                    st.error("Bạn cần ít nhất 1 ảnh mẫu để chỉnh nâng cao.")
                else:
                    try:
                        payload_run = dict(payload)
                        payload_run.update(parse_json_object(remix_extra_json))
                    except Exception as ex:
                        st.error(f"JSON bổ sung không hợp lệ: {ex}")
                    else:
                        batch_commands = _get_batch_commands("quick")
                        if batch_commands:
                            _run_command_batch(
                                base_payload=payload_run,
                                base_prompt=remix_prompt_text,
                                commands=batch_commands,
                                output_prefix="quick_remix_cmd",
                                workflow_label="Quick sửa ảnh nâng cao",
                                refs_available=bool(refs),
                            )
                        else:
                            output_file = f"{st.session_state.studio_output_prefix}_quick_remix_{timestamp_slug()}.png"
                            run_payload_generation(
                                base_url,
                                api_key,
                                payload_run,
                                "binary",
                                output_file,
                                "Quick sửa ảnh nâng cao",
                                show_inline_preview=False,
                            )
        with action2:
            st.toggle("Lưu ảnh ra máy", key="auto_save_outputs")
        st.caption("Flow này phù hợp khi bạn muốn nạp ảnh mẫu, tinh chỉnh sâu và tạo nhiều biến thể cùng lúc.")

    elif operation == "Sửa ảnh":
        render_workflow_intro(
            "🛠 Sửa ảnh nhanh",
            "Dán hoặc upload ảnh nguồn, mô tả phần cần sửa, chọn mức chỉnh và bấm Sửa ảnh.",
        )
        edit_prompt_text = st.text_area(
            "Mô tả chỉnh sửa",
            key="quick_edit_prompt_input",
            height=130,
            placeholder="Mô tả phần cần sửa và dán ảnh nguồn vào đây (URL/data:image/base64).",
        )
        prompt_refs = parse_pasted_image_refs(edit_prompt_text or "")
        edit_clip_refs: list[str] = [item for item in st.session_state.get("quick_edit_clip_refs", []) if isinstance(item, str)]

        upload_single = st.file_uploader(
            "Kéo/thả ảnh nguồn trực tiếp",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=False,
            key="quick_edit_upload",
        )

        e1, e2, e3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with e1:
            if st.button("📋 Clipboard", key="btn_quick_edit_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    edit_clip_refs = unique_list(edit_clip_refs + [data_url])
                    st.session_state.quick_edit_clip_refs = edit_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with e2:
            if st.button("🧹 Xóa", key="btn_clear_quick_edit_clip", use_container_width=True):
                st.session_state.quick_edit_clip_refs = []
                edit_clip_refs = []
        with e3:
            st.caption("Bạn có thể dán URL/data:image vào ô mô tả hoặc kéo/thả ảnh vào uploader.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(upload_single) + edit_clip_refs)
        _render_small_refs("Tổng ảnh nguồn", refs)

        strength_map = {"Nhẹ": 0.35, "Vừa": 0.65, "Mạnh": 0.9}
        preset = pill_single_select(
            "Mức chỉnh",
            options=list(strength_map.keys()),
            key="quick_edit_strength_preset",
            default=_normalize_quick_choice(str(st.session_state.get("quick_edit_strength_preset", "Vừa")), list(strength_map.keys())),
        )
        count_edit = pill_single_select(
            "Biến thể",
            options=["1", "2", "4"],
            key="quick_edit_count",
            default=_normalize_quick_choice(str(st.session_state.get("quick_edit_count", "1")), ["1", "2", "4"]),
        )
        transparent_bg = st.toggle(
            "Nền trong suốt PNG",
            value=bool(st.session_state.get("quick_edit_transparent_bg", False)),
            key="quick_edit_transparent_bg",
            help="Dùng khi muốn tách nền xanh lá #00FF00 khỏi ảnh và lưu PNG RGBA alpha=0.",
        )

        with st.expander("Chi tiết sửa ảnh", expanded=False):
            strength_value = st.slider("Strength", min_value=0.1, max_value=1.0, step=0.05, value=float(strength_map[preset]), key="quick_edit_strength_exact")
            edit_extra_json = st.text_area("JSON bổ sung", value="{}", height=82, key="quick_edit_extra_json")

        # Compute a lightweight preview payload before the action button
        try:
            _edit_count_preview = max(1, int(count_edit))
        except Exception:
            _edit_count_preview = 1
        _edit_strength_preview = float(strength_map.get(preset, 0.65))
        _edit_keys = parse_api_keys_pool(
            str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")),
            st.session_state.api_key,
        )
        _edit_payload_preview: dict[str, Any] = {
            "model": model,
            "prompt": _normalize_prompt_text(edit_prompt_text) or "Giữ bố cục chính, chỉnh theo yêu cầu",
            "n": _edit_count_preview,
            "strength": _edit_strength_preview,
        }
        apply_transparent_background_request(_edit_payload_preview, bool(transparent_bg))
        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=_edit_payload_preview,
                workflow_label="Sửa ảnh",
                count=_edit_count_preview,
                ref_count=len(refs),
                mode_choice=str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE)),
                speed_choice=str(st.session_state.get("quick_simple_speed", list(QUICK_SPEED_PRESETS.keys())[0])),
                key_pool_count=len(_edit_keys),
                user_command=edit_prompt_text,
            )

        if st.button("🛠 Sửa ảnh", type="primary", use_container_width=True, key="btn_quick_edit_submit"):
            if not refs:
                st.error("Bạn cần ít nhất 1 ảnh nguồn (dán vào prompt hoặc upload).")
            else:
                final_prompt = _normalize_prompt_text(edit_prompt_text) or "Giữ bố cục chính, chỉnh theo yêu cầu"
                final_prompt = _apply_character_detail_note(final_prompt)
                try:
                    payload = {
                        "model": model,
                        "prompt": final_prompt,
                        "n": int(count_edit),
                        "image": refs[0],
                        "strength": float(strength_value),
                    }
                    payload.update(parse_json_object(edit_extra_json))
                    apply_transparent_background_request(payload, bool(transparent_bg))
                except Exception as ex:
                    st.error(f"JSON bổ sung không hợp lệ: {ex}")
                else:
                    batch_commands = _get_batch_commands("quick")
                    if batch_commands:
                        _run_command_batch(
                            base_payload=payload,
                            base_prompt=edit_prompt_text,
                            commands=batch_commands,
                            output_prefix="quick_edit_cmd",
                            workflow_label="Quick sửa ảnh",
                            refs_available=bool(refs),
                        )
                    else:
                        output_file = f"{st.session_state.studio_output_prefix}_quick_edit_{timestamp_slug()}.png"
                        run_payload_generation(base_url, api_key, payload, "binary", output_file, "Quick sửa ảnh", show_inline_preview=False)

    elif operation == "Phân tích & tách nền":
        render_workflow_intro(
            "🧠 Phân tích & tách nền",
            "Nạp ảnh bất kỳ, app sẽ đọc màu viền/góc ảnh để tự chọn xóa nền xanh lá, xanh biển, hồng hoặc nền trơn rồi xuất PNG RGBA trong suốt.",
        )
        analyze_mode_labels = {
            "auto": "Tự động chọn cách đẹp nhất",
            "green": "Ưu tiên nền xanh lá #00FF00",
            "blue": "Ưu tiên nền xanh biển #0000FF",
            "magenta": "Ưu tiên nền hồng #FF00FF",
            "solid": "Ưu tiên nền trơn ở 4 góc",
        }
        ac1, ac2, ac3 = st.columns([1.15, 1.0, 1.0], gap="small")
        with ac1:
            analyze_mode = st.selectbox(
                "Kiểu phân tích",
                options=list(analyze_mode_labels.keys()),
                format_func=lambda key: analyze_mode_labels.get(key, key),
                key="quick_analyze_bg_mode",
            )
        with ac2:
            analyze_backup_source = st.checkbox(
                "Backup ảnh gốc",
                value=True,
                key="quick_analyze_bg_backup_source",
                help="Lưu thêm bản ảnh trước xử lý vào outputs/history để có file nền màu/raw đối chiếu.",
            )
        with ac3:
            analyze_show_details = st.checkbox(
                "Hiện phân tích màu",
                value=True,
                key="quick_analyze_bg_show_details",
            )

        analyze_input = st.text_area(
            "Dán ảnh hoặc data:image cần phân tích/tách nền",
            key="quick_analyze_bg_input",
            height=110,
            placeholder="Dán data:image/base64 hoặc dùng upload/clipboard bên dưới.",
        )
        prompt_refs = parse_pasted_image_refs(analyze_input or "")
        analyze_clip_refs: list[str] = [item for item in st.session_state.get("quick_analyze_bg_clip_refs", []) if isinstance(item, str)]
        analyze_upload = st.file_uploader(
            "Kéo/thả ảnh cần phân tích nền",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=True,
            key="quick_analyze_bg_upload",
        )

        bgc1, bgc2, bgc3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with bgc1:
            if st.button("📋 Clipboard", key="btn_quick_analyze_bg_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    analyze_clip_refs = unique_list(analyze_clip_refs + [data_url])
                    st.session_state.quick_analyze_bg_clip_refs = analyze_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with bgc2:
            if st.button("🧹 Xóa", key="btn_clear_quick_analyze_bg_clip", use_container_width=True):
                st.session_state.quick_analyze_bg_clip_refs = []
                analyze_clip_refs = []
        with bgc3:
            st.caption("Tự động tốt nhất với ảnh có nền màu phẳng/chroma hoặc nền trơn quanh viền. Nếu biết chắc màu nền, chọn chế độ ưu tiên để xử lý mạnh hơn.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(analyze_upload) + analyze_clip_refs)
        _render_small_refs("Ảnh cần phân tích", refs)

        if st.button("🧠 Phân tích & tách nền → PNG trong suốt", type="primary", use_container_width=True, key="btn_quick_analyze_bg_submit"):
            if not refs:
                st.error("Hãy upload/dán ít nhất 1 ảnh cần tách nền.")
            else:
                cols = st.columns(min(3, len(refs)))
                for idx, ref in enumerate(refs, start=1):
                    image_bytes = decode_data_image_ref(ref)
                    if not image_bytes:
                        st.warning(f"Ảnh #{idx}: không đọc được dữ liệu ảnh.")
                        continue
                    processed, analysis = auto_remove_analyzed_background(image_bytes, preferred=str(analyze_mode))
                    check = analysis.get("after_check") if isinstance(analysis.get("after_check"), dict) else inspect_image_transparency(processed)
                    output_file = build_daily_output_path(
                        f"analyzed_bg_removed_{timestamp_slug()}_{idx}.png",
                        "analyze_bg_remove",
                    )
                    saved = save_image(processed, output_file)
                    source_saved = ""
                    if analyze_backup_source:
                        source_ext = ".png"
                        ref_head = str(ref).split(",", 1)[0].lower()
                        if "image/jpeg" in ref_head or "image/jpg" in ref_head:
                            source_ext = ".jpg"
                        elif "image/webp" in ref_head:
                            source_ext = ".webp"
                        elif "image/bmp" in ref_head:
                            source_ext = ".bmp"
                        source_file = build_daily_output_path(
                            f"analyzed_bg_source_{timestamp_slug()}_{idx}{source_ext}",
                            "analyze_bg_source",
                            fallback_ext=source_ext,
                        )
                        source_saved = str(save_image(image_bytes, source_file))

                    history_time = datetime.now().isoformat(timespec="seconds")
                    method_label = str(analysis.get("method_label", "auto background remover"))
                    add_recent_output(
                        {
                            "time": history_time,
                            "model": "auto-background-analyzer",
                            "prompt": f"Phân tích & tách nền: {method_label}",
                            "kind": "binary",
                            "local_path": str(saved),
                            "url": "",
                            "image_bytes": b"",
                            "transparent_check": check,
                            "transparent_requested": True,
                            "background_analysis": analysis,
                        }
                    )
                    append_history(
                        {
                            "time": history_time,
                            "model": "auto-background-analyzer",
                            "prompt": f"Phân tích & tách nền: {method_label}",
                            "response_format": "binary",
                            "result_kind": "binary",
                            "local_path": str(saved),
                            "source_backup_path": source_saved,
                        }
                    )
                    with cols[(idx - 1) % len(cols)]:
                        st.image(processed, caption=f"Đã tách nền #{idx}", use_container_width=True)
                        st.caption(str(analysis.get("reason", "")))
                        render_transparency_check(check, requested=True)
                        if source_saved:
                            st.caption(f"Backup gốc: `{source_saved}`")
                        if analyze_show_details:
                            compact_analysis = {
                                "method": analysis.get("method_label"),
                                "corner_hex": analysis.get("corner_hex"),
                                "edge_hex": analysis.get("edge_hex"),
                                "corner_spread": analysis.get("corner_spread"),
                                "edge_solid_ratio": analysis.get("edge_solid_ratio"),
                                "edge_green_ratio": analysis.get("edge_green_ratio"),
                                "edge_blue_ratio": analysis.get("edge_blue_ratio"),
                                "edge_magenta_ratio": analysis.get("edge_magenta_ratio"),
                                "attempts": analysis.get("attempts", []),
                            }
                            with st.expander(f"Chi tiết phân tích #{idx}", expanded=False):
                                st.json(compact_analysis)
                        st.download_button(
                            f"⬇ Tải PNG #{idx}",
                            data=processed,
                            file_name=Path(saved).name,
                            mime="image/png",
                            key=f"download_analyzed_bg_removed_{idx}_{Path(saved).stem}",
                            use_container_width=True,
                        )
                st.success("Đã phân tích và tách nền xong.")

    elif operation in {"Xóa nền xanh", "Xóa nền chroma"}:
        render_workflow_intro(
            "🟦 Xóa nền chroma",
            "Nạp ảnh có nền xanh dương chroma key (#0000FF), app sẽ chuyển vùng xanh dương nối từ viền ảnh thành nền trong suốt PNG. Có thể đổi sang xanh lá để xử lý file cũ.",
        )
        chroma_color_choice = st.selectbox(
            "Màu nền cần xóa",
            options=["Xanh dương #0000FF", "Xanh lá #00FF00"],
            index=0,
            key="quick_chroma_remove_color",
        )
        remove_blue = chroma_color_choice.startswith("Xanh dương")
        green_input = st.text_area(
            "Dán ảnh hoặc data:image cần xóa nền chroma",
            key="quick_green_remove_input",
            height=110,
            placeholder="Dán data:image/base64 hoặc dùng upload/clipboard bên dưới.",
        )
        prompt_refs = parse_pasted_image_refs(green_input or "")
        green_clip_refs: list[str] = [item for item in st.session_state.get("quick_green_clip_refs", []) if isinstance(item, str)]
        green_upload = st.file_uploader(
            "Kéo/thả ảnh nền chroma",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=True,
            key="quick_green_remove_upload",
        )

        g1, g2, g3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with g1:
            if st.button("📋 Clipboard", key="btn_quick_green_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    green_clip_refs = unique_list(green_clip_refs + [data_url])
                    st.session_state.quick_green_clip_refs = green_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with g2:
            if st.button("🧹 Xóa", key="btn_clear_quick_green_clip", use_container_width=True):
                st.session_state.quick_green_clip_refs = []
                green_clip_refs = []
        with g3:
            st.caption("Tốt nhất: nền xanh dương phẳng #0000FF, không bóng đổ/gradient. Nếu xử lý file cũ thì chọn xanh lá #00FF00.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(green_upload) + green_clip_refs)
        _render_small_refs("Ảnh nền chroma", refs)

        if st.button("🟦 Xóa nền chroma → PNG trong suốt", type="primary", use_container_width=True, key="btn_quick_green_remove_submit"):
            if not refs:
                st.error("Hãy upload/dán ít nhất 1 ảnh nền chroma.")
            else:
                cols = st.columns(min(3, len(refs)))
                for idx, ref in enumerate(refs, start=1):
                    image_bytes = decode_data_image_ref(ref)
                    if not image_bytes:
                        st.warning(f"Ảnh #{idx}: không đọc được dữ liệu ảnh.")
                        continue
                    processed = ensure_transparent_png_rgba_bytes(
                        image_bytes,
                        remove_blue_screen=remove_blue,
                        remove_green_screen=not remove_blue,
                    )
                    check = inspect_image_transparency(processed)
                    output_file = build_daily_output_path(
                        f"outputs/chroma_removed_{timestamp_slug()}_{idx}.png",
                        "chroma_remove",
                    )
                    saved = save_image(processed, output_file)
                    history_time = datetime.now().isoformat(timespec="seconds")
                    add_recent_output(
                        {
                            "time": history_time,
                            "model": "chroma-screen-remover",
                            "prompt": f"Xóa nền chroma key {BLUE_SCREEN_HEX if remove_blue else GREEN_SCREEN_HEX}",
                            "kind": "binary",
                            "local_path": str(saved),
                            "url": "",
                            "image_bytes": b"",
                            "transparent_check": check,
                            "transparent_requested": True,
                        }
                    )
                    append_history(
                        {
                            "time": history_time,
                            "model": "chroma-screen-remover",
                            "prompt": f"Xóa nền chroma key {BLUE_SCREEN_HEX if remove_blue else GREEN_SCREEN_HEX}",
                            "response_format": "binary",
                            "result_kind": "binary",
                            "local_path": str(saved),
                        }
                    )
                    with cols[(idx - 1) % len(cols)]:
                        st.image(processed, caption=f"Đã xóa nền chroma #{idx}", use_container_width=True)
                        render_transparency_check(check, requested=True)
                        st.download_button(
                            f"⬇ Tải PNG #{idx}",
                            data=processed,
                            file_name=Path(saved).name,
                            mime="image/png",
                            key=f"download_chroma_removed_{idx}_{timestamp_slug()}",
                            use_container_width=True,
                        )
                st.success("Đã xử lý xong nền chroma.")

    elif operation == "Nâng cấp chất lượng":
        render_workflow_intro(
            "✨ Nâng cấp chất lượng",
            "Tăng nét, khử nhiễu và nâng độ phân giải mà giữ nguyên bố cục.",
        )
        upscale_input = st.text_area(
            "Ảnh cần nâng cấp + ghi chú",
            key="quick_upscale_input",
            height=120,
            placeholder="Dán ảnh vào đây rồi mô tả thêm (nếu cần). Ví dụ: tăng nét, giảm noise, giữ tự nhiên...",
        )
        prompt_refs = parse_pasted_image_refs(upscale_input or "")
        upscale_clip_refs: list[str] = [item for item in st.session_state.get("quick_upscale_clip_refs", []) if isinstance(item, str)]

        upload_single = st.file_uploader(
            "Kéo/thả ảnh nâng cấp trực tiếp",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=False,
            key="quick_upscale_upload",
        )

        u1, u2, u3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with u1:
            if st.button("📋 Clipboard", key="btn_quick_upscale_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    upscale_clip_refs = unique_list(upscale_clip_refs + [data_url])
                    st.session_state.quick_upscale_clip_refs = upscale_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with u2:
            if st.button("🧹 Xóa", key="btn_clear_quick_upscale_clip", use_container_width=True):
                st.session_state.quick_upscale_clip_refs = []
                upscale_clip_refs = []
        with u3:
            st.caption("Bạn có thể dán URL/data:image vào ô trên hoặc kéo/thả ảnh vào uploader.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(upload_single) + upscale_clip_refs)
        _render_small_refs("Tổng ảnh nguồn", refs)

        upscale_level = pill_single_select(
            "Mức tăng chất lượng",
            options=["2x", "4x"],
            key="quick_upscale_level",
            default=_normalize_quick_choice(str(st.session_state.get("quick_upscale_level", "2x")), ["2x", "4x"]),
        )
        upscale_mode = pill_single_select(
            "Ưu tiên",
            options=["Cân bằng", "Sắc nét", "Khử nhiễu"],
            key="quick_upscale_mode",
            default=_normalize_quick_choice(str(st.session_state.get("quick_upscale_mode", "Cân bằng")), ["Cân bằng", "Sắc nét", "Khử nhiễu"]),
        )

        with st.expander("Chi tiết nâng cấp", expanded=False):
            upscale_extra_json = st.text_area("JSON bổ sung", value="{}", height=82, key="quick_upscale_extra_json")

        _up_keys = parse_api_keys_pool(
            str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")),
            st.session_state.api_key,
        )
        _up_prompt_preview = (
            f"Nâng cấp ảnh lên {upscale_level}, ưu tiên {str(upscale_mode).lower()}, giữ bố cục gốc, cải thiện chi tiết và ánh sáng tự nhiên."
        )
        _up_payload_preview: dict[str, Any] = {
            "model": model,
            "prompt": _up_prompt_preview,
            "n": 1,
        }
        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=_up_payload_preview,
                workflow_label="Nâng cấp chất lượng",
                count=1,
                ref_count=len(refs),
                mode_choice=str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE)),
                speed_choice=str(st.session_state.get("quick_simple_speed", list(QUICK_SPEED_PRESETS.keys())[0])),
                key_pool_count=len(_up_keys),
                user_command=_up_prompt_preview,
                extra_rows=[("Mức tăng", upscale_level), ("Ưu tiên", upscale_mode)],
            )

        if st.button("✨ Nâng cấp", type="primary", use_container_width=True, key="btn_quick_upscale_submit"):
            if not refs:
                st.error("Bạn cần ít nhất 1 ảnh nguồn để nâng cấp.")
            else:
                note = _normalize_prompt_text(upscale_input)
                final_prompt = (
                    f"Nâng cấp ảnh lên {upscale_level}, ưu tiên {upscale_mode.lower()}, giữ bố cục gốc, cải thiện chi tiết và ánh sáng tự nhiên."
                )
                if note:
                    final_prompt = f"{final_prompt} Ghi chú thêm: {note}"
                final_prompt = _apply_character_detail_note(final_prompt)
                try:
                    payload = {
                        "model": model,
                        "prompt": final_prompt,
                        "n": 1,
                        "image": refs[0],
                    }
                    payload.update(parse_json_object(upscale_extra_json))
                except Exception as ex:
                    st.error(f"JSON bổ sung không hợp lệ: {ex}")
                else:
                    batch_commands = _get_batch_commands("quick")
                    if batch_commands:
                        _run_command_batch(
                            base_payload=payload,
                            base_prompt=upscale_input,
                            commands=batch_commands,
                            output_prefix="quick_upscale_cmd",
                            workflow_label="Quick nâng cấp",
                            refs_available=bool(refs),
                        )
                    else:
                        output_file = f"{st.session_state.studio_output_prefix}_quick_upscale_{timestamp_slug()}.png"
                        run_payload_generation(base_url, api_key, payload, "binary", output_file, "Quick nâng cấp", show_inline_preview=False)

    elif operation == "Dịch ảnh":
        render_workflow_intro(
            "🌐 Dịch chữ trên ảnh",
            "Giữ bố cục và font gốc, đổi nội dung chữ sang ngôn ngữ đích.",
        )
        translate_input = st.text_area(
            "Ảnh cần dịch",
            key="quick_translate_input",
            height=110,
            placeholder="Dán ảnh vào đây (URL/data:image/base64).",
        )
        prompt_refs = parse_pasted_image_refs(translate_input or "")
        translate_clip_refs: list[str] = [item for item in st.session_state.get("quick_translate_clip_refs", []) if isinstance(item, str)]

        upload_single = st.file_uploader(
            "Kéo/thả ảnh dịch trực tiếp",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            accept_multiple_files=False,
            key="quick_translate_upload",
        )

        tclip1, tclip2, tclip3 = st.columns([1.2, 0.8, 2.0], gap="small")
        with tclip1:
            if st.button("📋 Clipboard", key="btn_quick_translate_clipboard", use_container_width=True):
                data_url, err = grab_clipboard_image_data_url()
                if data_url:
                    translate_clip_refs = unique_list(translate_clip_refs + [data_url])
                    st.session_state.quick_translate_clip_refs = translate_clip_refs
                    st.success("Đã nhận ảnh clipboard.")
                else:
                    st.warning(err)
        with tclip2:
            if st.button("🧹 Xóa", key="btn_clear_quick_translate_clip", use_container_width=True):
                st.session_state.quick_translate_clip_refs = []
                translate_clip_refs = []
        with tclip3:
            st.caption("Bạn có thể dán URL/data:image vào ô trên hoặc kéo/thả ảnh vào uploader.")

        refs = unique_list(prompt_refs + _uploaded_to_refs(upload_single) + translate_clip_refs)
        _render_small_refs("Tổng ảnh nguồn", refs)

        t1, t2, t3 = st.columns([1, 1, 1.1], gap="medium")
        with t1:
            src_lang = st.selectbox("Nguồn", options=TRANSLATE_LANG_OPTIONS, index=1, key="quick_translate_src")
        with t2:
            tgt_lang = st.selectbox("Đích", options=TRANSLATE_LANG_OPTIONS, index=0, key="quick_translate_tgt")
        with t3:
            tone = st.selectbox("Ưu tiên", options=["Giữ nguyên tuyệt đối bố cục", "Ưu tiên đọc rõ", "Ưu tiên thẩm mỹ"], key="quick_translate_tone")

        note = st.text_input("Ghi chú", value="Giữ nguyên font và bố cục", key="quick_translate_note")
        translate_prompt = f"{build_translate_prompt(src_lang, tgt_lang, note)} Ưu tiên: {tone.lower()}."

        with st.expander("Chi tiết dịch ảnh", expanded=False):
            edit_prompt = st.toggle("Chỉnh prompt dịch", value=False, key="quick_translate_edit_prompt")
            final_prompt = st.text_area("Prompt dịch", value=translate_prompt, height=88, key="quick_translate_prompt_custom") if edit_prompt else translate_prompt
            translate_extra_json = st.text_area("JSON bổ sung", value="{}", height=82, key="quick_translate_extra_json")

        _tr_keys = parse_api_keys_pool(
            str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")),
            st.session_state.api_key,
        )
        _tr_payload_preview: dict[str, Any] = {
            "model": model,
            "prompt": str(final_prompt),
            "n": 1,
        }
        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=_tr_payload_preview,
                workflow_label="Dịch ảnh",
                count=1,
                ref_count=len(refs),
                mode_choice=str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE)),
                speed_choice=str(st.session_state.get("quick_simple_speed", list(QUICK_SPEED_PRESETS.keys())[0])),
                key_pool_count=len(_tr_keys),
                user_command=str(final_prompt),
                extra_rows=[("Nguồn", src_lang), ("Đích", tgt_lang), ("Ưu tiên", tone)],
            )

        if st.button("🌐 Dịch ảnh", type="primary", use_container_width=True, key="btn_quick_translate_submit"):
            if not refs:
                st.error("Bạn cần ít nhất 1 ảnh để dịch.")
            else:
                final_prompt = _apply_character_detail_note(final_prompt)
                try:
                    payload = {
                        "model": model,
                        "prompt": final_prompt,
                        "n": 1,
                        "image": refs[0],
                    }
                    payload.update(parse_json_object(translate_extra_json))
                except Exception as ex:
                    st.error(f"JSON bổ sung không hợp lệ: {ex}")
                else:
                    batch_commands = _get_batch_commands("quick")
                    if batch_commands:
                        _run_command_batch(
                            base_payload=payload,
                            base_prompt=str(final_prompt),
                            commands=batch_commands,
                            output_prefix="quick_translate_cmd",
                            workflow_label="Quick dịch ảnh",
                            refs_available=bool(refs),
                        )
                    else:
                        output_file = f"{st.session_state.studio_output_prefix}_quick_translate_{timestamp_slug()}.png"
                        run_payload_generation(base_url, api_key, payload, "binary", output_file, "Quick dịch ảnh", show_inline_preview=False)

    elif operation == "Vẽ asset game (không nền)":
        render_workflow_intro(
            "🎮 Vẽ asset game không nền",
            "Tạo item, danh hiệu, huy hiệu, nhân vật, vũ khí hoặc icon kỹ năng dạng PNG tách nền để dùng cho game/UI.",
        )

        g1, g2, g3 = st.columns([1.1, 1.1, 0.8], gap="medium")
        with g1:
            asset_type = st.selectbox(
                "Loại asset",
                options=["Item", "Danh hiệu / Huy hiệu", "Nhân vật", "Icon kỹ năng", "Vũ khí / Trang bị", "Khung avatar", "Tiền tệ / Đá quý"],
                key="quick_game_asset_type",
            )
        with g2:
            game_style = st.selectbox(
                "Phong cách game",
                options=["Fantasy RPG", "Anime game", "Chibi", "Pixel art", "Cyberpunk", "MOBA", "Mobile casual", "Realistic icon", "UI badge cao cấp"],
                key="quick_game_asset_style",
            )
        with g3:
            game_count = st.selectbox("Số ảnh", options=[1, 2, 4, 8], index=0, key="quick_game_asset_count")

        desc = st.text_area(
            "Mô tả asset cần vẽ",
            height=120,
            key="quick_game_asset_desc",
            placeholder="Ví dụ: kiếm lửa cấp huyền thoại, danh hiệu Chiến Thần, nhân vật pháp sư nữ full body...",
        )

        c1, c2, c3, c4 = st.columns(4, gap="small")
        with c1:
            rarity = st.selectbox("Độ hiếm", options=["Không chọn", "Common", "Rare", "Epic", "Legendary", "Mythic"], key="quick_game_asset_rarity")
        with c2:
            ratio = st.selectbox("Tỷ lệ", options=["1:1", "4:5", "9:16", "16:9"], index=0, key="quick_game_asset_ratio")
        with c3:
            transparent_bg = st.checkbox("Nền trong suốt PNG", value=True, key="quick_game_asset_transparent")
        with c4:
            add_glow = st.checkbox("Viền/glow rõ", value=True, key="quick_game_asset_glow")

        force_api_background = st.checkbox(
            "Tự xóa nền xanh dương sau khi vẽ",
            value=True,
            key="quick_game_asset_force_api_background",
            help="AI vẽ nền xanh dương #0000FF, app tự chuyển vùng xanh dương thành alpha=0. Tránh xoá nhầm chi tiết xanh lá/ngọc.",
        )

        title_text = ""
        if asset_type == "Danh hiệu / Huy hiệu":
            title_text = st.text_input("Chữ trên danh hiệu (nếu cần)", key="quick_game_asset_title_text", placeholder="Ví dụ: CHIẾN THẦN")

        negative_game = st.text_area(
            "Negative prompt",
            value="background, scenery, room, landscape, floor, wall, watermark, logo sai, chữ lỗi, extra object, blurry, low quality, cropped, cut off",
            height=78,
            key="quick_game_asset_negative",
        )

        asset_rules = [
            "game asset, professional game UI asset, centered composition, clean silhouette, isolated subject",
            "clean asset cutout composition, no scenery, no environment, no floor shadow outside asset",
            "sharp edges, readable shape, high detail, production-ready, marketplace game icon quality",
        ]
        if transparent_bg:
            asset_rules.append(BLUE_SCREEN_PROMPT_RULE)
        if add_glow:
            asset_rules.append("clean outline, subtle rim light, polished glow suitable for game inventory UI")
        if rarity != "Không chọn":
            asset_rules.append(f"rarity color theme: {rarity}")
        if asset_type == "Danh hiệu / Huy hiệu":
            asset_rules.append("game title badge/nameplate, decorative frame, readable centered typography")
            if title_text.strip():
                asset_rules.append(f'exact title text: "{title_text.strip()}"')
        elif asset_type == "Nhân vật":
            asset_rules.append("full body game character, complete body visible, character concept art, clean outline")
        elif asset_type == "Icon kỹ năng":
            asset_rules.append("square skill icon, strong symbol readability at small size, circular energy effects contained inside icon")

        final_prompt = "\n".join(
            part for part in [
                f"Loại asset: {asset_type}",
                f"Phong cách: {game_style}",
                f"Mô tả: {_normalize_prompt_text(desc)}" if _normalize_prompt_text(desc) else "",
                "Yêu cầu bắt buộc: " + "; ".join(asset_rules),
            ] if part
        )
        final_prompt = _apply_character_detail_note(final_prompt)

        payload_preview: dict[str, Any] = {
            "model": model,
            "prompt": final_prompt,
            "n": int(game_count),
            "aspect_ratio": ratio,
            "output_format": "png",
        }
        if negative_game.strip():
            payload_preview["negative_prompt"] = negative_game.strip()
        if transparent_bg:
            apply_transparent_background_request(payload_preview, bool(force_api_background))

        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=payload_preview,
                workflow_label="Vẽ asset game không nền",
                count=int(game_count),
                ref_count=0,
                mode_choice=str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE)),
                speed_choice=str(st.session_state.get("quick_simple_speed", list(QUICK_SPEED_PRESETS.keys())[0])),
                key_pool_count=len(parse_api_keys_pool(str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")), st.session_state.api_key)),
                user_command=final_prompt,
                extra_rows=[("Loại asset", asset_type), ("Style", game_style), ("Tỷ lệ", ratio), ("Nền", "Xanh dương → xóa nền" if transparent_bg else "Tự động")],
            )

        if st.button("🎮 Vẽ asset game", type="primary", use_container_width=True, key="btn_quick_game_asset_submit"):
            if not _normalize_prompt_text(desc) and asset_type != "Danh hiệu / Huy hiệu":
                st.error("Hãy nhập mô tả asset cần vẽ.")
            elif asset_type == "Danh hiệu / Huy hiệu" and not (_normalize_prompt_text(desc) or title_text.strip()):
                st.error("Hãy nhập mô tả hoặc chữ trên danh hiệu.")
            else:
                payload = dict(payload_preview)
                batch_commands = _get_batch_commands("quick")
                if batch_commands:
                    _run_command_batch(
                        base_payload=payload,
                        base_prompt=final_prompt,
                        commands=batch_commands,
                        output_prefix="quick_game_asset_cmd",
                        workflow_label="Quick asset game",
                        refs_available=False,
                    )
                else:
                    output_file = f"{st.session_state.studio_output_prefix}_quick_game_asset_{timestamp_slug()}.png"
                    run_payload_generation(base_url, api_key, payload, "binary", output_file, "Quick asset game", show_inline_preview=False)

    else:
        render_workflow_intro(
            "🎨 Sao chép phong cách",
            "Ảnh 1 cho chủ thể, Ảnh 2 cho phong cách. Có sẵn kịch bản 1 chạm và mẫu prompt chi tiết.",
        )
        content_input = st.text_area(
            "Ảnh 1 (nội dung/chủ thể)",
            key="quick_style_content_input",
            height=90,
            placeholder="Dán URL/data:image/base64 của ảnh 1.",
        )
        style_input = st.text_area(
            "Ảnh 2 (phong cách)",
            key="quick_style_style_input",
            height=90,
            placeholder="Dán URL/data:image/base64 của ảnh 2.",
        )
        content_refs = parse_pasted_image_refs(content_input or "")
        style_refs = parse_pasted_image_refs(style_input or "")

        up1, up2 = st.columns(2)
        with up1:
            content_upload = st.file_uploader(
                "Upload ảnh 1",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=False,
                key="quick_style_content_upload",
            )
        with up2:
            style_upload = st.file_uploader(
                "Upload ảnh 2",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=False,
                key="quick_style_style_upload",
            )

        content_refs = unique_list(content_refs + _uploaded_to_refs(content_upload))
        style_refs = unique_list(style_refs + _uploaded_to_refs(style_upload))

        c1, c2 = st.columns(2)
        with c1:
            _render_small_refs("Ảnh 1", content_refs)
        with c2:
            _render_small_refs("Ảnh 2", style_refs)

        style_strength = pill_single_select(
            "Độ ảnh hưởng phong cách",
            options=["Nhẹ", "Vừa", "Mạnh"],
            key="quick_style_strength",
            default=_normalize_quick_choice(str(st.session_state.get("quick_style_strength", "Vừa")), ["Nhẹ", "Vừa", "Mạnh"]),
        )
        style_strength_map = {"Nhẹ": 0.7, "Vừa": 1.0, "Mạnh": 1.4}

        focus_options = list(QUICK_STYLE_FOCUS_PROMPTS.keys())
        focus_choice = pill_single_select(
            "Ưu tiên học từ ảnh 2",
            options=focus_options,
            key="quick_style_focus_choice",
            default=_normalize_quick_choice(str(st.session_state.get("quick_style_focus_choice", focus_options[0])), focus_options),
        )

        lock_options = list(QUICK_STYLE_IDENTITY_LOCK_PROMPTS.keys())
        lock_choice = pill_single_select(
            "Mức khóa nhân vật ảnh 1",
            options=lock_options,
            key="quick_style_identity_lock",
            default=_normalize_quick_choice(str(st.session_state.get("quick_style_identity_lock", "Rất chặt")), lock_options),
        )

        effect_options = list(QUICK_STYLE_EFFECT_PRESETS.keys())
        effect_choice = pill_single_select(
            "Preset hiệu ứng cảnh",
            options=effect_options,
            key="quick_style_effect_preset",
            default=_normalize_quick_choice(str(st.session_state.get("quick_style_effect_preset", effect_options[0])), effect_options),
        )
        selected_effect_text = QUICK_STYLE_EFFECT_PRESETS.get(effect_choice, "")

        fx1, fx2, fx3 = st.columns([1.0, 1.0, 2.1], gap="small")
        with fx1:
            if st.button("🌸 Dùng preset cảnh", key="btn_quick_style_use_effect_preset", use_container_width=True):
                if not selected_effect_text.strip():
                    st.warning("Hãy chọn preset hiệu ứng trước.")
                else:
                    st.session_state.quick_style_scene_effect = selected_effect_text
                    st.success("Đã điền hiệu ứng cảnh từ preset.")
        with fx2:
            if st.button("🧹 Xóa hiệu ứng", key="btn_quick_style_clear_effect", use_container_width=True):
                st.session_state.quick_style_scene_effect = ""
        with fx3:
            st.caption("Preset này giúp mượn ánh sáng/bóng/bokeh từ ảnh 2, không chỉ nét và màu.")

        style_scene_effect = st.text_input(
            "Hiệu ứng/bối cảnh muốn mượn từ ảnh 2",
            key="quick_style_scene_effect",
            placeholder="Ví dụ: ánh sáng hoa đào sắc nét, bóng lá đổ trên mặt, bokeh tiền cảnh mềm...",
        )

        scenario_options = ["Không dùng kịch bản"] + list(QUICK_STYLE_SCENARIO_PRESETS.keys())
        scenario_choice = st.selectbox(
            "Kịch bản 1 chạm",
            options=scenario_options,
            key="quick_style_scenario_choice",
        )

        sc1, sc2, sc3 = st.columns([1.0, 1.0, 2.1], gap="small")
        with sc1:
            if st.button("⚡ Áp kịch bản", key="btn_quick_style_apply_scenario", use_container_width=True):
                if scenario_choice == "Không dùng kịch bản":
                    st.warning("Hãy chọn một kịch bản trước khi áp dụng.")
                else:
                    scenario = QUICK_STYLE_SCENARIO_PRESETS.get(scenario_choice, {})
                    st.session_state.quick_style_strength = str(scenario.get("strength", "Vừa"))
                    st.session_state.quick_style_focus_choice = str(scenario.get("focus", "Toàn diện (nét + màu + ánh sáng + bóng)"))
                    st.session_state.quick_style_identity_lock = str(scenario.get("lock", "Rất chặt"))
                    st.session_state.quick_style_scene_effect = str(scenario.get("effect", ""))
                    st.session_state.quick_style_prompt_note = str(scenario.get("note", ""))
                    st.success("Đã áp dụng kịch bản 1 chạm.")
                    st.rerun()
        with sc2:
            if st.button("➕ Gộp note kịch bản", key="btn_quick_style_append_scenario_note", use_container_width=True):
                if scenario_choice == "Không dùng kịch bản":
                    st.warning("Hãy chọn một kịch bản trước khi gộp.")
                else:
                    scenario = QUICK_STYLE_SCENARIO_PRESETS.get(scenario_choice, {})
                    scenario_note = str(scenario.get("note", "")).strip()
                    if not scenario_note:
                        st.warning("Kịch bản này chưa có note để gộp.")
                    else:
                        current_note = str(st.session_state.get("quick_style_prompt_note", "")).strip()
                        st.session_state.quick_style_prompt_note = (
                            f"{current_note}\n\n{scenario_note}" if current_note else scenario_note
                        )
                        st.success("Đã gộp note kịch bản vào mô tả.")
        with sc3:
            st.caption("Dùng cho case như: thay nhân vật ảnh 1 vào ảnh 2, giữ cảnh/ánh sáng ảnh 2.")

        if scenario_choice != "Không dùng kịch bản":
            with st.expander("Xem preview kịch bản", expanded=False):
                st.json(QUICK_STYLE_SCENARIO_PRESETS.get(scenario_choice, {}))

        template_options = list(QUICK_STYLE_NOTE_TEMPLATES.keys())
        style_template_choice = pill_single_select(
            "Mẫu lệnh nhanh",
            options=template_options,
            key="quick_style_note_template",
            default=_normalize_quick_choice(
                str(st.session_state.get("quick_style_note_template", template_options[0])),
                template_options,
            ),
        )
        selected_template_text = QUICK_STYLE_NOTE_TEMPLATES.get(style_template_choice, "")

        tpl1, tpl2, tpl3 = st.columns([1.0, 1.0, 2.1], gap="small")
        with tpl1:
            if st.button("⚡ Chèn mẫu", key="btn_quick_style_template_insert", use_container_width=True):
                if not selected_template_text.strip():
                    st.warning("Hãy chọn 1 mẫu lệnh trước khi chèn.")
                else:
                    current_note = str(st.session_state.get("quick_style_prompt_note", "")).strip()
                    st.session_state.quick_style_prompt_note = (
                        f"{current_note}. {selected_template_text}" if current_note else selected_template_text
                    )
                    st.success("Đã chèn mẫu lệnh vào mô tả.")
        with tpl2:
            if st.button("🪄 Thay bằng mẫu", key="btn_quick_style_template_replace", use_container_width=True):
                if not selected_template_text.strip():
                    st.warning("Hãy chọn 1 mẫu lệnh trước khi thay.")
                else:
                    st.session_state.quick_style_prompt_note = selected_template_text
                    st.success("Đã thay mô tả bằng mẫu lệnh.")
        with tpl3:
            st.caption("Chọn mẫu rồi bấm nút để điền nhanh vào ô Mô tả thêm.")

        detailed_template_options = list(QUICK_STYLE_DETAILED_PROMPT_TEMPLATES.keys())
        detailed_template_choice = st.selectbox(
            "Mẫu prompt chi tiết",
            options=detailed_template_options,
            key="quick_style_detailed_template",
        )
        selected_detailed_template = QUICK_STYLE_DETAILED_PROMPT_TEMPLATES.get(detailed_template_choice, "")

        dt1, dt2, dt3 = st.columns([1.0, 1.0, 2.1], gap="small")
        with dt1:
            if st.button("📄 Dùng mẫu chi tiết", key="btn_quick_style_detailed_replace", use_container_width=True):
                st.session_state.quick_style_prompt_note = selected_detailed_template
                st.success("Đã điền mẫu prompt chi tiết.")
        with dt2:
            if st.button("➕ Gộp vào mô tả", key="btn_quick_style_detailed_append", use_container_width=True):
                current_note = str(st.session_state.get("quick_style_prompt_note", "")).strip()
                st.session_state.quick_style_prompt_note = (
                    f"{current_note}\n\n{selected_detailed_template}" if current_note else selected_detailed_template
                )
                st.success("Đã gộp mẫu chi tiết vào mô tả.")
        with dt3:
            st.caption("Mẫu này là prompt dài để mô tả chi tiết; bạn chỉ cần sửa các phần [điền ...].")

        with st.expander("Xem nội dung mẫu prompt chi tiết", expanded=False):
            st.code(selected_detailed_template)

        style_prompt_note = st.text_area(
            "Mô tả thêm",
            key="quick_style_prompt_note",
            height=86,
            placeholder="Ví dụ: giữ đúng nhân vật ảnh 1, mượn ánh sáng hoa đào, bóng lá trên mặt và bokeh mềm từ ảnh 2.",
        )
        with st.expander("Chi tiết sao chép phong cách", expanded=False):
            style_extra_json = st.text_area("JSON bổ sung", value="{}", height=82, key="quick_style_extra_json")

        _st_keys = parse_api_keys_pool(
            str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")),
            st.session_state.api_key,
        )
        _st_user_command = (
            _normalize_prompt_text(style_prompt_note)
            or "Áp phong cách Ảnh 2 lên chủ thể Ảnh 1"
        )
        _st_payload_preview: dict[str, Any] = {
            "model": model,
            "prompt": _st_user_command,
            "n": 1,
        }
        with st.expander("📡 Lệnh sẽ gửi (xem trước)", expanded=False):
            render_payload_command_panel(
                payload=_st_payload_preview,
                workflow_label="Sao chép phong cách",
                count=1,
                ref_count=int(bool(content_refs)) + int(bool(style_refs)),
                mode_choice=str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE)),
                speed_choice=str(st.session_state.get("quick_simple_speed", list(QUICK_SPEED_PRESETS.keys())[0])),
                key_pool_count=len(_st_keys),
                user_command=_st_user_command,
                extra_rows=[
                    ("Cường độ", style_strength),
                    ("Ưu tiên học", focus_choice),
                    ("Khoá nhân vật", lock_choice),
                ],
            )

        if st.button("🎨 Sao chép phong cách", type="primary", use_container_width=True, key="btn_quick_style_transfer"):
            if not content_refs or not style_refs:
                st.error("Bạn cần đủ 2 ảnh: ảnh nội dung và ảnh phong cách.")
            else:
                strength_val = style_strength_map.get(style_strength, 1.0)
                focus_instruction = QUICK_STYLE_FOCUS_PROMPTS.get(focus_choice, "")
                lock_instruction = QUICK_STYLE_IDENTITY_LOCK_PROMPTS.get(lock_choice, "")
                effect_instruction = str(style_scene_effect or "").strip()
                base_prompt = (
                    f"Dùng Ảnh 1 làm chủ thể gốc, áp phong cách từ Ảnh 2 với cường độ {strength_val:.1f}. "
                    f"{lock_instruction} {focus_instruction} "
                    "Ưu tiên ảnh sắc nét, chuyển sáng-tối mượt, giữ chi tiết tóc/mắt/trang phục, tránh méo tay/chân."
                )
                if effect_instruction:
                    base_prompt += f" Mượn hiệu ứng cảnh từ Ảnh 2: {effect_instruction}."
                note = _normalize_prompt_text(style_prompt_note)
                final_prompt = f"{base_prompt}\n\nYêu cầu chi tiết cần tuân thủ:\n{note}" if note else base_prompt
                final_prompt = _apply_character_detail_note(final_prompt)
                try:
                    payload = {
                        "model": model,
                        "prompt": final_prompt,
                        "n": 1,
                        "images": [content_refs[0], style_refs[0]],
                    }
                    payload.update(parse_json_object(style_extra_json))
                except Exception as ex:
                    st.error(f"JSON bổ sung không hợp lệ: {ex}")
                else:
                    batch_commands = _get_batch_commands("quick")
                    if batch_commands:
                        _run_command_batch(
                            base_payload=payload,
                            base_prompt=final_prompt,
                            commands=batch_commands,
                            output_prefix="quick_style_cmd",
                            workflow_label="Quick style transfer",
                            refs_available=bool(content_refs or style_refs),
                        )
                    else:
                        output_file = f"{st.session_state.studio_output_prefix}_quick_style_{timestamp_slug()}.png"
                        run_payload_generation(base_url, api_key, payload, "binary", output_file, "Quick style transfer", show_inline_preview=False)

    render_recent_outputs_strip()



def page_playground(base_url: str, api_key: str) -> None:
    st.subheader("Sân chơi API")
    st.write("Gửi payload thô để kiểm thử tham số đặc thù của từng nhà cung cấp.")
    default_body = {"model": st.session_state.manual_model, "prompt": "thành phố tương lai về đêm", "size": "1024x1024"}
    body_text = st.text_area("Payload JSON", value=json.dumps(st.session_state.last_payload or default_body, ensure_ascii=False, indent=2), height=260)
    response_format = st.selectbox(
        "Định dạng phản hồi",
        options=RESPONSE_FORMAT_OPTIONS,
        index=1,
        format_func=lambda value: RESPONSE_FORMAT_LABELS.get(value, value),
    )
    output_file = st.text_input("Tệp đầu ra", value=f"outputs/playground_{timestamp_slug()}.png")

    if st.button("Gửi request", use_container_width=True):
        try:
            payload = parse_json_object(body_text)
        except Exception as ex:
            st.error(f"JSON không hợp lệ: {ex}")
            return
        with st.spinner("Đang gửi yêu cầu..."):
            try:
                result = generate_image_with_retry(
                    base_url=base_url,
                    api_key=api_key,
                    payload=payload,
                    response_format=response_format,
                    timeout_seconds=resolve_api_post_timeout_seconds(st.session_state.get("api_request_timeout")),
                    retry_count=resolve_image_retry_count(st.session_state.get("image_retry_count")),
                    retry_backoff_seconds=resolve_image_retry_backoff_seconds(st.session_state.get("image_retry_backoff")),
                    task_label="Playground",
                )
            except Exception as ex:
                st.error(str(ex))
                return
        if result["kind"] in {"binary", "b64_json"}:
            image_bytes: bytes = result["image_bytes"]
            saved = save_image(image_bytes, output_file)
            st.success(f"Đã lưu file: {saved}")
            st.image(image_bytes, width=260)
            with st.expander("Xem ảnh lớn", expanded=False):
                st.image(image_bytes, use_container_width=True)
        elif result["kind"] == "url":
            st.code(result["url"])
            st.image(result["url"], width=260)
            with st.expander("Xem ảnh lớn", expanded=False):
                st.image(result["url"], use_container_width=True)
        else:
            st.warning("Phản hồi không có dữ liệu ảnh.")
        if result.get("raw") is not None:
            st.json(result["raw"])


def page_gallery() -> None:
    st.subheader("Thư viện ảnh")
    compact_mode = bool(st.session_state.get("ui_compact_mode", True))
    history = load_history(limit=300)

    all_models = sorted({str(item.get("model", "")) for item in history if str(item.get("model", "")).strip()})

    f1, f2, f3, f4 = st.columns([2.2, 1.0, 1.0, 1.0])
    with f1:
        keyword = st.text_input(
            "Lọc theo model hoặc prompt",
            value="",
            placeholder="ví dụ: gpt-5.4 hoặc neon city",
            key="gallery_keyword",
        )
    with f2:
        day_options = ["Tất cả"] + sorted(
            {str(item.get("time", ""))[:10] for item in history if str(item.get("time", ""))},
            reverse=True,
        )
        selected_day = st.selectbox("Ngày", options=day_options, index=0, key="gallery_day")
    with f3:
        model_options = ["Tất cả"] + all_models
        selected_model = st.selectbox(
            "Model", options=model_options, index=0, key="gallery_model_filter",
            format_func=lambda v: v if v == "Tất cả" else (v.split("/")[-1] if "/" in v else v),
        )
    with f4:
        sort_options = ["Mới nhất trước", "Cũ nhất trước"]
        sort_choice = st.selectbox("Sắp xếp", options=sort_options, index=0, key="gallery_sort")

    a1, a2, a3 = st.columns([1, 1, 1])
    with a1:
        if st.button("📂 Mở thư mục", use_container_width=True, key="btn_gallery_open_folder"):
            output_dir = Path("outputs/history")
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(output_dir))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", str(output_dir)])
                st.toast(f"Đã mở: {output_dir.resolve()}")
            except Exception as ex:
                st.error(f"Không mở được thư mục: {ex}")
    with a2:
        if st.button("🗑 Xóa lịch sử", use_container_width=True, key="btn_gallery_clear_history"):
            if HISTORY_FILE.exists():
                HISTORY_FILE.unlink()
            st.success("Đã xóa lịch sử (file ảnh trong outputs/ vẫn còn).")
            st.rerun()
    with a3:
        prepare_zip_btn = st.button("📦 Tạo file ZIP từ kết quả lọc", use_container_width=True, key="btn_gallery_zip")

    if keyword.strip():
        term = keyword.strip().lower()
        history = [item for item in history if term in str(item.get("model", "")).lower() or term in str(item.get("prompt", "")).lower()]

    if selected_day != "Tất cả":
        history = [item for item in history if str(item.get("time", "")).startswith(selected_day)]

    if selected_model != "Tất cả":
        history = [item for item in history if str(item.get("model", "")) == selected_model]

    if sort_choice == "Cũ nhất trước":
        history = sorted(history, key=lambda x: str(x.get("time", "")))
    else:
        history = sorted(history, key=lambda x: str(x.get("time", "")), reverse=True)

    if prepare_zip_btn:
        try:
            import io as _io, zipfile as _zip
            buf = _io.BytesIO()
            seen: set[str] = set()
            count = 0
            with _zip.ZipFile(buf, "w", compression=_zip.ZIP_DEFLATED) as zf:
                for item in history:
                    p = Path(str(item.get("local_path", "")))
                    if not p.exists() or str(p) in seen:
                        continue
                    seen.add(str(p))
                    arcname = f"{str(item.get('time', ''))[:10]}/{p.name}"
                    try:
                        zf.write(p, arcname)
                        count += 1
                    except Exception:
                        continue
                    if count >= 800:  # safety cap
                        break
            buf.seek(0)
            st.download_button(
                f"⬇️ Tải xuống ZIP ({count} ảnh)",
                data=buf.getvalue(),
                file_name=f"wahu_gallery_{timestamp_slug()}.zip",
                mime="application/zip",
                key="btn_gallery_zip_dl",
                use_container_width=True,
            )
        except Exception as ex:
            st.error(f"Không tạo được ZIP: {ex}")

    st.caption(f"Tổng bản ghi hiển thị: {len(history)}")
    if not history:
        st.info("Chưa có dữ liệu lịch sử")
        return

    tab_grid, tab_table = st.tabs(["Lưới ảnh", "Bảng dữ liệu"])

    with tab_table:
        st.dataframe(
            [
                {
                    "Thời gian": item.get("time", ""),
                    "Model": item.get("model", ""),
                    "Kiểu dữ liệu": item.get("result_kind", ""),
                    "Định dạng phản hồi": item.get("response_format", ""),
                    "Đường dẫn máy": item.get("local_path", ""),
                    "URL": item.get("url", ""),
                }
                for item in history
            ],
            use_container_width=True,
            hide_index=True,
        )

    with tab_grid:
        local_items = [item for item in history if item.get("local_path")]
        if not local_items:
            st.info("Không có ảnh local trong bộ lọc hiện tại.")
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in local_items:
            day = str(item.get("time", ""))[:10] or "Không rõ ngày"
            grouped.setdefault(day, []).append(item)

        for day in sorted(grouped.keys(), reverse=True):
            day_items = grouped[day][:24]
            day_total = len(grouped[day])
            day_label = f"##### {day}  ({day_total} ảnh)"
            st.markdown(day_label)
            day_cols = 8 if compact_mode else 6
            thumb_width = 118 if compact_mode else 140
            cols = st.columns(day_cols)
            for idx, item in enumerate(day_items):
                path = Path(str(item.get("local_path", "")))
                if not path.exists():
                    continue
                with cols[idx % day_cols]:
                    st.image(str(path), width=thumb_width)
                    try:
                        size_kb = path.stat().st_size / 1024
                        size_label = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                    except Exception:
                        size_label = ""
                    caption = f"{item.get('model', '')} • {item.get('time', '')}"
                    if size_label:
                        caption = f"{caption} • {size_label}"
                    st.caption(caption)
                    try:
                        with path.open("rb") as fh:
                            st.download_button(
                                "Tải",
                                data=fh.read(),
                                file_name=path.name,
                                mime="image/png",
                                use_container_width=True,
                                key=f"dl_gallery_{day}_{idx}",
                            )
                    except Exception:
                        pass


def page_advanced_config(base_url: str, api_key: str) -> None:
    st.subheader("Cài đặt")
    tabs = st.tabs(["Kết nối", "Sân chơi API", "Tiện ích"])

    with tabs[0]:
        if "config_base_url" not in st.session_state:
            st.session_state.config_base_url = st.session_state.base_url
        if "config_api_key" not in st.session_state:
            st.session_state.config_api_key = st.session_state.api_key
        if "config_api_keys_pool_text" not in st.session_state:
            st.session_state.config_api_keys_pool_text = str(st.session_state.get("api_keys_pool_text", ""))

        env_path = Path(st.session_state.env_file)
        st.caption(f"Tệp env: `{env_path}` • Đang kết nối: {base_url or '—'}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Lưu config vào .env", use_container_width=True):
                save_env_file(
                    env_path,
                    st.session_state.config_base_url,
                    st.session_state.config_api_key,
                    st.session_state.get("config_api_keys_pool_text", ""),
                )
                st.session_state.base_url = st.session_state.config_base_url
                st.session_state.api_key = st.session_state.config_api_key
                st.session_state.api_keys_pool_text = str(st.session_state.get("config_api_keys_pool_text", ""))
                st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
                st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
                st.success("Đã lưu .env thành công")
        with c2:
            if st.button("Đọc lại .env", use_container_width=True):
                load_env_file(env_path)
                st.session_state.config_base_url = os.getenv("NINEROUTER_URL", "")
                st.session_state.config_api_key = os.getenv("NINEROUTER_KEY", "")
                st.session_state.config_api_keys_pool_text = os.getenv(
                    "NINEROUTER_KEYS", st.session_state.get("config_api_keys_pool_text", "")
                )
                st.session_state.base_url = st.session_state.config_base_url
                st.session_state.api_key = st.session_state.config_api_key
                st.session_state.api_keys_pool_text = str(st.session_state.get("config_api_keys_pool_text", ""))
                st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
                st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
                st.success("Đã nạp lại .env")
        st.text_input("NINEROUTER_URL", key="config_base_url")
        st.text_input("NINEROUTER_KEY", key="config_api_key", type="password")
        st.text_area(
            "NINEROUTER_KEYS",
            key="config_api_keys_pool_text",
            height=96,
            placeholder="Mỗi dòng 1 key hoặc dán nhiều key cách bằng khoảng trắng",
        )
        st.session_state.base_url = st.session_state.config_base_url
        st.session_state.api_key = st.session_state.config_api_key
        st.session_state.api_keys_pool_text = str(st.session_state.get("config_api_keys_pool_text", ""))
        st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
        st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text

        with st.expander("Lệnh CLI nhanh", expanded=False):
            st.code("python nine_router_image.py discover")
            st.code("python nine_router_image.py info --id openai/dall-e-3")
            st.code(
                "python nine_router_image.py generate --model cx/gpt-5.4-image --prompt \"neon city\" --response-format binary --output outputs/out.png"
            )

    with tabs[1]:
        page_playground(base_url, api_key)

    with tabs[2]:
        st.markdown("### Tiện ích Wahu Image Studio")

        # ----- System info -----
        try:
            import platform as _plat
            import shutil as _sh
            outputs_dir = Path("outputs")
            outputs_size = 0
            outputs_files = 0
            if outputs_dir.exists():
                for p in outputs_dir.rglob("*"):
                    if p.is_file():
                        outputs_files += 1
                        try:
                            outputs_size += p.stat().st_size
                        except Exception:
                            continue
            try:
                disk = _sh.disk_usage(str(Path.cwd()))
                disk_free_gb = disk.free / (1024 ** 3)
                disk_total_gb = disk.total / (1024 ** 3)
                disk_used_pct = int(round((disk.total - disk.free) / max(1, disk.total) * 100))
            except Exception:
                disk_free_gb = 0.0
                disk_total_gb = 0.0
                disk_used_pct = 0

            si1, si2, si3, si4 = st.columns(4)
            with si1:
                st.metric("Hệ điều hành", f"{_plat.system()} {_plat.release()}")
            with si2:
                st.metric("Python", _plat.python_version())
            with si3:
                if outputs_size >= 1024 ** 3:
                    label = f"{outputs_size / (1024 ** 3):.2f} GB"
                else:
                    label = f"{outputs_size / (1024 ** 2):.0f} MB"
                st.metric("Outputs", label, delta=f"{outputs_files} file")
            with si4:
                if disk_total_gb:
                    st.metric("Đĩa trống", f"{disk_free_gb:.1f} GB", delta=f"đã dùng {disk_used_pct}%")
        except Exception:
            pass

        st.divider()

        # ----- Cleanup tools -----
        st.markdown("**Dọn dẹp output**")
        st.caption(
            "Xóa file ảnh tạm `outputs/` để giải phóng đĩa. Lịch sử (`history.jsonl`) không bị ảnh hưởng."
        )
        cl1, cl2, cl3 = st.columns([1.2, 1.2, 1.6])
        with cl1:
            cleanup_days = st.number_input(
                "Xóa file cũ hơn (ngày)",
                min_value=1, max_value=365, value=30, step=1,
                key="cleanup_days_threshold",
            )
        with cl2:
            cleanup_dry = st.toggle("Chỉ xem trước", value=True, key="cleanup_dry_run")
        with cl3:
            if st.button("🧹 Quét & xóa", key="btn_config_cleanup_outputs", use_container_width=True):
                try:
                    cutoff = time.time() - cleanup_days * 86400
                    target_root = Path("outputs/history")
                    candidates: list[Path] = []
                    if target_root.exists():
                        for p in target_root.rglob("*"):
                            if p.is_file():
                                try:
                                    if p.stat().st_mtime < cutoff:
                                        candidates.append(p)
                                except Exception:
                                    continue
                    total_bytes = sum(p.stat().st_size for p in candidates if p.exists())
                    label_size = (
                        f"{total_bytes / (1024 ** 3):.2f} GB"
                        if total_bytes >= 1024 ** 3
                        else f"{total_bytes / (1024 ** 2):.1f} MB"
                    )
                    if cleanup_dry:
                        st.info(
                            f"Sẽ xóa {len(candidates)} file ({label_size}) cũ hơn {cleanup_days} ngày trong outputs/history."
                        )
                    else:
                        deleted = 0
                        for p in candidates:
                            try:
                                p.unlink()
                                deleted += 1
                            except Exception:
                                continue
                        st.success(f"Đã xóa {deleted}/{len(candidates)} file ({label_size}).")
                except Exception as ex:
                    st.error(f"Lỗi dọn dẹp: {ex}")

        st.divider()
        st.markdown("**Shortcut Desktop**")
        st.caption(
            "Tạo icon \"Wahu Image Studio\" trên Desktop để mở app bằng 1 cú click, không có cửa sổ cmd đen."
        )
        col_sc1, col_sc2 = st.columns([1.2, 1.8])
        with col_sc1:
            if st.button("🖥 Tạo shortcut Desktop", use_container_width=True, key="btn_config_create_shortcut"):
                ps_script = Path(__file__).resolve().parent / "create_desktop_shortcut.ps1"
                if not ps_script.exists():
                    st.error(f"Không tìm thấy {ps_script.name}.")
                else:
                    try:
                        result = subprocess.run(
                            [
                                "powershell",
                                "-NoProfile",
                                "-ExecutionPolicy",
                                "Bypass",
                                "-File",
                                str(ps_script),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=20,
                        )
                        if result.returncode == 0:
                            st.success("Đã tạo shortcut trên Desktop.")
                            with st.expander("Chi tiết", expanded=False):
                                st.code(result.stdout or "")
                        else:
                            st.error("Tạo shortcut thất bại.")
                            st.code((result.stdout or "") + "\n" + (result.stderr or ""))
                    except Exception as ex:
                        st.error(f"Không gọi được PowerShell: {ex}")
        with col_sc2:
            st.caption(
                "Hoặc chạy thủ công file `create_desktop_shortcut.bat` trong thư mục cài đặt."
            )

        st.divider()
        st.markdown("**Đường dẫn quan trọng**")
        app_dir = Path(__file__).resolve().parent
        important_paths = [
            ("Thư mục app", app_dir),
            ("Output ảnh", app_dir / "outputs"),
            ("Lịch sử ảnh (JSONL)", app_dir / "outputs" / "history.jsonl"),
            ("Lịch sử LoRA (JSONL)", app_dir / "outputs" / "lora_jobs.jsonl"),
            ("File env", Path(st.session_state.get("env_file", DEFAULT_ENV_FILE))),
        ]
        for label, p in important_paths:
            row1, row2 = st.columns([3.4, 0.9])
            with row1:
                st.text_input(label, value=str(p), key=f"util_path_{label}", disabled=True)
            with row2:
                if st.button("📂", key=f"btn_util_open_{label}", help="Mở thư mục", use_container_width=True):
                    try:
                        target = p if p.is_dir() else p.parent
                        target.mkdir(parents=True, exist_ok=True)
                        if sys.platform.startswith("win"):
                            os.startfile(str(target))  # type: ignore[attr-defined]
                        else:
                            subprocess.Popen(["xdg-open", str(target)])
                        st.toast(f"Đã mở: {target}")
                    except Exception as ex:
                        st.error(f"Không mở được: {ex}")

        st.divider()
        st.markdown("**Reset bộ nhớ phiên**")
        st.caption(
            "Xóa toàn bộ session_state nếu app rơi vào trạng thái lạ. Cấu hình .env sẽ được nạp lại từ tệp."
        )
        if st.button("🧨 Reset session", key="btn_config_reset_session"):
            keys = list(st.session_state.keys())
            for k in keys:
                del st.session_state[k]
            st.toast("Đã reset session — đang nạp lại app...")
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Wahu Image Studio",
        page_icon="🎨",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_state()
    ensure_runtime_timeout_defaults()
    render_css()

    page_name, base_url_raw = sidebar_settings()
    if page_name == PAGE_HOME:
        render_hero()
    try:
        base_url = normalize_base_url(base_url_raw)
    except Exception as ex:
        st.warning(str(ex))
        if page_name != PAGE_CONFIG:
            st.stop()
        page_advanced_config(base_url=st.session_state.base_url, api_key=st.session_state.api_key)
        return

    api_key = st.session_state.api_key

    if page_name == PAGE_HOME:
        page_home(base_url, api_key)
    elif page_name == PAGE_DRAW:
        page_generate_quick(base_url, api_key, bool(st.session_state.get("ui_compact_mode", True)))
    elif page_name == PAGE_TRAIN:
        page_lora_trainer(base_url, api_key)
    elif page_name == PAGE_MODEL:
        page_model_explorer(base_url, api_key)
    elif page_name == PAGE_GALLERY:
        page_gallery()
    else:
        page_advanced_config(base_url, api_key)


if __name__ == "__main__":
    main()
