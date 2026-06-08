# Flow API — Cách lấy & chạy API vẽ ảnh (Google Labs Flow)

> Hướng dẫn đầy đủ cách reverse-engineer API vẽ ảnh của **Google Labs Flow**
> (model **NARWHAL** = Nano Banana) và chạy một **proxy OpenAI-compatible đa tài khoản**
> để cắm thẳng vào tool ảnh (Base URL).
>
> Repo: https://github.com/WahuVN/tool-image-gpt-api

---

## 0. TL;DR

- Flow tạo ảnh qua: `cookie đăng nhập → access_token → projectId → recaptcha token → batchGenerateImages → tải ảnh`.
- **Mấu chốt đã giải được:**
  1. reCAPTCHA Enterprise dùng **action = `IMAGE_GENERATION`** (KHÔNG phải `FLOW_GENERATION`).
  2. Token phải sinh trong **trình duyệt thật (profile đã đăng nhập)**, không headless — headless bị chấm điểm bot → 403.
- Proxy `flow-tool` phơi API kiểu OpenAI tại `http://localhost:8790`, nhiều acc xoay vòng + chạy song song. Tool ảnh chỉ cần đổi **Base URL** sang đó.

---

## 1. Luồng API Flow (đã xác minh thật)

```
[cookie đăng nhập Flow]
      │
      ▼
GET  https://labs.google/fx/api/auth/session            → access_token (Bearer, ~1h) + email
      │
      ▼
POST https://labs.google/fx/api/trpc/project.createProject   → projectId
      │
      ▼
[recaptcha token]  ← grecaptcha.enterprise.execute(KEY, {action:'IMAGE_GENERATION'})
      │
      ▼
POST https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages
      │
      ▼
response.media[].image.generatedImage.fifeUrl  → GET tải ảnh
```

### 1.1. Lấy access token + email
```
GET https://labs.google/fx/api/auth/session
Header: Cookie: <cookie labs.google>
→ { user:{email,...}, access_token, expires }
```

### 1.2. Xem điểm/quota còn lại của tài khoản
```
GET https://aisandbox-pa.googleapis.com/v1/credits
Header: Authorization: Bearer <access_token>
→ { "credits": 50, "userPaygateTier": "PAYGATE_TIER_NOT_PAID",
    "sku": "G1_FREEMIUM", "serviceTier": "SERVICE_TIER_ENTRY",
    "subscriptionCredits": 50 }
```

### 1.3. Tạo project
```
POST https://labs.google/fx/api/trpc/project.createProject
Header: Cookie + Content-Type: application/json
Body : {"json":{"projectTitle":"...","toolName":"PINHOLE"}}
→ projectId tại result.data.json.result.projectId
```

### 1.4. Tạo ảnh
```
POST https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages
Headers:
  Authorization: Bearer <access_token>
  Content-Type:  text/plain;charset=UTF-8       (cố ý text/plain để né CORS preflight)
Body (JSON.stringify):
{
  "clientContext": {
    "recaptchaContext": { "token":"<recaptcha_token>",
                          "applicationType":"RECAPTCHA_APPLICATION_TYPE_WEB" },
    "projectId": "<projectId>", "tool":"PINHOLE",
    "sessionId": ";<epoch_millis>"
  },
  "mediaGenerationContext": { "batchId":"<uuid4>" },
  "useNewMedia": true,
  "requests": [{
    "clientContext": { ...giống trên... },
    "imageModelName": "NARWHAL",
    "imageAspectRatio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "structuredPrompt": { "parts":[{ "text":"<prompt>" }] },
    "seed": 207,
    "imageInputs": []
  }]
}
```
Ảnh trả ở `media[].image.generatedImage.fifeUrl` (thường là **JPEG**). Tải bằng GET.

---

## 2. Hằng số quan trọng

