import sqlite3
import json
import time

DB = "print_queue.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        status TEXT,
        retries INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def add_job(data):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute(
        "INSERT INTO jobs (data, status) VALUES (?, ?)",
        (json.dumps(data), "pending")
    )

    conn.commit()
    conn.close()


def get_pending_jobs():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT id, data, retries FROM jobs WHERE status='pending'")
    rows = c.fetchall()

    conn.close()
    return rows


def mark_done(job_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))

    conn.commit()
    conn.close()


def mark_failed(job_id, retries):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    MAX_RETRIES = 3
    
    if retries >= MAX_RETRIES:
        # Mark as failed after max retries exceeded
        c.execute("UPDATE jobs SET status='failed', retries=? WHERE id=?", (retries, job_id))
        print(f"[DB] Job {job_id} marked as FAILED after {retries} retries")
    else:
        # Keep as pending for retry
        c.execute("UPDATE jobs SET retries=? WHERE id=?", (retries, job_id))
        print(f"[DB] Job {job_id} marked for retry ({retries}/{MAX_RETRIES})")

    conn.commit()
    conn.close()


def get_all_jobs():
    """Retrieve all jobs with their current status"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT id, data, status, retries, created_at FROM jobs ORDER BY id DESC")
    rows = c.fetchall()

    conn.close()
    
    jobs = []
    for row in rows:
        jobs.append({
            "id": row[0],
            "data": json.loads(row[1]),
            "status": row[2],
            "retries": row[3],
            "created_at": row[4]
        })
    return jobs