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
DEFAULT_MODEL = "cx/gpt-5.4-image"
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
DEFAULT_API_POST_TIMEOUT_SECONDS = 300
DEFAULT_IMAGE_RETRY_COUNT = 2
DEFAULT_IMAGE_RETRY_BACKOFF_SECONDS = 1.4
MAX_IMAGE_RETRY_COUNT = 5
MAX_API_TIMEOUT_SECONDS = 900
DEFAULT_ENABLE_EXPERIMENTAL_PASTE_COMPONENT = False
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
    "AI đa năng (copy ảnh + lệnh tự do)",
    "Làm truyện tranh",
    "Sửa ảnh nâng cao",
    "Sửa ảnh",
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
PAGE_PRESET = "✨ Preset"
PAGE_TRAIN = "🧬 Train LoRA"
PAGE_MODEL = "🧠 Model"
PAGE_GALLERY = "🖼️ Thư viện"
PAGE_CONFIG = "⚙️ Cài đặt"

PAGE_OPTIONS = [
    PAGE_HOME,
    PAGE_DRAW,
    PAGE_PRESET,
    PAGE_TRAIN,
    PAGE_MODEL,
    PAGE_GALLERY,
    PAGE_CONFIG,
]

PAGE_OPTIONS_BASIC = [
    PAGE_HOME,
    PAGE_DRAW,
    PAGE_TRAIN,
    PAGE_GALLERY,
]

PAGE_OPTIONS_ADVANCED = [
    PAGE_PRESET,
    PAGE_MODEL,
    PAGE_CONFIG,
]