| Thứ | Giá trị |
|-----|---------|
| Base API ảnh | `https://aisandbox-pa.googleapis.com` |
| Tên nội bộ Flow | `PINHOLE` |
| reCAPTCHA site key | `6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV` |
| **reCAPTCHA action** | **`IMAGE_GENERATION`** |
| applicationType | `RECAPTCHA_APPLICATION_TYPE_WEB` |
| Model ảnh | `NARWHAL` (Nano Banana) |
| Tỉ lệ | `IMAGE_ASPECT_RATIO_LANDSCAPE` / `PORTRAIT` / `SQUARE` |
| Content-Type khi generate | `text/plain;charset=UTF-8` |

JS sinh token (chạy trong trang Flow đã đăng nhập):
```js
grecaptcha.enterprise.execute(
  '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV',
  { action: 'IMAGE_GENERATION' }
)
```

---

## 3. Vì sao hay bị 403 / 401 (đọc kỹ)

- **403 "reCAPTCHA evaluation failed"**: token sinh sai action hoặc sinh trong trình
  duyệt headless / profile mới (điểm hành vi thấp). Phải dùng **action IMAGE_GENERATION**
  + **trình duyệt thật đã đăng nhập** (không headless).
- **403 sau khi spam thử**: reCAPTCHA hạ điểm tài khoản/IP tạm thời. Đổi acc khác hoặc chờ.
- **401 Unauthorized ở createProject**: cookie hết hạn, hoặc tài khoản bị **hạn chế tạm**
  do dùng tự động dồn dập. `session` vẫn 200 nhưng mutation bị chặn → đổi acc khác.
- **Mỗi token reCAPTCHA dùng 1 lần**, sống ngắn (~2 phút) → sinh xong gọi API ngay.

> ⚠️ Tự động hoá vượt reCAPTCHA của Google **vi phạm ToS**, có **rủi ro khoá tài khoản**,
> và dễ hỏng khi Google đổi luật (vd đổi action). Dùng có chừng mực, ưu tiên xoay vòng nhiều acc.

---

## 4. Chạy proxy đa tài khoản (thư mục `flow-tool`)

### 4.1. Cài đặt
```bash
pip install flow-captcha-solver requests playwright browser_cookie3 pywin32 pycryptodomex
playwright install chromium
```
Python 3.10+ (đã test 3.14), Windows.

### 4.2. Cấu trúc
| File | Vai trò |
|------|---------|
| `flow_proxy_multi.py` | **Proxy OpenAI-compatible + trang quản lý acc** (chạy file này) |
| `flow_accounts.py` | Engine đa-acc: lưu cookie, worker pool mint token, xoay vòng |
| `flow_multi.py` | Tạo ảnh đa-acc song song (access_token + project + token + tải ảnh) |
| `flow_accounts_ui.py` | Giao diện `/accounts` |
| `accounts.json` | Lưu danh sách acc + cookie (tự tạo) |

### 4.3. Chạy
```bash
cd flow-tool
python flow_proxy_multi.py
```
- API:        `http://localhost:8790`
- Quản lý acc: `http://localhost:8790/accounts`
- Số worker song song: biến môi trường `FLOW_WORKERS` (mặc định 3).

### 4.4. Thêm & đăng nhập tài khoản (kiểu 9Router)
1. Mở `http://localhost:8790/accounts`.
2. **Thêm tài khoản**: đặt tên, chọn trình duyệt (Chrome/CocCoc/Brave), chọn:
   - **Dedicated**: tool tạo thư mục riêng, bạn đăng nhập mới.
   - **Existing**: dùng profile sẵn có (cần đóng trình duyệt đó khi tool chạy).
3. Bấm **Đăng nhập** → đăng nhập Google + mở Flow trong **cửa sổ thường** → **đóng** cửa sổ.
   (Phải là cửa sổ thường vì Google chặn đăng nhập trong trình duyệt mở cổng debug.)
