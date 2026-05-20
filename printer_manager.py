"""
printer_manager.py
المحرك الرئيسي للطباعة
يحتوي على منطق الطباعة بصمت للـ PDF، الصور، HTML و ZPL
مع معالجة الأخطاء والتنظيف للملفات المؤقتة.
"""
import os
import json
import time
import base64
import tempfile
import subprocess
import socket
from PIL import Image
from config import SUMATRA
from logger import log
from database import mark_done, mark_failed

def build_zpl_payload(data: dict):
    """تجهيز محتوى ZPL للطباعة"""
    if data.get("content_bytes_base64"):
        return base64.b64decode(data["content_bytes_base64"])

    zpl_content = data.get("content", "")
    if isinstance(zpl_content, bytes):
        return zpl_content
    if not isinstance(zpl_content, str):
        zpl_content = str(zpl_content)

    encoding = (data.get("content_encoding") or "utf-8").strip()
    return zpl_content.encode(encoding, errors="strict")

def parse_zpl_status(status_str):
    """تحليل نص الرد القادم من أمر ~HS لطابعات Zebra"""
    try:
        parts = status_str.replace("\x02", "").replace("\x03", "").split(",")
        if len(parts) >= 3:
            paper_out = parts[1].strip()  
            pause_status = parts[2].strip()  
            
            reasons = []
            if paper_out == "1": reasons.append("Paper Out (نفد الورق)")
            if pause_status == "1": reasons.append("Printer Paused (متوقفة مؤقتاً)")
            
            if reasons:
                return f"Error: {', '.join(reasons)}"
            return "Ready & Printing"
    except Exception:
        pass
    return "Unknown (Status Parsed Fallback)"

def decode_job_status_flags(win32print, status):
    """تحليل كود الخطأ في طابور الويندوز"""
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
    ]
    messages = []
    for const_name, label in flag_map:
        const_value = getattr(win32print, const_name, None)
        if const_value is not None and (status & const_value):
            messages.append(label)
    return messages or ["Queued"]

