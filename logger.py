"""
logger.py
مدير تسجيل الأحداث (Logging) للتطبيق
"""
import queue
import datetime
from config import LOG_FILE

# طابور (Queue) آمن للاستخدام بين الـ Threads المتعددة
log_queue = queue.Queue()

def log(msg: str):
    """
    تسجيل رسالة عادية في الطابور وحفظها في ملف اللوج
    """
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_queue.put(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_exception(exc: Exception):
    """
    تسجيل الأخطاء البرمجية (Exceptions) مع تفاصيل التتبع
    """
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
