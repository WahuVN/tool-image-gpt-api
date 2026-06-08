# Flow Tool - Tạo ảnh qua Google Labs Flow API (tự lấy reCAPTCHA)

Ghép trọn luồng trong `PHAN_TICH_FLOW_API.md` mục 9.1, trong đó **bước [ẨN] recaptcha_token**
được lấy **tự động** bằng thư viện `flow-captcha-solver`.

```
cookie login -> access_token -> projectId -> [recaptcha tự động] -> batchGenerateImages -> tải ảnh
```

## 1. Cài đặt (đã xong nếu bạn theo các bước trước)

```bash
pip install flow-captcha-solver requests
playwright install chromium
```

## 2. Lấy cookie đăng nhập

### Cách 1 - Tự động từ trình duyệt (khuyến nghị)

Dùng GUI hoặc lệnh dưới. Tool đọc thẳng file Cookies của Brave/Chrome/Edge và giải mã.

```bash
python cookie_grabber.py --browser brave --save
```

Vì Brave khoá file cookie khi đang chạy, nếu báo "bị khoá" hãy thêm `--auto-close`
(tool sẽ tạm đóng Brave, lấy cookie, rồi bạn mở lại — Brave khôi phục tab):

```bash
python cookie_grabber.py --browser brave --save --auto-close
```

> Trong **GUI** chỉ cần bấm nút **"Tự lấy cookie từ trình duyệt"**; nếu bị khoá nó sẽ hỏi
> có đóng Brave để lấy không.
>
> Nếu trình duyệt dùng *app-bound encryption* (cookie v20, Chromium rất mới) thì không
> giải mã tự động được — khi đó dùng Cách 2.

### Cách 2 - Dán thủ công

1. Mở Brave, đăng nhập `https://labs.google/fx/vi/tools/flow`.
2. **F12** → tab **Network** → bấm 1 request tới `labs.google`.
3. **Request Headers** → copy toàn bộ giá trị dòng `cookie:`.
4. Dán vào `flow_cookie.txt` (hoặc ô cookie trong GUI rồi bấm "Lưu cookie").

> Cookie hết hạn theo phiên đăng nhập. Gặp lỗi "access_token" thì lấy lại cookie mới.

## 3. Ba cách dùng

### Cách A - GUI (tool vẽ ảnh có giao diện) ⭐

```bash
python gui.py
```
hoặc nhấp đúp **`run_gui.bat`**.

Trong cửa sổ:
1. Chọn trình duyệt → bấm **"Tự lấy cookie từ trình duyệt"** (hoặc dán cookie thủ công).
2. Nhập **prompt**, chọn **model / tỉ lệ / số ảnh / seed**.
3. Bấm **TẠO ẢNH**. Ảnh hiện ngay trong cửa sổ và lưu vào `output/`.

### Cách B - CLI (chạy tay nhanh)

```bash
python generate.py "a cute cat on a sofa"
python generate.py "phong canh nui tuyet" --aspect PORTRAIT --n 2 --model NARWHAL
python generate.py "test" --show          # hiện cửa sổ trình duyệt để debug
```

Ảnh lưu trong thư mục `output/`.

### Cách C - Import trực tiếp trong Python (nếu tool vẽ của bạn là Python)

```python
from flow_client import FlowClient

client = FlowClient(cookie=open("flow_cookie.txt", encoding="utf-8").read())
client.start()
try:
    paths = client.generate_images("a dragon flying", n=1, aspect_ratio="IMAGE_ASPECT_RATIO_SQUARE")
    print(paths)   # ['output/flow_...png']
finally:
    client.stop()
```

### Cách D - HTTP server (tích hợp vào tool vẽ bất kỳ ngôn ngữ)

Đây là cách tích hợp vào `D:\TOOL\TOOL Anh` mà **không cần sửa lõi tool vẽ** nhiều:

```bash
python server.py            # http://127.0.0.1:8799
# hoặc nhấp đúp run_server.bat
```

Tool vẽ chỉ cần gọi HTTP:

```
POST http://127.0.0.1:8799/generate
Content-Type: application/json

{ "prompt": "a cat", "n": 1, "aspect": "LANDSCAPE", "download": true }
```

Phản hồi:

```json
{ "ok": true, "images": ["output/flow_1730000000_0_207.png"] }
```

