"""
gui.py
واجهة المستخدم (Tkinter) وشريط المهام (System Tray)
تم تعديل التصميم ليكون بالثيم الفاتح (Light Theme) مطابقاً للصورة المطلوبة
"""
import os
import threading
import time
import tkinter as tk
from tkinter import ttk
import pystray
from PIL import Image, ImageDraw

from config import HOST, PORT, APP_VERSION, ENABLE_AUTO_UPDATE, UPDATE_CHECK_INTERVAL, ICON_PATH
from logger import log
from database import get_all_jobs, delete_job, restart_job
from updater import check_for_updates

def make_tray_icon():
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.ellipse([2, 2, 62, 62], fill="#1a73e8")
    d.rectangle([14, 26, 50, 44], fill="white")
    d.rectangle([20, 18, 44, 28], fill="white")
    d.rectangle([20, 38, 44, 50], fill="#e8f0fe")
    d.ellipse([40, 30, 46, 36], fill="#1a73e8")
    return img

class PrintServerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CloudERP Print Server")
        self.root.geometry("900x550")
        self.root.minsize(800, 450)
        self.root.configure(bg="#f0f4f8") # خلفية فاتحة
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        try:
            if os.path.exists(ICON_PATH):
                self._window_icon = tk.PhotoImage(file=ICON_PATH)
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

        self._build_ui()
        self._start_jobs_poller()
        self._start_update_poller()

    def _build_ui(self):
        FONT_MONO  = ("Segoe UI", 10)
        BG         = "#f4f7fb"  # لون خلفية النافذة الأساسي
        CARD       = "#ffffff"  # البطاقات باللون الأبيض
        ACCENT     = "#0f4b8f"  # الأزرق الغامق للنصوص
        GREEN_BG   = "#d4edda"  # خلفية زر الحالة الأخضر
        GREEN_FG   = "#155724"  # لون نص زر الحالة الأخضر
        TEXT       = "#333333"  # النصوص العادية
        MUTED      = "#6c757d"  # النصوص الثانوية (الرمادي)

        self.root.configure(bg=BG)

        # الشريط العلوي (Header)
        header = tk.Frame(self.root, bg=BG, height=70)
        header.pack(fill="x", padx=20, pady=15)
        header.pack_propagate(False)

        # العنوان على اليسار
        title_frame = tk.Frame(header, bg=BG)
        title_frame.pack(side="left")
        tk.Label(title_frame, text="🖨", font=("Segoe UI", 26), bg=BG, fg=ACCENT).pack(side="left", padx=(0, 10))
        tk.Label(title_frame, text="QaratErp Print Server", font=("Segoe UI Semibold", 18), bg=BG, fg=ACCENT).pack(side="left")

        # الحالة على اليمين
        status_frame = tk.Frame(header, bg=BG)
        status_frame.pack(side="right", fill="y")
        
        # زر التشغيل الأخضر
        pill_frame = tk.Frame(status_frame, bg=GREEN_BG, padx=12, pady=6, highlightbackground="#c3e6cb", highlightthickness=1)
        pill_frame.pack(side="right", padx=(15, 0), pady=12)
        self.status_dot = tk.Label(pill_frame, text="● RUNNING ✔", font=("Segoe UI", 10, "bold"), bg=GREEN_BG, fg=GREEN_FG)
        self.status_dot.pack()

        # التحديثات والرابط
        self.update_label = tk.Label(status_frame, text="Checking updates...", font=("Segoe UI", 11), bg=BG, fg=MUTED)
        self.update_label.pack(side="right", padx=15, pady=18)

        tk.Label(status_frame, text=f"http://{HOST}:{PORT}", font=("Segoe UI", 11), bg=BG, fg=TEXT).pack(side="right", padx=15, pady=18)

        # خط فاصل
        tk.Frame(self.root, bg="#dce1e6", height=1).pack(fill="x")

        # مساحة المحتوى الأساسية
        main_frame = tk.Frame(self.root, bg=BG)
        main_frame.pack(fill="both", expand=True, padx=25, pady=20)

        # عنوان الجدول
        tk.Label(main_frame, text="Recent Jobs", font=("Segoe UI Semibold", 13), bg=BG, fg="#000000", anchor="w").pack(fill="x", pady=(0, 10))

        # إطار يحتوي على الجدول والأزرار الجانبية
        content_frame = tk.Frame(main_frame, bg=BG)
        content_frame.pack(fill="both", expand=True)

        # بطاقة الجدول البيضاء
        table_card = tk.Frame(content_frame, bg=CARD, highlightbackground="#e2e8f0", highlightthickness=1)
        table_card.pack(side="left", fill="both", expand=True)

        cols = ("id", "status", "type", "printer", "filename", "response", "created")
        self.tree = ttk.Treeview(table_card, columns=cols, show="headings", height=8)

        # إعداد ستايل الجدول ليطابق الصورة
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=CARD, foreground=TEXT, fieldbackground=CARD, rowheight=40, font=FONT_MONO, borderwidth=0)
        style.configure("Treeview.Heading", background=CARD, foreground="#000000", font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Treeview", background=[("selected", "#e3f2fd")], foreground=[("selected", "#000000")])

        # تعيين أعمدة الجدول
        widths = {"id": 50, "status": 80, "type": 90, "printer": 200, "filename": 180, "response": 120, "created": 100}
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=widths.get(c, 100), anchor="center" if c in ("id", "status", "type") else "w")

        # شريط التمرير
        sb = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        sb.pack(side="right", fill="y", pady=2, padx=(0, 2))

        # إطار الأزرار الجانبية
        action_frame = tk.Frame(content_frame, bg=BG)
        action_frame.pack(side="right", fill="y", padx=(20, 0))

        # زر إعادة التشغيل
        self.btn_restart = tk.Button(
            action_frame, 
            text="⟳\n\nRestart\nSelected Job", 
            font=("Segoe UI", 11), 
            bg=CARD, 
            fg=TEXT, 
            relief="solid", 
            bd=1,
            cursor="hand2",
            width=14,
            height=5,
            command=self._restart_selected_job
        )
        self.btn_restart.pack(side="top", fill="x", pady=0)
        
        # زر الحذف
        self.btn_delete = tk.Button(
            action_frame, 
            text="🗑\n\nDelete\nSelected Job", 
            font=("Segoe UI", 11), 
            bg=CARD, 
            fg="#dc3545", 
            relief="solid", 
            bd=1,
            cursor="hand2",
            width=14,
            height=5,
            command=self._delete_selected_job
        )
        self.btn_delete.pack(side="top", fill="x", pady=(15, 0))

        # القائمة عند الضغط بالزر الأيمن
        self._job_menu = tk.Menu(self.root, tearoff=0)
        self._job_menu.add_command(label="Restart Job", command=self._restart_selected_job)
        self._job_menu.add_command(label="Delete Job", command=self._delete_selected_job)
        self.tree.bind("<Button-3>", self._on_job_right_click)

        # ألوان الحالات
        self.tree.tag_configure("done", foreground="#28a745")
        self.tree.tag_configure("failed", foreground="#dc3545")
        self.tree.tag_configure("pending", foreground="#ffc107")
        self.tree.tag_configure("processing", foreground="#007bff")

    def _start_jobs_poller(self):
        def poll():
            self._refresh_jobs()
            self.root.after(3000, poll)
        self.root.after(1000, poll)

    def _update_status(self, text):
        try: self.update_label.config(text=text)
        except Exception: pass

    def _check_update_now(self):
        self._update_status("Checking updates...")
        def run():
            status = check_for_updates()
            self.root.after(0, lambda: self._update_status(status))
        threading.Thread(target=run, daemon=True).start()

    def _start_update_poller(self):
        if not ENABLE_AUTO_UPDATE: return
        def poll():
            while True:
                status = check_for_updates()
                self.root.after(0, lambda s=status: self._update_status(s))
                time.sleep(UPDATE_CHECK_INTERVAL)
        threading.Thread(target=poll, daemon=True).start()

    def _refresh_jobs(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for j in get_all_jobs(50):
            tag = j["status"]
            
            # تجميل نوع الملف
            job_type = str(j.get("type", "")).upper()
            if job_type == "PDF":
                type_display = "📄 PDF"
            elif job_type == "IMAGE":
                type_display = "🖼 IMG"
            elif job_type == "HTML":
                type_display = "🌐 HTML"
            elif job_type == "ZPL":
                type_display = "🏷 ZPL"
            else:
                type_display = job_type

            # استخراج التاريخ فقط للتبسيط كالصورة (أو يمكن إبقاء الوقت)
            created_date = str(j["created"]).split(" ")[0] if j["created"] else ""

            self.tree.insert("", "end",
                values=(j["id"], j["status"], type_display,
                        j["printer"], j["filename"], j["printer_response"], created_date),
                tags=(tag,))

    def _on_job_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            try: self._job_menu.tk_popup(event.x_root, event.y_root)
            finally: self._job_menu.grab_release()

    def _get_selected_job_id(self):
        selection = self.tree.selection()
        if not selection: return None
        values = self.tree.item(selection[0], "values")
        return int(values[0]) if values else None

    def _delete_selected_job(self):
        job_id = self._get_selected_job_id()
        if job_id is None: return
        delete_job(job_id)
        self._refresh_jobs()
        log(f"Job deleted: {job_id}")

    def _restart_selected_job(self):
        job_id = self._get_selected_job_id()
        if job_id is None: return
        restart_job(job_id)
        self._refresh_jobs()
        log(f"Job restarted: {job_id}")

    def hide_window(self): self.root.withdraw()
    
    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self, icon=None, item=None):
        try: icon.stop()
        except Exception: pass
        self.root.quit()
        os._exit(0)

    def run(self):
        if os.path.exists(ICON_PATH): tray_img = Image.open(ICON_PATH)
        else: tray_img = make_tray_icon()
        
        menu = pystray.Menu(
            pystray.MenuItem("Open Print Server", self.show_window, default=True),
            pystray.MenuItem("Check for Updates", self._check_update_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit_app),
        )
        icon = pystray.Icon("CloudERP Print", tray_img, "CloudERP Print Server", menu)
        threading.Thread(target=icon.run, daemon=True).start()
        
        self.show_window()
        self.root.mainloop()
