"""
worker.py
طابور العمليات (Worker) الذي يراقب قاعدة البيانات وينفذ مهام الطباعة.
يستخدم ThreadPoolExecutor لمعالجة المهام بشكل متوازٍ لكي لا يتم تعطيل
الطلبات الأخرى بسبب طابعة معطلة.
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from logger import log
from database import get_pending_jobs
from printer_manager import print_job

def _start_worker_loop():
    log("Print worker started — polling every 2s with ThreadPool")
    # إنشاء Pool بـ 5 مسارات (Threads) متزامنة كحد أقصى (يمكن زيادة الرقم حسب الحاجة)
    with ThreadPoolExecutor(max_workers=5) as executor:
        while True:
            try:
                jobs = get_pending_jobs()
                for job in jobs:
                    # تحديث مبدئي لحالة الطلب حتى لا يتم التقاطه مرتين في الدورة التالية
                    # سيتم تحديث حالته الحقيقية (done أو failed) من داخل print_job
                    from database import get_connection
                    conn = get_connection()
                    conn.execute("UPDATE jobs SET status='processing' WHERE id=?", (job[0],))
                    conn.commit()
                    conn.close()
                    
                    # إرسال المهمة للـ Pool لمعالجتها
                    executor.submit(print_job, job)
            except Exception as e:
                log(f"Worker loop error: {e}")
                
            time.sleep(2)

def start_worker():
    """تشغيل الـ Worker في مسار (Thread) خلفي منفصل"""
    threading.Thread(target=_start_worker_loop, daemon=True).start()