4. Bấm **Kiểm tra** → tool **lưu cookie** vào `accounts.json` (hiện 🔑 + trạng thái `ready`).
5. Bấm **Điểm/Quota** để xem email + số điểm còn lại.
6. Thêm nhiều acc → hệ thống tự **xoay vòng** + **chạy song song**; acc 403/hết quota → cooldown → chuyển acc khác.

> Cookie sống theo phiên đăng nhập. Khi acc báo 401/“cần đăng nhập” → bấm Đăng nhập + Kiểm tra lại.

### 4.5. Nạp cookie THỦ CÔNG — không cần mở trình duyệt (khuyên dùng khi 401)

Khi acc báo `401 createProject` / `Hết acc khỏe` / `chưa đăng nhập/cookie` nghĩa là
**cookie hết hạn**. Thay vì mở trình duyệt đăng nhập lại trong tool, chỉ cần lấy cookie
mới từ trình duyệt đã đăng nhập Flow rồi nạp thẳng vào:

**Lấy cookie** (1 trong 2 cách):
- DevTools (F12) ▸ tab **Network** ▸ tải lại trang Flow ▸ chọn 1 request tới `labs.google`
  ▸ **Headers** ▸ copy toàn bộ giá trị **Cookie**.
- Hoặc cài extension **Cookie-Editor** ▸ vào labs.google ▸ **Export** (JSON).

**Nạp cookie** (1 trong 3 cách):
1. **Thả file**: lưu cookie thành `cookies/<tên-acc>.txt` (hoặc `.json`). Proxy tự nạp khi
   khởi động / mở `/accounts` / bấm "📂 Nạp từ thư mục".
2. **Trang `/accounts`**: card **"📥 Nạp cookie trực tiếp"** → điền tên acc + dán cookie → **Nạp**.
   Hoặc bấm **📥 Nạp cookie** ở dòng acc để điền sẵn tên.
3. **CLI** (không cần web):
   ```bash
   python flow_cookies_cli.py import flow01 --file cookies\flow01.txt
   python flow_cookies_cli.py import flow01 --clip   # đọc từ clipboard
   python flow_cookies_cli.py reload                 # nạp mọi file trong cookies/
   python flow_cookies_cli.py list                   # xem acc + trạng thái
   python flow_cookies_cli.py log -n 50              # xem log
   ```

> Bắt buộc có cookie `__Secure-next-auth.session-token` (domain `labs.google`) thì acc mới
> `ready`. Token reCAPTCHA vẫn lấy qua worker trình duyệt nền (không tránh được), nhưng phần
> đăng nhập/cookie thì hết phải thao tác trên tab web.

**Log**: mọi sự kiện (nạp cookie, cooldown, vẽ ảnh, lỗi) ghi ra `flow-tool/flow.log`
và xem được qua `GET /api/logs?n=200` hoặc nút "📜 Xem log".

---

## 5. Endpoint của proxy (port 8790)

| Method | Path | Ghi chú |
|--------|------|---------|
| GET | `/v1/models`, `/v1/models/image` | liệt kê model (`NARWHAL`, `flow`) |
| GET | `/api/health` | trạng thái + số acc sẵn sàng |
| GET | `/api/logs?n=200` | xem log gần đây |
| POST | `/v1/images/generations` | tạo ảnh (OpenAI format, trả `b64_json` hoặc `binary`) |
| GET | `/accounts` | trang quản lý acc |
| GET | `/api/accounts` | danh sách acc + trạng thái |
| GET | `/api/accounts/browsers` | liệt kê trình duyệt + profile có sẵn |
| GET | `/api/accounts/{id}/status` | email + điểm/quota |
| POST | `/api/accounts` | thêm acc `{name,browser,mode,profile_directory}` |
| POST | `/api/accounts/import` | **nạp cookie** `{name,raw}` (tạo acc nếu chưa có) |
| POST | `/api/accounts/{id}/cookies` | **nạp cookie** cho acc có sẵn `{raw}` |
| POST | `/api/accounts/reload-cookies` | nạp mọi file trong `cookies/` |
| POST | `/api/accounts/{id}/login` `/check` `/enable` `/disable` | đăng nhập / lưu cookie / bật / tắt |
| DELETE | `/api/accounts/{id}` | xoá acc |