SIZE_PRESETS = {
    "Vu\u00f4ng 1024": "1024x1024",
    "Vu\u00f4ng 1536": "1536x1536",
    "Ngang 3:2": "1536x1024",
    "Ngang 16:9": "1792x1024",
    "D\u1ecdc 2:3": "1024x1536",
    "D\u1ecdc 9:16": "1024x1792",
    "B\u00e0i \u0111\u0103ng MXH": "1080x1080",
    "Story/Reel": "1080x1920",
    "Wallpaper 4K": "3840x2160",
    "T\u00f9y ch\u1ec9nh": "",
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
    "Ch\u1ea5t l\u01b0\u1ee3ng cao (HD)": {
        "quality": "hd",
        "steps": 40,
        "guidance_scale": 7.5,
        "cfg_scale": 7.0,
        "prompt_suffix": "ultra detailed, crisp focus, cinematic texture",
    },
    "Si\u00eau chi ti\u1ebft (Ultra+)": {
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

SCENE_PRESETS = {
    "Mặc định (không ép bố cục)": {
        "template": "{subject}",
        "size": "Vuông 1024",
        "ratio": "1:1",
    },
    "Phong c\u1ea3nh \u0111i\u1ec7n \u1ea3nh": {
        "template": "{subject}, wide shot, strong visual depth",
        "size": "Ngang 16:9",
        "ratio": "16:9",
    },
    "Ch\u00e2n dung avatar": {
        "template": "close-up portrait of {subject}, centered composition",
        "size": "Vu\u00f4ng 1024",
        "ratio": "1:1",
    },
    "Poster qu\u1ea3ng c\u00e1o": {
        "template": "advertising poster featuring {subject}, bold typography space",
        "size": "D\u1ecdc 9:16",
        "ratio": "9:16",
    },
    "Ảnh sản phẩm": {
        "template": "studio product photo of {subject}, premium branding style",
        "size": "Vu\u00f4ng 1024",
        "ratio": "1:1",
    },
    "Ki\u1ebfn tr\u00fac hi\u1ec7n \u0111\u1ea1i": {
        "template": "modern architecture of {subject}, clean lines and geometry",
        "size": "Ngang 3:2",
        "ratio": "3:2",
    },
    "Fantasy": {
        "template": "epic fantasy concept art of {subject}, grand environment",
        "size": "Ngang 16:9",
        "ratio": "16:9",
    },
    "Ý tưởng logo": {
        "template": "minimal logo concept for {subject}, iconic symbol",
        "size": "Vu\u00f4ng 1024",
        "ratio": "1:1",
    },
}

WORKFLOW_PRESETS = {
    "1 chạm: Avatar": {
        "scene": "Ch\u00e2n dung avatar",
        "style": "Chân thực",
        "quality_profile": "Ch\u1ea5t l\u01b0\u1ee3ng cao (HD)",
        "size_preset": "Vu\u00f4ng 1024",
        "ratio": "1:1",
        "response_format": "binary",
        "n": 1,
        "extra": {"image_detail": "high"},
    },
    "1 chạm: Poster": {
        "scene": "Poster qu\u1ea3ng c\u00e1o",
        "style": "Điện ảnh",
        "quality_profile": "Si\u00eau chi ti\u1ebft (Ultra+)",
        "size_preset": "D\u1ecdc 9:16",
        "ratio": "9:16",
        "response_format": "binary",
        "n": 1,
        "extra": {"background": "opaque"},
    },
    "1 chạm: Sản phẩm": {
        "scene": "Ảnh sản phẩm",
        "style": "3D",
        "quality_profile": "Ch\u1ea5t l\u01b0\u1ee3ng cao (HD)",
        "size_preset": "Vu\u00f4ng 1536",
        "ratio": "1:1",
        "response_format": "binary",
        "n": 1,
        "extra": {"output_format": "png"},
    },
    "1 chạm: Anime": {
        "scene": "Fantasy",
        "style": "Anime",
        "quality_profile": "Cân bằng",
        "size_preset": "Ngang 16:9",
        "ratio": "16:9",
        "response_format": "binary",
        "n": 1,
        "extra": {},
    },
    "1 chạm: Logo": {
        "scene": "Ý tưởng logo",
        "style": "Logo tối giản",
        "quality_profile": "Cân bằng",
        "size_preset": "Vu\u00f4ng 1024",
        "ratio": "1:1",
        "response_format": "binary",
        "n": 1,
        "extra": {"background": "transparent", "output_format": "png"},
    },
}

COMPOSE_LAYOUT_OPTIONS = {
    "collage": "Cắt dán tự do",
    "mosaic": "Ô lưới",
    "side-by-side": "Đặt cạnh nhau",
    "blend": "Hòa trộn mềm",
}

EDIT_PRESET_PROMPTS = {
    "Tăng chất lượng ảnh": "Giữ bố cục chính, tăng độ nét, giảm noise, cân bằng ánh sáng và màu sắc.",
    "Đổi phong cách điện ảnh": "Giữ đối tượng chính, chuyển sang tông điện ảnh, ánh sáng chiều sâu, tương phản cao.",
    "Làm đẹp chân dung": "Giữ gương mặt tự nhiên, cải thiện da nhẹ, làm rõ mắt, cân sáng mềm mại.",
    "Nâng cấp sản phẩm": "Giữ sản phẩm trung tâm, nền sạch, phản xạ đẹp, ánh sáng studio chuyên nghiệp.",
}

COMPOSE_PRESET_PROMPTS = {
    "Poster truyền thông": "Ghép các ảnh thành poster rõ chủ thể chính, chừa khoảng trống chữ, phối màu hài hòa.",
    "Ảnh bìa mạng xã hội": "Ghép ảnh theo bố cục cân đối, nổi bật thương hiệu, hợp tỉ lệ hiển thị online.",
    "Moodboard ý tưởng": "Ghép ảnh thành bảng ý tưởng sáng tạo, nhấn mạnh tính nhất quán màu và cảm xúc.",
    "Trình bày sản phẩm": "Ghép nhiều góc chụp sản phẩm thành một layout sạch và chuyên nghiệp.",
}

TRANSLATE_TONE_OPTIONS = [
    "Giữ nguyên tuyệt đối bố cục",
    "Ưu tiên đọc rõ",
    "Ưu tiên thẩm mỹ",
]

STORY_BEAT_OPTIONS = [
    "Mở đầu -> Cao trào -> Kết",
    "Hành trình nhân vật",
    "Quảng bá sản phẩm",
    "Minh họa kiến thức",
]

QUALITY_TIER_PRESETS = {
    "Fast": {
        "quality_profile": "Nhanh",
        "note": "Nhanh và tiết kiệm",
        "count": 1,
    },
    "Pro": {
        "quality_profile": "Chất lượng cao (HD)",
        "note": "Đẹp, cân bằng tốc độ",
        "count": 2,
    },
    "Cực kỳ": {
        "quality_profile": "Siêu chi tiết (Ultra+)",
        "note": "Chi tiết tối đa",
        "count": 4,
    },
}

CREATE_PROMPT_MODIFIERS = {
    "Khía cạnh vuông": "ưu tiên bố cục vuông, cân đối trung tâm",
    "Không phong cách": "không áp phong cách nghệ thuật nặng",
    "Không màu": "ưu tiên bảng màu tối giản, ít tông màu",
    "Không ánh sáng": "ánh sáng phẳng, tự nhiên, không hiệu ứng phức tạp",
    "Không cấu trúc": "hạn chế chi tiết nền rối và cấu trúc phức tạp",
}

MODEL_RECOMMENDED = [
    "cx/gpt-5.4-image",
    "cx/gpt-5.3-image",
    "cx/gpt-5.2-image",
]

MODEL_TOP_PRIORITY = [
    "cx/gpt-5.4-image",
    "cx/gpt-5.3-image",
    "cx/gpt-5.2-image",
    "cx/gpt-5.5-image",
]

MODEL_COMPAT_FALLBACKS = {
    # Map of unsupported-version → newer-supported-version (Codex client too old).
    "gpt-5.5-image": "gpt-5.4-image",
}

# Do not auto-fallback to `openai/*` here. A local 9Router server may expose only
# `cx/*-image` models and return "No credentials for provider: openai" for OpenAI
# routes. Keep model selection tied to `/v1/models/image`.
MODEL_ENTITLEMENT_FALLBACKS: tuple[str, ...] = ()

DEFAULT_WORKFLOW_PRESET = "1 chạm: Avatar"
DEFAULT_SCENE_PRESET = "Mặc định (không ép bố cục)"

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

REFERENCE_DRAW_MODES = {
    "Giữ bố cục, nâng chất lượng": "giữ bố cục ảnh mẫu, tăng độ nét, cải thiện ánh sáng",
    "Giữ chủ thể, đổi phong cách": "giữ chủ thể chính, thay đổi phong cách theo prompt",
    "Biến thể sáng tạo": "tạo biến thể mới dựa trên ảnh mẫu, vẫn giữ tinh thần hình gốc",
}

WORKFLOW_TABS = [
    "Tạo ảnh",
    "Sửa ảnh",
    "Ghép ảnh",
    "Dịch ảnh",
    "Làm truyện",
]

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
        raise ValueError("NINEROUTER_URL \u0111ang tr\u1ed1ng.")
    if not normalized.startswith("http://") and not normalized.startswith("https://"):
        raise ValueError("NINEROUTER_URL ph\u1ea3i b\u1eaft \u0111\u1ea7u b\u1eb1ng http:// ho\u1eb7c https://")
    return normalized


def build_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    url = f"{base_url}{path}"
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
    headers = {"Content-Type": "application/json"}
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
    return _clamp_int(source, 30, MAX_API_TIMEOUT_SECONDS)


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


def is_retryable_generate_error(ex: Exception) -> bool:
    message = str(ex or "")
    lowered = message.lower()

    if is_codex_upgrade_required_error(message):
        return False
    if is_codex_entitlement_error(message):
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
            "G?i ?: server 9Router hi?n ch?a c?u h?nh provider OpenAI. "
            "H?y d?ng model c? s?n trong `/v1/models/image` (v? d? `cx/gpt-5.4-image`) "
            "ho?c c?u h?nh OpenAI credentials ? ph?a server."
        )
    if is_codex_entitlement_error(text):
        return (
            "G?i ?: model `cx/gpt-5.x-image` y?u c?u entitlement ph? h?p ? ph?a server. "
            "H?y ki?m tra t?i kho?n/quy?n provider `cx` tr?n 9Router ho?c ch?n model "
            "kh?c c? s?n trong `/v1/models/image`."
        )
    if is_codex_upgrade_required_error(text):
        return "G?i ?: model hi?n t?i c?n Codex m?i h?n. H?y n?ng c?p Codex ho?c ??i sang `cx/gpt-5.4-image`."
    if "invalid size" in lowered and "minimum pixel budget" in lowered:
        return "G?i ?: d?ng size >= 1024x1024 ho?c b? tr??ng size ?? backend t? ch?n k?ch th??c h?p l?."
    if "[401]" in lowered or "unauthorized" in lowered:
        return "G?i ?: ki?m tra l?i API key / quy?n truy c?p model."
    if "[429]" in lowered or "rate limit" in lowered:
        return "G?i ?: gi?m lu?ng song song, t?ng backoff retry ho?c ch? quota reset."
    if "timed out" in lowered or "timeout" in lowered:
        return "G?i ?: t?ng Timeout request l?n 360-480s v? retry 1-2 l?n."
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
        raise RuntimeError(f"GET {url} th\u1ea5t b\u1ea1i [{ex.code}]\n{text}") from ex
    except TimeoutError as ex:
        raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
    except socket.timeout as ex:
        raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
    except error.URLError as ex:
        if isinstance(ex.reason, TimeoutError) or isinstance(ex.reason, socket.timeout):
            raise RuntimeError(f"GET {url} bị timeout sau {resolved_timeout}s") from ex
        raise RuntimeError(f"Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c t\u1edbi {url}: {ex.reason}") from ex
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
    data = http_get_json(build_url(base_url, "/v1/models/image"), api_key or None)
    models = data.get("data", [])
    return [item.get("id", "") for item in models if item.get("id")]


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


def generate_image(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    response_format: str,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    endpoint = build_url(base_url, "/v1/images/generations")
    if response_format == "binary":
        endpoint = build_url(base_url, "/v1/images/generations", {"response_format": "binary"})
    try:
        body, content_type = http_post(endpoint, payload, api_key or None, timeout_seconds=timeout_seconds)
    except RuntimeError as ex:
        # If server rejects with 400 "Invalid JSON body" or "bad_request",
        # retry once with a sanitized payload (drop optional/non-standard fields).
        msg = str(ex)
        is_bad_request = "[400]" in msg and (
            "invalid_request_error" in msg.lower()
            or "bad_request" in msg.lower()
            or "invalid json" in msg.lower()
        )
        if not is_bad_request:
            raise
        cleaned, removed = sanitize_payload_for_retry(payload)
        if not removed or cleaned == payload:
            raise
        body, content_type = http_post(endpoint, cleaned, api_key or None, timeout_seconds=timeout_seconds)

    if response_format == "binary":
        return {"kind": "binary", "image_bytes": body, "content_type": content_type, "raw": None}

    parsed = json.loads(body.decode("utf-8"))
    data = parsed.get("data", [])
    if not data:
        return {"kind": "json", "raw": parsed}
    first = data[0]
    if first.get("url"):
        return {"kind": "url", "url": first["url"], "raw": parsed}
    if first.get("b64_json"):
        return {"kind": "b64_json", "image_bytes": base64.b64decode(first["b64_json"]), "raw": parsed}
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

    attempt = 1
    while attempt <= total_attempts:
        timeout_now = min(MAX_API_TIMEOUT_SECONDS, timeout_base + (attempt - 1) * 30)
        try:
            return generate_image(
                base_url=base_url,
                api_key=api_key,
                payload=current_payload,
                response_format=response_format,
                timeout_seconds=timeout_now,
            )
        except Exception as ex:
            last_error = ex

            current_model = str(current_payload.get("model", "")).strip()
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
                f"{tag}L?n {attempt}/{total_attempts} l?i: {ex}. "
                f"S? th? l?i sau {delay:.1f}s (timeout={timeout_now}s)."
            )
            time.sleep(delay)
            attempt += 1

    assert last_error is not None
    hint = build_generate_error_hint(str(last_error))
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
            "Tài khoản Codex/ChatGPT phía server không có Plus/Pro. "
            "Đổi sang `openai/gpt-image-1` hoặc `openai/dall-e-3`, hoặc đăng nhập gói Plus/Pro."
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
    current_is_available = bool(current) and current in image_models
    pool = unique_list(image_models + ([current] if current_is_available else []) + [DEFAULT_MODEL])
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
    return True, f"?? n?p {len(st.session_state.models)} model"


def apply_everyday_studio_defaults() -> None:
    st.session_state.manual_model = suggest_top_model(
        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
        str(st.session_state.get("manual_model", "")),
    )

    st.session_state.quick_scene = DEFAULT_SCENE_PRESET if DEFAULT_SCENE_PRESET in SCENE_PRESETS else list(SCENE_PRESETS.keys())[0]
    st.session_state.quick_style = "Không áp phong cách"
    st.session_state.quick_quality_profile = "Cân bằng"
    st.session_state.quick_aspect_ratio = "1:1"
    st.session_state.quick_size_preset = "Vuông 1024"
    st.session_state.quick_subject = ""
    st.session_state.quick_mood = ""
    st.session_state.quick_lighting = ""
    st.session_state.quick_camera = ""

    st.session_state.create_quality_tier = "Fast"
    st.session_state.create_count_ui = 1
    st.session_state.create_response_format_ui = "binary"
    st.session_state.studio_count = 1
    st.session_state.studio_response_format = "binary"

    st.session_state.quick_use_optimizer = False
    st.session_state.quick_auto_negative = False
    st.session_state.create_use_reference = False
    st.session_state.create_reference_mode = "1 ảnh"
    st.session_state.create_modifiers = []
    st.session_state.create_extra_json = "{}"


def parse_json_object(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("JSON ph\u1ea3i l\u00e0 object")
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
    if bool(st.session_state.get("ui_debug_mode", False)):
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
    if bool(st.session_state.get("ui_debug_mode", False)):
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
    if bool(st.session_state.get("ui_debug_mode", False)):
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


def build_scene_prompt(scene_name: str, subject: str) -> str:
    template = SCENE_PRESETS.get(scene_name, {}).get("template", "{subject}")
    return template.replace("{subject}", subject.strip() or "một ý tưởng sáng tạo")


def optimize_prompt(base_prompt: str, style_name: str, quality_name: str, mood: str, lighting: str, camera: str) -> str:
    parts = [base_prompt.strip()]
    if mood.strip():
        parts.append(mood.strip())
    if lighting.strip():
        parts.append(lighting.strip())
    if camera.strip():
        parts.append(camera.strip())
    style_suffix = STYLE_PRESETS.get(style_name, {}).get("prompt_suffix", "")
    quality_suffix = QUALITY_PROFILES.get(quality_name, {}).get("prompt_suffix", "")
    if style_suffix:
        parts.append(str(style_suffix))
    if quality_suffix:
        parts.append(str(quality_suffix))
    return ", ".join(unique_list(parts))


def apply_quality_profile_to_state() -> None:
    profile = QUALITY_PROFILES.get(st.session_state.gen_quality_profile, {})
    st.session_state.gen_steps = int(profile.get("steps", st.session_state.gen_steps))
    st.session_state.gen_guidance_scale = float(profile.get("guidance_scale", st.session_state.gen_guidance_scale))
    st.session_state.gen_cfg_scale = float(profile.get("cfg_scale", st.session_state.gen_cfg_scale))
    if not st.session_state.gen_quality_override:
        st.session_state.gen_quality_override = str(profile.get("quality", ""))


def apply_workflow_preset(name: str) -> None:
    preset = WORKFLOW_PRESETS.get(name)
    if not preset:
        return
    st.session_state.quick_scene = preset["scene"]
    st.session_state.quick_style = preset["style"]
    st.session_state.quick_quality_profile = preset["quality_profile"]
    st.session_state.quick_size_preset = preset["size_preset"]
    st.session_state.quick_aspect_ratio = preset["ratio"]
    st.session_state.quick_response_format = preset["response_format"]
    st.session_state.quick_count = int(preset["n"])
    st.session_state.gen_extra_json = json.dumps(preset.get("extra", {}), ensure_ascii=False)


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
             9Router Studio Pro - Desktop AI Image Generator
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

          /* ----- Responsive ----- */
          @media (max-width: 1180px) {{
            section[data-testid="stSidebar"] {{
              width: 220px !important;
              min-width: 220px !important;
            }}
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
    today_label = datetime.now().strftime("%d/%m/%Y")
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-row">
            <div class="hero-title">
              <h1>9Router Image Studio</h1>
              <p>Tạo / sửa ảnh và train LoRA trong một giao diện gọn.</p>
            </div>
            <div class="hero-meta">
              <span class="hero-chip">{api_state_dot} {html.escape(api_state_label)}</span>
              <span class="hero-chip">🧠 {html.escape(model_label)}</span>
              <span class="hero-chip">📅 {html.escape(today_label)}</span>
            </div>
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
    st.session_state.force_page_selector_sync = False
    st.session_state.ui_compact_mode = True
    st.session_state.ui_debug_mode = False
    st.session_state.enable_paste_component = DEFAULT_ENABLE_EXPERIMENTAL_PASTE_COMPONENT

    st.session_state.models = []
    st.session_state.model_nonce = 0
    st.session_state.manual_model = DEFAULT_MODEL

    st.session_state.gen_workflow_preset = DEFAULT_WORKFLOW_PRESET
    st.session_state.quick_scene = DEFAULT_SCENE_PRESET
    st.session_state.quick_subject = ""
    st.session_state.quick_style = "Không áp phong cách"
    st.session_state.quick_quality_profile = "Cân bằng"
    st.session_state.quick_size_preset = "Vu\u00f4ng 1024"
    st.session_state.quick_aspect_ratio = "1:1"
    st.session_state.quick_response_format = "binary"
    st.session_state.quick_count = 1
    st.session_state.quick_mood = ""
    st.session_state.quick_lighting = ""
    st.session_state.quick_camera = ""
    st.session_state.quick_use_optimizer = False
    st.session_state.quick_auto_negative = False
    st.session_state.quick_prompt_preview = ""
    st.session_state.create_use_reference = False
    st.session_state.create_reference_mode = "1 ảnh"
    st.session_state.create_quality_tier = "Fast"
    st.session_state.create_modifiers = []
    st.session_state.create_extra_json = "{}"
    st.session_state.create_count_ui = 1
    st.session_state.create_response_format_ui = "binary"
    st.session_state.create_ref_preserve_mode = True

    st.session_state.gen_prompt = ""
    st.session_state.gen_negative_prompt = ""
    st.session_state.gen_style = "Không áp phong cách"
    st.session_state.gen_quality_profile = "Cân bằng"
    st.session_state.gen_size_preset = "Vu\u00f4ng 1024"
    st.session_state.gen_custom_size = ""
    st.session_state.gen_aspect_ratio = "1:1"
    st.session_state.gen_count = 1
    st.session_state.gen_response_format = "binary"
    st.session_state.gen_output_file = f"outputs/out_{timestamp_slug()}.png"
    st.session_state.gen_quality_override = ""
    st.session_state.gen_style_override = ""
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

    st.session_state.draw_active_flow = WORKFLOW_TABS[0]
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
        "force_page_selector_sync": False,
        "ui_compact_mode": True,
        "ui_debug_mode": False,
        "enable_paste_component": DEFAULT_ENABLE_EXPERIMENTAL_PASTE_COMPONENT,
        "models": [],
        "model_nonce": 0,
        "manual_model": DEFAULT_MODEL,
        "studio_top_model": DEFAULT_MODEL,
        "studio_response_format": "binary",
        "studio_count": 1,
        "studio_output_prefix": "outputs/result",
        "draw_active_flow": WORKFLOW_TABS[0],
        "auto_save_outputs": True,
        "recent_outputs": [],
        "recent_view_output_id": "",
        "gen_workflow_preset": DEFAULT_WORKFLOW_PRESET,
        "quick_scene": DEFAULT_SCENE_PRESET,
        "quick_subject": "",
        "quick_style": "Không áp phong cách",
        "quick_quality_profile": "Cân bằng",
        "quick_size_preset": "Vu\u00f4ng 1024",
        "quick_aspect_ratio": "1:1",
        "quick_response_format": "binary",
        "quick_count": 1,
        "quick_mood": "",
        "quick_lighting": "",
        "quick_camera": "",
        "quick_use_optimizer": False,
        "quick_auto_negative": False,
        "quick_prompt_preview": "",
        "create_use_reference": False,
        "create_reference_mode": "1 ảnh",
        "create_quality_tier": "Fast",
        "create_modifiers": [],
        "create_extra_json": "{}",
        "create_count_ui": 1,
        "create_response_format_ui": "binary",
        "create_ref_preserve_mode": True,
        "gen_prompt": "",
        "gen_negative_prompt": "",
        "gen_style": "Không áp phong cách",
        "gen_quality_profile": "Cân bằng",
        "gen_size_preset": "Vu\u00f4ng 1024",
        "gen_custom_size": "",
        "gen_aspect_ratio": "1:1",
        "gen_count": 1,
        "gen_response_format": "binary",
        "gen_quality_override": "",
        "gen_style_override": "",
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
    if not st.session_state.quick_api_keys_pool_text:
        st.session_state.quick_api_keys_pool_text = st.session_state.api_keys_pool_text
    if not st.session_state.studio_api_keys_pool_text:
        st.session_state.studio_api_keys_pool_text = st.session_state.api_keys_pool_text
    if not st.session_state.config_api_keys_pool_text:
        st.session_state.config_api_keys_pool_text = st.session_state.api_keys_pool_text


def available_page_options() -> list[str]:
    options = list(PAGE_OPTIONS_BASIC)
    if bool(st.session_state.get("ui_debug_mode", False)):
        options.extend(PAGE_OPTIONS_ADVANCED)
    elif PAGE_CONFIG not in options:
        options.append(PAGE_CONFIG)
    return unique_list(options)


def navigate_to_page(page_name: str) -> None:
    st.session_state.page_name = page_name
    st.session_state.force_page_selector_sync = True
    st.rerun()


def sidebar_settings() -> tuple[str, str]:
    with st.sidebar:
        page_options = available_page_options()
        if st.session_state.page_name not in page_options:
            st.session_state.page_name = PAGE_DRAW
            st.session_state.force_page_selector_sync = True
        if bool(st.session_state.get("force_page_selector_sync", False)) or st.session_state.get("page_name_selector") not in page_options:
            st.session_state.page_name_selector = st.session_state.page_name
            st.session_state.force_page_selector_sync = False

        nav_label_map = {
            PAGE_DRAW: "🎨  Tạo ảnh",
            PAGE_HOME: "🏠  Tổng quan",
            PAGE_GALLERY: "🖼️  Thư viện",
            PAGE_PRESET: "✨  Mẫu prompt",
            PAGE_TRAIN: "🧬  Train LoRA",
            PAGE_MODEL: "🧠  Model",
            PAGE_CONFIG: "⚙️  Cài đặt",
        }
        ordered_pages = [PAGE_DRAW, PAGE_HOME, PAGE_GALLERY, PAGE_PRESET, PAGE_TRAIN, PAGE_MODEL, PAGE_CONFIG]
        menu_options = [item for item in ordered_pages if item in page_options]
        if st.session_state.get("page_name_selector") not in menu_options:
            st.session_state.page_name_selector = (
                st.session_state.page_name if st.session_state.page_name in menu_options else menu_options[0]
            )

        st.markdown(
            """
            <div class="nr-brand">
              <div class="nr-brand-logo">9R</div>
              <div class="nr-brand-text">
                <div class="nr-brand-title">9Router Studio</div>
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
        opt_l, opt_r = st.columns(2, gap="small")
        with opt_l:
            st.toggle("Gọn", key="ui_compact_mode", help="Chế độ compact giảm khoảng cách giữa các thành phần.")
        with opt_r:
            st.toggle("Nâng cao", key="ui_debug_mode", help="Mở thêm các trang nâng cao và chế độ debug.")
        if bool(st.session_state.get("ui_debug_mode", False)):
            st.toggle(
                "Bật dán ảnh thử nghiệm",
                key="enable_paste_component",
                help="Chỉ bật khi cần test component dán ảnh.",
            )
        else:
            st.session_state.enable_paste_component = False

        configured = "🟢 Đã cấu hình" if str(st.session_state.base_url).strip() else "🟡 Chưa cấu hình"
        st.caption(f"API: {configured}")

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
    if st.session_state.gen_size_preset == "T\u00f9y ch\u1ec9nh":
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

            stamp = str(entry.get("time", ""))[-8:]
            model_name = str(entry.get("model", ""))
            st.caption(f"{model_name} • {stamp}")
            if st.button("🔍 Phóng to", key=f"btn_recent_view_{widget_id}", use_container_width=True):
                st.session_state.recent_view_output_id = entry_id

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
        saved_path = ""
        if bool(st.session_state.get("auto_save_outputs", True)):
            final_file = output_file
            if Path(final_file).suffix == "":
                final_file += infer_ext(result.get("content_type", ""))
            saved = save_image(image_bytes, final_file)
            saved_path = str(saved)
            if show_inline_preview:
                st.success(f"Đã lưu ảnh: {saved}")
            history["local_path"] = saved_path
        elif show_inline_preview:
            st.info("Ảnh chưa lưu vào máy (đang tắt lưu tự động).")

        if show_inline_preview:
            st.image(image_bytes, caption="Ảnh vừa tạo (thumbnail)", width=260)
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
                "url": "",
                "image_bytes": b"" if saved_path else image_bytes,
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

    if result.get("raw") is not None and bool(st.session_state.get("ui_debug_mode", False)):
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
    if bool(st.session_state.get("ui_debug_mode", False)):
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


def page_preset_studio() -> None:
    st.subheader("Bộ preset")
    st.caption("Chọn preset sẵn rồi áp dụng vào Studio để tạo ảnh ngay.")

    sel_col, btn_col = st.columns([2.6, 1], gap="medium")
    with sel_col:
        preset_name = st.selectbox("Preset quy trình", options=list(WORKFLOW_PRESETS.keys()), key="studio_preset")
    preset = WORKFLOW_PRESETS[preset_name]
    with btn_col:
        if st.button("✨ Áp dụng preset", type="primary", use_container_width=True):
            apply_workflow_preset(preset_name)
            apply_quality_profile_to_state()
            st.success("Đã áp dụng preset.")

    c1, c2 = st.columns([1, 1], gap="medium")
    with c1:
        st.markdown("**Thông số preset**")
        st.json(preset)
    with c2:
        preview = optimize_prompt(
            base_prompt=build_scene_prompt(preset["scene"], "chủ thể của bạn"),
            style_name=preset["style"],
            quality_name=preset["quality_profile"],
            mood="không khí điện ảnh",
            lighting="ánh sáng viền mềm",
            camera="khung hình điện ảnh 35mm",
        )
        st.markdown("**Gợi ý prompt preview**")
        st.code(preview)


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
        is_debug_mode = bool(st.session_state.get("ui_debug_mode", False))

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


def render_create_workflow(base_url: str, api_key: str, model: str, compact_mode: bool) -> None:
    def reset_create_form() -> None:
        st.session_state.quick_subject = ""
        st.session_state.create_ref_inline_pasted = ""
        st.session_state.create_ref_inline_quick_link = ""
        st.session_state.create_modifiers = []
        st.session_state.create_use_reference = False
        st.session_state.create_clipboard_slot_bytes = [None] * 6

    if "create_ref_inline_pasted" not in st.session_state:
        st.session_state.create_ref_inline_pasted = ""
    if "create_ref_inline_quick_link" not in st.session_state:
        st.session_state.create_ref_inline_quick_link = ""
    if "create_clipboard_slot_count" not in st.session_state:
        st.session_state.create_clipboard_slot_count = 2
    if "create_clipboard_slot_bytes" not in st.session_state:
        st.session_state.create_clipboard_slot_bytes = [None] * 6

    prompt_input = st.text_area(
        "Ô prompt chính (đặt trên cùng)",
        key="quick_subject",
        height=180,
        placeholder="Mô tả ảnh muốn tạo. Có thể dán URL/data:image/base64 hoặc link ảnh mẫu vào đây.",
    )

    tier_default = st.session_state.create_quality_tier if st.session_state.create_quality_tier in QUALITY_TIER_PRESETS else "Fast"
    top_cols = [1.35, 0.7, 1.0, 0.85, 0.95] if compact_mode else [1.45, 0.78, 1.05, 0.88, 1.02]
    top_gap = "small" if compact_mode else "medium"
    top_a, top_b, top_c, top_d, top_f = st.columns(top_cols, gap=top_gap)
    with top_a:
        selected_tier = pill_single_select(
            "Mức chất lượng",
            options=list(QUALITY_TIER_PRESETS.keys()),
            key="create_quality_tier",
            default=tier_default,
        )
    with top_b:
        st.number_input("Số ảnh", min_value=1, max_value=60, step=1, key="create_count_ui")
    with top_c:
        response_format_widget("Kiểu trả ảnh", key="create_response_format_ui", index=0)
    with top_d:
        st.toggle("Dùng ảnh mẫu", key="create_use_reference")
    with top_f:
        action_l, action_r = st.columns([0.85, 1.4], gap="small")
        with action_l:
            st.button("🧹 Xóa", use_container_width=True, key="btn_create_reset", on_click=reset_create_form)
        with action_r:
            generate_clicked = st.button("✨ Tạo ảnh", type="primary", use_container_width=True, key="btn_create_image")

    tier_config = QUALITY_TIER_PRESETS[selected_tier]
    st.session_state.quick_quality_profile = str(tier_config["quality_profile"])
    st.caption(f"Chế độ {selected_tier}: {tier_config['note']} • gợi ý {tier_config['count']} ảnh/lần")

    split_cols = [1.9, 1.0] if compact_mode else [1.75, 1.05]
    split_gap = "medium" if compact_mode else "large"
    left_col, right_col = st.columns(split_cols, gap=split_gap)

    quick_mods: list[str] = []
    auto_clicked = False
    auto_rounds = 4
    auto_delay = 0.4
    auto_random_scene = True
    auto_random_style = True
    is_debug_mode = bool(st.session_state.get("ui_debug_mode", False))
    with left_col:
        fast_gap = "small" if compact_mode else "medium"
        fast1, fast2, fast3, fast4 = st.columns([1.2, 1, 1, 0.85], gap=fast_gap)
        with fast1:
            st.selectbox("Bối cảnh", options=list(SCENE_PRESETS.keys()), key="quick_scene")
        with fast2:
            st.selectbox("Phong cách", options=list(STYLE_PRESETS.keys()), key="quick_style")
        with fast3:
            st.selectbox("Kích thước", options=list(SIZE_PRESETS.keys()), key="quick_size_preset")
        with fast4:
            st.selectbox("Tỉ lệ", options=ASPECT_RATIO_PRESETS, key="quick_aspect_ratio")

        if st.session_state.quick_size_preset == "Tùy chỉnh":
            st.text_input("Kích thước tùy chỉnh (ví dụ: 1344x768)", key="gen_custom_size")

        quick_mods = pill_multi_select(
            "Tinh chỉnh nhanh",
            options=list(CREATE_PROMPT_MODIFIERS.keys()),
            key="create_modifiers",
            default=st.session_state.create_modifiers,
        )

        opt1, opt2 = st.columns(2)
        with opt1:
            st.checkbox("Tối ưu prompt tự động", key="quick_use_optimizer")
        with opt2:
            st.checkbox("Tự thêm negative prompt", key="quick_auto_negative")

        with st.expander("Tinh chỉnh nâng cao", expanded=False):
            detail1, detail2, detail3 = st.columns(3)
            with detail1:
                st.text_input("Cảm xúc", key="quick_mood")
            with detail2:
                st.text_input("Ánh sáng", key="quick_lighting")
            with detail3:
                st.text_input("Góc máy", key="quick_camera")
            st.text_area("JSON bổ sung (tùy chọn)", value=str(st.session_state.get("create_extra_json", "{}")), height=84, key="create_extra_json")

            if is_debug_mode:
                st.divider()
                st.caption("Auto ngẫu nhiên chỉ hiện ở chế độ nâng cao.")
                a1, a2, a3 = st.columns([1, 1, 1])
                with a1:
                    auto_rounds = int(st.number_input("Số lượt auto", min_value=2, max_value=20, value=4, step=1, key="create_auto_rounds"))
                with a2:
                    auto_delay = float(st.slider("Nghỉ giữa lượt (giây)", min_value=0.0, max_value=2.0, value=0.4, step=0.1, key="create_auto_delay"))
                with a3:
                    auto_clicked = st.button("Bắt đầu Auto", key="btn_create_auto", use_container_width=True)
                t1, t2 = st.columns(2)
                with t1:
                    auto_random_scene = st.checkbox("Đổi bối cảnh mỗi lượt", value=True, key="create_auto_random_scene")
                with t2:
                    auto_random_style = st.checkbox("Đổi phong cách mỗi lượt", value=True, key="create_auto_random_style")

    ref_mode = "1 ảnh"
    draw_mode = st.session_state.get("create_reference_draw_mode", list(REFERENCE_DRAW_MODES.keys())[0])
    uploaded_files: list[Any] = []
    pasted_refs_text = ""
    save_inputs = True
    slot_clipboard_images: list[bytes] = []
    slot_role_instructions: list[str] = []

    slot_role_options = [
        "Giữ nội dung/chủ thể",
        "Lấy phong cách màu",
        "Lấy bố cục/góc máy",
        "Lấy chất liệu/texture",
        "Tự do",
    ]
    slot_role_map = {
        "Giữ nội dung/chủ thể": "giữ chủ thể và nội dung từ ảnh mẫu",
        "Lấy phong cách màu": "ưu tiên phong cách màu từ ảnh mẫu",
        "Lấy bố cục/góc máy": "ưu tiên bố cục và góc máy từ ảnh mẫu",
        "Lấy chất liệu/texture": "ưu tiên chất liệu và texture từ ảnh mẫu",
        "Tự do": "tham chiếu linh hoạt từ ảnh mẫu",
    }
    preserve_ref_mode = bool(st.session_state.get("create_ref_preserve_mode", True))

    with right_col:
        st.markdown("#### Ảnh mẫu")
        if st.session_state.create_use_reference:
            ref_mode = st.radio(
                "Số ảnh mẫu",
                options=["1 ảnh", "Nhiều ảnh"],
                horizontal=True,
                key="create_reference_mode",
            )
            draw_mode = st.selectbox(
                "Cách vẽ theo ảnh mẫu",
                options=list(REFERENCE_DRAW_MODES.keys()),
                key="create_reference_draw_mode",
            )
            preserve_ref_mode = st.checkbox(
                "Giữ gần ảnh mẫu (mặc định)",
                value=preserve_ref_mode,
                key="create_ref_preserve_mode",
            )

            st.number_input(
                "Số ô dán clipboard",
                min_value=1,
                max_value=6,
                step=1,
                key="create_clipboard_slot_count",
            )

            if paste_image_button is not None:
                for slot_idx in range(int(st.session_state.create_clipboard_slot_count)):
                    button_col, clear_col = st.columns([1.35, 0.65], gap="small")
                    with button_col:
                        pasted_from_clipboard = paste_image_button(
                            f"📋 Dán ảnh ô {slot_idx + 1}",
                            key=f"create_clipboard_paste_{slot_idx}",
                        )
                        clipboard_image = getattr(pasted_from_clipboard, "image_data", None)
                        if clipboard_image is not None:
                            buffer = io.BytesIO()
                            clipboard_image.save(buffer, format="PNG")
                            st.session_state.create_clipboard_slot_bytes[slot_idx] = buffer.getvalue()
                    with clear_col:
                        if st.button(f"Xóa ô {slot_idx + 1}", key=f"btn_clear_clip_slot_{slot_idx}", use_container_width=True):
                            st.session_state.create_clipboard_slot_bytes[slot_idx] = None

                    slot_bytes = st.session_state.create_clipboard_slot_bytes[slot_idx]
                    if slot_bytes:
                        role_col, weight_col = st.columns([1.45, 0.95], gap="small")
                        with role_col:
                            selected_role = st.selectbox(
                                f"Vai trò ô {slot_idx + 1}",
                                options=slot_role_options,
                                key=f"create_clip_slot_role_{slot_idx}",
                            )
                        with weight_col:
                            role_weight = st.slider(
                                f"Độ ảnh hưởng ô {slot_idx + 1}",
                                min_value=0.1,
                                max_value=2.0,
                                value=1.0,
                                step=0.1,
                                key=f"create_clip_slot_weight_{slot_idx}",
                            )

                        role_phrase = slot_role_map.get(selected_role, "tham chiếu từ ảnh mẫu")
                        slot_role_instructions.append(
                            f"{role_phrase} ô {slot_idx + 1} (mức {role_weight:.1f})"
                        )
                        st.image(slot_bytes, width=132, caption=f"Ô {slot_idx + 1}")
                        slot_clipboard_images.append(slot_bytes)
            else:
                st.caption("Clipboard chưa sẵn sàng. Dùng Upload hoặc dán URL/base64.")

            uploaded_files = st.file_uploader(
                "Tải ảnh mẫu (PNG/JPG/WEBP)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key="create_ref_inline_uploader",
            )
            pasted_refs_text = st.text_area(
                "Dán URL / data:image / base64",
                key="create_ref_inline_pasted",
                height=88,
                placeholder="Mỗi dòng một nguồn ảnh",
            )
            save_inputs = st.checkbox(
                "Lưu bản sao ảnh mẫu",
                value=True,
                key="create_ref_inline_save_input_copy",
            )

            slot_count_show = int(st.session_state.get("create_clipboard_slot_count", 1))
            if slot_count_show > 0:
                st.markdown("**Ảnh đã copy theo từng ô**")
                thumb_cols = st.columns(slot_count_show)
                for slot_idx in range(slot_count_show):
                    with thumb_cols[slot_idx]:
                        slot_bytes = st.session_state.create_clipboard_slot_bytes[slot_idx]
                        if slot_bytes:
                            st.image(slot_bytes, width=88, caption=f"Ô {slot_idx + 1}")
                        else:
                            st.caption(f"Ô {slot_idx + 1}: chưa có ảnh")
        else:
            pasted_refs_text = st.text_input(
                "Dán nhanh link ảnh (tùy chọn)",
                key="create_ref_inline_quick_link",
                placeholder="https://...",
            )
            if st.session_state.quick_aspect_ratio == ASPECT_RATIO_ORIGINAL:
                st.info("Tỉ lệ 'Nguyên gốc theo ảnh mẫu' cần bật Dùng ảnh mẫu để hoạt động đúng.")

    refs: list[str] = []
    preview_bytes: list[bytes] = []
    saved_paths: list[str] = []

    uploaded_list = uploaded_files or []
    if ref_mode == "1 ảnh" and len(uploaded_list) > 1:
        uploaded_list = uploaded_list[:1]

    for idx, up in enumerate(uploaded_list, start=1):
        content = up.getvalue()
        mime_type = guess_mime_type(getattr(up, "name", "image.png"), getattr(up, "type", ""))
        refs.append(safe_image_to_data_url(content, mime_type))
        preview_bytes.append(content)
        if save_inputs:
            saved_paths.append(save_uploaded_input_copy(content, getattr(up, "name", f"img_{idx}.png"), "create_ref", idx))

    for clip_idx, clip_bytes in enumerate(slot_clipboard_images, start=1):
        refs.append(safe_image_to_data_url(clip_bytes, "image/png"))
        preview_bytes.append(clip_bytes)
        if save_inputs:
            saved_paths.append(save_uploaded_input_copy(clip_bytes, f"clipboard_{clip_idx}.png", "create_ref", 100 + clip_idx))

    refs.extend(parse_pasted_image_refs(pasted_refs_text or ""))
    prompt_refs = parse_pasted_image_refs(prompt_input or "")
    refs.extend(prompt_refs)
    refs = unique_list(refs)

    if preview_bytes:
        with st.expander(f"Xem trước {len(preview_bytes)} ảnh mẫu", expanded=False):
            preview_cols = st.columns(min(4, len(preview_bytes)))
            for idx, img_bytes in enumerate(preview_bytes):
                with preview_cols[idx % len(preview_cols)]:
                    st.image(img_bytes, width=150)

    if refs:
        st.markdown(
            f"<div class='studio-status-chip'>Đã nhận {len(refs)} ảnh mẫu cho lượt tạo này</div>",
            unsafe_allow_html=True,
        )

    if saved_paths:
        with st.expander("Đường dẫn ảnh mẫu đã lưu", expanded=False):
            for path in saved_paths:
                st.code(path)

    subject_for_scene = prompt_input
    if prompt_refs:
        subject_for_scene = re.sub(r"https?://\S+|data:image/\S+", " ", prompt_input, flags=re.IGNORECASE).strip()
        if not subject_for_scene:
            subject_for_scene = "ảnh mẫu đã dán"

    base_prompt = build_scene_prompt(st.session_state.quick_scene, subject_for_scene)
    suggested_prompt = (
        optimize_prompt(
            base_prompt=base_prompt,
            style_name=st.session_state.quick_style,
            quality_name=st.session_state.quick_quality_profile,
            mood=st.session_state.quick_mood,
            lighting=st.session_state.quick_lighting,
            camera=st.session_state.quick_camera,
        )
        if st.session_state.quick_use_optimizer
        else base_prompt
    )

    if quick_mods:
        mod_text = ", ".join(CREATE_PROMPT_MODIFIERS[item] for item in quick_mods)
        suggested_prompt = f"{suggested_prompt}, {mod_text}"

    if st.session_state.create_use_reference or refs:
        suggested_prompt = f"{suggested_prompt}, {REFERENCE_DRAW_MODES.get(draw_mode, '')}"
        if preserve_ref_mode:
            suggested_prompt = (
                f"{suggested_prompt}, giữ nguyên bố cục/chủ thể chính từ ảnh mẫu, chỉ thay đổi nhẹ theo yêu cầu"
            )
        if slot_role_instructions:
            suggested_prompt = f"{suggested_prompt}, {'; '.join(slot_role_instructions)}"

    final_prompt = suggested_prompt
    with st.expander("Xem/chỉnh prompt cuối", expanded=False):
        edit_final_prompt = st.toggle("Chỉnh prompt cuối", value=False, key="create_edit_final_prompt")
        if edit_final_prompt:
            final_prompt = st.text_area("Prompt cuối cùng", value=suggested_prompt, height=110)
        else:
            preview_prompt = suggested_prompt if len(suggested_prompt) <= 520 else f"{suggested_prompt[:520]}..."
            st.markdown(f"<div class='prompt-preview-box'>{html.escape(preview_prompt)}</div>", unsafe_allow_html=True)

    if (auto_clicked or generate_clicked) and not subject_for_scene.strip() and not refs:
        st.error("Hãy nhập mô tả hoặc thêm ảnh mẫu trước khi tạo để tránh prompt lạc đề.")
        return

    if auto_clicked:
        try:
            extra_auto = parse_json_object(str(st.session_state.get("create_extra_json", "{}")))
        except Exception as ex:
            st.error(f"JSON bổ sung không hợp lệ: {ex}")
            return

        flavor_tags = [
            "biến thể sáng tạo",
            "chi tiết sắc nét",
            "ánh sáng điện ảnh",
            "bố cục mạnh",
            "phong cách mới lạ",
            "tập trung chủ thể",
        ]

        progress = st.progress(0.0)
        st.info(f"Đang auto tạo ngẫu nhiên {auto_rounds} lượt...")

        for run_idx in range(auto_rounds):
            scene_auto = random.choice(list(SCENE_PRESETS.keys())) if auto_random_scene else st.session_state.quick_scene
            style_auto = random.choice(list(STYLE_PRESETS.keys())) if auto_random_style else st.session_state.quick_style

            base_auto_prompt = build_scene_prompt(scene_auto, subject_for_scene)
            auto_prompt = (
                optimize_prompt(
                    base_prompt=base_auto_prompt,
                    style_name=style_auto,
                    quality_name=st.session_state.quick_quality_profile,
                    mood=st.session_state.quick_mood,
                    lighting=st.session_state.quick_lighting,
                    camera=st.session_state.quick_camera,
                )
                if st.session_state.quick_use_optimizer
                else base_auto_prompt
            )

            if quick_mods:
                mod_text = ", ".join(CREATE_PROMPT_MODIFIERS[item] for item in quick_mods)
                auto_prompt = f"{auto_prompt}, {mod_text}"

            auto_prompt = f"{auto_prompt}, {random.choice(flavor_tags)}"

            if st.session_state.create_use_reference or refs:
                auto_prompt = f"{auto_prompt}, {REFERENCE_DRAW_MODES.get(draw_mode, '')}"
                if preserve_ref_mode:
                    auto_prompt = (
                        f"{auto_prompt}, giữ nguyên bố cục/chủ thể chính từ ảnh mẫu, chỉ thay đổi nhẹ theo yêu cầu"
                    )
                if slot_role_instructions:
                    auto_prompt = f"{auto_prompt}, {'; '.join(slot_role_instructions)}"

            payload: dict[str, Any] = {
                "model": model,
                "prompt": auto_prompt,
                "n": int(st.session_state.create_count_ui),
            }

            selected_size = ""
            if st.session_state.quick_size_preset == "Tùy chỉnh":
                selected_size = st.session_state.gen_custom_size.strip()
            else:
                selected_size = SIZE_PRESETS.get(st.session_state.quick_size_preset, "").strip()
            if selected_size and not (refs and st.session_state.quick_aspect_ratio == ASPECT_RATIO_ORIGINAL):
                payload["size"] = selected_size

            quality_value = str(QUALITY_PROFILES.get(st.session_state.quick_quality_profile, {}).get("quality", "")).strip()
            if quality_value:
                payload["quality"] = quality_value

            style_value = str(STYLE_PRESETS.get(style_auto, {}).get("style", "")).strip()
            if style_value:
                payload["style"] = style_value

            response_format = str(st.session_state.create_response_format_ui)
            if response_format in {"url", "b64_json"}:
                payload["response_format"] = response_format

            if st.session_state.quick_auto_negative:
                auto_negative = str(STYLE_PRESETS.get(style_auto, {}).get("negative_prompt", "")).strip()
                if auto_negative:
                    payload["negative_prompt"] = auto_negative

            if st.session_state.quick_aspect_ratio.strip() and st.session_state.quick_aspect_ratio != ASPECT_RATIO_ORIGINAL:
                payload["aspect_ratio"] = st.session_state.quick_aspect_ratio.strip()

            payload.update(extra_auto)

            if refs:
                if ref_mode == "1 ảnh":
                    payload["image"] = refs[0]
                else:
                    payload["images"] = refs

            output_file = f"{st.session_state.studio_output_prefix}_auto_{run_idx + 1}_{timestamp_slug()}.png"
            run_payload_generation(
                base_url,
                api_key,
                payload,
                response_format,
                output_file,
                f"Auto ngẫu nhiên {run_idx + 1}/{auto_rounds}",
            )

            progress.progress((run_idx + 1) / auto_rounds)
            if auto_delay > 0 and run_idx < auto_rounds - 1:
                time.sleep(auto_delay)

        st.success("Đã hoàn tất auto tạo ngẫu nhiên")

    if generate_clicked:
        try:
            st.session_state.studio_count = int(st.session_state.create_count_ui)
            st.session_state.studio_response_format = str(st.session_state.create_response_format_ui)
            st.session_state.gen_style = st.session_state.quick_style
            st.session_state.gen_quality_profile = st.session_state.quick_quality_profile
            st.session_state.gen_size_preset = st.session_state.quick_size_preset
            st.session_state.gen_aspect_ratio = st.session_state.quick_aspect_ratio
            st.session_state.gen_count = int(st.session_state.studio_count)
            st.session_state.gen_response_format = st.session_state.studio_response_format
            st.session_state.gen_prompt = final_prompt
            st.session_state.gen_negative_prompt = ""
            st.session_state.gen_quality_override = ""
            st.session_state.gen_style_override = ""
            st.session_state.gen_extra_json = str(st.session_state.get("create_extra_json", "{}"))

            payload = build_payload(
                model=model,
                prompt=final_prompt,
                include_advanced=False,
                response_format=st.session_state.studio_response_format,
            )
            if refs:
                if ref_mode == "1 ảnh":
                    payload["image"] = refs[0]
                else:
                    payload["images"] = refs
                if st.session_state.quick_aspect_ratio == ASPECT_RATIO_ORIGINAL:
                    payload.pop("aspect_ratio", None)
                    payload.pop("size", None)
        except Exception as ex:
            st.error(f"Không thể tạo payload: {ex}")
            return

        output_file = f"{st.session_state.studio_output_prefix}_create_{timestamp_slug()}.png"
        run_payload_generation(base_url, api_key, payload, st.session_state.studio_response_format, output_file, "Tạo ảnh")


def render_edit_workflow(base_url: str, api_key: str, model: str, compact_mode: bool) -> None:
    render_workflow_intro(
        "Sửa ảnh theo ảnh mẫu",
        "Giữ bố cục ảnh gốc, chỉ thay phần bạn muốn chỉnh.",
    )
    left_col, right_col = st.columns([1.45, 1.05], gap="large")
    with right_col:
        refs, _, _ = collect_reference_images("edit", allow_multiple=False, compact_mode=compact_mode)

    with left_col:
        p1, p2, p3 = st.columns([1.25, 0.95, 0.8], gap="medium")
        with p1:
            preset_name = st.selectbox("Mục tiêu chỉnh sửa", options=list(EDIT_PRESET_PROMPTS.keys()), key="edit_preset_name")
        with p2:
            edit_strength = st.slider("Mức thay đổi", min_value=0.1, max_value=1.0, step=0.05, value=0.7, key="edit_strength")
        with p3:
            if st.button("Nạp mẫu", key="btn_load_edit_preset", use_container_width=True):
                st.session_state.edit_prompt = EDIT_PRESET_PROMPTS[preset_name]

        edit_prompt = st.text_area(
            "Mô tả chỉnh sửa",
            value=EDIT_PRESET_PROMPTS[preset_name],
            height=96,
            key="edit_prompt",
        )
        with st.expander("JSON bổ sung", expanded=False):
            edit_extra = st.text_area("JSON bổ sung (tùy chọn)", value="{}", height=84, key="edit_extra_json")

    if st.button("Sửa ảnh", type="primary", use_container_width=True, key="btn_edit_image"):
        if not refs:
            st.error("Bạn cần tải lên hoặc dán ít nhất 1 ảnh tham chiếu.")
            return
        try:
            payload: dict[str, Any] = {
                "model": model,
                "prompt": edit_prompt,
                "n": int(st.session_state.studio_count),
                "image": refs[0],
                "strength": float(edit_strength),
            }
            payload.update(parse_json_object(edit_extra))
        except Exception as ex:
            st.error(f"JSON bổ sung không hợp lệ: {ex}")
            return

        output_file = f"{st.session_state.studio_output_prefix}_edit_{timestamp_slug()}.png"
        run_payload_generation(base_url, api_key, payload, st.session_state.studio_response_format, output_file, "Sửa ảnh")


def render_compose_workflow(base_url: str, api_key: str, model: str, compact_mode: bool) -> None:
    render_workflow_intro(
        "Ghép nhiều ảnh",
        "Ghép nhiều ảnh thành 1 bố cục gọn, nhất quán.",
    )
    left_col, right_col = st.columns([1.45, 1.05], gap="large")
    with right_col:
        refs, _, _ = collect_reference_images("compose", allow_multiple=True, compact_mode=compact_mode)

    with left_col:
        c1, c2, c3 = st.columns([1.2, 1.0, 0.8], gap="medium")
        with c1:
            compose_preset = st.selectbox("Mẫu ghép", options=list(COMPOSE_PRESET_PROMPTS.keys()), key="compose_preset_name")
        with c2:
            compose_layout = st.selectbox(
                "Kiểu ghép",
                options=list(COMPOSE_LAYOUT_OPTIONS.keys()),
                key="compose_layout",
                format_func=lambda value: COMPOSE_LAYOUT_OPTIONS.get(value, value),
            )
        with c3:
            if st.button("Nạp mẫu", key="btn_load_compose_preset", use_container_width=True):
                st.session_state.compose_prompt = COMPOSE_PRESET_PROMPTS[compose_preset]

        compose_prompt = st.text_area(
            "Mô tả ghép ảnh",
            value=COMPOSE_PRESET_PROMPTS[compose_preset],
            height=96,
            key="compose_prompt",
        )
        with st.expander("JSON bổ sung", expanded=False):
            compose_extra = st.text_area("JSON bổ sung (tùy chọn)", value="{}", height=84, key="compose_extra_json")

    if st.button("Ghép ảnh", type="primary", use_container_width=True, key="btn_compose_image"):
        if len(refs) < 2:
            st.error("Bạn cần ít nhất 2 ảnh để ghép.")
            return
        try:
            payload = {
                "model": model,
                "prompt": f"{compose_prompt}. Bố cục ưu tiên kiểu {COMPOSE_LAYOUT_OPTIONS.get(compose_layout, compose_layout)}",
                "n": int(st.session_state.studio_count),
                "images": refs,
            }
            payload.update(parse_json_object(compose_extra))
        except Exception as ex:
            st.error(f"JSON bổ sung không hợp lệ: {ex}")
            return

        output_file = f"{st.session_state.studio_output_prefix}_compose_{timestamp_slug()}.png"
        run_payload_generation(base_url, api_key, payload, st.session_state.studio_response_format, output_file, "Ghép ảnh")


def render_translate_workflow(base_url: str, api_key: str, model: str, compact_mode: bool) -> None:
    render_workflow_intro(
        "Dịch chữ trên ảnh",
        "Giữ nguyên bố cục, chỉ thay nội dung chữ.",
    )
    left_col, right_col = st.columns([1.45, 1.05], gap="large")
    with right_col:
        refs, _, _ = collect_reference_images("translate", allow_multiple=False, compact_mode=compact_mode)

    with left_col:
        t1, t2, t3 = st.columns([1, 1, 1.12], gap="medium")
        with t1:
            src_lang = st.selectbox("Ngôn ngữ nguồn", options=TRANSLATE_LANG_OPTIONS, index=1, key="translate_src")
        with t2:
            target_lang = st.selectbox("Ngôn ngữ đích", options=TRANSLATE_LANG_OPTIONS, index=0, key="translate_tgt")
        with t3:
            tone = st.selectbox("Mức ưu tiên", options=TRANSLATE_TONE_OPTIONS, key="translate_tone")

        translate_note = st.text_area(
            "Ghi chú thêm",
            value="Giữ nguyên font và vị trí chữ tối đa có thể",
            height=74,
            key="translate_note",
        )
        translate_prompt = f"{build_translate_prompt(src_lang, target_lang, translate_note)} Ưu tiên: {tone.lower()}."

        edit_translate_prompt = st.toggle("Chỉnh prompt dịch", value=False, key="translate_edit_prompt")
        if edit_translate_prompt:
            translate_prompt_user = st.text_area("Prompt dịch ảnh", value=translate_prompt, height=96, key="translate_prompt_preview")
        else:
            translate_prompt_user = translate_prompt
            st.markdown(f"<div class='prompt-preview-box'>{html.escape(translate_prompt_user[:360])}</div>", unsafe_allow_html=True)

        with st.expander("JSON bổ sung", expanded=False):
            translate_extra = st.text_area("JSON bổ sung (tùy chọn)", value="{}", height=84, key="translate_extra_json")

    if st.button("Dịch ảnh", type="primary", use_container_width=True, key="btn_translate_image"):
        if not refs:
            st.error("Bạn cần tải lên hoặc dán 1 ảnh trước khi dịch.")
            return
        try:
            payload = {
                "model": model,
                "prompt": translate_prompt_user,
                "n": int(st.session_state.studio_count),
                "image": refs[0],
            }
            payload.update(parse_json_object(translate_extra))
        except Exception as ex:
            st.error(f"JSON bổ sung không hợp lệ: {ex}")
            return

        output_file = f"{st.session_state.studio_output_prefix}_translate_{timestamp_slug()}.png"
        run_payload_generation(base_url, api_key, payload, st.session_state.studio_response_format, output_file, "Dịch ảnh")


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
        story_beat = st.selectbox("Nhịp truyện", options=STORY_BEAT_OPTIONS, key="story_beat")
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
            if st.button("⟲ Reset", use_container_width=True, key="btn_quick_clean_defaults"):
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

                if paste_image_button is not None and bool(st.session_state.get("enable_paste_component", False)):
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
                        min_value=30,
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

        if refs:
            if len(refs) == 1:
                payload["image"] = refs[0]
            else:
                payload["images"] = refs

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
                        st.code(str(selected_output.get("prompt", "")))

        if bool(st.session_state.get("ui_debug_mode", False)):
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

        lock1, lock2 = st.columns([1.0, 1.2], gap="small")
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
                    min_value=30,
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
                    min_value=30,
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
        s1, s2 = st.columns([1.0, 2.2], gap="small")
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
            tone = st.selectbox("Ưu tiên", options=TRANSLATE_TONE_OPTIONS, key="quick_translate_tone")

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



def page_generate(base_url: str, api_key: str, workflow_override: str | None = None) -> None:
    compact_mode = st.session_state.ui_compact_mode

    if "studio_response_format" not in st.session_state:
        st.session_state.studio_response_format = "binary"
    if "studio_count" not in st.session_state:
        st.session_state.studio_count = 1
    if "studio_output_prefix" not in st.session_state:
        st.session_state.studio_output_prefix = "outputs/result"
    if "draw_active_flow" not in st.session_state:
        st.session_state.draw_active_flow = WORKFLOW_TABS[0]
    if not bool(st.session_state.get("ui_debug_mode", False)) and not workflow_override:
        page_generate_quick(base_url, api_key, compact_mode)
        return

    st.subheader("Xưởng ảnh")

    model = suggest_top_model(
        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
        str(st.session_state.manual_model),
    )
    st.session_state.manual_model = model
    quick_models = get_quick_model_choices()
    if st.session_state.get("studio_top_model") not in quick_models:
        st.session_state.studio_top_model = suggest_top_model(
            [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
            st.session_state.manual_model,
        )

    top_cols = [2.0, 1.4, 1.1] if compact_mode else [2.1, 1.5, 1.2]
    top_gap = "small" if compact_mode else "medium"
    top1, top3, top5 = st.columns(top_cols, gap=top_gap)
    with top1:
        selected_top = pill_single_select(
            "Model đỉnh (1 chạm)",
            options=quick_models,
            key="studio_top_model",
            default=st.session_state.studio_top_model,
        )
        if selected_top and selected_top != st.session_state.manual_model:
            st.session_state.manual_model = selected_top
            model = selected_top
    with top3:
        st.selectbox("Preset nhanh", options=list(WORKFLOW_PRESETS.keys()), key="gen_workflow_preset")
    with top5:
        ab_l, ab_r = st.columns(2, gap="small")
        with ab_l:
            if st.button("Nạp model", use_container_width=True, key="btn_studio_load_models"):
                ok_load, load_msg = load_models_into_state(base_url, api_key)
                if ok_load:
                    st.session_state.studio_top_model = suggest_top_model(st.session_state.models, st.session_state.manual_model)
                    st.success(load_msg)
                else:
                    st.error(load_msg)
        with ab_r:
            if st.button("Áp preset", use_container_width=True, key="btn_studio_apply_preset"):
                apply_workflow_preset(st.session_state.gen_workflow_preset)
                st.session_state.create_count_ui = int(st.session_state.quick_count)
                st.session_state.create_response_format_ui = str(st.session_state.quick_response_format)
                st.success("Đã áp dụng preset")

    if st.button("↺ Mặc định vẽ thường", key="btn_studio_everyday_defaults"):
        apply_everyday_studio_defaults()
        st.session_state.studio_top_model = st.session_state.manual_model
        st.success("Đã đưa về cấu hình vẽ thường")

    model_total = len(st.session_state.models)
    top_model = suggest_top_model(
        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
        st.session_state.manual_model,
    )
    st.caption(
        f"Đang dùng: {st.session_state.manual_model} • Đỉnh gợi ý: {top_model} • Đã nạp {model_total} model"
    )

    if bool(st.session_state.get("ui_debug_mode", False)):
        with st.expander("Model nâng cao", expanded=False):
            adv1, adv2 = st.columns(2)
            with adv1:
                if st.button("Đặt model đỉnh", use_container_width=True, key="btn_studio_pick_top_model"):
                    st.session_state.manual_model = suggest_top_model(
                        [str(item) for item in st.session_state.get("models", []) if isinstance(item, str)],
                        st.session_state.manual_model,
                    )
                    st.session_state.studio_top_model = st.session_state.manual_model
                    st.success(f"Đang dùng model: {st.session_state.manual_model}")
            with adv2:
                if st.button("Nạp model + đặt đỉnh", use_container_width=True, key="btn_studio_load_and_pick_top"):
                    ok_load, load_msg = load_models_into_state(base_url, api_key, enforce_top_model=True)
                    if ok_load:
                        st.session_state.studio_top_model = st.session_state.manual_model
                        st.success(load_msg)
                    else:
                        st.error(load_msg)
            model = selected_model_widget("studio")

    if workflow_override:
        active_flow = workflow_override
        st.info(f"Đang ở trang riêng: **{workflow_override}**")
    else:
        active_flow = pill_single_select(
            "Luồng thao tác",
            options=WORKFLOW_TABS,
            key="draw_active_flow",
            default=st.session_state.draw_active_flow,
        )

    if active_flow == "Tạo ảnh":
        render_create_workflow(base_url, api_key, model, compact_mode)
    elif active_flow == "Sửa ảnh":
        render_edit_workflow(base_url, api_key, model, compact_mode)
    elif active_flow == "Ghép ảnh":
        render_compose_workflow(base_url, api_key, model, compact_mode)
    elif active_flow == "Dịch ảnh":
        render_translate_workflow(base_url, api_key, model, compact_mode)
    else:
        render_story_workflow(base_url, api_key, model)

    render_recent_outputs_strip()

    with st.expander("Thiết lập chung", expanded=False):
        is_debug_mode = bool(st.session_state.get("ui_debug_mode", False))
        if is_debug_mode:
            common_cols = [1.05, 0.9, 1.4, 1.1] if compact_mode else [1.08, 0.92, 1.46, 1.14]
            common_gap = "small" if compact_mode else "medium"
            common1, common2, common3, common4 = st.columns(common_cols, gap=common_gap)
        else:
            common_cols = [1.2, 1.0, 1.1] if compact_mode else [1.26, 1.04, 1.14]
            common_gap = "small" if compact_mode else "medium"
            common1, common2, common4 = st.columns(common_cols, gap=common_gap)
        with common1:
            response_format_widget("Định dạng phản hồi", key="studio_response_format", index=0)
        with common2:
            st.number_input("Số lượng ảnh", min_value=1, max_value=60, step=1, key="studio_count")
        if is_debug_mode:
            with common3:
                st.text_input("Tiền tố file lưu", key="studio_output_prefix")
        with common4:
            st.toggle("Lưu ảnh vào máy", key="auto_save_outputs")

        mode_gap = "small" if compact_mode else "medium"
        mode1, mode2 = st.columns([1.25, 1.0], gap=mode_gap)
        with mode1:
            st.selectbox("Chế độ gọi API", options=MULTI_API_MODES, key="multi_api_mode")
        with mode2:
            st.number_input(
                "Luồng song song tối đa",
                min_value=1,
                max_value=MAX_PARALLEL_WORKERS,
                step=1,
                key="multi_api_max_parallel",
            )

        timeout1, timeout2, timeout3 = st.columns([1.0, 1.0, 1.15], gap=mode_gap)
        with timeout1:
            st.number_input(
                "Timeout request (giây)",
                min_value=30,
                max_value=MAX_API_TIMEOUT_SECONDS,
                step=10,
                key="api_request_timeout",
            )
        with timeout2:
            st.number_input(
                "Retry khi timeout/lỗi tạm",
                min_value=0,
                max_value=MAX_IMAGE_RETRY_COUNT,
                step=1,
                key="image_retry_count",
            )
        with timeout3:
            st.number_input(
                "Backoff retry cơ bản (giây)",
                min_value=0.2,
                max_value=10.0,
                step=0.1,
                key="image_retry_backoff",
            )
        st.caption("Gợi ý ổn định: timeout 300-420s, retry 1-2, backoff 1.2-2.0s.")

        if st.session_state.multi_api_mode != MODE_SINGLE_API:
            pool = parse_api_keys_pool(
                str(st.session_state.get("api_keys_pool_text", "") or st.session_state.get("api_key", "")),
                st.session_state.api_key,
            )
            preview_count = max(1, int(st.session_state.get("studio_count", 1)))
            mode_value = str(st.session_state.get("multi_api_mode", DEFAULT_MULTI_API_MODE))
            can_split = should_split_batch_requests(mode_value, preview_count, len(pool))
            if can_split:
                preview_workers = resolve_parallel_workers(
                    mode=mode_value,
                    requested_count=preview_count,
                    key_pool_count=len(pool),
                    max_parallel=int(st.session_state.get("multi_api_max_parallel", 1)),
                )
                st.caption(
                    f"Đã nhận {len(pool)} key • batch {preview_count} ảnh • chạy tối đa {preview_workers} luồng."
                )
            else:
                st.caption(
                    f"Chế độ `{mode_value}` hiện chưa đủ điều kiện tách batch, hệ thống sẽ fallback về 1 request thường."
                )
            if st.button("⚙️ Mở Cài đặt API key", key="btn_open_config_from_studio_keys", use_container_width=False):
                navigate_to_page(PAGE_CONFIG)
        st.markdown(
            "<div class='compact-note'>Bạn có thể tắt lưu máy, tạo xong chỉ xem thumbnail rồi chọn ảnh cần tải xuống.</div>",
            unsafe_allow_html=True,
        )



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
    c1, c2, c3 = st.columns([2, 1.2, 0.9])
    with c1:
        keyword = st.text_input("Lọc theo model hoặc prompt", value="", placeholder="ví dụ: gpt-5.4 hoặc neon city")
    with c2:
        day_options = ["Tất cả"] + sorted(
            {str(item.get("time", ""))[:10] for item in history if str(item.get("time", ""))},
            reverse=True,
        )
        selected_day = st.selectbox("Ngày", options=day_options, index=0)
    with c3:
        if st.button("🗑 Xóa lịch sử", use_container_width=True):
            if HISTORY_FILE.exists():
                HISTORY_FILE.unlink()
            st.success("Đã xóa lịch sử")
            st.rerun()

    if keyword.strip():
        term = keyword.strip().lower()
        history = [item for item in history if term in str(item.get("model", "")).lower() or term in str(item.get("prompt", "")).lower()]

    if selected_day != "Tất cả":
        history = [item for item in history if str(item.get("time", "")).startswith(selected_day)]

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
            st.markdown(f"##### {day}")
            day_cols = 8 if compact_mode else 6
            thumb_width = 118 if compact_mode else 140
            cols = st.columns(day_cols)
            for idx, item in enumerate(grouped[day][:24]):
                path = Path(str(item.get("local_path", "")))
                if not path.exists():
                    continue
                with cols[idx % day_cols]:
                    st.image(str(path), width=thumb_width)
                    st.caption(f"{item.get('model', '')} • {item.get('time', '')}")


def page_advanced_config(base_url: str, api_key: str) -> None:
    st.subheader("Cài đặt")
    tabs = st.tabs(["Kết nối", "Sân chơi API"])

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


def main() -> None:
    st.set_page_config(
        page_title="9Router Image Studio Pro",
        page_icon="🎨",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_state()
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
        page_generate(base_url, api_key)
    elif page_name == PAGE_PRESET:
        page_preset_studio()
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
