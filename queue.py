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

    c.execute("UPDATE jobs SET retries=? WHERE id=?", (retries, job_id))

    conn.commit()
    conn.close()