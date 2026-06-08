# Tích hợp API Google Labs Flow vào tool vẽ — Tài liệu bàn giao

> Mục tiêu: ghi lại TOÀN BỘ thứ đã biết để bạn (hoặc tool vẽ khác) tự đấu nối và lấy API
> tạo ảnh của Flow. Trọng tâm là khâu **recaptcha token** — chỗ duy nhất còn chặn.
>
> Thư mục code: `D:\TOOL\TOOL API Flow\flow-tool\`
> Tài liệu phân tích gốc: `D:\TOOL\TOOL API Flow\PHAN_TICH_FLOW_API.md`

---

## 0. TL;DR (ĐÃ GIẢI QUYẾT - tool tạo được ảnh thật)

- Toàn bộ luồng API chạy thật và **đã tạo được ảnh** (`output/*.png`, ~700 KB).
- **Nguyên nhân 403 trước đây = HAI lỗi cùng lúc** (không phải chỉ điểm số):
  1. **Sai action**: thư viện dùng `FLOW_GENERATION`, web Flow thật dùng **`IMAGE_GENERATION`**.
  2. **Trình duyệt headless/profile mới** bị reCAPTCHA chấm điểm bot → cần dùng **Brave thật**
     (profile thật, có reputation, không headless, `navigator.webdriver=false`).
- **Cách chạy được** (đã code sẵn, mặc định): lấy token qua **Brave thật** mở bằng
  `--remote-debugging-port` + gọi `grecaptcha.enterprise.execute(KEY, {action:'IMAGE_GENERATION'})`.
  Không cần click tay.
- Chạy thử: `python generate.py "a cat" --n 1` → ra ảnh trong `output/`.

> Bằng chứng kiểm chứng (3 phép thử):
> | Cách sinh token | Kết quả |
> |---|---|
> | v3 thường (`grecaptcha.execute`, action FLOW_GENERATION), headless | 403 |
> | Enterprise, action FLOW_GENERATION, Brave thật | 403 |
> | Enterprise, action FLOW_GENERATION, headless đã login | 403 |
> | Enterprise, action **IMAGE_GENERATION**, headless đã login | 403 |
> | Enterprise, action **IMAGE_GENERATION**, **Brave thật** | ✅ 200, ra ảnh |

---

## 1. Luồng API đầy đủ (đã xác minh thật)

```
[cookie đăng nhập Flow]
      |
      v
GET https://labs.google/fx/api/auth/session        --> access_token (Bearer, sống ~1h)
      |
      v
POST https://labs.google/fx/api/trpc/project.createProject   --> projectId
      |
      v
[LẤY recaptcha_token]   <-- CHỖ DUY NHẤT CÒN CHẶN
      |
      v
POST https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages
      |
      v
response.media[].image.generatedImage.fifeUrl   --> GET tải ảnh .png
```

### 1.1. Lấy access token
```
GET https://labs.google/fx/api/auth/session
Header: Cookie: <cookie labs.google>
-> JSON: { user, expires, access_token }
```
- **Đã chạy**: trả `access_token` dạng `ya29.a0...` dài ~416 ký tự.
- Lưu ý: chỉ cần cookie domain `labs.google` (đặc biệt `__Secure-next-auth.session-token`).
  KHÔNG gộp toàn bộ cookie google.com vào header, sẽ bị **HTTP 431** (header quá lớn).

### 1.2. Tạo project
```
POST https://labs.google/fx/api/trpc/project.createProject
Header: Cookie + Content-Type: application/json
Body: {"json": {"projectTitle": "<tiêu đề>", "toolName": "PINHOLE"}}
-> projectId tại result.data.json.result.projectId
```
- **Đã chạy**: trả projectId dạng UUID, ví dụ `23003584-3f01-41d9-b92a-2674b4401a89`.

### 1.3. Gọi API tạo ảnh
```
POST https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages
Headers:
  Authorization: Bearer <access_token>
  Content-Type:  text/plain;charset=UTF-8      (cố ý text/plain để né CORS preflight)
Body (JSON.stringify):
{
  "clientContext": {
    "recaptchaContext": { "token": "<recaptcha_token>",
                          "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB" },
    "projectId": "<projectId>",
    "tool": "PINHOLE",
    "sessionId": ";<epoch_millis>"
  },
  "mediaGenerationContext": { "batchId": "<uuid4>" },
  "useNewMedia": true,
  "requests": [
    {
      "clientContext": { ...giống trên... },
      "imageModelName": "NARWHAL",
      "imageAspectRatio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
      "structuredPrompt": { "parts": [ { "text": "<prompt>" } ] },
      "seed": 207,
      "imageInputs": []
    }
  ]
}
```
- **Đã chạy tới đây**: request gửi thành công, server phản hồi — nhưng **403** nếu token
  reCAPTCHA điểm thấp (xem mục 3).

### 1.4. Đọc & tải ảnh
```
response.media[i].image.generatedImage.fifeUrl     -> URL ảnh (có chữ ký, hết hạn)
response.media[i].image.dimensions                 -> {width, height}
GET <fifeUrl>  -> ghi ra file .png
```

---

## 2. Hằng số quan trọng

| Thứ | Giá trị |
|-----|---------|
| Base API tạo ảnh | `https://aisandbox-pa.googleapis.com` |
| Tên nội bộ của Flow | `PINHOLE` |
| reCAPTCHA site key (Enterprise) | `6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV` |
| reCAPTCHA action (ĐÚNG) | **`IMAGE_GENERATION`** (KHÔNG phải `FLOW_GENERATION`) |
| applicationType | `RECAPTCHA_APPLICATION_TYPE_WEB` |
| Model ảnh (Nano Banana) | `NARWHAL` |
| Tỉ lệ ảnh | `IMAGE_ASPECT_RATIO_LANDSCAPE` / `PORTRAIT` / `SQUARE` |
| API key nhúng (cho API công khai) | `AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY` |
| Firebase project | `gweb-ai-sandbox-prod` (project number `365941595420`) |
| Content-Type generate | `text/plain;charset=UTF-8` (quan trọng) |

reCAPTCHA chạy trong web là (CHÚ Ý action đúng):
```js
grecaptcha.enterprise.execute('6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV',
                              { action: 'IMAGE_GENERATION' })
```

---

## 3. Vấn đề recaptcha — đã thử gì, vì sao chặn

### 3.1. Lỗi gặp phải
```
HTTP 403
{
  "error": {
    "code": 403,
    "message": "reCAPTCHA evaluation failed",
    "status": "PERMISSION_DENIED",
    "details": [ { "@type": "type.googleapis.com/google.rpc.ErrorInfo", ... } ]
  }
}
```

### 3.2. Cách tái dùng token thật (bắt từ click người) — single-use
Token web tự sinh khi bạn bấm "Tạo" có điểm cao, nhưng **dùng-một-lần**: web đã gửi nó rồi,
ta bắt lại để tái dùng → server báo đã tiêu → 403. Vì vậy phải **tự sinh token mới**, không reuse.

### 3.3. Vì sao trước đây 403 (đã làm rõ)
Hai nguyên nhân cộng dồn:
1. **Sai action** `FLOW_GENERATION` (thư viện) thay vì `IMAGE_GENERATION` (web thật). reCAPTCHA
   Enterprise đánh giá theo đúng action.
2. **Headless / profile mới**: điểm hành vi thấp → bị chặn dù action đã đúng.

Chỉ khi **sửa cả hai** (Brave thật + action IMAGE_GENERATION) thì token mới được chấp nhận.

---

## 4. GIẢI PHÁP ĐANG DÙNG (đã code sẵn)

Token được lấy qua **Brave thật** (module `brave_token.py` → `BraveTokenEngine`):
1. Mở Brave với `--remote-debugging-port=9222` + đúng `--user-data-dir` + profile Default
   (đóng Brave cũ trước nếu đang chạy, vì cờ debug chỉ áp dụng khi khởi động mới).
2. `connect_over_cdp` bằng Playwright.
3. Mở/đi tới trang Flow (project) để `grecaptcha.enterprise` được nạp.
4. Gọi `grecaptcha.enterprise.execute(KEY, {action: 'IMAGE_GENERATION'})` → token điểm cao.
5. Đọc luôn cookie `labs.google` từ chính phiên Brave này (cho `access_token`).

`flow_client.py` mặc định `token_mode="brave"` nên chỉ cần:
```python
client = FlowClient(cookie="", token_mode="brave")   # cookie tự lấy từ Brave
client.start()
paths = client.generate_images("a cat", n=1)
client.stop()
```

### Điểm cắm token (nếu muốn đổi nguồn)
`flow_client.py` → `_get_recaptcha_token(project_id)` gọi `self._engine.get_token(project_id)`.
Engine có thể là:
- `BraveTokenEngine` (mặc định, ĐÃ HOẠT ĐỘNG) — `brave_token.py`.
- `CaptchaEngine` (flow-captcha-solver headless) — hiện bị chặn vì headless điểm thấp.

### Các nguồn token khác (tham khảo, nếu Brave không tiện)
- **2Captcha/anti-captcha** reCAPTCHA Enterprise v3: gửi `websiteURL` (trang project),
  `websiteKey=6LdsFiUs...`, `pageAction=IMAGE_GENERATION`, `enterprise=true`. Điểm tuỳ dịch vụ.
- **Gemini API chính thức** (`gemini-2.5-flash-image` = Nano Banana): bỏ hẳn reCAPTCHA, hợp pháp,
  ổn định — khuyến nghị cho sản phẩm thật.

---

## 5. Lấy cookie đăng nhập từ trình duyệt (đã giải quyết)

Brave/Chrome mới mã hoá cookie kiểu **app-bound (v20)** → KHÔNG giải mã trực tiếp bằng DPAPI.
File `Cookies` còn bị **khoá độc quyền** khi trình duyệt chạy (copy/esentutl/SQLite đều fail).

**Cách đã chạy được** (trong `cookie_grabber.py`):
1. Đóng trình duyệt nếu đang chạy.
2. Mở lại với cờ `--remote-debugging-port=9222` + đúng `--user-data-dir` + `--profile-directory=Default`.
3. Dùng Playwright `connect_over_cdp("http://127.0.0.1:9222")`.
4. Đọc `context.cookies()` → trình duyệt tự giải mã trong bộ nhớ (lấy được cả HttpOnly + v20).
5. Lọc cookie domain `google.com` / `labs.google`.

Hàm dùng:
- `grab_via_cdp(browser)` → trả chuỗi `name=value; ...`
- `grab_cookies_struct(browser)` → trả list dict kiểu Playwright (có domain/path) để **bơm
  vào trình duyệt khác** (đã dùng cho AuthBrowserInstance).

> Đã verify: lấy được 73 cookie gồm `__Secure-next-auth.session-token`, và `access_token`
> rút ra từ session hoạt động.

---

## 6. Cấu trúc code & vai trò file

| File | Vai trò | Có cần sửa? |
|------|---------|-------------|
| `brave_token.py` | **Lấy token qua Brave thật + action IMAGE_GENERATION (CÁCH ĐANG CHẠY)** | Tái dùng |
| `flow_client.py` | Lõi luồng API. `token_mode="brave"` (mặc định) dùng brave_token | Ít khi |
| `captcha_engine.py` | flow-captcha-solver headless (bị chặn) — chỉ giữ tham khảo | — |
| `cookie_grabber.py` | Lấy cookie từ Brave/Chrome/Edge qua CDP | Tái dùng |
| `generate.py` | CLI: `python generate.py "prompt"` (mặc định mode brave) | Tham khảo |
| `gui.py` | Giao diện tool vẽ (mode brave) | Tái dùng |
| `server.py` | HTTP server cục bộ: `POST /generate` (mode brave) | Tái dùng |
| `flow_cookie.txt` | Cookie header labs.google đã lọc | Tự sinh |

### Bug đã sửa sẵn (lưu ý khi đọc code)
- `FlowCaptchaManager` của thư viện `flow-captcha-solver` bị **race condition**: event loop
  nền thoát sớm trên Python 3.14/Windows → `get_token_sync` trả None. Đã thay bằng
  `CaptchaEngine` tự giữ loop `run_forever` + **ProactorEventLoop** (bắt buộc để Playwright
  spawn tiến trình trên Windows; SelectorEventLoop sẽ lỗi `NotImplementedError`).

---

## 7. Môi trường đã cài

```
pip install flow-captcha-solver requests browser_cookie3 pywin32 pycryptodomex
playwright install chromium
```
Python 3.14, Windows. Brave cài tại `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`.

---

## 8. Cách test nhanh sau khi sửa token

```bash
cd "D:\TOOL\TOOL API Flow\flow-tool"
python generate.py "a cute orange cat on a wooden table" --n 1 --grab brave
```
- Nếu thấy `media[].fifeUrl` và file .png trong `output/` → THÀNH CÔNG.
- Nếu `403 reCAPTCHA evaluation failed` → token vẫn điểm thấp, đổi nguồn token (mục 4).
- Nếu `401` → access_token hết hạn, lấy lại cookie.
- Nếu `431` → header cookie quá lớn, chỉ giữ cookie domain labs.google.

---

## 9. Đầu vào tối thiểu để gọi API (checklist)

- [ ] Cookie đăng nhập Flow còn hạn (đặc biệt `__Secure-next-auth.session-token`).
- [ ] `access_token` Bearer (rút từ `/fx/api/auth/session`).
- [ ] `projectId` (tạo mới hoặc dùng lại).
- [ ] `recaptcha_token` cho action **`IMAGE_GENERATION`**, sinh trong **Brave thật** ← mấu chốt.
- [ ] Header `Content-Type: text/plain;charset=UTF-8` khi gọi `batchGenerateImages`.

> Đã đủ 5 thứ và tạo được ảnh thật. Tất cả đã tự động hoá trong `flow-tool` (mode brave).

---

## 10. Cảnh báo

- Tự động hoá vượt reCAPTCHA của Google **vi phạm điều khoản dịch vụ**, có **rủi ro khoá tài
  khoản**, và **không ổn định** (Google đổi luật là hỏng).
- Server cục bộ (`server.py`) chạy ở `127.0.0.1`, **không có xác thực** — đừng mở ra mạng ngoài.
- Hướng bền vững, hợp pháp: **Gemini API chính thức** (mục 4-D).
