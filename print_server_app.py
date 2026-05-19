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
import binascii
import tempfile
import subprocess
import socket  # تم إضافته للاتصال المباشر بطابعات الشبكة ZPL
import tkinter as tk
from tkinter import ttk, scrolledtext
import pystray
from PIL import Image, ImageDraw
import queue
import datetime
import urllib.request
import urllib.error

# ─── Embedded FastAPI server ─────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ─── Print queue (inline, no separate file needed) ────────────────============
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "print_queue.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            data             TEXT    NOT NULL,
            retries          INTEGER DEFAULT 0,
            status           TEXT    DEFAULT 'pending',
            created          TEXT    DEFAULT (datetime('now')),
            printer_response TEXT    DEFAULT ''
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
    # إضافة عمود تسجيل رد الطابعة إن لم يكن موجوداً
    if "printer_response" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN printer_response TEXT DEFAULT ''")

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
        "SELECT id, status, retries, created, data, printer_response FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = json.loads(r[4])
        result.append({
            "id": r[0], "status": r[1], "retries": r[2],
            "created": r[3], "type": d.get("type","?"),
            "filename": d.get("filename","?"), "printer": d.get("printer","?"),
            "printer_response": r[5] if r[5] else ""
        })
    return result

def mark_done(job_id, response="Success"):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='done', printer_response=? WHERE id=?", (response, job_id))
    conn.commit()
    conn.close()

def mark_failed(job_id, retries, response="Failed"):
    status = "failed" if retries >= 3 else "pending"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET retries=?, status=?, printer_response=? WHERE id=?", (retries, status, response, job_id))
    conn.commit()
    conn.close()

def delete_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

def restart_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status='pending', retries=0, printer_response='' WHERE id=?", (job_id,))
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
APP_VERSION = "1.0.0"
UPDATE_API_URL = os.environ.get("PRINT_SERVER_UPDATE_API", "")
UPDATE_CHECK_INTERVAL = 60 * 30  
UPDATE_DOWNLOAD_TIMEOUT = 30
UPDATE_FILENAME = "print_server_app_update.exe"
ENABLE_AUTO_UPDATE = True

# ─── FastAPI App ──────────────────────────────────────────────────────────────
api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

def auth(token):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def validate_print_payload(data: dict):
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid payload: expected JSON object")

    job_type = data.get("type")
    allowed_types = {"pdf", "image", "html", "zpl"}
    if job_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Invalid type. Allowed: {', '.join(sorted(allowed_types))}")

    filename = data.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise HTTPException(status_code=400, detail="Invalid filename: non-empty string is required")

    printer = data.get("printer")
    if not isinstance(printer, str) or not printer.strip():
        raise HTTPException(status_code=400, detail="Invalid printer: non-empty string is required")

    if job_type in {"pdf", "image"}:
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=400, detail=f"Invalid {job_type} content: base64 string is required")
        try:
            base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid {job_type} content: malformed base64")

    elif job_type == "html":
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=400, detail="Invalid html content: non-empty string is required")

    elif job_type == "zpl":
        zpl_text = data.get("content")
        zpl_raw_b64 = data.get("content_bytes_base64")
        if not zpl_text and not zpl_raw_b64:
            raise HTTPException(
                status_code=400,
                detail="Invalid zpl payload: provide `content` text or `content_bytes_base64`"
            )

        if zpl_raw_b64:
            if not isinstance(zpl_raw_b64, str) or not zpl_raw_b64.strip():
                raise HTTPException(status_code=400, detail="Invalid `content_bytes_base64`: non-empty base64 string required")
            try:
                base64.b64decode(zpl_raw_b64, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=400, detail="Invalid `content_bytes_base64`: malformed base64")

        if zpl_text is not None and not isinstance(zpl_text, (str, bytes)):
            raise HTTPException(status_code=400, detail="Invalid zpl `content`: expected string/bytes")

        if zpl_text is not None and isinstance(zpl_text, str) and not zpl_text.strip() and not zpl_raw_b64:
            raise HTTPException(status_code=400, detail="Invalid zpl `content`: empty string")

        if "content_encoding" in data:
            content_encoding = data.get("content_encoding")
            if not isinstance(content_encoding, str) or not content_encoding.strip():
                raise HTTPException(status_code=400, detail="Invalid `content_encoding`: non-empty string required")
            try:
                "test".encode(content_encoding.strip())
            except LookupError:
                raise HTTPException(status_code=400, detail=f"Invalid `content_encoding`: unknown codec `{content_encoding}`")

