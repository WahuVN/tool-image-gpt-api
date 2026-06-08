"""Catalog art còn thiếu cho Tu Tiên Cờ — nguồn: ART-DANH-SACH-VE-HET-2026-06-06.md.

Xuất ra D:\\TOOL\\TOOL Anh\\TuTien5\\<relpath>.png (relpath đã gồm Assets/Resources/...).

Tái dùng dataclass ArtItem + toàn bộ workflow chroma/alpha của tutienco_art_*.
- transparent=True  -> vẽ trên nền chroma (hồng) rồi tách alpha PNG.
- transparent=False -> banner/nền opaque, không tách nền.

Nhóm:
  A.  Skin UI + FX (trắng/xám tint được, nền trong suốt, 9-slice set trong Unity)
  B1..B13  Art nội dung cho từng màn
  C.  Bổ sung / sprite sheet / redo background
"""

from __future__ import annotations

from tutienco_art_catalog import ArtItem  # reuse dataclass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUPPORTED_ASPECTS: dict[str, float] = {
    "1:1": 1.0,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:5": 0.8,
    "5:4": 1.25,
    "3:2": 1.5,
    "2:3": 2 / 3,
    "21:9": 21 / 9,
}


def _aspect(size: tuple[int, int]) -> str:
    """Chọn aspect ratio hỗ trợ gần nhất với size mục tiêu (resize local sẽ pad/fit)."""
    width, height = size
    ratio = width / height
    return min(_SUPPORTED_ASPECTS, key=lambda key: abs(_SUPPORTED_ASPECTS[key] - ratio))


STYLE = (
    "polished cartoon / semi-chibi 2D fantasy cultivation (tu tien) mobile game art, "
    "clean lines, clean colors, high contrast, readable when small"
)

# Nền trong suốt cho icon/vật phẩm.
ICON_RULES: tuple[str, ...] = (
    "single main object centered, transparent background, alpha channel, no scenery",
    "soft rim light, polished texture, sharp readable silhouette",
    "no text, no logo, no watermark, no UI mockup",
)

# Skin UI trắng/xám để code tự tô màu (tint).
SKIN_RULES: tuple[str, ...] = (
    "WHITE / NEUTRAL GRAY only so the engine can tint it any color later",
    "single UI element centered, transparent background, alpha channel",
    "subtle bevel: lighter top sheen and soft bottom shadow, thin inner rim",
    "symmetric, flat, clean edges, no text, no logo, no colored accent",
)

# Hiệu ứng/overlay (glow, sparkle...).
FX_RULES: tuple[str, ...] = (
    "isolated glowing effect, transparent background, alpha channel, no scenery",
    "high contrast, crisp glow, no character, no object behind it",
    "no text, no logo, no watermark",
)

# Sprite sheet nhiều frame đều nhau.
SHEET_RULES: tuple[str, ...] = (
    "uniform grid of equal-size animation frames left to right, transparent background",
    "alpha channel, isolated effect, no character, no scenery, no labels",
    "high contrast glow with crisp edges, no text, no watermark",
)

# Banner / nền opaque (không trong suốt).
BANNER_RULES: tuple[str, ...] = (
    "opaque full background, do NOT make it transparent",
    "leave the central area clean for UI overlay",
    "no text, no readable symbols, no logo, no UI controls",
)


def _item(
    code: str,
    reldir: str,
    size: tuple[int, int],
    desc: str,
    group: str,
    subgroup: str,
    *,
    transparent: bool = True,
    rules: tuple[str, ...] = ICON_RULES,
    style: str = STYLE,
    priority: str = "P1",
    title: str | None = None,
) -> ArtItem:
    return ArtItem(
        code=code,
        title_vi=title or code,
        desc=desc,
        size=size,
        aspect=_aspect(size),
        transparent=transparent,
        relpath=f"{reldir}/{code}",
        group=group,
        subgroup=subgroup,
        style_hint=style,
        extra_rules=rules,
        priority=priority,
    )


# =====================================================================
# NHÓM A — SKIN GIAO DIỆN + FX  (trắng/xám, nền trong suốt, 9-slice)
# =====================================================================

_GROUP_A = "A. Skin UI + FX"

