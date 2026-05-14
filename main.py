from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import win32print
import win32api
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
# SUMATRA PDF PATH
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUMATRA_PATH = os.path.join(BASE_DIR, "SumatraPDF.exe")

# =========================
# REQUEST MODEL
# =========================
class PrintRequest(BaseModel):
    printer: str
    type: str        # pdf | image | html
    filename: str
    content: str     # base64 OR html string

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
# MAIN PRINT ENGINE
# =========================
@app.post("/print")
def print_file(data: PrintRequest):

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, data.filename)

    try:

        # =========================
        # PDF PRINT (BEST OPTION)
        # =========================
        if data.type == "pdf":

            pdf_bytes = base64.b64decode(data.content)

            with open(file_path, "wb") as f:
                f.write(pdf_bytes)

            subprocess.run([
                SUMATRA_PATH,
                "-print-to",
                data.printer,
                file_path
            ], check=True)

            return {"success": True, "type": "pdf"}

        # =========================
        # IMAGE PRINT (PNG / JPG)
        # =========================
        elif data.type == "image":

            img_bytes = base64.b64decode(data.content)

            with open(file_path, "wb") as f:
                f.write(img_bytes)

            # Windows default image printing
            win32api.ShellExecute(
                0,
                "print",
                file_path,
                None,
                ".",
                0
            )

            return {"success": True, "type": "image"}

        # =========================
        # HTML PRINT
        # =========================
        elif data.type == "html":

            html_path = file_path + ".html"

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(data.content)

            # Uses default browser print engine
            win32api.ShellExecute(
                0,
                "print",
                html_path,
                None,
                ".",
                0
            )

            return {"success": True, "type": "html"}

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported type. Use pdf | image | html"
            )

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