def parse_zpl_status(status_str):
    """تحليل نص الرد القادم من أمر ~HS لطابعات Zebra وتفسيره بشكل مفهوم"""
    try:
        # الرد النموذجي يكون على شكل: \x02030,0,0,1234,000,0,-,0,000,0,0,0\x03
        parts = status_str.replace("\x02", "").replace("\x03", "").split(",")
        if len(parts) >= 3:
            paper_out = parts[1].strip()  # 1 تعني نفاد الورق
            pause_status = parts[2].strip()  # 1 تعني الطابعة في وضع التوقف المؤقت
            
            reasons = []
            if paper_out == "1": reasons.append("Paper Out (نفد الورق)")
            if pause_status == "1": reasons.append("Printer Paused (الطابعة متوقفة مؤقتاً)")
            
            if reasons:
                return f"Error: {', '.join(reasons)}"
            return "Ready & Printing"
    except Exception:
        pass
    return "Unknown (Status Parsed Fallback)"

def build_zpl_payload(data: dict):
    """
    Build bytes payload for ZPL without implicit lossy conversion.
    Optional keys:
      - content_bytes_base64: send exact bytes payload
      - content_encoding: encoding for text content (default: utf-8)
    """
    if data.get("content_bytes_base64"):
        return base64.b64decode(data["content_bytes_base64"])

    zpl_content = data.get("content", "")
    if isinstance(zpl_content, bytes):
        return zpl_content
    if not isinstance(zpl_content, str):
        zpl_content = str(zpl_content)

    encoding = (data.get("content_encoding") or "utf-8").strip()
    return zpl_content.encode(encoding, errors="strict")

def decode_job_status_flags(win32print, status):
    flag_map = [
        ("JOB_STATUS_PAUSED", "Paused"),
        ("JOB_STATUS_ERROR", "Error"),
        ("JOB_STATUS_DELETING", "Deleting"),
        ("JOB_STATUS_SPOOLING", "Spooling"),
        ("JOB_STATUS_PRINTING", "Printing"),
        ("JOB_STATUS_OFFLINE", "Offline"),
        ("JOB_STATUS_PAPEROUT", "Paper Out"),
        ("JOB_STATUS_PRINTED", "Printed"),
        ("JOB_STATUS_DELETED", "Deleted"),
        ("JOB_STATUS_BLOCKED_DEVQ", "Blocked Queue"),
        ("JOB_STATUS_USER_INTERVENTION", "User Intervention Required"),
        ("JOB_STATUS_RESTART", "Restarting"),
        ("JOB_STATUS_COMPLETE", "Complete"),
        ("JOB_STATUS_RETAINED", "Retained"),
        ("JOB_STATUS_RENDERING_LOCALLY", "Rendering Locally"),
    ]
    messages = []
    for const_name, label in flag_map:
        const_value = getattr(win32print, const_name, None)
        if const_value is not None and (status & const_value):
            messages.append(label)
    return messages or ["Queued"]

