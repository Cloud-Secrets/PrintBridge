"""
database.py
إدارة قاعدة البيانات SQLite للتعامل مع طابور الطباعة (Print Queue)
"""
import sqlite3
import json
from config import DB_PATH

def get_connection():
    """
    إرجاع اتصال بقاعدة البيانات مع تفعيل وضع WAL لتجنب مشاكل التزامن
    """
    conn = sqlite3.connect(DB_PATH, timeout=10) # انتظار يصل لـ 10 ثوانٍ في حال القفل
    # تفعيل وضع Write-Ahead Logging لأداء وتزامن أفضل (يحل مشكلة database is locked)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

def init_db():
    """
    تهيئة وإنشاء جداول قاعدة البيانات إذا لم تكن موجودة
    """
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            data             TEXT    NOT NULL,
            retries          INTEGER DEFAULT 0,
            status           TEXT    DEFAULT 'pending',
            created          TEXT    DEFAULT (datetime('now')),
            printer_response TEXT    DEFAULT ''
        )
    """)

    # التحقق من وجود الأعمدة لإضافتها للنسخ القديمة في حال التحديث
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "retries" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN retries INTEGER DEFAULT 0")
    if "status" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'pending'")
    if "created" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN created TEXT")
        conn.execute("UPDATE jobs SET created = datetime('now') WHERE created IS NULL")
    if "printer_response" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN printer_response TEXT DEFAULT ''")

    conn.commit()
    conn.close()

def add_job(data: dict):
    """
    إضافة طلب طباعة جديد إلى الطابور
    """
    conn = get_connection()
    conn.execute("INSERT INTO jobs (data) VALUES (?)", (json.dumps(data),))
    conn.commit()
    conn.close()

def get_pending_jobs():
    """
    جلب كافة الطلبات التي بانتظار الطباعة (status = pending)
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, data, retries FROM jobs WHERE status='pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return rows

def get_all_jobs(limit=50):
    """
    جلب سجل الطلبات للواجهة الرسومية (GUI)
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, status, retries, created, data, printer_response FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = json.loads(r[4])
        result.append({
            "id": r[0], "status": r[1], "retries": r[2],
            "created": r[3], "type": d.get("type","?"),
            "filename": d.get("filename","?"), "printer": d.get("printer","?"),
            "printer_response": r[5] if r[5] else ""
        })
    return result

def mark_done(job_id, response="Success"):
    """
    تحديث حالة الطلب إلى (مكتمل)
    """
    conn = get_connection()
    conn.execute("UPDATE jobs SET status='done', printer_response=? WHERE id=?", (response, job_id))
    conn.commit()
    conn.close()

def mark_failed(job_id, retries, response="Failed"):
    """
    تحديث حالة الطلب كفاشل في حال استنفاد المحاولات
    """
    # نوقف المحاولة بعد 3 مرات
    status = "failed" if retries >= 3 else "pending"
    conn = get_connection()
    conn.execute("UPDATE jobs SET retries=?, status=?, printer_response=? WHERE id=?", (retries, status, response, job_id))
    conn.commit()
    conn.close()

def delete_job(job_id):
    """
    حذف طلب نهائياً من الطابور
    """
    conn = get_connection()
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

def restart_job(job_id):
    """
    إعادة تعيين الطلب ليتم طباعته مجدداً
    """
    conn = get_connection()
    conn.execute("UPDATE jobs SET status='pending', retries=0, printer_response='' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()