# (code, size, desc)
_SKIN = [
    ("btn_primary", (256, 128), "rounded-rectangle button body R~18, slightly convex face with top sheen and soft bottom shadow, thin glowing inner rim"),
    ("btn_secondary", (256, 128), "rounded-rectangle button body like primary but flatter, lighter relief"),
    ("btn_icon", (128, 128), "square soft-rounded button R~28%, gently raised face"),
    ("panel_main", (256, 256), "frosted glass panel R~26, thin glowing inner border"),
    ("panel_glass", (192, 192), "clearer glass panel R~26, soft light streak near the top"),
    ("card", (192, 192), "rounded card R~18, top sheen and inner bevel (light top edge, dark bottom)"),
    ("pill", (240, 96), "fully rounded pill (R = half height), thin inner rim, currency chip frame"),
    ("tab_on", (200, 96), "tab with raised relief face, active state look"),
    ("tab_off", (200, 96), "flat dim tab, inactive state look"),
    ("progress_track", (64, 32), "horizontal progress bar groove, rounded, recessed dark channel"),
    ("progress_fill", (64, 32), "horizontal progress bar fill, glossy face with top highlight streak"),
    ("divider", (64, 8), "thin horizontal divider line fading out at both ends (alpha gradient)"),
    ("toggle_track", (128, 64), "on/off switch track, horizontal pill shaped groove"),
    ("toggle_knob", (64, 64), "round convex toggle knob, soft shadow"),
    ("slider_track", (64, 24), "horizontal slider groove, recessed channel"),
    ("slider_handle", (56, 56), "round slider handle with bright rim"),
    ("badge_dot", (64, 64), "round glowing notification disc (background for a number or !)"),
]

# (code, size, desc)
_FX = [
    ("glow_soft", (256, 256), "soft round radial glow fading to the edges, halo behind buttons/avatars/gems"),
    ("sparkle", (128, 128), "4-point sparkle star with a bright core"),
    ("ring_glow", (256, 256), "hollow glowing ring, empty transparent center, luminous border"),
    ("rune_circle", (512, 512), "concentric magic array (fa zhen) with evenly divided rune marks, intricate lines"),
    ("vignette", (1024, 1024), "transparent center darkening toward the four corners, cinematic depth overlay"),
    ("petal", (128, 128), "soft teardrop flower petal / drifting spirit-energy particle"),
    ("ornament_corner", (192, 192), "ornate cultivation-fantasy corner flourish for the TOP-LEFT corner (engine mirrors it to 4 corners)"),
]


def _build_group_a() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code, size, desc in _SKIN:
        items.append(_item(
            code, "Assets/Resources/UI/skin", size,
            f"UI skin element, {desc}",
            _GROUP_A, "A1. Skin", rules=SKIN_RULES, priority="P0",
        ))
    for code, size, desc in _FX:
        items.append(_item(
            code, "Assets/Resources/UI/fx", size,
            f"UI overlay effect, {desc}",
            _GROUP_A, "A2. FX", rules=FX_RULES, priority="P0",
        ))
    return items


# =====================================================================
# NHÓM B — ART NỘI DUNG CHO MÀN ĐANG VẼ PROCEDURAL
# =====================================================================

# ---- B1. Điểm Danh -----------------------------------------------------
_B1 = "B1. Daily"
_B1_ICONS = [
    ("day_claimed", (256, 256), "calendar cell already claimed: green check mark, soft glow"),
    ("day_today", (256, 256), "calendar cell for today: gold glowing ring marker, no text"),
    ("day_missed", (256, 256), "calendar cell missed: reddish-brown with a light crack, not gloomy"),
    ("day_upcoming", (256, 256), "calendar cell upcoming: light blue-gray lock, dim glow"),
    ("milestone_chest", (512, 512), "daily milestone chest 7/14/21/28/30, gold, spirit energy and reward tickets"),
    ("makeup_token", (512, 512), "make-up check-in token: a talisman turning a day back, blue-gold time ring"),
    ("ad_reward", (512, 512), "ad reward: magic mirror granting a reward plus spirit-energy rays, no brand logo"),
    ("streak_fire", (512, 512), "login streak flame: small gold-blue spirit-energy fire"),
]


