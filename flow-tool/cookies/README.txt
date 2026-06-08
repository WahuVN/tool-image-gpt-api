NẠP COOKIE FLOW KHÔNG CẦN MỞ TRÌNH DUYỆT
=========================================

Cách 1 - Thả file vào đây:
  - Tạo file tên theo acc, ví dụ: flow01.txt  (hoặc flow01.json)
  - Nội dung: 1 trong 3 định dạng
      a) Chuỗi header:  __Secure-next-auth.session-token=....; khac=....
         (DevTools > Network > chọn request labs.google > Headers > Cookie, copy hết)
      b) JSON export từ extension "Cookie-Editor" / "EditThisCookie"
      c) Netscape cookies.txt
  - Proxy tự nạp khi khởi động, khi mở trang /accounts, hoặc bấm "Nạp từ thư mục".
  - File nạp xong được chuyển vào cookies/imported/.

Cách 2 - Trang quản lý:  http://localhost:8790/accounts
  - Card "Nạp cookie trực tiếp": điền tên acc + dán cookie + bấm Nạp.

Cách 3 - Dòng lệnh:
  python flow_cookies_cli.py import flow01 --file cookies\flow01.txt
  python flow_cookies_cli.py import flow01 --clip      (đọc từ clipboard)
  python flow_cookies_cli.py reload
  python flow_cookies_cli.py list
  python flow_cookies_cli.py log -n 50

QUAN TRỌNG: cookie phải có __Secure-next-auth.session-token (domain labs.google)
thì acc mới "sẵn sàng". Cookie hết hạn -> nạp lại cookie mới (không cần đăng nhập lại
trong tool, chỉ cần copy cookie từ trình duyệt đã đăng nhập).