def print_job(job):
    try:
        import win32print, win32api
    except ImportError:
        log("ERROR: pywin32 not installed")
        return

    data   = json.loads(job[1])
    job_id = job[0]
    retries = job[2] + 1

    try:
        temp = tempfile.gettempdir()
        file_path = os.path.join(temp, data["filename"])

        if data["type"] == "pdf":
            pdf = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(pdf)
            subprocess.run([SUMATRA, "-print-to", data["printer"], file_path])
            log(f"PDF printed → {data['printer']}: {data['filename']}")
            mark_done(job_id, "Sent to SumatraPDF")

        elif data["type"] == "image":
            img = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(img)
            win32api.ShellExecute(0, "print", file_path, None, ".", 0)
            log(f"Image printed → {data['printer']}: {data['filename']}")
            mark_done(job_id, "Sent to Windows Shell")

        elif data["type"] == "html":
            html_path = file_path + ".html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(data["content"])
            win32api.ShellExecute(0, "print", html_path, None, ".", 0)
            log(f"HTML printed → {data['printer']}: {data['filename']}")
            mark_done(job_id, "Sent to Windows Shell")

        elif data["type"] == "zpl":
            zpl_data = build_zpl_payload(data)
            printer_name = data["printer"]
            
            # --- الطريقة الأولى: إذا كانت الطابعة طابعة شبكة (مثال: "1192.168.1.50") ---
            # يتم فحص إذا كان اسم الطابعة المعطى هو عنوان IP أو مسار شبكي يحتوي على IP
            is_network_ip = False
            ip_address = printer_name
            
            # محاولة استخراج الـ IP إذا كان مكتوباً بشكل صريح
            clean_ip = printer_name.replace("\\", "/").split("/")[-1]
            if any(char.isdigit() for char in clean_ip) and "." in clean_ip:
                is_network_ip = True
                ip_address = clean_ip

            if is_network_ip:
                try:
                    # الاتصال المباشر بالطابعة عبر منفذ الطباعة الافتراضي لـ Zebra وهو 9100
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(4.0)
                    s.connect((ip_address, 9100))
                    
                    # 1. إرسال أمر الاستعلام عن الحالة قبل الطباعة
                    s.sendall(b"~HS")
                    status_response = s.recv(1024).decode('ascii', errors='ignore')
                    parsed_status = parse_zpl_status(status_response)
                    
                    if "Error" in parsed_status:
                        s.close()
                        raise Exception(f"Printer reported error before printing: {parsed_status}")
                    
                    # 2. إرسال ملف الـ ZPL الفعلي للطباعة
                    s.sendall(zpl_data)
                    s.close()
                    
                    log(f"ZPL Printed via Network Socket to {ip_address}")
                    mark_done(job_id, f"Network Print: {parsed_status}")
                    return
                except Exception as net_err:
                    log(f"Network ZPL failed or timeout for {ip_address}: {net_err}")
                    # إذا فشل اتصال الشبكة المباشر سنتركه يتجه للطريقة الثانية (ويندوز)

            # --- الطريقة الثانية: الطباعة القياسية عبر نظام الويندوز لـ USB / Shared Printers ---
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                # إرسال أمر الطباعة
                hdc = win32print.StartDocPrinter(hprinter, 1, ("ZPL Print", None, "RAW"))
                win32print.StartPagePrinter(hprinter)
                win32print.WritePrinter(hprinter, zpl_data)
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
                
                # مراقبة الـ Job في الويندوز لمدة ثانيتين لاكتشاف الأخطاء الفورية (مثل الطابعة Offline)
                time.sleep(1.5)
                jobs = win32print.EnumJobs(hprinter, 0, 100, 1)
                printer_status_msg = "Spooler: Queued"
                
                for j in jobs:
                    # فحص إذا كان الـ Job المرسل يحمل حالة خطأ في الويندوز
                    if j['pPrinterName'] == printer_name:
                        p_status = j['Status']
                        flags = decode_job_status_flags(win32print, p_status)
                        printer_status_msg = f"Spooler: {', '.join(flags)}"
                        break
                
                blocking_terms = {"Error", "Offline", "Paper Out", "User Intervention Required", "Blocked Queue"}
                if any(term in printer_status_msg for term in blocking_terms):
                    raise Exception(printer_status_msg)
                
                log(f"ZPL printed via Windows → {printer_name}: {data['filename']}")
                mark_done(job_id, printer_status_msg)
                
            finally:
                win32print.ClosePrinter(hprinter)

    except Exception as e:
        log(f"ERROR job #{job_id} (attempt {retries}): {e}")
        mark_failed(job_id, retries, str(e))

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
    validate_print_payload(data)
    add_job(data)
    log(f"Job queued: {data.get('type','?')} / {data.get('filename','?')}")
    return {"status": "queued"}

