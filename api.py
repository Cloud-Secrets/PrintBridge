"""
api.py
خادم FastAPI للتعامل مع طلبات الـ API والـ WebSockets من الـ ERP
"""
import threading
import sys
import json
import base64
import binascii
from fastapi import FastAPI, HTTPException, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import HOST, PORT, API_TOKEN, LOG_FILE
from logger import log, log_exception
from database import init_db, add_job, get_all_jobs

# ─── FastAPI App ──────────────────────────────────────────────────────────────
api = FastAPI(title="CloudERP Print Server API")
api.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# تهيئة قاعدة البيانات عند تشغيل الـ API
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


def _run_uvicorn():
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

def start_api_server():
    """تشغيل خادم الـ API في مسار خلفي منفصل"""
    threading.Thread(target=_run_uvicorn, daemon=True).start()
