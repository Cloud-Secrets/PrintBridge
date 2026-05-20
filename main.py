"""
main.py
نقطة الدخول (Entry Point) للتطبيق.
يقوم بتهيئة الخادم، بدء طابور العمليات (Worker)، وإظهار واجهة المستخدم.
"""
import os
import sys

# إذا تم تشغيل التطبيق كملف تنفيذي عبر PyInstaller، نمنع ظهور شاشة الـ Console
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception: 
        pass

from logger import log
from api import start_api_server
from worker import start_worker
from gui import PrintServerApp

def main():
    log("=== Application Starting ===")
    
    # 1. تشغيل خادم FastAPI للرد على طلبات الـ ERP
    start_api_server()
    
    # 2. تشغيل الـ Worker للبحث عن طلبات الطباعة المتوفرة في قاعدة البيانات
    start_worker()
    
    # 3. إطلاق واجهة المستخدم (Tkinter & Tray)
    app = PrintServerApp()
    app.run()

if __name__ == "__main__":
    main()
