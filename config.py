"""
config.py
ملف الإعدادات والثوابت الخاصة بتطبيق الخادم
"""
import os
import sys

# تحديد المسار الرئيسي للتطبيق
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.argv[0])
    RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = APP_DIR

# مسارات الملفات الأساسية
DB_PATH = os.path.join(APP_DIR, "print_queue.db")
LOG_FILE = os.path.join(APP_DIR, "print_server_app.log")
ICON_PATH = os.path.join(RESOURCE_DIR, "icon.png")
SUMATRA = os.path.join(RESOURCE_DIR, "SumatraPDF.exe")

# إعدادات الخادم والشبكة
HOST = "127.0.0.1"
PORT = 5000
# قراءة التوكن من متغيرات البيئة لزيادة الأمان، وإذا لم يوجد نستخدم التوكن الافتراضي
API_TOKEN = os.environ.get("PRINT_SERVER_API_TOKEN", "CloudErpToken")

# إعدادات التحديث التلقائي
APP_VERSION = "1.0.0"
UPDATE_API_URL = os.environ.get("PRINT_SERVER_UPDATE_API", "")
UPDATE_CHECK_INTERVAL = 60 * 30  
UPDATE_DOWNLOAD_TIMEOUT = 30
UPDATE_FILENAME = "print_server_app_update.exe"
ENABLE_AUTO_UPDATE = True
