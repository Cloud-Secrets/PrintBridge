"""
CloudERP Silent Print Server
Desktop GUI + System Tray app (no terminal window)
Dependencies: pip install fastapi uvicorn pywin32 pystray pillow
"""

import threading
import time
import os
import sys
import json
import base64
import tempfile
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext
import pystray
from PIL import Image, ImageDraw
import queue
import datetime

# ─── Embedded FastAPI server ─────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ─── Print queue (inline, no separate file needed) ────────────────────────────
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "print_queue.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            data     TEXT    NOT NULL,
            retries  INTEGER DEFAULT 0,
            status   TEXT    DEFAULT 'pending',
            created  TEXT    DEFAULT (datetime('now'))
        )
    """)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "retries" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN retries INTEGER DEFAULT 0")
    if "status" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'pending'")
    if "created" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN created TEXT")
        conn.execute("UPDATE jobs SET created = datetime('now') WHERE created IS NULL")

    conn.commit()
    conn.close()

def add_job(data: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO jobs (data) VALUES (?)", (json.dumps(data),))
    conn.commit()
    conn.close()

def get_pending_jobs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, data, retries FROM jobs WHERE status='pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return rows

def get_all_jobs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, status, retries, created, data FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = json.loads(r[4])
        result.append({
            "id": r[0], "status": r[1], "retries": r[2],
            "created": r[3], "type": d.get("type","?"),
            "filename": d.get("filename","?"), "printer": d.get("printer","?")
        })
    return result

def mark_done(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

def mark_failed(job_id, retries):
    status = "failed" if retries >= 3 else "pending"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET retries=?, status=? WHERE id=?", (retries, status, job_id))
    conn.commit()
    conn.close()


def delete_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()


def restart_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='pending', retries=0 WHERE id=?", (job_id,))
    conn.commit()
    conn.close()


# ─── Global log queue (thread-safe) ──────────────────────────────────────────
log_queue = queue.Queue()

def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_queue.put(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_exception(exc: Exception):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] EXCEPTION: {exc}"
    log_queue.put(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            import traceback
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass

# ─── Config ───────────────────────────────────────────────────────────────────
API_TOKEN  = "CloudErpToken"

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.argv[0])
    RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = APP_DIR

DB_PATH    = os.path.join(APP_DIR, "print_queue.db")
LOG_FILE   = os.path.join(APP_DIR, "print_server_app.log")
ICON_PATH  = os.path.join(RESOURCE_DIR, "icon.png")
SUMATRA    = os.path.join(RESOURCE_DIR, "SumatraPDF.exe")
HOST       = "127.0.0.1"
PORT       = 5000

# ─── FastAPI App ──────────────────────────────────────────────────────────────
api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

def auth(token):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def route_printer(printer_type):
    try:
        import win32print
        printers = win32print.EnumPrinters(2)
        names = [p[2] for p in printers]
        for p in names:
            if printer_type in p.lower():
                return p
        return names[0] if names else None
    except Exception:
        return None

def print_job(job):
    try:
        import win32print, win32api
    except ImportError:
        log("ERROR: pywin32 not installed")
        return

    data   = json.loads(job[1])
    job_id = job[0]

    try:
        temp      = tempfile.gettempdir()
        file_path = os.path.join(temp, data["filename"])

        if data["type"] == "pdf":
            pdf = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(pdf)
            subprocess.run([SUMATRA, "-print-to", data["printer"], file_path])
            log(f"PDF printed → {data['printer']}: {data['filename']}")

        elif data["type"] == "image":
            img = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(img)
            win32api.ShellExecute(0, "print", file_path, None, ".", 0)
            log(f"Image printed → {data['printer']}: {data['filename']}")

        elif data["type"] == "html":
            html_path = file_path + ".html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(data["content"])
            win32api.ShellExecute(0, "print", html_path, None, ".", 0)
            log(f"HTML printed → {data['printer']}: {data['filename']}")

        elif data["type"] == "zpl":
            zpl_data  = data["content"].encode("utf-8")
            zpl_path  = os.path.join(tempfile.gettempdir(), data["filename"] + ".zpl")
            with open(zpl_path, "wb") as f:
                f.write(zpl_data)
            hprinter = win32print.OpenPrinter(data["printer"])
            try:
                win32print.StartDocPrinter(hprinter, 1, ("ZPL Print", None, "RAW"))
                win32print.StartPagePrinter(hprinter)
                win32print.WritePrinter(hprinter, zpl_data)
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
            log(f"ZPL printed → {data['printer']}: {data['filename']}")

        mark_done(job_id)

    except Exception as e:
        retries = job[2] + 1
        log(f"ERROR job #{job_id} (attempt {retries}): {e}")
        mark_failed(job_id, retries)

def worker():
    log("Print worker started — polling every 2 s")
    while True:
        jobs = get_pending_jobs()
        for job in jobs:
            print_job(job)
        time.sleep(2)

threading.Thread(target=worker, daemon=True).start()

@api.get("/")
def home():
    return {"status": "running"}

@api.get("/printers")
def printers():
    try:
        import win32print
        return [p[2] for p in win32print.EnumPrinters(2)]
    except Exception:
        return []

@api.get("/jobs")
def get_jobs():
    return {"jobs": get_all_jobs()}

@api.post("/print")
def create_print(data: dict, authorization: str = Header(None)):
    auth(authorization)
    add_job(data)
    log(f"Job queued: {data.get('type','?')} / {data.get('filename','?')}")
    return {"status": "queued"}

@api.websocket("/ws")
async def ws_print(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        job  = json.loads(data)
        add_job(job)
        log(f"WS job queued: {job.get('type','?')}")
        await websocket.send_text("queued")

def start_uvicorn():
    if getattr(sys, "frozen", False):
        if sys.stderr is None or sys.stdout is None:
            try:
                stream = open(LOG_FILE, "a", encoding="utf-8")
                sys.stdout = stream
                sys.stderr = stream
            except Exception:
                pass

    log(f"API server starting on http://{HOST}:{PORT}")
    try:
        uvicorn.run(api, host=HOST, port=PORT, log_level="error", access_log=False)
    except Exception as exc:
        log_exception(exc)

threading.Thread(target=start_uvicorn, daemon=True).start()


# ─── Tray Icon ────────────────────────────────────────────────────────────────
def make_tray_icon():
    """Draw a simple printer icon as PNG in memory."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)

    # Background circle
    d.ellipse([2, 2, 62, 62], fill="#1a73e8")

    # Printer body
    d.rectangle([14, 26, 50, 44], fill="white")
    # Printer top (paper slot)
    d.rectangle([20, 18, 44, 28], fill="white")
    # Paper output
    d.rectangle([20, 38, 44, 50], fill="#e8f0fe")
    # Indicator dot
    d.ellipse([40, 30, 46, 36], fill="#1a73e8")

    return img