Ví dụ tạo ảnh:
```bash
curl -X POST http://localhost:8790/v1/images/generations \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"NARWHAL\",\"prompt\":\"a cute red panda\",\"n\":2,\"size\":\"1536x1024\"}"
```
`size` → tỉ lệ Flow: `1024x1024`=SQUARE, `1536x1024`=LANDSCAPE, `1024x1536`=PORTRAIT.

---

## 6. Cắm vào tool ảnh (Base URL)

Tool ảnh nói chuyện kiểu OpenAI → chỉ cần đổi **Base URL = `http://localhost:8790`**,
Key để trống, Model `NARWHAL` (hoặc `flow`). Không phải sửa giao diện tool.

```js
// ví dụ gọi từ JS
const r = await fetch("http://localhost:8790/v1/images/generations", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ model: "NARWHAL", prompt: "a cat", n: 1, response_format: "b64_json" })
});
const data = await r.json();   // data.data[0].b64_json
```

---

## 7. Kiến trúc đa-acc (kiểu 9Router) — vì sao chỉ cần “1 tab”

- Mỗi acc đăng nhập 1 lần → **cookie được lưu** trong `accounts.json`.
- `access_token` + tạo project gọi **HTTP bằng cookie đã lưu** (không cần trình duyệt).
- Token reCAPTCHA mint qua **pool worker dùng chung** (mặc định 3 trình duyệt):
  mỗi lần *xoá cookie worker → bơm cookie của acc → vào trang project → execute*.
  ⇒ Vài tab phục vụ hết tất cả acc, **chạy song song nhiều luồng**.
- Tạo n ảnh: chia cho nhiều acc/worker qua thread pool.

---

## 8. Khắc phục sự cố

| Triệu chứng | Nguyên nhân & cách xử |
|-------------|-----------------------|
| `Không có acc sẵn sàng` | Chưa acc nào đăng nhập/lưu cookie → Đăng nhập + Kiểm tra. Hoặc tất cả đang cooldown. |
| `403 reCAPTCHA evaluation failed` | Acc bị hạ điểm tạm → chờ/đổi acc. Bảo đảm action = IMAGE_GENERATION. |
| `401 createProject Unauthorized` | Cookie hết hạn / acc bị hạn chế → đăng nhập lại hoặc đổi acc. |
| Ảnh là `.png` nhưng mở lỗi | Flow trả JPEG; proxy đã tự nhận dạng content-type. |
| Mở đăng nhập báo “browser không an toàn” | Đừng dùng cổng debug khi đăng nhập — tool đã tách: login = cửa sổ thường. |

---

## 9. Giới hạn

- Chỉ hỗ trợ **text → ảnh**. Các tác vụ cần **ảnh đầu vào** (sửa ảnh, tách nền, upscale,
  dịch ảnh, style transfer) chưa hỗ trợ qua Flow (cần endpoint upload/transform riêng).
- 9Router **không** route ảnh tới provider tuỳ chỉnh (nó báo “does not support image
  generation”) → không cắm Flow vào 9Router được; dùng proxy này thay thế.
- Hướng bền vững/hợp pháp cho sản phẩm: **Gemini API chính thức** `gemini-2.5-flash-image`
  (cũng là Nano Banana) — không reCAPTCHA, ổn định.

---

*Tài liệu mô tả kỹ thuật cho mục đích nghiên cứu/tự động hoá cá nhân. Tự động hoá vượt
chống-bot của Google vi phạm điều khoản dịch vụ và có rủi ro khoá tài khoản — cân nhắc kỹ.*
