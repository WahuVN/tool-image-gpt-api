# -*- coding: utf-8 -*-
"""
Tool vẽ ảnh bằng Google Labs Flow API (giao diện đồ hoạ).

- Tự lấy cookie đăng nhập từ Brave (hoặc Chrome/Edge), hoặc dán tay.
- Nhập prompt, chọn model / tỉ lệ / số ảnh / seed -> tạo ảnh.
- Hiển thị ảnh và lưu vào thư mục output/.

Chạy:  python gui.py     (hoặc nhấp đúp run_gui.bat)
"""

import os
import threading
import traceback
import pathlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cookie_grabber as cg
from flow_client import FlowClient, FlowError

HERE = pathlib.Path(__file__).parent
COOKIE_FILE = HERE / "flow_cookie.txt"

ASPECTS = ["LANDSCAPE", "PORTRAIT", "SQUARE"]
ASPECT_MAP = {
    "LANDSCAPE": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "PORTRAIT": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "SQUARE": "IMAGE_ASPECT_RATIO_SQUARE",
}
MODELS = ["NARWHAL", "IMAGEN_3_5", "IMAGEN_3_1"]


class FlowGUI:
    def __init__(self, root):
        self.root = root
        root.title("Flow Image Tool - Google Labs Flow API")
        root.geometry("960x720")

        self.client = None
        self._busy = False
        self._images = []  # giữ tham chiếu PhotoImage

        self._build_ui()
        self._load_existing_cookie()

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        # --- Khung cookie ---
        cf = ttk.LabelFrame(self.root, text="1. Cookie (KHÔNG bắt buộc - chế độ Brave tự lấy)")
        cf.pack(fill="x", **pad)

        row = ttk.Frame(cf); row.pack(fill="x", **pad)
        ttk.Label(row, text="Trình duyệt:").pack(side="left")
        self.browser_var = tk.StringVar(value="brave")
        ttk.Combobox(row, textvariable=self.browser_var,
                     values=["brave", "chrome", "edge"], width=10,
                     state="readonly").pack(side="left", padx=4)
        ttk.Button(row, text="Tự lấy cookie từ trình duyệt",
                   command=self.on_grab_cookie).pack(side="left", padx=4)
        self.cookie_status = ttk.Label(row, text="Chưa có cookie", foreground="#b00")
        self.cookie_status.pack(side="left", padx=8)

        self.cookie_text = tk.Text(cf, height=3, wrap="none")
        self.cookie_text.pack(fill="x", **pad)
        ttk.Label(cf, text="(Có thể dán cookie thủ công vào ô trên rồi bấm Lưu cookie)",
                  foreground="#666").pack(anchor="w", padx=6)
        ttk.Button(cf, text="Lưu cookie", command=self.on_save_cookie).pack(anchor="e", padx=6, pady=2)

        # --- Khung tham số ---
        pf = ttk.LabelFrame(self.root, text="2. Tham số tạo ảnh")
        pf.pack(fill="x", **pad)

        r1 = ttk.Frame(pf); r1.pack(fill="x", **pad)
        ttk.Label(r1, text="Prompt:").pack(side="left")
        self.prompt_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self.prompt_var).pack(side="left", fill="x", expand=True, padx=4)

        r2 = ttk.Frame(pf); r2.pack(fill="x", **pad)
        ttk.Label(r2, text="Model:").pack(side="left")
        self.model_var = tk.StringVar(value="NARWHAL")
        ttk.Combobox(r2, textvariable=self.model_var, values=MODELS, width=14).pack(side="left", padx=4)
        ttk.Label(r2, text="Tỉ lệ:").pack(side="left", padx=(10, 0))
        self.aspect_var = tk.StringVar(value="LANDSCAPE")
        ttk.Combobox(r2, textvariable=self.aspect_var, values=ASPECTS, width=12,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(r2, text="Số ảnh:").pack(side="left", padx=(10, 0))
        self.n_var = tk.IntVar(value=1)
        ttk.Spinbox(r2, from_=1, to=8, textvariable=self.n_var, width=5).pack(side="left", padx=4)
        ttk.Label(r2, text="Seed:").pack(side="left", padx=(10, 0))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(r2, textvariable=self.seed_var, width=12).pack(side="left", padx=4)

        r3 = ttk.Frame(pf); r3.pack(fill="x", **pad)
        self.show_browser_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="Hiện trình duyệt captcha (debug)",
                        variable=self.show_browser_var).pack(side="left")
        ttk.Label(r3, text="Số trình duyệt:").pack(side="left", padx=(10, 0))
        self.browsers_var = tk.IntVar(value=2)
        ttk.Spinbox(r3, from_=1, to=4, textvariable=self.browsers_var, width=5).pack(side="left", padx=4)
        self.gen_btn = ttk.Button(r3, text="TẠO ẢNH", command=self.on_generate)
        self.gen_btn.pack(side="right", padx=4)

        # --- Khung ảnh ---
        imgf = ttk.LabelFrame(self.root, text="3. Kết quả")
        imgf.pack(fill="both", expand=True, **pad)
        self.canvas = tk.Canvas(imgf, bg="#222", height=320)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.img_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.img_frame, anchor="nw")

        # --- Log ---
        self.log = tk.Text(self.root, height=8, bg="#111", fg="#0f0", wrap="word")
        self.log.pack(fill="x", **pad)

    # ------------------------------------------------------------- helpers
    def _log(self, msg):
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def _load_existing_cookie(self):
        if COOKIE_FILE.exists():
            c = COOKIE_FILE.read_text(encoding="utf-8").strip()
            if c:
                self.cookie_text.delete("1.0", "end")
                self.cookie_text.insert("1.0", c)
                self._set_cookie_ok(c)

    def _set_cookie_ok(self, cookie):
        has = "session-token" in cookie
        if has:
            self.cookie_status.config(text=f"Cookie OK ({len(cookie)} ký tự)", foreground="#080")
        else:
            self.cookie_status.config(
                text="Có cookie nhưng thiếu session-token (?)", foreground="#a60")

    # -------------------------------------------------------------- events
    def on_grab_cookie(self):
        browser = self.browser_var.get()
        try:
            self._log(f"Đang lấy cookie từ {browser}...")
            cookie = cg.grab_cookies(browser)
            self._apply_cookie(cookie)
        except cg.CookieError as e:
            msg = str(e)
            if "bị khoá" in msg or "locked" in msg.lower():
                if messagebox.askyesno(
                    "Trình duyệt đang khoá cookie",
                    f"{browser} đang mở nên file cookie bị khoá.\n\n"
                    "Đóng hẳn trình duyệt để lấy cookie? (Bạn mở lại sau, các tab sẽ được khôi phục)"):
                    self._log(f"Đóng {browser}...")
                    cg.close_browser(browser)
                    try:
                        cookie = cg.grab_cookies(browser)
                        self._apply_cookie(cookie)
                    except cg.CookieError as e2:
                        messagebox.showerror("Lỗi", str(e2))
                        self._log(f"[LỖI] {e2}")
            else:
                messagebox.showerror("Lỗi lấy cookie", msg)
                self._log(f"[LỖI] {msg}")

    def _apply_cookie(self, cookie):
        self.cookie_text.delete("1.0", "end")
        self.cookie_text.insert("1.0", cookie)
        COOKIE_FILE.write_text(cookie, encoding="utf-8")
        self._set_cookie_ok(cookie)
        self._log(f"Đã lấy & lưu cookie ({len(cookie)} ký tự). session-token: {'session-token' in cookie}")

    def on_save_cookie(self):
        cookie = self.cookie_text.get("1.0", "end").strip()
        if not cookie:
            messagebox.showwarning("Trống", "Chưa có cookie để lưu.")
            return
        COOKIE_FILE.write_text(cookie, encoding="utf-8")
        self._set_cookie_ok(cookie)
        self._log("Đã lưu cookie thủ công.")

    def on_generate(self):
        if self._busy:
            return
        prompt = self.prompt_var.get().strip()
        if not prompt:
            messagebox.showwarning("Thiếu prompt", "Hãy nhập mô tả ảnh.")
            return
        # Chế độ brave: không cần cookie (tự lấy từ Brave). Chỉ cần cho chế độ solver.
        cookie = self.cookie_text.get("1.0", "end").strip()

        self._busy = True
        self.gen_btn.config(state="disabled", text="Đang tạo...")
        threading.Thread(target=self._generate_worker, args=(prompt, cookie), daemon=True).start()

    def _generate_worker(self, prompt, cookie):
        try:
            seed = self.seed_var.get().strip()
            seed = int(seed) if seed else None
            n = max(1, int(self.n_var.get()))

            if self.client is None:
                self._log("Mở Brave và lấy token (lần đầu hơi chậm)...")
                self.client = FlowClient(
                    cookie=cookie,
                    headless=not self.show_browser_var.get(),
                    num_browsers=int(self.browsers_var.get()),
                    output_dir=str(HERE / "output"),
                    token_mode="brave",
                )
                self.client.start()
            elif cookie:
                # cập nhật cookie mới nếu người dùng dán
                self.client.cookie = cookie
                self.client._session.headers["Cookie"] = cookie

            self._log(f"Tạo {n} ảnh cho prompt: {prompt!r} ...")
            paths = self.client.generate_images(
                prompt=prompt,
                model=self.model_var.get().strip() or "NARWHAL",
                aspect_ratio=ASPECT_MAP[self.aspect_var.get()],
                n=n,
                seed=seed,
            )
            self._log("Hoàn tất. Đang hiển thị...")
            self.root.after(0, lambda: self._show_images(paths))
        except FlowError as e:
            self._log(f"[LỖI Flow] {e}")
            self.root.after(0, lambda: messagebox.showerror("Lỗi Flow", str(e)))
        except Exception as e:
            self._log(f"[LỖI] {e}\n{traceback.format_exc()}")
            self.root.after(0, lambda: messagebox.showerror("Lỗi", str(e)))
        finally:
            self._busy = False
            self.root.after(0, lambda: self.gen_btn.config(state="normal", text="TẠO ẢNH"))

    def _show_images(self, paths):
        for w in self.img_frame.winfo_children():
            w.destroy()
        self._images.clear()
        col = 0
        for p in paths:
            try:
                img = tk.PhotoImage(file=p)
                # thu nhỏ nếu quá to
                factor = max(1, img.width() // 280)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self._images.append(img)
                cell = ttk.Frame(self.img_frame)
                cell.grid(row=0, column=col, padx=6, pady=6)
                tk.Label(cell, image=img).pack()
                ttk.Label(cell, text=pathlib.Path(p).name, wraplength=280).pack()
                col += 1
            except Exception as e:
                self._log(f"Không hiển thị được {p}: {e}")
        self.img_frame.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        self._log(f"Đã lưu {len(paths)} ảnh trong: {HERE / 'output'}")

    def on_close(self):
        try:
            if self.client:
                self.client.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FlowGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
