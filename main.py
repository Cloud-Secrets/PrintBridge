from fastapi import FastAPI, WebSocket, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

import base64
import os
import tempfile
import subprocess
import json
import threading
import time

import win32print
import win32api

from print_queue import init_db, add_job, get_pending_jobs, mark_done, mark_failed

# =========================
# CONFIG
# =========================
API_TOKEN = "CloudErpToken"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUMATRA = os.path.join(BASE_DIR, "SumatraPDF.exe")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# INIT DB
# =========================
init_db()

# =========================
# AUTH
# =========================
def auth(token: str):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# =========================
# ROUTER (printer selection)
# =========================
def route_printer(printer_type):
    printers = win32print.EnumPrinters(2)
    names = [p[2] for p in printers]

    for p in names:
        if printer_type in p.lower():
            return p

    return names[0] if names else None

# =========================
# PRINT ENGINE
# =========================
def print_job(job):
    data = json.loads(job[1])
    job_id = job[0]

    try:
        temp = tempfile.gettempdir()
        file_path = os.path.join(temp, data["filename"])

        # PDF
        if data["type"] == "pdf":
            pdf = base64.b64decode(data["content"])

            with open(file_path, "wb") as f:
                f.write(pdf)

            subprocess.run([
                SUMATRA,
                "-print-to",
                data["printer"],
                file_path
            ])
            print(f"[WORKER] PDF printed: {file_path}")

        # IMAGE
        elif data["type"] == "image":
            img = base64.b64decode(data["content"])

            with open(file_path, "wb") as f:
                f.write(img)

            win32api.ShellExecute(0, "print", file_path, None, ".", 0)
            print(f"[WORKER] Image printed: {file_path}")

        # HTML
        elif data["type"] == "html":
            html_path = file_path + ".html"

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(data["content"])

            win32api.ShellExecute(0, "print", html_path, None, ".", 0)
            print(f"[WORKER] HTML printed: {html_path}")
        elif data["type"] == "zpl":

            # ZPL is raw text (NOT base64)
            zpl_data = data["content"].encode("utf-8")

            # create temp file
            file_path = os.path.join(tempfile.gettempdir(), data["filename"] + ".zpl")

            with open(file_path, "wb") as f:
                f.write(zpl_data)

            # send RAW to printer (Windows method)
            hprinter = win32print.OpenPrinter(data["printer"])
            try:
                job = win32print.StartDocPrinter(hprinter, 1, ("ZPL Print", None, "RAW"))
                win32print.StartPagePrinter(hprinter)
                win32print.WritePrinter(hprinter, zpl_data)
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)

            print(f"[WORKER] ZPL printed: {file_path}")
            return {"success": True, "type": "zpl"}

        mark_done(job_id)
        print(f"[WORKER] Job {job_id} completed successfully")

    except Exception as e:
        retries = job[2] + 1
        print(f"[WORKER] Error processing job {job_id} (attempt {retries}): {e}")
        import traceback
        traceback.print_exc()
        mark_failed(job_id, retries)


# =========================
# QUEUE WORKER (background)
# =========================
def worker():
    print("[WORKER] Background worker started, polling every 2 seconds...")
    while True:
        jobs = get_pending_jobs()

        if jobs:
            print(f"[WORKER] Found {len(jobs)} pending job(s)")
        
        for job in jobs:
            print_job(job)

        time.sleep(2)

threading.Thread(target=worker, daemon=True).start()

# =========================
# API
# =========================

@app.get("/")
def home():
    return {"status": "running"}

@app.get("/printers")
def printers():
    return [p[2] for p in win32print.EnumPrinters(2)]

@app.get("/jobs")
def get_jobs():
    """Get all jobs with their status"""
    from print_queue import get_all_jobs
    jobs = get_all_jobs()
    return {"jobs": jobs}

@app.post("/print")
def create_print(data: dict, authorization: str = Header(None)):
    auth(authorization)

    add_job(data)
    print(f"[PRINT] Job queued: {data}")
    return {"status": "queued"}

# =========================
# WEBSOCKET (REAL TIME PRINT)
# =========================
@app.websocket("/ws")
async def ws_print(websocket: WebSocket):
    await websocket.accept()

    while True:
        data = await websocket.receive_text()
        job = json.loads(data)

        add_job(job)

        await websocket.send_text("queued")


# =========================
# START SERVER (IMPORTANT FOR EXE)
# =========================
import uvicorn

if __name__ == "__main__":
    print("Starting FastAPI server on http://127.0.0.1:5000")
    uvicorn.run(app, host="127.0.0.1", port=5000, log_level="info")
else:
    # For PyInstaller exe - run directly when module loads
    try:
        print("Starting FastAPI server on http://127.0.0.1:5000")
        uvicorn.run(app, host="127.0.0.1", port=5000, log_level="info")
    except Exception as e:
        print(f"Error starting server: {e}")
        import traceback
        traceback.print_exc()
