# Wahu Image Studio (App + CLI)

Ứng dụng tạo/sửa/ghép/dịch ảnh qua API `9Router /v1/images/generations` với giao diện tiếng Việt, gọn và dễ dùng.

## Tính năng chính
- Điều hướng nhiều trang, tách rõ từng chức năng để đỡ rối.
- 8 tác vụ trong cùng trang Studio:
  - `Tạo ảnh` — prompt + tham chiếu ảnh + tham số Advanced (CFG, Steps, Detail, Sampler, Seed, Clip Skip, Negative).
  - `AI đa năng (copy ảnh + lệnh tự do)` — dán ảnh + gõ lệnh, hệ thống tự dựng prompt.
  - `Làm truyện tranh` — comic builder nhiều trang/khung, giữ nhất quán nhân vật, xuất PNG/PDF.
  - `Sửa ảnh nâng cao` — style/quality/strength/seed/sampler/steps/multi-API.
  - `Sửa ảnh` — upload + mô tả phần cần sửa, mức chỉnh.
  - `Nâng cấp chất lượng` — upscale + khử nhiễu giữ bố cục.
  - `Dịch ảnh` — đổi chữ trên ảnh sang ngôn ngữ khác, giữ font/bố cục.
  - `Sao chép phong cách` — Ảnh 1 = chủ thể, Ảnh 2 = phong cách; có sẵn kịch bản 1 chạm.
- Trang `Train LoRA`:
  - Tải nhiều ảnh nhân vật và chỉnh caption từng ảnh.
  - Quét folder ảnh local làm dataset train.
  - 5 chức năng train: nhân vật / nét vẽ / sản phẩm / logo-chữ / concept chung.
  - Preset train (Nhanh thử / Nhân vật chuẩn / Chi tiết cao) + cấu hình nâng cao.
  - Gửi job train qua endpoint tùy chỉnh + theo dõi trạng thái job.
- Hỗ trợ ảnh tham chiếu: upload, dán URL, dán base64, dán clipboard OS.
- Multi-key parallel: chia 1 batch nhiều ảnh sang nhiều API key, tối đa 60 luồng.
- Tùy chỉnh ổn định mạng: Timeout, Retry, Backoff.
- Khi có lỗi timeout / rate limit, app gợi ý đề xuất khắc phục nhanh ngay tại chỗ (tăng timeout +120s, giảm số ảnh, giảm luồng song song).
- Tự lưu lịch sử và xem lại ảnh đã tạo theo ngày.

## Các tệp quan trọng
- `nine_router_image_app.py` — app Streamlit (giao diện web/desktop).
- `nine_router_image.py` — CLI discover/info/generate.
- `wahu_desktop_app.py` — launcher mở app trong cửa sổ Edge/Chrome dạng desktop.
- `setup_9router_image_app.bat` — setup 1 lần (venv + dependencies + .env mẫu).
- `run_9router_image_app.bat` — chạy app dạng web (cửa sổ cmd).
- `run_wahu_desktop_app.bat` — chạy app dạng desktop window.
- `launch_wahu.vbs` — launcher chạy ngầm, không có cửa sổ cmd đen.
- `create_desktop_shortcut.bat` — tạo shortcut "Wahu Image Studio" trên Desktop.
- `.env.9router` — cấu hình `NINEROUTER_URL` / `NINEROUTER_KEY`.

## 1) Cài đặt nhanh
1. Chạy `setup_9router_image_app.bat`.
2. Mở `.env.9router` và điền:
   - `NINEROUTER_URL=http://localhost:20128`
   - `NINEROUTER_KEY=...` (nếu server bật auth)
3. Chạy `run_9router_image_app.bat` (web) hoặc `run_wahu_desktop_app.bat` (desktop window).
4. Mặc định mở tại [http://localhost:8501](http://localhost:8501).

## 2) Tạo shortcut "Wahu Image Studio" trên Desktop (1 click là mở app)
1. Chạy `create_desktop_shortcut.bat` (chỉ cần 1 lần).
2. Trên Desktop sẽ xuất hiện icon **Wahu Image Studio**. Nhấp đúp là app tự khởi server và mở Edge/Chrome ở chế độ desktop window.
3. Không có cửa sổ cmd đen vì shortcut gọi `launch_wahu.vbs` chạy ngầm.
4. Click lần nữa khi server đang chạy: chỉ mở thêm cửa sổ browser, không khởi server thứ hai.

## 3) Cách mở app thủ công (không dùng .bat)
```bash
cd "D:\TOOL\TOOL Anh"
.venv\Scripts\python.exe -m streamlit run nine_router_image_app.py --server.headless true --server.port 8501 --server.address 0.0.0.0
```

## 4) Điều hướng trong app
- `🏠 Tổng quan` — dashboard, thống kê nhanh, ảnh gần đây.
- `🎨 Studio` — 8 tác vụ vẽ trong cùng 1 trang qua thanh chọn `Tác vụ`.
  - Tham số Advanced (CFG / Steps / Detail / Sampler / Seed / Clip Skip / Negative) chỉ vào payload khi user chỉnh khỏi mặc định.
  - Khi gặp lỗi timeout/rate limit, app gợi ý đề xuất khắc phục nhanh ngay tại chỗ.
- `🧬 Train LoRA` — tạo dataset train từ nhiều ảnh và quản lý job train.
- `🧠 Model` — tìm model + xem info + gợi ý tham số.
- `🖼️ Thư viện` — lịch sử ảnh, lọc và nhóm theo ngày.
- `⚙️ Cài đặt` — lưu/nạp `.env`, sân chơi API, lệnh CLI mẫu.

## 5) Lưu ảnh theo ngày
- Ảnh tạo mới được tự động lưu vào: `outputs/history/YYYY-MM-DD/`.
- Trang Thư viện hiển thị theo ngày để dễ tìm lại ảnh cũ.

## 6) CLI nhanh (tùy chọn)
```bash
python nine_router_image.py discover
python nine_router_image.py info --id openai/dall-e-3
python nine_router_image.py generate --model cx/gpt-5.4-image --prompt "neon city" --response-format binary --output outputs/out.png
```
