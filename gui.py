"""
gui.py
واجهة المستخدم (Tkinter) وشريط المهام (System Tray)
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
        self.root.geometry("850x480")
        self.root.minsize(700, 380)
        self.root.configure(bg="#0f1117")
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
        FONT_MONO  = ("Consolas", 9)
        BG         = "#0f1117"
        CARD       = "#1c1f2b"
        ACCENT     = "#1a73e8"
        GREEN      = "#34a853"
        TEXT       = "#e8eaf6"
        MUTED      = "#7986cb"

        header = tk.Frame(self.root, bg=ACCENT, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="🖨  QaratErp Print Server",
                 font=("Segoe UI Semibold", 14), bg=ACCENT, fg="white"
                 ).pack(side="left", padx=18, pady=12)

        self.status_dot = tk.Label(header, text="● RUNNING",
                                   font=("Segoe UI", 9, "bold"),
                                   bg=ACCENT, fg=GREEN)
        self.status_dot.pack(side="right", padx=18)

        self.update_label = tk.Label(header, text="Checking updates...", font=("Segoe UI", 9), bg=ACCENT, fg="#b3c7f7")
        self.update_label.pack(side="right", padx=8)

        tk.Label(header, text=f"http://{HOST}:{PORT}", font=FONT_MONO, bg=ACCENT, fg="#b3c7f7").pack(side="right", padx=4)

        pane = tk.PanedWindow(self.root, orient="vertical", bg=BG, sashwidth=6, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=10, pady=10)

        jobs_frame = tk.Frame(pane, bg=CARD)
        tk.Label(jobs_frame, text="  Recent Jobs", font=("Segoe UI Semibold", 10), bg=CARD, fg=MUTED, anchor="w").pack(fill="x", pady=(6, 0))

        cols = ("id", "status", "type", "printer", "filename", "response", "created")
        self.tree = ttk.Treeview(jobs_frame, columns=cols, show="headings", height=8)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#0a0d14", foreground=TEXT, fieldbackground="#0a0d14", rowheight=24, font=FONT_MONO)
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED, font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])

        widths = {"id": 40, "status": 72, "type": 50, "printer": 120, "filename": 120, "response": 200, "created": 80}
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=widths.get(c, 100), anchor="w")

        sb = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 6))

        hint = tk.Label(jobs_frame, text="Right-click any job to restart or delete it.", font=("Segoe UI", 9), bg=CARD, fg="#9aa0c3", anchor="w")
        hint.pack(fill="x", padx=6, pady=(0, 4))

        self._job_menu = tk.Menu(self.root, tearoff=0)
        self._job_menu.add_command(label="Restart Job", command=self._restart_selected_job)
        self._job_menu.add_command(label="Delete Job", command=self._delete_selected_job)
        self.tree.bind("<Button-3>", self._on_job_right_click)

        action_bar = tk.Frame(jobs_frame, bg=CARD)
        action_bar.pack(fill="x", padx=6, pady=(0, 8))
        tk.Button(action_bar, text="Restart Job", command=self._restart_selected_job, font=("Segoe UI", 9), bg="#252840", fg=MUTED, relief="flat", cursor="hand2", padx=10).pack(side="left", padx=(0, 6))
        tk.Button(action_bar, text="Delete Job", command=self._delete_selected_job, font=("Segoe UI", 9), bg="#252840", fg=MUTED, relief="flat", cursor="hand2", padx=10).pack(side="left")

        self.tree.tag_configure("done",    foreground="#34a853")
        self.tree.tag_configure("failed",  foreground="#ea4335")
        self.tree.tag_configure("pending", foreground="#fbbc04")
        self.tree.tag_configure("processing", foreground="#4285f4")

        pane.add(jobs_frame, minsize=140)

        footer = tk.Frame(self.root, bg="#12151f", height=30)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="Minimise to hide • right-click tray icon to quit", font=("Segoe UI", 8), bg="#12151f", fg="#4a5080").pack(side="left", padx=12, pady=6)

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
            self.tree.insert("", "end",
                values=(j["id"], j["status"], j["type"],
                        j["printer"], j["filename"], j["printer_response"], j["created"]),
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