def _build_b1() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/daily", s, d, _B1, "Icons", priority="P1")
        for c, s, d in _B1_ICONS
    ]
    items.append(_item(
        "monthly_calendar", "Assets/Resources/banners/daily", (1536, 640),
        "30-day monthly calendar banner with glowing milestone chests, no text",
        _B1, "Banner", transparent=False, rules=BANNER_RULES, priority="P1",
    ))
    return items


# ---- B2. Battle Pass ---------------------------------------------------
_B2 = "B2. Battle Pass"
_B2_ICONS = [
    ("pass_free", (512, 512), "free track ticket: silver/blue ticket, clean"),
    ("pass_premium", (512, 512), "premium track ticket: gold ticket, premium aura"),
    ("tier_locked", (256, 256), "locked tier: padlock over a node, gray-blue"),
    ("tier_claimable", (256, 256), "claimable tier: glowing blue-gold"),
    ("tier_claimed", (256, 256), "claimed tier: check mark / seal, no text"),
    ("exp_crystal", (512, 512), "EXP crystal: blue-gold crystal holding energy"),
    ("chest_free", (512, 512), "free chest: small silver chest, blue glow"),
    ("chest_premium", (512, 512), "premium chest: gold/purple chest, aura"),
    ("chest_final_50", (512, 512), "final tier-50 chest: large ultra-rare, diamonds, strong aura"),
    ("premium_lock", (256, 256), "premium lock: gold padlock over an unpurchased track"),
]


def _build_b2() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/battle_pass", s, d, _B2, "Icons", priority="P1")
        for c, s, d in _B2_ICONS
    ]
    items.append(_item(
        "season_01_linh_khi_khoi_phuc", "Assets/Resources/banners/battle_pass", (1536, 640),
        "Season 1 'Linh Khi Khoi Phuc' banner: reward path, chests, exp crystals, blue-gold spirit energy, no text",
        _B2, "Banner", transparent=False, rules=BANNER_RULES, priority="P1",
    ))
    return items


# ---- B3. Vật phẩm tiêu hao --------------------------------------------
_B3 = "B3. Consumables"
_B3_ITEMS = [
    ("hoi_tu_dan", "Hoi Tu Dan: jade-green pill, spirit-energy smoke"),
    ("dai_hoi_tu_dan", "Dai Hoi Tu Dan: larger pill, gold rim"),
    ("exp_dan", "Tu Luyen Dan: purple-blue EXP pill, experience sparks"),
    ("dai_exp_dan", "Dai Tu Luyen Dan: large EXP pill, strong glowing ring"),
    ("linh_khi_dan", "Linh Khi Dan: blue qi pill, round aura"),
    ("ho_tro_dan", "Ho Tro Dan: support pill, blue glow plus a small shield"),
    ("tha_tu_dan", "Tha Tu Dan: comeback pill, half red half gold, protective aura"),
    ("chong_cuong_dan", "Chong Cuong Dan: reduce all-in cost, red shield"),
    ("manh_vo_ngau_nhien", "Manh Vo Hon Don: multicolor crystal shard, purple-blue glow"),
    ("ve_gacha_thap", "Ve Gacha Thap: silver/blue gacha ticket with rune marks"),
]


def _build_b3() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/consumables", (512, 512), d, _B3, "Pills", priority="P1")
        for c, d in _B3_ITEMS
    ]


# ---- B4. Cosmetic Shop -------------------------------------------------
_B4 = "B4. Shop"
_B4_ITEMS = [
    ("cosmetic_premium_frame", "premium avatar frame: sparkling gold border, empty inside, no portrait"),
    ("cosmetic_card_skin", "cultivation card skin: a special playing card, gold-purple border"),
    ("cosmetic_rename_token", "rename token: command tablet plus brush and ink seal"),
    ("cosmetic_entrance_effect", "table entrance effect: glowing gateway / entrance path, star dust"),
]


def _build_b4() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/shop", (512, 512), d, _B4, "Cosmetic", priority="P1")
        for c, d in _B4_ITEMS
    ]