def print_job(job):
    """
    استلام بيانات الطلب من قاعدة البيانات وتنفيذ الطباعة المناسبة.
    job[0]: id, job[1]: data (JSON), job[2]: retries
    """
    try:
        import win32print, win32api
    except ImportError:
        log("ERROR: pywin32 not installed")
        return

    job_id = job[0]
    data = json.loads(job[1])
    retries = job[2] + 1
    file_path = None
    pdf_path = None

    try:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, data.get("filename", f"job_{job_id}"))
        printer_name = data["printer"]
        job_type = data["type"]

        # ---------------------------------------------------------
        # 1. طباعة PDF (صامتة عبر Sumatra)
        # ---------------------------------------------------------
        if job_type == "pdf":
            pdf_bytes = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(pdf_bytes)
            
            # اضافة -silent لضمان الطباعة بدون أي نوافذ
            subprocess.run([SUMATRA, "-print-to", printer_name, file_path, "-silent"])
            log(f"PDF printed → {printer_name}: {data.get('filename', '')}")
            mark_done(job_id, "Success (SumatraPDF)")

        # ---------------------------------------------------------
        # 2. طباعة الصور (صامتة بتحويلها إلى PDF أولاً)
        # ---------------------------------------------------------
        elif job_type == "image":
            img_bytes = base64.b64decode(data["content"])
            with open(file_path, "wb") as f:
                f.write(img_bytes)
            
            pdf_path = file_path + ".pdf"
            img_pil = Image.open(file_path)
            # التأكد من الصيغة لتحويلها إلى PDF
            if img_pil.mode != 'RGB':
                img_pil = img_pil.convert('RGB')
            img_pil.save(pdf_path, "PDF", resolution=100.0)
            
            subprocess.run([SUMATRA, "-print-to", printer_name, pdf_path, "-silent"])
            log(f"Image printed (via PDF) → {printer_name}: {data.get('filename', '')}")
            mark_done(job_id, "Success (Converted to PDF)")

        # ---------------------------------------------------------
        # 3. طباعة HTML (صامتة عبر Headless Edge أو Chrome)
        # ---------------------------------------------------------
        elif job_type == "html":
            html_path = file_path + ".html"
            file_path = html_path # for cleanup
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(data["content"])
            
            # البحث عن متصفح Edge للطباعة الصامتة
            # Edge موجود افتراضيا في معظم أجهزة ويندوز 10/11
            edge_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
            ]
            browser_exe = None
            for p in edge_paths:
                if os.path.exists(p):
                    browser_exe = p
                    break
                    
            if browser_exe:
                # طباعة صامتة عبر Edge
                cmd = [
                    browser_exe,
                    "--headless",
                    "--disable-gpu",
                    f"--print-to-printer={printer_name}",
                    html_path
                ]
                subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW)
                log(f"HTML printed (Headless Edge) → {printer_name}")
                mark_done(job_id, "Success (Headless Edge)")
            else:
                # إذا لم يوجد المتصفح، استخدم الطريقة القديمة كـ Fallback
                win32api.ShellExecute(0, "print", html_path, f'"{printer_name}"', ".", 0)
                log(f"HTML printed (ShellExecute) → {printer_name}")
                mark_done(job_id, "Sent to Windows Shell")

        # ---------------------------------------------------------
        # 4. طباعة ZPL (مباشر عبر IP أو عبر Spooler للـ USB)
        # ---------------------------------------------------------
        elif job_type == "zpl":
            zpl_data = build_zpl_payload(data)
            
            # فحص إذا كان اسم الطابعة المعطى هو عنوان IP حقيقي للطباعة المباشرة
            # نتجاهل الأسماء العادية مثل "Zebra ZD421"
            clean_ip = printer_name.replace("\\", "/").split("/")[-1]
            is_network_ip = any(char.isdigit() for char in clean_ip) and "." in clean_ip and len(clean_ip.split('.')) == 4
            
            success = False
            if is_network_ip:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(4.0)
                    s.connect((clean_ip, 9100))
                    
                    s.sendall(b"~HS")
                    status_response = s.recv(1024).decode('ascii', errors='ignore')
                    parsed_status = parse_zpl_status(status_response)
                    
                    if "Error" in parsed_status:
                        s.close()
                        raise Exception(f"Printer error before printing: {parsed_status}")
                    
                    s.sendall(zpl_data)
                    s.close()
                    
                    log(f"ZPL Printed via Network Socket to {clean_ip}")
                    mark_done(job_id, f"Network Print: {parsed_status}")
                    success = True
                except Exception as net_err:
                    log(f"Network ZPL socket failed for {clean_ip}: {net_err}")
                    # إذا فشل الاتصال برقم IP سنرمي الاستثناء، 
                    # ولن نحاول الطباعة بالويندوز إلا إذا كان اسم طابعة مسجل.
                    raise Exception(f"Direct IP Print Failed: {net_err}")

            if not success:
                # الطباعة عبر Windows Spooler للطابعات الـ USB أو المشتركة نصيا
                hprinter = win32print.OpenPrinter(printer_name)
                try:
                    hdc = win32print.StartDocPrinter(hprinter, 1, ("ZPL Print", None, "RAW"))
                    win32print.StartPagePrinter(hprinter)
                    win32print.WritePrinter(hprinter, zpl_data)
                    win32print.EndPagePrinter(hprinter)
                    win32print.EndDocPrinter(hprinter)
                    
                    # فحص الأخطاء السريعة بعد الإرسال بثانية واحدة
                    time.sleep(1.0)
                    jobs = win32print.EnumJobs(hprinter, 0, 100, 1)
                    printer_status_msg = "Spooler: Queued"
                    
                    for j in jobs:
                        if j['pPrinterName'] == printer_name:
                            p_status = j['Status']
                            flags = decode_job_status_flags(win32print, p_status)
                            printer_status_msg = f"Spooler: {', '.join(flags)}"
                            break
                    
                    blocking_terms = {"Error", "Offline", "Paper Out", "User Intervention Required", "Blocked Queue"}
                    if any(term in printer_status_msg for term in blocking_terms):
                        raise Exception(printer_status_msg)
                    
                    log(f"ZPL printed via Windows → {printer_name}")
                    mark_done(job_id, printer_status_msg)
                    
                finally:
                    win32print.ClosePrinter(hprinter)

    except Exception as e:
        log(f"ERROR job #{job_id} (attempt {retries}): {e}")
        mark_failed(job_id, retries, str(e))
        
    finally:
        # ---------------------------------------------------------
        # تنظيف الملفات المؤقتة دائماً في النهاية لمنع تسرب التخزين
        # ---------------------------------------------------------
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