Nếu muốn nhận URL trực tiếp (không tải file) thì gửi `"download": false`,
khi đó `images` chứa các `fifeUrl`.

#### Ví dụ gọi từ JavaScript (nếu tool vẽ là web/Electron)

```js
const res = await fetch("http://127.0.0.1:8799/generate", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "a cat", n: 1, download: false }),
});
const data = await res.json();
if (data.ok) showImage(data.images[0]);   // fifeUrl
```

#### Ví dụ gọi từ Python (tool vẽ Python)

```python
import requests
r = requests.post("http://127.0.0.1:8799/generate",
                  json={"prompt": "a cat", "n": 1})
print(r.json()["images"])
```

## 4. Tham số generate

| Tham số | Mặc định | Ý nghĩa |
|---------|----------|---------|
| `prompt` | (bắt buộc) | Mô tả ảnh |
| `model` | `NARWHAL` | Model ảnh (Nano Banana) |
| `aspect` | `LANDSCAPE` | `LANDSCAPE` / `PORTRAIT` / `SQUARE` |
| `n` | `1` | Số ảnh |
| `seed` | ngẫu nhiên | Seed cố định để tái tạo |
| `project_id` | tạo mới | Dùng lại project có sẵn |
| `download` | `true` | `true` lưu file, `false` trả URL |

## 5. Cơ chế tự xử lý

- **Tự lấy recaptcha token** qua pool trình duyệt stealth (site key + action `FLOW_GENERATION`
  đã khớp sẵn với Flow).
- **Tự retry khi 403**: nếu token bị từ chối (`PUBLIC_ERROR_UNUSUAL_ACTIVITY`), client báo
  `report_failure()` để pool đổi fingerprint rồi lấy token mới, thử lại tối đa 4 lần.
- **Tự làm mới Bearer token** khi gặp 401.

## 6. Lưu ý quan trọng (đọc kỹ)

- reCAPTCHA Enterprise của Flow **chấm điểm hành vi**. Token sinh tự động (không có cử chỉ
  người thật) có thể bị chấm điểm thấp → trả **403**. Đây là rào cản đã ghi trong
  `PHAN_TICH_FLOW_API.md` mục 6. Tool này **tự retry** nhưng **không đảm bảo 100%** vượt qua,
  và việc tự động hoá vượt chống-bot **vi phạm điều khoản dịch vụ Google, có rủi ro khoá
  tài khoản**. Cân nhắc kỹ trước khi dùng tài khoản chính.
- Hướng bền vững, hợp pháp hơn: dùng **Gemini API chính thức** (`gemini-2.5-flash-image` =
  Nano Banana) như đề xuất mục 7 trong tài liệu phân tích.
- Server chạy ở `127.0.0.1` (chỉ máy bạn truy cập được) và **không có xác thực**. Đừng mở ra
  mạng ngoài; nếu cần, hãy thêm token/API-key cho endpoint `/generate`.

## 7. File trong thư mục này

| File | Vai trò |
|------|---------|
| `gui.py` | **Tool vẽ ảnh có giao diện** (tự lấy cookie + tạo ảnh + xem ảnh) |
| `cookie_grabber.py` | Tự lấy & giải mã cookie từ Brave/Chrome/Edge |
| `flow_client.py` | Lõi: client Flow + ghép captcha solver |
| `generate.py` | CLI tạo ảnh |
| `server.py` | HTTP server cục bộ cho tool vẽ gọi vào |
| `run_gui.bat` | Chạy GUI bằng nhấp đúp |
| `run_server.bat` | Chạy server bằng nhấp đúp |
| `flow_cookie.txt` | Nơi lưu cookie đăng nhập |
| `output/` | Ảnh tải về |


---

## 8. Đấu vào tool vẽ ở D:\TOOL\TOOL Anh (proxy OpenAI-compatible)

Tool vẽ (Wahu / 9Router app) nói chuyện kiểu OpenAI. `flow_openai_proxy.py` phơi ra đúng
API đó nhưng backend là Flow → **không cần sửa giao diện tool**, chỉ đổi Base URL.

### Các bước
1. Chạy proxy (nhấp đúp file trong TOOL Anh):
   ```
   D:\TOOL\TOOL Anh\run_flow_proxy.bat
   ```
   Lần đầu sẽ đóng Brave cũ rồi mở lại kèm cổng debug để lấy token (Brave khôi phục tab).
   Khi thấy `Sẵn sàng tại http://127.0.0.1:8790` là xong.

