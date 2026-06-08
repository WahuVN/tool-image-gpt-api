"""Catalog các art còn thiếu cho project Tu Tiên Cờ.

Mỗi item có:
- code: tên file (snake_case, không đuôi). Dùng làm tên file PNG.
- title_vi: tên hiển thị tiếng Việt.
- desc: mô tả ngắn (mood, palette, key element).
- size: (width, height) pixel cuối cùng. App sẽ resize sau khi gen.
- aspect: aspect ratio gửi cho API ("1:1", "2:3", "16:9", "9:16", "4:5").
- transparent: True nếu cần nền trong suốt PNG.
- relpath: đường dẫn tương đối tính từ Assets/ (KHÔNG có đuôi).
- group: category lớn để gom UI.
- style_hint: phong cách art (anime/fantasy/icon/...).
- extra_rules: list các yêu cầu thêm dán vào prompt.

Cấu trúc đường dẫn cuối cùng = <export_root>/<relpath>.png
Mặc định export_root = "Assets" (theo Unity convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtItem:
    code: str
    title_vi: str
    desc: str
    size: tuple[int, int]
    aspect: str
    transparent: bool
    relpath: str
    group: str
    subgroup: str = ""
    style_hint: str = ""
    extra_rules: tuple[str, ...] = field(default_factory=tuple)
    priority: str = "P1"


# =====================================================================
# A. CHARACTER  (8 portrait + 8 chibi + 64 expression = 80 PNG)
# =====================================================================

_CHARACTERS = [
    ("sun_wukong",       "Tôn Ngộ Không",
        "monkey king wukong, golden armor + red sash, fiery magic, cocky smirk, "
        "BBQ skewer/staff, palette gold + red"),
    ("phat_to",          "Phật Tổ",
        "buddha-like sage, mysterious smile, golden halo, lotus throne, "
        "palette gold + warm amber"),
    ("dao_si_bat_ma",    "Đạo Sĩ Bắt Ma",
        "taoist ghost-hunter, yellow robe with talisman patterns, holding paper charms, "
        "palette pale yellow + ink blue"),
    ("tieu_long_nu",     "Tiểu Long Nữ",
        "cold elegant swordswoman, white silk hanfu, jade ornaments, sharp gaze, "
        "palette white + jade green"),
    ("tru_bat_gioi",     "Trư Bát Giới",
        "anthropomorphic pig warrior, nine-tooth rake, lazy goofy smile, "
        "palette pink skin + earth brown"),
    ("sa_tang",          "Sa Tăng",
        "stoic monk-warrior carrying baggage and necklace of skulls, "
        "palette brown + jade beads"),
    ("bach_cot_tinh",    "Bạch Cốt Tinh",
        "white-bone demoness, pale skin, purple dark aura, seductive cruel grin, "
        "palette white + violet"),
    ("ta_thong_thien",   "Tà Thông Thiên",
        "great demonic overlord, dark armor, blood-red cape, evil aura, "
        "palette pure black + blood red"),
]

_CHARACTER_EXPRESSIONS = [
    ("idle",        "biểu cảm bình thản, nhẹ nhàng, mắt mở tự nhiên"),
    ("smug",        "biểu cảm tự đắc, khóe miệng nhếch lên, mắt khinh khỉnh"),
    ("cry",         "biểu cảm khóc, nước mắt rơi, lông mày chau lại, miệng méo"),
    ("blood_nose",  "biểu cảm bị bắn máu mũi (anime gag), mặt đỏ, máu nhỏ ra mũi"),
    ("focus",       "biểu cảm tập trung cao độ, mắt nheo, môi mím chặt"),
    ("panic",       "biểu cảm hoảng loạn, mắt mở to, miệng mở, mồ hôi"),
    ("bluff",       "biểu cảm tỏ vẻ, gượng gạo, ánh mắt né tránh, cười giả"),
    ("victory",     "biểu cảm chiến thắng, cười rạng rỡ, ánh mắt sáng"),
]


def _build_character_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _CHARACTERS:
        # A1. Portrait 512x768
        items.append(ArtItem(
            code=f"{code}_portrait",
            title_vi=f"{title_vi} – Portrait",
            desc=f"full upper-body character portrait, {desc}, dramatic lighting, "
                 "high-quality anime / Chinese fantasy concept art, cinematic mood",
            size=(512, 768),
            aspect="2:3",
            transparent=True,
            relpath=f"Resources/characters/{code}/portrait",
            group="A. Character",
            subgroup="Portrait",
            style_hint="anime fantasy concept art",
            extra_rules=(
                "single character only, no other characters, no background scenery",
                "centered composition, full upper-body visible",
                "transparent background, alpha channel, isolated subject",
            ),
            priority="P0",
        ))
        # A2. Chibi 256x256
        items.append(ArtItem(
            code=f"{code}_chibi",
            title_vi=f"{title_vi} – Chibi",
            desc=f"super-deformed chibi version of {desc}, oversized head, big eyes, "
                 "tiny body, cute expression, full body visible",
            size=(256, 256),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/characters/{code}/chibi",
            group="A. Character",
            subgroup="Chibi",
            style_hint="chibi anime",
            extra_rules=(
                "chibi proportions, head ~50% of body height",
                "transparent background, alpha channel, no scenery",
                "centered, full body, clean outline",
            ),
            priority="P0",
        ))
        # A3. Expression overlays 128x128
        for exp_code, exp_desc in _CHARACTER_EXPRESSIONS:
            items.append(ArtItem(
                code=f"{code}_expr_{exp_code}",
                title_vi=f"{title_vi} – {exp_code}",
                desc=f"close-up face icon of {desc}, {exp_desc}, anime expression sheet",
                size=(128, 128),
                aspect="1:1",
                transparent=True,
                relpath=f"Resources/characters/{code}/expr/{exp_code}",
                group="A. Character",
                subgroup="Expression",
                style_hint="anime expression icon",
                extra_rules=(
                    "head and shoulders only, face takes most of frame",
                    "transparent background, no scenery, no body",
                    "clear readable expression, anime style",
                ),
                priority="P1",
            ))
    return items


# =====================================================================
# B. PHÁP BẢO / BẢO VẬT  (13 + 21 + 19 = 53)
# =====================================================================

_RELICS_PERMANENT = [
    ("kinh_chieu_yeu",         "Kính Chiếu Yêu",         "ancient bronze mirror with demon-revealing rune, soft purple glow"),
    ("bang_dinh_chong_nhuc",   "Băng Dính Chống Nhục",   "magical roll of yellow talisman tape, ironic fantasy item"),
    ("guong_mat_day",          "Gương Mặt Dày",          "thick jade face plate / mask, smug aura, gold trim"),
    ("luoi_kiem_huyen_am",     "Lưỡi Kiếm Huyền Âm",     "dark obsidian shadow blade, purple mist around it"),
    ("linh_phu_tram_an",       "Linh Phù Trầm Ẩn",       "stealth talisman paper with faint blue runes"),
    ("nhan_co_truyen_dao",     "Nhẫn Cỏ Truyền Đạo",     "humble grass ring with tiny green leaf, soft bokeh"),
    ("bat_vang_tran_phai",     "Bát Vàng Trấn Phái",     "majestic golden alms bowl with engraved sutras, holy light"),
    ("la_chan_be_quan",        "Lá Chắn Bế Quan",        "round meditation shield with closed-gate symbol"),
    ("quat_ba_tieu",           "Quạt Ba Tiêu",           "giant banana-leaf fan with wind aura, light green"),
    ("dan_thanh_dan",          "Đan Thánh Đan",          "glowing red elixir pill in jade dish, golden runes"),
    ("tui_can_khon_lung_lo",   "Túi Càn Khôn",           "small magical pouch overflowing with stars and treasure"),
    ("dong_ho_cat_tuyet_tu",   "Đồng Hồ Cát Tuyệt Tự",   "ornate hourglass with black sand, time-stop aura"),
    ("ngoc_boi_phuc",          "Ngọc Bội Phúc",          "carved jade pendant of blessing 福, red silk tassel"),
]

_RELICS_LIAR_TEMP = [
    ("hoi_thien_dan",              "Hồi Thiên Đan",              "common liar relic, silver-gray rarity rim, glowing red orange elixir pill, healing qi swirl, lifesaving feeling"),
    ("thien_van_phu",              "Thiên Vận Phù",              "common liar relic, silver-gray rarity rim, lucky yellow paper talisman, cloud runes, soft gold glow"),
    ("dao_tam_linh_phu",           "Đạo Tâm Linh Phù",           "common liar relic, silver-gray rarity rim, pale green white talisman, pure aura, resisting inner demon corruption"),
    ("van_tam_chau",               "Vấn Tâm Châu",               "common liar relic, silver-gray rarity rim, dark black blue mind pearl, thought veins, purple glow, reads opponent mentality"),
    ("dong_sat_linh_dong",         "Động Sát Linh Đồng",         "common liar relic, silver-gray rarity rim, small bronze bell fused with observing eye, detects bluff odds"),
    ("hu_khong_gioi",              "Hư Không Giới",              "common liar relic, silver-gray rarity rim, space ring with blue violet portal core, hides card information"),
    ("vo_anh_phu",                 "Vô Ảnh Phù",                 "common liar relic, silver-gray rarity rim, almost transparent talisman, faint glowing edge, stealth no-shadow effect"),
    ("thien_co_nhan",              "Thiên Cơ Nhãn",              "rare liar relic, blue rarity rim, third celestial eye, blue gold aura, mysterious divination"),
    ("thien_co_kinh",              "Thiên Cơ Kính",              "rare liar relic, blue rarity rim, ancient bronze divination mirror, astronomy glyphs, blue glow, reveals full stats"),
    ("an_tuc_phu",                 "Ẩn Tức Phù",                 "rare liar relic, blue rarity rim, hidden-breath talisman fading into mist, concealed qi, avoids being challenged"),
    ("pha_vong_dong_tu",           "Phá Vọng Đồng Tử",           "rare liar relic, blue rarity rim, illusion-breaking pupil, sharp beam cutting through fog and card shadows"),
    ("tran_hon_chung",             "Trấn Hồn Chung",             "rare liar relic, blue rarity rim, large soul-suppressing bell, green bronze and gold, sound waves blocking bad events"),
    ("phan_thien_kinh",            "Phản Thiên Kính",            "rare liar relic, blue rarity rim, mirror reflecting a beam backward, counter-effect and loss reduction"),
    ("doat_menh_phu",              "Đoạt Mệnh Phù",              "rare liar relic, blue rarity rim, red black fate-seizing talisman, destiny thread pulled and cut, high risk reward, no gore"),
    ("thien_menh_dong_xu",         "Thiên Mệnh Đồng Xu",         "rare liar relic, blue rarity rim, yin-yang fate coin, one gold side and one dark violet side, coin flip x2 or x0"),
    ("tam_ke_phu",                 "Tâm Kế Phù",                 "rare liar relic, blue rarity rim, strategy talisman with brain-like battle diagram, illusion strings trick opponent"),
    ("thien_co_nhan_chan_ban",     "Thiên Cơ Nhãn Chân Bản",     "super rare liar relic, gold rim with red glow, upgraded celestial eye, larger iris, multiple rune rings, powerful gold red aura"),
    ("tran_hon_chung_chan_ban",    "Trấn Hồn Chung Chân Bản",    "super rare liar relic, gold rim with red glow, heavy soul-suppressing bell, double sound wave layers, overwhelming power"),
    ("hu_khong_gioi_chan_ban",     "Hư Không Giới Chân Bản",     "super rare liar relic, gold rim with red glow, true space ring, deep portal, stars and void shards, stronger than common ring"),
    ("pha_vong_dong_tu_chan_ban",  "Phá Vọng Đồng Tử Chân Bản",  "super rare liar relic, gold rim with red glow, true illusion-breaking eye, gaze pierces many fog and card layers"),
    ("phan_thien_kinh_chan_ban",   "Phản Thiên Kính Chân Bản",   "super rare liar relic, gold rim with red glow, true heaven-reflecting mirror, cracked luminous surface, strong beam reflection"),
]

_RELICS_THREE_CARD_TEMP = [
    ("dinh_tam_dan",              "Định Tâm Đan",              "common three-card relic, pale white rarity rim, white light blue elixir pill, calm qi waves, stabilizes after loss"),
    ("ho_menh_phu",               "Hộ Mệnh Phù",               "common three-card relic, pale white rarity rim, guardian talisman with small glowing shield, white gold protection"),
    ("tu_linh_bai_phu",           "Tụ Linh Bài Phù",           "common three-card relic, pale white rarity rim, talisman gathering spiritual particles into three small cards, showdown reward"),
    ("van_tam_kinh",              "Vấn Tâm Kính",              "common three-card relic, pale white rarity rim, small heart-questioning mirror showing opponent aura, three-card glyph"),
    ("hu_khong_gioi",             "Hư Không Giới",             "common three-card relic, pale white rarity rim, void ring with small portal hiding personal card label, three-card glyph"),
    ("thien_van_phu",             "Thiên Vận Phù",             "common three-card relic, pale white rarity rim, pale yellow lucky talisman, refund luck after losing call, three-card glyph"),
    ("tinh_tam_huong",            "Tĩnh Tâm Hương",            "common three-card relic, pale white rarity rim, calming incense stick, blue white smoke soothing inner demon after big loss"),
    ("thien_co_kinh",             "Thiên Cơ Kính",             "rare three-card relic, red rarity rim, divination mirror reflecting three small cards, opponent stat reading"),
    ("ma_tam_an",                 "Ma Tâm Ấn",                 "rare three-card relic, red rarity rim, black red demonic-heart seal, purple red glow, pressure to force fold"),
    ("thien_nhan_phu",            "Thiên Nhãn Phù",            "rare three-card relic, red rarity rim, talisman with heavenly eye, gold white glow, bonus after winning showdown"),
    ("phan_thien_giap",           "Phản Thiên Giáp",           "rare three-card relic, red rarity rim, reflective armor shard or shield, countering bad beat, red gold"),
    ("doat_menh_phu",             "Đoạt Mệnh Phù",             "rare three-card relic, red rarity rim, red black fate-seizing talisman, destiny pull, stronger next raise"),
    ("huyet_chien_lenh",          "Huyết Chiến Lệnh",          "rare three-card relic, red rarity rim, red command token, red fire tassels, all-in battle energy"),
    ("thien_menh_dong_xu",        "Thiên Mệnh Đồng Xu",        "rare three-card relic, red rarity rim, yin-yang fate coin, coin flip x2 or x0, three-card glyph"),
    ("thien_co_kinh_chan_ban",    "Thiên Cơ Kính Chân Bản",    "super rare three-card relic, black rim with purple glow, true divination mirror, layered runes, violet gold advanced stats"),
    ("phan_thien_giap_chan_ban",  "Phản Thiên Giáp Chân Bản",  "super rare three-card relic, black rim with purple glow, true reflective armor, black gold violet, strong bad beat defense"),
    ("doat_menh_phu_chan_ban",    "Đoạt Mệnh Phù Chân Bản",    "super rare three-card relic, black rim with purple glow, true fate-seizing talisman, fate ring bent, red black violet"),
    ("huyet_chien_lenh_chan_ban", "Huyết Chiến Lệnh Chân Bản", "super rare three-card relic, black rim with purple glow, true blood battle command token, red black, violet red flames"),
    ("thien_van_chan_phu",        "Thiên Vận Chân Phụ",        "super rare three-card relic, black rim with purple glow, high-grade heavenly luck talisman, white gold, many bright clouds and runes"),
]


def _build_relic_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    common_rules = (
        "isolated single object, transparent background, alpha channel, no scenery",
        "centered composition, soft rim glow, premium game inventory icon style",
        "high detail, polished texture, sharp readable silhouette",
    )
    # B1. Permanent
    for code, title_vi, desc in _RELICS_PERMANENT:
        items.append(ArtItem(
            code=code,
            title_vi=title_vi,
            desc=f"chinese-fantasy magical treasure relic icon, {desc}",
            size=(256, 256),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/relics/{code}",
            group="B. Relics",
            subgroup="B1. Permanent",
            style_hint="game relic icon",
            extra_rules=common_rules,
            priority="P0",
        ))
    # B2. Liar temp
    for code, title_vi, desc in _RELICS_LIAR_TEMP:
        items.append(ArtItem(
            code=code,
            title_vi=title_vi,
            desc=f"chinese-fantasy temporary liar-game relic icon, {desc}",
            size=(256, 256),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/relics_liar_temp/{code}",
            group="B. Relics",
            subgroup="B2. Liar temp",
            style_hint="game relic icon",
            extra_rules=common_rules,
            priority="P1",
        ))
    # B3. Three-card temp
    for code, title_vi, desc in _RELICS_THREE_CARD_TEMP:
        items.append(ArtItem(
            code=code,
            title_vi=title_vi,
            desc=f"chinese-fantasy temporary three-card-game relic icon, {desc}",
            size=(256, 256),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/relics_three_card_temp/{code}",
            group="B. Relics",
            subgroup="B3. Three-card temp",
            style_hint="game relic icon",
            extra_rules=common_rules,
            priority="P1",
        ))
    return items


# =====================================================================
# C. AVATAR FRAME  (11)
# =====================================================================

_FRAMES = [
    ("frame_phamnhan",  "Phàm Nhân",   "plain stone gray frame, simple chamfer", "gray"),
    ("frame_luyenkhi",  "Luyện Khí",   "light blue frame, faint qi mist",        "light blue"),
    ("frame_trucco",    "Trúc Cơ",     "jade green frame, bamboo etching",       "jade green"),
    ("frame_kimdan",    "Kim Đan",     "gold frame, sun rune at corners",        "gold"),
    ("frame_nguyenanh", "Nguyên Anh",  "soft purple frame, ghost-baby motif",    "soft purple"),
    ("frame_hoathan",   "Hóa Thần",    "deep purple frame, divine sigils",       "deep purple"),
    ("frame_luyenhu",   "Luyện Hư",    "orange frame, void cracks",              "orange"),
    ("frame_hopthe",    "Hợp Thể",     "red frame, dual-yin-yang corners",       "red"),
    ("frame_daithua",   "Đại Thừa",    "deep pink frame, lotus throne details",  "deep pink"),
    ("frame_dokiep",    "Độ Kiếp",     "white-gold frame, lightning bolts",      "white gold"),
    ("frame_tiennhan",  "Tiên Nhân",   "celestial gold frame, immortal halo",    "celestial gold"),
]


def _build_frame_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc, palette in _FRAMES:
        items.append(ArtItem(
            code=code,
            title_vi=f"Khung – {title_vi}",
            desc=f"square avatar border frame, {desc}, palette {palette}, "
                 "ornate chinese-fantasy ornament, hollow center for avatar",
            size=(256, 256),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/Frames/{code}",
            group="C. Frame",
            subgroup="Avatar frame",
            style_hint="UI border frame",
            extra_rules=(
                "AVATAR FRAME: square ornament BORDER ONLY",
                "the CENTER must be fully transparent (alpha=0), border ~32px thick",
                "no portrait inside, no character, only the decorative ring",
                "transparent background, alpha channel, isolated frame only",
                "symmetric, clean readable shape at 256px",
            ),
            priority="P0",
        ))
    return items


# =====================================================================
# D. UI BUTTON  (6)
# =====================================================================

_UI_BUTTONS = [
    ("btn_settings",  "Nút Cài đặt",     "gear icon button, neutral gray panel"),
    ("btn_chat",      "Nút Chat",        "speech bubble icon button"),
    ("btn_back",      "Nút Quay lại",    "arrow-back icon button"),
    ("btn_close",     "Nút Đóng",        "X close icon button"),
    ("btn_play",      "Nút Vào trận",    "play triangle primary button, vibrant blue"),
    ("btn_secondary", "Nút Phụ",         "blank secondary button, soft gray"),
]


def _build_ui_button_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _UI_BUTTONS:
        items.append(ArtItem(
            code=code,
            title_vi=title_vi,
            desc=f"square game UI button, {desc}, soft round corners, subtle inner shadow",
            size=(128, 128),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/UI/{code}",
            group="D. UI Button",
            subgroup="Common",
            style_hint="game UI button",
            extra_rules=(
                "single button only, transparent background, alpha channel",
                "centered icon, clean readable at 128px",
                "no text, no extra decoration outside the button",
            ),
            priority="P1",
        ))
    return items


# =====================================================================
# E. ICON  (10 lobby + 4 currency)
# =====================================================================

_LOBBY_ICONS = [
    ("icon_match",    "Vào trận",      "crossed swords icon, golden frame"),
    ("icon_daily",    "Điểm danh",     "calendar with check mark icon"),
    ("icon_quest",    "Nhiệm vụ",      "scroll quest icon, red ribbon"),
    ("icon_shop",     "Cửa hàng",      "treasure chest shop icon"),
    ("icon_gacha",    "Quay thưởng",   "lucky wheel / lantern gacha icon"),
    ("icon_avatar",   "Nhân vật",      "silhouette avatar icon"),
    ("icon_friends",  "Bạn bè",        "two-people friend icon"),
    ("icon_invite",   "Mời bạn",       "envelope invite icon"),
    ("icon_settings", "Cài đặt",       "gear settings icon"),
    ("icon_relic",    "Bảo vật",       "small gourd relic icon"),
]


def _build_lobby_icon_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _LOBBY_ICONS:
        items.append(ArtItem(
            code=code,
            title_vi=f"Lobby – {title_vi}",
            desc=f"flat clean game lobby icon, {desc}, chinese-fantasy palette, "
                 "centered, strong silhouette",
            size=(128, 128),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/lobby/{code}",
            group="E. Icon",
            subgroup="E1. Lobby",
            style_hint="lobby icon",
            extra_rules=(
                "single icon only, transparent background, alpha channel",
                "no text, readable at 64px thumbnail",
            ),
            priority="P0",
        ))
    return items


_CURRENCY_ICONS = [
    ("icon_tu_vi",            "Tu Vi (lớn)",         "golden spirit-stone coin, glowing core",       (128, 128)),
    ("icon_than_nguyen",      "Thần Nguyên (lớn)",   "purple diamond gem, faceted shine",            (128, 128)),
    ("icon_tu_vi_small",      "Tu Vi (nhỏ)",         "golden spirit-stone coin, glowing core",       (32, 32)),
    ("icon_than_nguyen_small","Thần Nguyên (nhỏ)",   "purple diamond gem, faceted shine",            (32, 32)),
]


def _build_currency_icon_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc, size in _CURRENCY_ICONS:
        items.append(ArtItem(
            code=code,
            title_vi=f"Tiền – {title_vi}",
            desc=f"flat clean game currency icon, {desc}, glossy material, "
                 "centered, strong silhouette",
            size=size,
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/currency/{code}",
            group="E. Icon",
            subgroup="E2. Currency",
            style_hint="currency icon",
            extra_rules=(
                "single currency icon only, transparent background, alpha channel",
                "no text, no extra object, readable as small thumbnail",
            ),
            priority="P0",
        ))
    return items


# =====================================================================
# F. BACKGROUND  (5 missing)
# =====================================================================

_BACKGROUNDS = [
    ("modeselect_bg", "Chọn chế độ",
        "split-screen mode-select background, left side liar/deception (purple smoke), "
        "right side holdem/three-card (gold light), center mystic divider"),
    ("gacha_bg",      "Banner gacha",
        "gacha banner background, flying stars, cherry blossoms, lantern lights, "
        "celestial palette purple gold, magical sparkle"),
    ("shop_bg",       "Cửa hàng",
        "ancient chinese fantasy shop interior background, treasure shelves, "
        "warm lantern glow, jade displays, cozy atmosphere"),
    ("result_win_bg", "Kết quả - Thắng",
        "victory result background, golden fireworks, buddha silhouette in clouds, "
        "celebrating mood, warm gold tones"),
    ("result_lose_bg","Kết quả - Thua",
        "defeat result background, dark rainy night, cracked stone temple, "
        "dim blue tones, melancholic mood"),
]


def _build_background_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _BACKGROUNDS:
        items.append(ArtItem(
            code=code,
            title_vi=f"Background – {title_vi}",
            desc=f"full-hd 1920x1080 game scene background, {desc}, "
                 "no characters, no foreground subject, leave space for UI overlay",
            size=(1920, 1080),
            aspect="16:9",
            transparent=False,
            relpath=f"Resources/Backgrounds/{code}",
            group="F. Background",
            subgroup="Scene",
            style_hint="environment art",
            extra_rules=(
                "wide cinematic background scene, no main character",
                "edges should not contain critical detail (will be overlaid)",
                "high detail, painterly, chinese-fantasy aesthetic",
            ),
            priority="P1",
        ))
    return items


# =====================================================================
# G. VFX  (8)
# =====================================================================

_VFX = [
    ("vfx_aura_light",      "Aura sáng (sheet 8x8)",
        "spritesheet of glowing light aura around character, 8x8 grid of frames, "
        "concentric soft halo, animation cycle"),
    ("vfx_thunder",         "Lôi kiếp (sheet 4)",
        "spritesheet of lightning bolts, 4 horizontal frames, blue-white electric arcs"),
    ("vfx_phoenix",         "Phượng hoàng",
        "single frame of fire phoenix flying upward, red-orange flames, victory effect"),
    ("vfx_chu_chao",        "Chu chảo all-in",
        "single frame of swirling magical pot/cauldron with golden runes, all-in moment"),
    ("hit_explosion",       "Nổ trúng",
        "single frame of small comic-style explosion burst, yellow-red burst lines"),
    ("sparkle_win",         "Sparkle thắng",
        "single frame of celebratory sparkle stars and confetti glitter, gold tones"),
    ("thunder_tribulation", "Sét lôi kiếp (sheet 4)",
        "spritesheet of large divine tribulation lightning, 4 frames, dramatic sky bolt"),
    ("particle_chip",       "Chip nhỏ",
        "single small game chip / coin token, glossy red with gold edge, isolated"),
]


def _build_vfx_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _VFX:
        sheet = "sheet" in title_vi.lower()
        size = (1024, 1024) if sheet else (512, 512)
        aspect = "1:1"
        items.append(ArtItem(
            code=code,
            title_vi=f"VFX – {title_vi}",
            desc=f"game VFX sprite, {desc}, on transparent background, particle art",
            size=size,
            aspect=aspect,
            transparent=True,
            relpath=f"Resources/effects/{code}",
            group="G. VFX",
            subgroup="Particle",
            style_hint="vfx sprite",
            extra_rules=(
                "transparent background, alpha channel, isolated effect",
                "no character, no scenery",
                "high contrast, glow + crisp edges",
                ("uniform grid of frames, equal cell size, no labels" if sheet else "single frame only"),
            ),
            priority="P1",
        ))
    return items


# =====================================================================
# H-K. SYSTEM SUPPLEMENT 2026-05-28  (65)
# =====================================================================

_SYSTEM_BACKGROUNDS_20260528 = [
    ("achievement_bg", "Thành Tựu", "nền Thành Tựu: đại sảnh bia công đức/kim bảng trong thế giới tu tiên, huy chương và phù văn mờ ở xa, ánh vàng xanh trang trọng, vùng giữa tối nhẹ và ít chi tiết để đặt danh sách achievement, không chữ, không UI"),
    ("battle_pass_bg", "Battle Pass", "nền Battle Pass mùa: con đường tu luyện kéo dài qua nhiều mốc thưởng phát sáng, linh khí xanh-vàng hồi phục, cảm giác season pass, rương thưởng mờ hai bên, chừa giữa sạch, không chữ, không UI"),
    ("inventory_bg", "Túi Đồ", "nền Túi Đồ: kho pháp khí/đan phòng tu tiên, kệ đan dược, túi càn khôn, bình ngọc và pháp bảo đặt hai bên, ánh sáng ấm, trung tâm sạch cho list vật phẩm, không chữ"),
    ("mail_bg", "Hộp Thư", "nền Hộp Thư: bàn thư tiên môn, phong thư phù, hạc giấy bay nhẹ, ấn sáp phát sáng, tone xanh-vàng, vùng giữa tối nhẹ để đọc thư, không chữ"),
    ("chat_bg", "Chat", "nền Chat: quán trà tu tiên/hội quán trò chuyện, bàn trà, đèn lồng, bóng đạo hữu mờ phía xa, vibe xã giao ấm áp, chừa vùng giữa cho khung chat, không chữ"),
    ("friends_bg", "Bạn Bè", "nền Bạn Bè: sân tông môn có bảng danh hữu, cổng môn phái, đèn lồng, lệnh bài kết giao, không khí thân thiện, chừa giữa sạch, không chữ"),
    ("lobby_browser_bg", "Danh Sách Phòng", "nền Danh Sách Phòng: quán đấu bài/bảng nhiệm vụ với nhiều thẻ phòng treo hai bên, bàn đấu mờ phía sau, vùng giữa tối nhẹ cho room list, không chữ"),
    ("hand_history_bg", "Lịch Sử Ván", "nền Lịch Sử Ván: cuộn trúc ghi chiến tích, bàn bài mờ, dấu thắng thua như ấn ký, ánh vàng cổ, trung tâm sạch, không chữ"),
    ("settings_bg", "Cài Đặt", "nền Cài Đặt: phòng điều khiển pháp trận âm thanh/ngôn ngữ, tinh thạch điều âm, bảng phù đơn giản, tone tối sạch, ít chi tiết, không chữ"),
    ("tutorial_bg", "Tutorial", "nền Tutorial nhập môn: tranh cuộn mở ra mô tả hành trình từ sảnh đến bàn đấu, style tu tiên thân thiện, không ghi chữ vì game sẽ đặt text"),
    ("tribulation_bg", "Độ Kiếp", "nền Độ Kiếp: đỉnh núi lôi kiếp, mây đen, cột sét, vòng pháp trận dưới chân, ánh tím xanh vàng, chừa giữa cho overlay xác suất/cost, không chữ"),
    ("quickmatch_bg", "Ghép Trận Nhanh", "nền Ghép Trận Nhanh: cổng dịch chuyển tìm đối thủ, hai luồng bài Holdem và Bài Nói Dối xoáy vào bàn đấu, cảm giác matchmaking, không chữ"),
    ("create_room_bg", "Tạo Phòng", "nền Tạo Phòng: bàn chủ phòng, ghế trống quanh bàn, ngọc giản cấu hình phòng, ánh sáng tông môn, không chữ"),
    ("private_room_bg", "Phòng Riêng", "nền Phòng Riêng: cửa mật thất có khóa phù, 6 ô mã phòng dạng ký hiệu trừu tượng không phải chữ thật, ánh sáng mời bạn, không UI text"),
    ("daily_bg", "Điểm Danh", "nền Điểm Danh: lịch tháng tu tiên, rương mốc 7/14/21/28/30 đặt hai bên, ánh vàng dịu, chừa giữa cho calendar grid, không chữ"),
    ("quest_bg", "Nhiệm Vụ", "nền Nhiệm Vụ: bảng nhiệm vụ tông môn, giấy nhiệm vụ treo, bút lông, ấn nhiệm vụ, vibe phiêu lưu hằng ngày, không chữ"),
]

_SYSTEM_LOBBY_ICONS_20260528 = [
    ("icon_achievement", "Thành Tựu", "cúp/kim bảng công đức kết hợp phù văn, màu vàng xanh, rõ ở 64px"),
    ("icon_battle_pass", "Battle Pass", "vé mùa/cuộn lệnh bài vàng, có mốc thưởng nhỏ và hào quang premium"),
    ("icon_inventory", "Túi Đồ", "túi càn khôn mở, lộ đan dược và pháp khí, viền sáng"),
    ("icon_mail", "Hộp Thư", "phong thư/hạc giấy có ấn phù và chấm thông báo đỏ nhỏ"),
    ("icon_chat", "Chat", "bong bóng hội thoại kết hợp phù văn thoại, thân thiện, dễ đọc"),
    ("icon_history", "Lịch Sử Ván", "cuộn trúc ghi log trận, có dấu thắng thua nhỏ, không chữ"),
    ("icon_room_browser", "Danh Sách Phòng", "bảng phòng đấu với nhiều thẻ phòng nhỏ và bàn bài phía sau"),
    ("icon_prestige", "Độ Kiếp", "người tu luyện đứng dưới tia sét, pháp trận tròn, màu tím xanh vàng"),
    ("icon_event", "Sự Kiện", "cổng event tu tiên mở ra, sao/phù chú bùng sáng, không chữ"),
    ("icon_leaderboard", "Bảng Xếp Hạng", "bục top 1/2/3 và kim bảng vàng, không ghi số/chữ rõ"),
]

_ACHIEVEMENT_CATEGORY_ICONS_20260528 = [
    ("cat_combat", "Nhóm Chiến Đấu", "kiếm, lá bài và tia đỏ, cảm giác combat thắng trận", (512, 512)),
    ("cat_progression", "Nhóm Tiến Cảnh", "bậc thang tu luyện lên núi/cảnh giới, xanh ngọc và vàng", (512, 512)),
    ("cat_collection", "Nhóm Sưu Tầm", "rương mở có pháp bảo và mảnh nhân vật, màu tím vàng", (512, 512)),
    ("cat_social", "Nhóm Xã Hội", "hai đạo hữu/lệnh bài kết bạn, vòng sáng liên kết", (512, 512)),
    ("tier_bronze", "Huy hiệu Đồng", "medal đồng, viền rõ, không chữ", (256, 256)),
    ("tier_silver", "Huy hiệu Bạc", "medal bạc, ánh lạnh, không chữ", (256, 256)),
    ("tier_gold", "Huy hiệu Vàng", "medal vàng sáng, không chữ", (256, 256)),
    ("tier_diamond", "Huy hiệu Kim Cương", "medal xanh kim cương cực hiếm, không chữ", (256, 256)),
]

_ACHIEVEMENT_ICONS_20260528 = [
    ("ach_first_blood", "Khai Chiến Đầu Tiên", "lá bài thắng đầu tiên, vệt kiếm sáng, cúp nhỏ đồng"),
    ("ach_win_50", "Thắng 50 Ván", "nhiều lá bài xoay quanh cúp bạc, không ghi số chữ rõ"),
    ("ach_win_500", "Chiến Thần 500 Ván", "cúp vàng lớn, hào quang chiến trận, cảm giác cực mạnh"),
    ("ach_allin_10", "Tất Tay 10 Lần Thắng", "đống chip/Tu Vi đẩy vào bàn, lửa đỏ, năng lượng mạo hiểm"),
    ("ach_bluff_50", "Nói Dối Thành Công", "mặt nạ cười, lá bài giấu sau tay, khói tím tinh quái"),
    ("ach_bigpot_100k", "Đại Pot", "núi Tu Vi/chip lớn bung sáng, cảm giác jackpot"),
    ("ach_level_10", "Cấp 10", "bậc thang tu luyện thấp, linh khí mới bùng lên"),
    ("ach_level_50", "Cấp 50", "pháp trận lớn, tinh thạch cấp trung, hào quang xanh vàng"),
    ("ach_level_100", "Cấp 100", "tiên quang đỉnh cấp, cột sáng vàng trắng, biểu tượng cực hiếm"),
    ("ach_tribulation_kim_dan", "Độ Kiếp Kim Đan", "kim đan vàng phát sáng trong lôi vân, sét nhẹ xung quanh"),
    ("ach_tribulation_hop_the", "Độ Kiếp Hợp Thể", "thân ảnh hợp nhất với pháp tướng, hào quang lớn"),
    ("ach_unlock_4_chars", "Mở 4 Nhân Vật", "bốn bóng nhân vật sáng dần, mảnh nhân vật bay quanh"),
    ("ach_unlock_all_chars", "Mở Tất Cả Nhân Vật", "tám chân dung mini trừu tượng quanh hào quang, không quá chi tiết"),
    ("ach_first_5star", "Nhân Vật 5 Sao Đầu", "chân dung sáng với năm sao vàng bay quanh"),
    ("ach_relic_max_3", "3 Bảo Vật Tối Đa", "ba pháp bảo xoay quanh pháp trận max level, ánh vàng"),
    ("ach_login_7", "Đăng Nhập 7 Ngày", "lịch tuần có dấu check, ngọn lửa streak xanh vàng"),
    ("ach_login_30", "Đăng Nhập 30 Ngày", "lịch tháng hoàn chỉnh, rương vàng, ánh thưởng lớn"),
    ("ach_friend_5", "Kết Giao 5 Bạn", "nhóm lệnh bài bạn bè, năm điểm sáng nối nhau"),
    ("ach_top10_weekly", "Top 10 Tuần", "kim bảng xếp hạng, vòng nguyệt quế, bục danh vọng"),
]

_QUEST_ICONS_20260528 = [
    ("quest_d_win_2", "Ngày Thắng 2 Ván", "hai lá bài chiến thắng, cúp nhỏ, ánh xanh daily"),
    ("quest_d_win_holdem_1", "Thắng Holdem 1 Ván", "hai lá tẩy poker, chip/Tu Vi, cúp xanh"),
    ("quest_d_win_liar_1", "Thắng Bài Nói Dối 1 Ván", "bài úp, mặt nạ nói dối, cờ thắng nhỏ"),
    ("quest_d_allin_1", "Tất Tay 1 Lần", "chip/Tu Vi đẩy vào giữa bàn, lửa đỏ all-in"),
    ("quest_d_bluff_2", "Lừa Thành Công 2 Lần", "mặt nạ tím, hai lá bài ẩn, khói tinh quái"),
    ("quest_d_ads_5", "Xem 5 Quảng Cáo", "pháp kính/linh kính nhận thưởng, tia sáng, không logo quảng cáo thật"),
    ("quest_d_bigpot_1", "Thắng Pot Lớn", "rương Tu Vi lớn bung sáng, chip bay ra"),
    ("quest_d_challenge_2", "Tố Đúng 2 Lần", "lá bài bị lật, ngón tay chỉ phá lời nói dối, tia sáng"),
    ("quest_w_win_15", "Tuần Thắng 15 Ván", "cúp lớn, nhiều lá bài xếp thành vòng chiến thắng, màu vàng xanh"),
    ("quest_w_win_holdem_8", "Tuần Thắng Holdem 8", "bàn poker nhỏ, lá tẩy và cúp, ánh xanh dương"),
    ("quest_w_win_liar_8", "Tuần Thắng Liar 8", "bàn bài nói dối, mặt nạ và cờ thắng, ánh tím"),
    ("quest_w_bluff_10", "Tuần Lừa 10 Lần", "mặt nạ vàng tím, nhiều lá bài bay, cảm giác bậc thầy bluff"),
]

def _supplement_icon_rules() -> tuple[str, ...]:
    return (
        "transparent background, alpha channel, centered object, no scenery",
        "thick clean outline, high contrast, readable at 64px",
        "no text, no logo, no watermark, no UI button mockup",
    )

def _build_system_supplement_20260528_items() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, title_vi, desc in _SYSTEM_BACKGROUNDS_20260528:
        items.append(ArtItem(
            code=code,
            title_vi=f"System BG - {title_vi}",
            desc=f"full-screen 16:9 mobile game background, {desc}",
            size=(1920, 1080),
            aspect="16:9",
            transparent=False,
            relpath=f"Resources/Backgrounds/{code}",
            group="H. System 2026-05-28",
            subgroup="H1. Backgrounds",
            style_hint="2D cultivation fantasy poker background",
            extra_rules=(
                "not transparent, opaque full-screen background",
                "leave the center clean enough for UI panels",
                "no text, no readable symbols, no logo, no UI controls",
            ),
            priority="P0",
        ))
    for code, title_vi, desc in _SYSTEM_LOBBY_ICONS_20260528:
        items.append(ArtItem(
            code=code,
            title_vi=f"Lobby Icon - {title_vi}",
            desc=f"system lobby feature icon, {desc}",
            size=(512, 512),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/lobby/{code}",
            group="H. System 2026-05-28",
            subgroup="H2. Lobby icons",
            style_hint="2D polished mobile game icon",
            extra_rules=_supplement_icon_rules(),
            priority="P0",
        ))
    for code, title_vi, desc, size in _ACHIEVEMENT_CATEGORY_ICONS_20260528:
        items.append(ArtItem(
            code=code,
            title_vi=f"Achievement - {title_vi}",
            desc=f"achievement category or tier badge icon, {desc}",
            size=size,
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/achievements/{code}",
            group="J. Achievements 2026-05-28",
            subgroup="J1. Category and tier",
            style_hint="2D polished achievement badge icon",
            extra_rules=_supplement_icon_rules(),
            priority="P0",
        ))
    for code, title_vi, desc in _ACHIEVEMENT_ICONS_20260528:
        items.append(ArtItem(
            code=code,
            title_vi=f"Achievement - {title_vi}",
            desc=f"individual achievement icon, {desc}",
            size=(512, 512),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/achievements/{code}",
            group="J. Achievements 2026-05-28",
            subgroup="J2. Achievement icons",
            style_hint="2D polished achievement badge icon",
            extra_rules=_supplement_icon_rules(),
            priority="P0",
        ))
    for code, title_vi, desc in _QUEST_ICONS_20260528:
        items.append(ArtItem(
            code=code,
            title_vi=f"Quest - {title_vi}",
            desc=f"quest reward/task icon, {desc}",
            size=(512, 512),
            aspect="1:1",
            transparent=True,
            relpath=f"Resources/icons/quests/{code}",
            group="K. Quest 2026-05-28",
            subgroup="K1. Daily and weekly quest icons",
            style_hint="2D polished mobile game quest icon",
            extra_rules=_supplement_icon_rules(),
            priority="P0",
        ))
    return items


# =====================================================================
# Build full catalog
# =====================================================================

CATALOG: list[ArtItem] = (
    _build_character_items()
    + _build_relic_items()
    + _build_frame_items()
    + _build_ui_button_items()
    + _build_lobby_icon_items()
    + _build_currency_icon_items()
    + _build_background_items()
    + _build_vfx_items()
    + _build_system_supplement_20260528_items()
)


GROUP_ORDER = [
    "A. Character",
    "B. Relics",
    "C. Frame",
    "D. UI Button",
    "E. Icon",
    "F. Background",
    "G. VFX",
    "H. System 2026-05-28",
    "J. Achievements 2026-05-28",
    "K. Quest 2026-05-28",
]


def items_by_group() -> dict[str, list[ArtItem]]:
    result: dict[str, list[ArtItem]] = {g: [] for g in GROUP_ORDER}
    for item in CATALOG:
        result.setdefault(item.group, []).append(item)
    return result


def find_by_code(code: str) -> ArtItem | None:
    for item in CATALOG:
        if item.code == code:
            return item
    return None


def stats() -> dict[str, int]:
    by_group: dict[str, int] = {}
    for item in CATALOG:
        by_group[item.group] = by_group.get(item.group, 0) + 1
    return by_group


# =====================================================================
# Merge catalog TuTien5 (checklist 2026-06-06) để app vẽ chung 1 pipeline.
# TuTien5 item có relpath bắt đầu bằng "Assets/Resources/..." nên dễ phân biệt
# với item gốc ("Resources/..."). Các preset "vẽ toàn bộ" của TuTien2/3/4 sẽ
# loại trừ nhóm này (xử lý ở tutienco_art_workflow).
# =====================================================================
try:
    from tutien5_art_catalog import CATALOG as _TUTIEN5_CATALOG, GROUP_ORDER as _TUTIEN5_GROUP_ORDER

    CATALOG = CATALOG + list(_TUTIEN5_CATALOG)
    GROUP_ORDER = GROUP_ORDER + [g for g in _TUTIEN5_GROUP_ORDER if g not in GROUP_ORDER]
except Exception:  # pragma: no cover - nếu thiếu file vẫn chạy catalog gốc
    pass