# ---- B5. Hộp Thư -------------------------------------------------------
_B5 = "B5. Mail"
_B5_ITEMS = [
    ("mail_system", (512, 512), "system mail: envelope with a system seal, blue-gold"),
    ("mail_admin", (512, 512), "admin mail: red/gold envelope with a compensation seal"),
    ("mail_friend_gift", (512, 512), "friend gift mail: letter with a gift box and ribbon"),
    ("mail_friend_request", (512, 512), "friend request mail: letter with two cultivator-friends symbol"),
    ("envelope_unread", (256, 256), "unread mail: closed envelope with a red dot"),
    ("envelope_read", (256, 256), "read mail: opened envelope, muted color"),
    ("reward_attachment", (256, 256), "reward attachment: gift / spirit-coin clipped on a letter"),
    ("mail_expired", (256, 256), "expired mail: gray letter with an hourglass"),
]


def _build_b5() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/mail", s, d, _B5, "Mail", priority="P1")
        for c, s, d in _B5_ITEMS
    ]


# ---- B6. Xã Hội --------------------------------------------------------
_B6 = "B6. Social"
_B6_ITEMS = [
    ("friend_online", "friend online: green dot / glowing cultivator"),
    ("friend_in_match", "friend in match: yellow dot plus a tiny card table"),
    ("friend_offline", "friend offline: gray dot"),
    ("request_incoming", "incoming request: arrow pointing in plus a person"),
    ("request_outgoing", "outgoing request: arrow pointing out plus a person"),
    ("blocked_user", "blocked user: a person plus a no-entry sign"),
]


def _build_b6() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/social", (256, 256), d, _B6, "Social", priority="P1")
        for c, d in _B6_ITEMS
    ]


# ---- B7. Chat & Thông báo ---------------------------------------------
_B7 = "B7. Chat & Notif"
_B7_CHAT = [
    ("world_chat", (512, 512), "world chat: chat bubble plus a cultivation globe"),
    ("room_chat", (512, 512), "room chat: chat bubble plus a small card table"),
    ("dm_chat", (512, 512), "direct message: chat bubble plus a privacy lock"),
    ("quick_voice", (512, 512), "quick chat / voice: chat bubble plus sound waves"),
    ("chat_bubble", (512, 512), "chat bubble over an avatar: soft bubble frame, cream light fill, clear outline"),
]
_B7_NOTIF = [
    ("badge_red_dot", (128, 128), "red notification dot with a bright rim"),
    ("badge_count_bg", (256, 256), "red circle with a bright rim, empty center for a number"),
]


def _build_b7() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/chat", s, d, _B7, "Chat", priority="P1")
        for c, s, d in _B7_CHAT
    ]
    items += [
        _item(c, "Assets/Resources/icons/notifications", s, d, _B7, "Notif", priority="P1")
        for c, s, d in _B7_NOTIF
    ]
    return items


# ---- B8. Phòng / Matchmaking ------------------------------------------
_B8 = "B8. Rooms"
_B8_COMMON = [
    ("mode_holdem", "Holdem mode: two poker cards plus chips/spirit coins, blue-gold"),
    ("mode_liar", "Liar mode: face-down cards plus a mask, purple smoke"),
    ("quick_match", "quick match: swirling gateway plus speed rays"),
    ("create_room", "create room: empty table plus a rune plus sign"),
    ("private_room", "private room: locked door plus a rune code, purple-blue"),
    ("room_code", "room code: command tablet with 6 abstract symbol slots"),
    ("public_room", "public room: open room board with many cards, blue"),
    ("room_locked", "locked room: padlock over a card table"),
    ("room_full", "full room: table with all seats / players filled"),
    ("buy_in", "buy-in level: spirit coins / chips deposit, gold glow"),
    ("player_count", "player count: a group of people around a table"),
    ("bot_count", "bot count: cultivation-style AI puppet / disciple"),
]
# Phòng Liar — mỗi file là bàn Bài Nói Dối theo chủ đề cảnh giới/đạo.
_B8_LIAR = [
    "room_dau_tap", "room_tan_thu", "room_luyen_khi", "room_truc_co", "room_kim_dan",
    "room_chinh_dao", "room_ma_dao", "room_thien_menh", "room_sinh_tu", "room_cau_dao",
    "room_tam_ma_kiep", "room_nhan_qua",
]
# Phòng Xì Tố 3 Lá — mỗi file là ba lá bài theo chủ đề.
_B8_THREE_CARD = [
    "room_dau_tap", "room_tan_thu", "room_luyen_khi", "room_truc_co", "room_kim_dan",
    "room_chinh_dao", "room_ma_dao", "room_thien_ma", "room_sinh_tu", "room_thien_menh",
    "room_tong_mon",
]