# ─── Main GUI Window ──────────────────────────────────────────────────────────
class PrintServerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CloudERP Print Server")
        self.root.geometry("700x480")
        self.root.minsize(580, 380)
        self.root.configure(bg="#0f1117")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Try to set the app icon from icon.png.
        try:
            if os.path.exists(ICON_PATH):
                self._window_icon = tk.PhotoImage(file=ICON_PATH)
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

        self._build_ui()
        # self._start_log_poller()
        self._start_jobs_poller()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        FONT_MONO  = ("Consolas", 9)
        FONT_LABEL = ("Segoe UI", 10)
        BG         = "#0f1117"
        CARD       = "#1c1f2b"
        ACCENT     = "#1a73e8"
        GREEN      = "#34a853"
        TEXT       = "#e8eaf6"
        MUTED      = "#7986cb"

        # ── Header ─────────────────────────────────────────────────────────
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

        tk.Label(header, text=f"http://{HOST}:{PORT}",
                 font=FONT_MONO, bg=ACCENT, fg="#b3c7f7"
                 ).pack(side="right", padx=4)

        # ── Main panes ─────────────────────────────────────────────────────
        pane = tk.PanedWindow(self.root, orient="vertical",
                              bg=BG, sashwidth=6, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Log panel ──────────────────────────────────────────────────────
        # log_frame = tk.Frame(pane, bg=CARD, bd=0)
        # tk.Label(log_frame, text="  Activity Log",
        #          font=("Segoe UI Semibold", 10),
        #          bg=CARD, fg=MUTED, anchor="w"
        #          ).pack(fill="x", pady=(6, 0))

        # self.log_box = scrolledtext.ScrolledText(
        #     log_frame, bg="#0a0d14", fg=TEXT,
        #     font=FONT_MONO, bd=0, relief="flat",
        #     insertbackground=TEXT, state="disabled",
        #     wrap="word", height=10
        # )
        # self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        # btn_bar = tk.Frame(log_frame, bg=CARD)
        # btn_bar.pack(fill="x", padx=6, pady=(0, 6))
        # tk.Button(btn_bar, text="Clear Log", command=self._clear_log,
        #           font=("Segoe UI", 9), bg="#252840", fg=MUTED,
        #           relief="flat", cursor="hand2", padx=10
        #           ).pack(side="right")

        # pane.add(log_frame, minsize=140)

        # ── Jobs panel ─────────────────────────────────────────────────────
        jobs_frame = tk.Frame(pane, bg=CARD)
        tk.Label(jobs_frame, text="  Recent Jobs",
                 font=("Segoe UI Semibold", 10),
                 bg=CARD, fg=MUTED, anchor="w"
                 ).pack(fill="x", pady=(6, 0))

        cols = ("id", "status", "type", "printer", "filename", "created")
        self.tree = ttk.Treeview(jobs_frame, columns=cols,
                                 show="headings", height=8)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#0a0d14", foreground=TEXT,
                        fieldbackground="#0a0d14", rowheight=24,
                        font=FONT_MONO)
        style.configure("Treeview.Heading",
                        background=CARD, foreground=MUTED,
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])

        widths = {"id": 40, "status": 72, "type": 60,
                  "printer": 160, "filename": 160, "created": 80}
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=widths.get(c, 100), anchor="w")

        sb = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 6))

        hint = tk.Label(jobs_frame,
                        text="Right-click any job to restart or delete it.",
                        font=("Segoe UI", 9), bg=CARD, fg="#9aa0c3",
                        anchor="w")
        hint.pack(fill="x", padx=6, pady=(0, 4))

        self._job_menu = tk.Menu(self.root, tearoff=0)
        self._job_menu.add_command(label="Restart Job", command=self._restart_selected_job)
        self._job_menu.add_command(label="Delete Job", command=self._delete_selected_job)
        self.tree.bind("<Button-3>", self._on_job_right_click)

        action_bar = tk.Frame(jobs_frame, bg=CARD)
        action_bar.pack(fill="x", padx=6, pady=(0, 8))
        tk.Button(action_bar, text="Restart Job",
                  command=self._restart_selected_job,
                  font=("Segoe UI", 9), bg="#252840", fg=MUTED,
                  relief="flat", cursor="hand2", padx=10
                  ).pack(side="left", padx=(0, 6))
        tk.Button(action_bar, text="Delete Job",
                  command=self._delete_selected_job,
                  font=("Segoe UI", 9), bg="#252840", fg=MUTED,
                  relief="flat", cursor="hand2", padx=10
                  ).pack(side="left")

        # Color tags
        self.tree.tag_configure("done",    foreground="#34a853")
        self.tree.tag_configure("failed",  foreground="#ea4335")
        self.tree.tag_configure("pending", foreground="#fbbc04")

        pane.add(jobs_frame, minsize=140)

        # ── Footer ─────────────────────────────────────────────────────────
        footer = tk.Frame(self.root, bg="#12151f", height=30)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        tk.Label(footer,
                 text="Minimise to hide • right-click tray icon to quit",
                 font=("Segoe UI", 8), bg="#12151f", fg="#4a5080"
                 ).pack(side="left", padx=12, pady=6)

    # ── Polling helpers ─────────────────────────────────────────────────────
    # def _start_log_poller(self):
    #     def poll():
    #         while not log_queue.empty():
    #             msg = log_queue.get_nowait()
    #             self.log_box.configure(state="normal")
    #             self.log_box.insert("end", msg + "\n")
    #             self.log_box.configure(state="disabled")
    #             self.log_box.see("end")
    #         self.root.after(500, poll)
    #     self.root.after(500, poll)

    def _start_jobs_poller(self):
        def poll():
            self._refresh_jobs()
            self.root.after(3000, poll)
        self.root.after(1000, poll)

    def _refresh_jobs(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for j in get_all_jobs(50):
            tag = j["status"]
            self.tree.insert("", "end",
                values=(j["id"], j["status"], j["type"],
                        j["printer"], j["filename"], j["created"]),
                tags=(tag,))

    def _on_job_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            try:
                self._job_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._job_menu.grab_release()

    def _get_selected_job_id(self):
        selection = self.tree.selection()
        if not selection:
            return None
        values = self.tree.item(selection[0], "values")
        return int(values[0]) if values else None

    def _delete_selected_job(self):
        job_id = self._get_selected_job_id()
        if job_id is None:
            return
        delete_job(job_id)
        self._refresh_jobs()
        log(f"Job deleted: {job_id}")

    def _restart_selected_job(self):
        job_id = self._get_selected_job_id()
        if job_id is None:
            return
        restart_job(job_id)
        self._refresh_jobs()
        log(f"Job restarted: {job_id}")

    # def _clear_log(self):
    #     self.log_box.configure(state="normal")
    #     self.log_box.delete("1.0", "end")
    #     self.log_box.configure(state="disabled")

    # ── Tray integration ────────────────────────────────────────────────────
    def hide_window(self):
        self.root.withdraw()

    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self, icon=None, item=None):
        try:
            icon.stop()
        except Exception:
            pass
        self.root.quit()
        os._exit(0)

    def run(self):
        # Build tray icon
        if os.path.exists(ICON_PATH):
            tray_img = Image.open(ICON_PATH)
        else:
            tray_img = make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Open Print Server", self.show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit_app),
        )
        icon = pystray.Icon("CloudERP Print", tray_img,
                            "CloudERP Print Server", menu)

        # Run tray in background thread
        threading.Thread(target=icon.run, daemon=True).start()

        # Show window initially
        self.show_window()
        self.root.mainloop()


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Hide the console window on Windows
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

    app = PrintServerApp()
    app.run()