@api.websocket("/ws")
async def ws_print(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            data = await websocket.receive_text()
            job  = json.loads(data)
            validate_print_payload(job)
            add_job(job)
            log(f"WS job queued: {job.get('type','?')}")
            await websocket.send_text("queued")
        except HTTPException as e:
            await websocket.send_text(f"error:{e.detail}")
        except json.JSONDecodeError:
            await websocket.send_text("error:Invalid JSON payload")
        except Exception as e:
            await websocket.send_text(f"error:{str(e)}")


def parse_version(version: str):
    try:
        return tuple(int(part) for part in version.split(".") if part.isdigit())
    except Exception:
        return ()

def is_newer_version(latest: str, current: str):
    return parse_version(latest) > parse_version(current)

def fetch_update_info():
    if not UPDATE_API_URL:
        return None
    try:
        request = urllib.request.Request(
            UPDATE_API_URL,
            headers={"User-Agent": "CloudERP Print Server"}
        )
        with urllib.request.urlopen(request, timeout=UPDATE_DOWNLOAD_TIMEOUT) as response:
            data = response.read().decode("utf-8")
            info = json.loads(data)
            if isinstance(info, dict):
                return info
    except Exception as exc:
        log(f"Update check failed: {exc}")
    return None

def download_update_package(url: str):
    try:
        with urllib.request.urlopen(url, timeout=UPDATE_DOWNLOAD_TIMEOUT) as response:
            tmp_path = os.path.join(tempfile.gettempdir(), UPDATE_FILENAME)
            with open(tmp_path, "wb") as f:
                f.write(response.read())
        log(f"Update package downloaded to {tmp_path}")
        return tmp_path
    except Exception as exc:
        log(f"Update download failed: {exc}")
        return None

def start_update_installer(path: str):
    try:
        log("Launching update installer...")
        subprocess.Popen([path], cwd=os.path.dirname(path))
        if getattr(sys, "frozen", False):
            os._exit(0)
        return True
    except Exception as exc:
        log_exception(exc)
        return False

def check_for_updates():
    info = fetch_update_info()
    if not info:
        return "Update check failed"

    latest = info.get("version")
    url = info.get("url")
    if latest and is_newer_version(latest, APP_VERSION):
        log(f"Update available: {latest} (current {APP_VERSION})")
        if url:
            downloaded = download_update_package(url)
            if downloaded:
                if start_update_installer(downloaded):
                    return f"Updating to {latest}..."
                return f"Downloaded update {latest}, install failed"
        return f"Update available: {latest}"

    return f"Up to date ({APP_VERSION})"

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
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.ellipse([2, 2, 62, 62], fill="#1a73e8")
    d.rectangle([14, 26, 50, 44], fill="white")
    d.rectangle([20, 18, 44, 28], fill="white")
    d.rectangle([20, 38, 44, 50], fill="#e8f0fe")
    d.ellipse([40, 30, 46, 36], fill="#1a73e8")
    return img

# ─── Main GUI Window ──────────────────────────────────────────────────────────
class PrintServerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CloudERP Print Server")
        self.root.geometry("850x480")  # قمنا بتوسيع النافذة قليلاً لتناسب العمود الجديد
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

        # أضفنا عمود التقرير والرد هنا "response"
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
        if not ENABLE_AUTO_UPDATE or not UPDATE_API_URL: return
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


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception: pass

    app = PrintServerApp()
    app.run()