def _build_b8() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/rooms", (512, 512), d, _B8, "B8a. Common", priority="P1")
        for c, d in _B8_COMMON
    ]
    items += [
        _item(
            c, "Assets/Resources/icons/rooms/liar", (512, 512),
            f"Liar card-game room icon themed '{c.replace('room_', '').replace('_', ' ')}': "
            "a Bai Noi Doi (liar) table styled to that cultivation realm / dao theme, purple-gold mystic mood",
            _B8, "B8b. Liar rooms", priority="P2",
        )
        for c in _B8_LIAR
    ]
    items += [
        _item(
            c, "Assets/Resources/icons/rooms/three_card", (512, 512),
            f"Three-card poker room icon themed '{c.replace('room_', '').replace('_', ' ')}': "
            "three playing cards styled to that cultivation realm / dao theme, blue-gold mystic mood",
            _B8, "B8c. Three-card rooms", priority="P2",
        )
        for c in _B8_THREE_CARD
    ]
    return items


# ---- B9. Avatar / Nâng sao --------------------------------------------
_B9 = "B9. Avatar"
_B9_ITEMS = [
    ("star_empty", "Assets/Resources/icons/avatar", (256, 256), "empty star, dim gold outline (star upgrade)"),
    ("star_filled", "Assets/Resources/icons/avatar", (256, 256), "bright filled gold star"),
    ("shard_character", "Assets/Resources/icons/avatar", (512, 512), "glowing broken character shard (unlock / star up)"),
    ("silhouette_locked", "Assets/Resources/icons/avatar", (512, 512), "character silhouette in gray smoke plus a dim padlock"),
    ("vfx_star_upgrade", "Assets/Resources/effects", (512, 512), "star-upgrade effect: ring of gold stars plus light rays (overlay)"),
]


def _build_b9() -> list[ArtItem]:
    return [
        _item(c, d_, s, d, _B9, "Avatar", priority="P1")
        for c, d_, s, d in _B9_ITEMS
    ]


# ---- B10. Gacha --------------------------------------------------------
_B10 = "B10. Gacha"
_B10_ICONS = [
    ("ticket_low", (512, 512), "low gacha ticket: silver/blue, summon rune marks"),
    ("ticket_high", (512, 512), "high gacha ticket: rare gold/purple, strong aura"),
    ("rarity_3star", (256, 256), "3-star rarity badge, blue/silver"),
    ("rarity_4star", (256, 256), "4-star rarity badge, purple"),
    ("rarity_5star", (256, 256), "5-star rarity badge, blazing gold, ultra rare"),
]


def _build_b10() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/gacha", s, d, _B10, "Icons", priority="P1")
        for c, s, d in _B10_ICONS
    ]
    items.append(_item(
        "banner_tieu_dao_vo_vi", "Assets/Resources/banners/gacha", (1536, 640),
        "Gacha 'Tieu Dao Vo Vi' banner: summon gateway, blurred character/treasure on both sides, no text",
        _B10, "Banner", transparent=False, rules=BANNER_RULES, priority="P1",
    ))
    return items


# ---- B11. Kết Quả Trận -------------------------------------------------
_B11 = "B11. Result"
_B11_ITEMS = [
    ("result_win_medal", "win medal: gold medal / trophy"),
    ("result_lose_mark", "lose mark: light defeat symbol, red-gray, not gloomy"),
    ("mvp_badge", "MVP badge: gold, star / trophy"),
    ("passive_triggered", "passive triggered: a glowing rune lighting up"),
]


def _build_b11() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/result", (512, 512), d, _B11, "Result", priority="P1")
        for c, d in _B11_ITEMS
    ]