2. Mở app vẽ, vào phần cấu hình:
   - **Base URL** = `http://localhost:8790`
   - **Key** = để trống hoặc gõ bất kỳ
   - **Model** = `NARWHAL` (hoặc `flow`)

3. Vẽ như bình thường. Ảnh do Flow tạo.

### Endpoint proxy (port 8790)
| Method | Path | Ghi chú |
|--------|------|---------|
| GET | `/v1/models`, `/v1/models/image` | liệt kê model (NARWHAL/flow) |
| GET | `/api/health` | health check |
| POST | `/v1/images/generations` | tạo ảnh, trả `b64_json` (hoặc `binary`) |

`size` (vd `1536x1024`) được map sang tỉ lệ Flow (LANDSCAPE/PORTRAIT/SQUARE).

### Lưu ý
- Proxy giữ 1 phiên Brave + serialize request (1 ảnh/lần) để ổn định token.
- Vẫn là tự động hoá vượt chống-bot Google: rủi ro khoá tài khoản, dễ hỏng nếu Google đổi
  `action`. Nếu hỏng, sửa `RECAPTCHA_ACTION` trong `brave_token.py`.
- Cổng mặc định 8790, đổi bằng biến môi trường `FLOW_PROXY_PORT`.


---

## 9. Đa tài khoản Flow + xoay vòng + chạy song song

Chạy proxy đa-acc (thay cho proxy 1 acc):
```
python flow_proxy_multi.py
```
hoặc nhấp đúp **run_flow_proxy.bat** (đã trỏ sang bản multi).

### Quản lý tài khoản: http://localhost:8790/accounts
- **Thêm acc**: nhập tên → chọn trình duyệt (Chrome/CocCoc/Brave) → chọn chế độ:
  - **Thư mục riêng (dedicated)**: tool tạo user-data-dir riêng. Bấm **Đăng nhập** → cửa sổ
    mở tới Flow → bạn sign-in Google 1 lần → bấm **Kiểm tra**. Đây là cách chạy song song
    chuẩn nhất (mỗi acc 1 thư mục, không vướng khóa Chrome).
  - **Dùng profile có sẵn (existing)**: chọn profile Chrome/CocCoc bạn đã có. Lưu ý: phải
    đóng trình duyệt đó khi proxy chạy (Chrome khóa user-data-dir mỗi process).
- Mỗi dòng acc: trạng thái (sẵn sàng / cần đăng nhập / cooldown), số lần dùng/lỗi, nút
  Đăng nhập / Kiểm tra / Mở / Bật-Tắt / Xóa.

### Cơ chế
- **Xoay vòng**: mỗi yêu cầu ảnh chọn acc khỏe nhất (ít lỗi/ít dùng), vòng tròn.
- **Tránh acc lỗi**: acc trả 403/hết quota → cooldown 120s, tự chuyển acc khác (retry tới 3 acc).
- **Song song**: tạo n ảnh chạy đồng thời qua nhiều acc (mặc định 4 luồng, đổi bằng biến
  môi trường `FLOW_MAX_WORKERS`). Token reCAPTCHA mint song song trên các trình duyệt acc.
- Endpoint vẽ vẫn là `http://localhost:8790` → app Wahu không phải đổi gì.

### File
| File | Vai trò |
|------|---------|
| `flow_accounts.py` | Quản lý acc + engine trình duyệt đa-acc (Chrome/CocCoc/Brave) |
| `flow_multi.py` | Tạo ảnh đa-acc song song + xoay vòng + retry |
| `flow_proxy_multi.py` | Proxy OpenAI-compatible đa-acc + API quản lý acc |
| `flow_accounts_ui.py` | Trang `/accounts` |
| `accounts.json` | Cấu hình các acc (tự sinh) |
| `accounts_data/` | User-data-dir riêng của các acc dedicated |

### Lưu ý
- Mỗi acc cần **đăng nhập Flow ít nhất 1 lần** (Google account có quyền dùng Flow).
- Vẫn là tự động hoá vượt chống-bot Google: dùng nhiều acc giúp phân tán nhưng vẫn có rủi ro
  khóa tài khoản. Cân nhắc dùng acc phụ.
