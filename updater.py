"""
updater.py
مسؤول عن فحص وتنزيل التحديثات التلقائية للتطبيق
"""
import os
import sys
import json
import urllib.request
import urllib.error
import tempfile
import subprocess
from config import UPDATE_API_URL, UPDATE_DOWNLOAD_TIMEOUT, UPDATE_FILENAME, APP_VERSION
from logger import log, log_exception

def parse_version(version: str):
    """تحويل النص إلى أرقام للمقارنة (مثلاً '1.0.1' إلى (1, 0, 1))"""
    try:
        return tuple(int(part) for part in version.split(".") if part.isdigit())
    except Exception:
        return ()

def is_newer_version(latest: str, current: str):
    return parse_version(latest) > parse_version(current)

def fetch_update_info():
    """الاتصال بالـ API للتحقق من وجود نسخة جديدة"""
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
    """تنزيل ملف التحديث إلى مسار مؤقت"""
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
    """تشغيل ملف التثبيت الخاص بالتحديث وإغلاق التطبيق الحالي"""
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
    """الفحص الرئيسي الذي يستدعى من الـ GUI أو الـ Poller"""
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