# ---- B12. Lịch Sử Ván --------------------------------------------------
_B12 = "B12. History"
_B12_ITEMS = [
    ("win_tag", (256, 256), "win tag: blue/gold tag"),
    ("lose_tag", (256, 256), "lose tag: red/gray tag"),
    ("allin_tag", (256, 256), "all-in tag: chips / spirit coins bursting into flame"),
    ("bluff_tag", (256, 256), "bluff tag: small mask, purple smoke"),
    ("replay", (512, 512), "replay: replay button / time scroll, looping arrow"),
]


def _build_b12() -> list[ArtItem]:
    return [
        _item(c, "Assets/Resources/icons/history", s, d, _B12, "History", priority="P1")
        for c, s, d in _B12_ITEMS
    ]


# ---- B13. Sự kiện đặc biệt (khối lớn, priority P3 - để sau cùng) -------
_B13 = "B13. Events"
# Mỗi event = icon 512 (trong suốt) + banner 1536x640 (opaque, không chữ).
_B13_LIAR = [
    "thien_kiep", "thien_co_nghich_chuyen", "tam_ma_xam_thuc", "linh_khi_hon_loan",
    "thien_dao_ap_che", "doat_thien_co", "hu_khong_loan_luu", "bi_canh_thuong_co",
    "thien_co_hien_the", "huyet_chien_dai", "thien_loi_trung_phat", "nghich_thien_cai_menh",
    "thien_tam_dao_dong", "chung_sinh_nghi_ky", "thien_dao_quan_sat", "phat_phap_bao_only",
]
_B13_THREE_CARD = [
    "thien_bai_cong_minh", "ma_bai_cong_minh", "thien_ma_dao_dong", "linh_khi_dang_trao",
    "huyet_chien_khi", "thien_dao_ap_che", "bi_canh_tu_linh", "ma_khi_che_mat",
    "loi_kiep_mo_bai", "nghich_thien_cai_menh", "thien_co_hien_the", "phat_phap_bao_only",
]


def _build_b13() -> list[ArtItem]:
    items: list[ArtItem] = []
    for code in _B13_LIAR:
        theme = code.replace("_", " ")
        items.append(_item(
            f"icon_{code}", "Assets/Resources/events/liar", (512, 512),
            f"Liar special-event icon for '{theme}': a single emblematic mystic symbol of that event theme",
            _B13, "B13a. Liar events", priority="P3",
        ))
        items.append(_item(
            f"banner_{code}", "Assets/Resources/events/liar", (1536, 640),
            f"Liar special-event banner for '{theme}': cinematic cultivation-fantasy key art, no text",
            _B13, "B13a. Liar events", transparent=False, rules=BANNER_RULES, priority="P3",
        ))
    for code in _B13_THREE_CARD:
        theme = code.replace("_", " ")
        items.append(_item(
            f"icon_{code}", "Assets/Resources/events/three_card", (512, 512),
            f"Three-card special-event icon for '{theme}': a single emblematic mystic symbol of that event theme",
            _B13, "B13b. Three-card events", priority="P3",
        ))
        items.append(_item(
            f"banner_{code}", "Assets/Resources/events/three_card", (1536, 640),
            f"Three-card special-event banner for '{theme}': cinematic cultivation-fantasy key art, no text",
            _B13, "B13b. Three-card events", transparent=False, rules=BANNER_RULES, priority="P3",
        ))
    return items


# =====================================================================
# NHÓM C — BỔ SUNG NHỎ / SPRITE SHEET / REDO BACKGROUND
# =====================================================================
_C = "C. Supplement"

