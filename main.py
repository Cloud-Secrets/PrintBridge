from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import win32print
import tempfile
import subprocess
import base64
import os

# =========================
# APP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# PATH TO SUMATRAPDF (inside EXE folder)
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUMATRA_PATH = os.path.join(
    BASE_DIR,
    "SumatraPDF.exe"
)

# =========================
# REQUEST MODEL
# =========================
class PrintRequest(BaseModel):
    printer: str
    filename: str
    content: str   # base64 PDF

# =========================
# HEALTH CHECK
# =========================
@app.get("/")
def home():
    return {"status": "running"}

# =========================
# GET PRINTERS
# =========================
@app.get("/printers")
def get_printers():

    printers = win32print.EnumPrinters(2)

    return [p[2] for p in printers]

# =========================
# PRINT PDF SILENTLY
# =========================
@app.post("/print")
def print_pdf(data: PrintRequest):

    try:
        # temp file path
        temp_dir = tempfile.gettempdir()

        file_path = os.path.join(
            temp_dir,
            data.filename
        )

        # decode base64 PDF
        pdf_bytes = base64.b64decode(data.content)

        with open(file_path, "wb") as f:
            f.write(pdf_bytes)

        # silent print using SumatraPDF
        subprocess.run([
            SUMATRA_PATH,
            "-print-to",
            data.printer,
            file_path
        ], check=True)

        return {
            "success": True,
            "printer": data.printer
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# START SERVER (IMPORTANT FOR EXE)
# =========================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=5000
    )