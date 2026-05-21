# 9Router Image Studio Pro (App + CLI)

Ứng dụng tạo/sửa/ghép/dịch ảnh qua API `9Router /v1/images/generations` với giao diện tiếng Việt, gọn và dễ dùng.

## Tính năng chính
- Điều hướng nhiều trang, tách rõ từng chức năng để đỡ rối.
- 5 luồng tạo ảnh riêng:
  - `Tạo ảnh`
  - `Sửa ảnh`
  - `Ghép ảnh`
  - `Dịch ảnh`
  - `Làm truyện`
- Luồng `Làm truyện` mới hỗ trợ comic builder nhiều trang/panel:
  - Thêm nhiều nhân vật (nhân vật 1, 2, 3...) và tải ảnh mẫu riêng từng nhân vật.
  - Nhập lệnh riêng cho từng khung, nhập thoại bong bóng cho nhân vật 1/2 và chữ dẫn truyện.
  - Chọn style truyện: Anime, Manga đen trắng, Webtoon màu, Chibi, Semi-realistic.
  - Bật/tắt giữ nhất quán nhân vật giữa các trang.
  - Sắp xếp panel bằng nút lên/xuống, thêm/xóa trang, xuất truyện thành PNG/PDF.
- Trang `Train LoRA` mới:
  - Tải nhiều ảnh nhân vật và chỉnh caption theo từng ảnh.
  - Nhập đường dẫn thư mục ảnh local (hoặc `file:///...`) để app tự quét toàn bộ ảnh và nạp dataset train.
  - Chia rõ chức năng train: `Train nhân vật`, `Train nét vẽ`, `Train sản phẩm`, `Train logo/chữ`, `Train concept chung`.
  - Có nút `Áp cơ chế train` để tự set loại LoRA, preset train, trigger token và caption gợi ý theo chức năng.
  - Có phần `Cơ chế train (ghi rõ)` mô tả từng bước từ nạp ảnh -> tạo caption -> đóng gói payload -> gửi job.
  - Chọn preset train (Nhanh thử / Nhân vật chuẩn / Chi tiết cao).
  - Cấu hình train nâng cao: steps, epochs, LR, dim/alpha, resolution...
  - Gửi job train qua API endpoint tùy chỉnh + theo dõi trạng thái job.
  - Xuất dataset local vào `outputs/lora_datasets/...` để dùng lại.
- Hỗ trợ ảnh tham chiếu:
  - Tải file ảnh lên
  - Dán URL ảnh
  - Dán chuỗi `base64` (mỗi dòng 1 ảnh)
- Có preset thông số sẵn để giảm nhập tay.
- Hỗ trợ nhiều API key để chia batch vẽ song song (multi-key parallel).
- Chế độ `Chia nhiều API (song song)` có thể tách batch ngay cả khi chỉ có 1 key,
  cho phép đẩy nhiều luồng hơn (tối đa 60, ví dụ 30 ảnh/lượt).
- Có tùy chỉnh ổn định mạng: `Timeout request`, `Retry khi timeout`, `Backoff retry` cho các luồng vẽ.
- Tự lưu lịch sử và xem lại ảnh đã tạo.

## Các tệp quan trọng
- `D:\TOOL\TOOL Anh\nine_router_image_app.py`: app Streamlit giao diện web.
- `D:\TOOL\TOOL Anh\nine_router_image.py`: CLI discover/info/generate.
- `D:\TOOL\TOOL Anh\setup_9router_image_app.bat`: setup 1 lần.
- `D:\TOOL\TOOL Anh\run_9router_image_app.bat`: chạy app.
- `D:\TOOL\TOOL Anh\.env.9router`: cấu hình URL/KEY.

## 1) Cài đặt nhanh
1. Chạy `D:\TOOL\TOOL Anh\setup_9router_image_app.bat`.
2. Mở `D:\TOOL\TOOL Anh\.env.9router` và điền:
   - `NINEROUTER_URL=http://localhost:20128`
   - `NINEROUTER_KEY=...` (nếu server bật auth)
3. Chạy `D:\TOOL\TOOL Anh\run_9router_image_app.bat`.
4. Mở trình duyệt tại [http://localhost:8501](http://localhost:8501).

## 2) Cách mở app thủ công (không dùng .bat)
```bash
cd "D:\TOOL\TOOL Anh"
.venv\Scripts\python.exe -m streamlit run nine_router_image_app.py --server.headless true --server.port 8501 --server.address 0.0.0.0
```

## 3) Điều hướng trong app
- `🏠 Tổng quan`: dashboard, thống kê nhanh, ảnh gần đây.
- `🎨 Studio`: 5 luồng vẽ trong cùng một nơi (tạo/sửa/ghép/dịch/làm truyện).
  - Trong `Thiết lập chung` có chế độ `Chia nhiều API (song song)` để vẽ nhiều ảnh một lúc.
- `✨ Preset`: áp dụng preset nhanh.
- `🧬 Train LoRA`: tạo dataset train từ nhiều ảnh và quản lý job train.
- `🧠 Model`: tìm model + xem info + gợi ý tham số.
- `🖼️ Thư viện`: xem lịch sử, lọc và nhóm theo ngày.
- `⚙️ Cài đặt`: lưu/nạp `.env`, sân chơi API, lệnh CLI mẫu.

## 4) Lưu ảnh theo ngày
- Ảnh tạo mới được tự động lưu vào: `outputs/history/YYYY-MM-DD`.
- Thư viện hiển thị theo ngày để dễ tìm lại ảnh cũ.

## 5) CLI nhanh (tùy chọn)
```bash
python nine_router_image.py discover
python nine_router_image.py info --id openai/dall-e-3
python nine_router_image.py generate --model cx/gpt-5.4-image --prompt "neon city" --response-format binary --output outputs/out.png
```