_C_QUESTS = [
    ("quest_w_allin_5", (512, 512), "Weekly All-in x5: large pile of chips, all-in fire"),
    ("quest_w_login_7", (512, 512), "Weekly login 7 days: a full week calendar with checks"),
    ("quest_w_upgrade_relic", (512, 512), "Weekly upgrade relic: a treasure on a forge anvil, gold sparks"),
    ("quest_w_bigpot_3", (512, 512), "Weekly 3 big pots: three stacked spirit-coin chests"),
    ("quest_state_claimable", (256, 256), "blue-gold check mark with a glowing ring"),
    ("quest_state_claimed", (256, 256), "completed seal, soft blue"),
    ("quest_state_locked", (256, 256), "dim padlock / light chain"),
]
# Sprite sheet hiệu ứng: 4 frame ngang (trừ aura).
_C_SHEETS = [
    ("hit_explosion_sheet", (1024, 256), "4 frames 256px: spell-force impact explosion"),
    ("thunder_tribulation_sheet", (2048, 512), "4 frames 512px: tribulation lightning pillar"),
    ("vfx_thunder_sheet", (2048, 512), "4 frames 512px: lightning arcs around an event UI"),
    ("particle_chip_sheet", (1024, 256), "4 frames: flying spirit-coin / chip particles"),
    ("sparkle_win_sheet", (1024, 256), "4 frames: gold stars bursting for win / gacha"),
    ("vfx_chu_chao_sheet", (1024, 256), "4 frames: warping space / swirling rune marks"),
]
_C_FX = [
    ("vfx_claim_ready", (512, 512), "blue-gold glowing ring behind a claim button"),
    ("vfx_locked_shadow", (512, 512), "gray smoke plus a dim padlock covering a locked item"),
    ("vfx_mail_pop", (512, 512), "paper crane / letter popping out plus light rays"),
    ("vfx_event_warning", (512, 512), "red-purple warning ring before an event"),
]
# Redo background (opaque 1920x1080).
_C_BACKGROUNDS = [
    ("lobby_bg", "redraw the lobby background sharper, cultivation-fantasy lobby scene"),
    ("table_bg", "redraw the card-table background sharper, cultivation-fantasy table scene"),
    ("TuTienLoginBg", "redraw the login background as 16:9, cultivation-fantasy login scene"),
]


def _build_c() -> list[ArtItem]:
    items = [
        _item(c, "Assets/Resources/icons/quests", s, d, _C, "C1. Quests", priority="P2")
        for c, s, d in _C_QUESTS
    ]
    items += [
        _item(c, "Assets/Resources/effects", s, d, _C, "C2. Sheets", rules=SHEET_RULES, priority="P2")
        for c, s, d in _C_SHEETS
    ]
    items += [
        _item(c, "Assets/Resources/effects", s, d, _C, "C3. FX", rules=FX_RULES, priority="P2")
        for c, s, d in _C_FX
    ]
    items += [
        _item(
            c, "Assets/Resources/Backgrounds", (1920, 1080), d, _C, "C4. Backgrounds (redo)",
            transparent=False, rules=BANNER_RULES, priority="P2",
        )
        for c, d in _C_BACKGROUNDS
    ]
    return items


# =====================================================================
# Build full catalog
# =====================================================================

CATALOG: list[ArtItem] = (
    _build_group_a()
    + _build_b1()
    + _build_b2()
    + _build_b3()
    + _build_b4()
    + _build_b5()
    + _build_b6()
    + _build_b7()
    + _build_b8()
    + _build_b9()
    + _build_b10()
    + _build_b11()
    + _build_b12()
    + _build_b13()
    + _build_c()
)

GROUP_ORDER = [
    _GROUP_A,
    _B1, _B2, _B3, _B4, _B5, _B6, _B7, _B8, _B9, _B10, _B11, _B12, _B13,
    _C,
]


def items_by_group() -> dict[str, list[ArtItem]]:
    result: dict[str, list[ArtItem]] = {g: [] for g in GROUP_ORDER}
    for item in CATALOG:
        result.setdefault(item.group, []).append(item)
    return result


def find_by_code(code: str) -> ArtItem | None:
    return next((item for item in CATALOG if item.code == code), None)


def stats() -> dict[str, int]:
    by_group: dict[str, int] = {}
    for item in CATALOG:
        by_group[item.group] = by_group.get(item.group, 0) + 1
    return by_group


if __name__ == "__main__":
    total = len(CATALOG)
    print(f"TuTien5 catalog total={total}")
    for group in GROUP_ORDER:
        count = sum(1 for item in CATALOG if item.group == group)
        print(f"  {group}: {count}")
    # Cảnh báo trùng path (nếu có).
    seen: dict[str, str] = {}
    for item in CATALOG:
        if item.relpath in seen:
            print(f"  DUPLICATE relpath: {item.relpath} ({seen[item.relpath]} vs {item.code})")
        seen[item.relpath] = item.code
