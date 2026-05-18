import customtkinter as ctk
from PIL import Image
import tkinter as tk
from tkinter import messagebox
import random
import datetime
import threading
import time
import os
import sqlite3
import json
import requests

# =========================================================
# MODERN CLOUD ERP PRINT SERVER UI
# =========================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ModernPrintServer:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("CloudERP Print Server")
        self.root.geometry("1450x860")
        self.root.minsize(1200, 700)

        self.current_theme = "dark"

        # Backend API base (can be overridden via env var)
        self.api_base = os.environ.get("PRINT_SERVER_API", "http://127.0.0.1:5000")
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "print_queue.db")

        # =====================================================
        # COLORS
        # =====================================================
        self.dark_colors = {
            "bg": "#0B1120",
            "sidebar": "#111827",
            "card": "#172033",
            "accent": "#4F46E5",
            "text": "#F8FAFC",
            "muted": "#94A3B8",
            "border": "#1E293B",
        }

        self.light_colors = {
            "bg": "#F3F4F6",
            "sidebar": "#FFFFFF",
            "card": "#FFFFFF",
            "accent": "#4F46E5",
            "text": "#111827",
            "muted": "#6B7280",
            "border": "#E5E7EB",
        }

        self.colors = self.dark_colors

        self.root.configure(fg_color=self.colors["bg"])

        self.jobs = [
            {
                "id": 5,
                "status": "Completed",
                "type": "PDF",
                "printer": "HP Smart Tank 666E",
                "filename": "sample.pdf",
                "created": "2026-05-15",
            },
            {
                "id": 6,
                "status": "Pending",
                "type": "ZPL",
                "printer": "Zebra ZD220",
                "filename": "barcode.zpl",
                "created": "2026-05-15",
            },
            {
                "id": 7,
                "status": "Failed",
                "type": "RAW",
                "printer": "EPSON TM-T20",
                "filename": "receipt.txt",
                "created": "2026-05-15",
            },
        ]

        self.build_ui()

        # Start background polling for backend status and jobs
        threading.Thread(target=self._background_refresh, daemon=True).start()

    # =========================================================
    # UI
    # =========================================================
    def build_ui(self):
        self.main_frame = ctk.CTkFrame(
            self.root,
            fg_color=self.colors["bg"],
            corner_radius=0,
        )
        self.main_frame.pack(fill="both", expand=True)

        self.build_sidebar()
        self.build_content()

    # =========================================================
    # SIDEBAR
    # =========================================================
    def build_sidebar(self):
        # Sidebar width will be set dynamically to 25% of window width
        initial_width = max(240, int(self.root.winfo_screenwidth() * 0.25))
        self.sidebar = ctk.CTkFrame(
            self.main_frame,
            width=initial_width,
            corner_radius=0,
            fg_color=self.colors["sidebar"],
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Update sidebar width whenever the window is resized
        self.root.bind("<Configure>", self._on_resize)

        logo = ctk.CTkLabel(
            self.sidebar,
            text="🖨 CloudERP",
            font=("Segoe UI", 28, "bold"),
            text_color=self.colors["text"],
        )
        logo.pack(pady=(40, 30))

        menu_items = [
            "Dashboard",
            "Jobs",
            "Printers",
            "Logs",
            "Settings",
        ]

        for item in menu_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=item,
                height=52,
                corner_radius=16,
                fg_color="transparent",
                hover_color=self.colors["accent"],
                anchor="w",
                font=("Segoe UI", 15, "bold"),
            )
            btn.pack(fill="x", padx=20, pady=8)

        bottom_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=self.colors["card"],
            corner_radius=24,
            height=180,
        )
        bottom_card.pack(side="bottom", fill="x", padx=20, pady=20)

        ctk.CTkLabel(
            bottom_card,
            text="Print Server",
            font=("Segoe UI", 24, "bold"),
        ).pack(pady=(35, 5))

        ctk.CTkLabel(
            bottom_card,
            text="v2.0.0",
            text_color=self.colors["muted"],
        ).pack()

        ctk.CTkLabel(
            bottom_card,
            text="● System Active",
            text_color="#22C55E",
            font=("Segoe UI", 13, "bold"),
        ).pack(pady=15)

    # =========================================================
    # CONTENT
    # =========================================================
    def build_content(self):
        self.content = ctk.CTkFrame(
            self.main_frame,
            fg_color=self.colors["bg"],
        )
        self.content.pack(side="left", fill="both", expand=True)

        self.build_header()
        self.build_cards()
        self.build_main_area()

        # add manual refresh button on header for quick testing
        try:
            refresh_btn = ctk.CTkButton(self.content, text="Refresh", width=100, command=self._manual_refresh)
            refresh_btn.pack(anchor="ne", padx=20, pady=(8,0))
        except Exception:
            pass

    # =========================================================
    # HEADER
    # =========================================================
    def build_header(self):
        header = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
            height=90,
        )
        header.pack(fill="x", padx=30, pady=(25, 15))

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")

        ctk.CTkLabel(
            left,
            text="CloudERP Print Server",
            font=("Segoe UI", 34, "bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            left,
            text="Monitor printers and jobs in real-time",
            text_color=self.colors["muted"],
            font=("Segoe UI", 14),
        ).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")

        self.theme_switch = ctk.CTkSwitch(
            right,
            text="Light Mode",
            command=self.toggle_theme,
        )
        self.theme_switch.pack(side="right", padx=12)

        status = ctk.CTkLabel(
            right,
            text="● RUNNING",
            fg_color="#14532D",
            text_color="#22C55E",
            corner_radius=100,
            height=38,
            width=130,
            font=("Segoe UI", 13, "bold"),
        )
        status.pack(side="right", padx=10)

        server = ctk.CTkLabel(
            right,
            text="127.0.0.1:5000",
            fg_color=self.colors["card"],
            corner_radius=14,
            height=38,
            width=180,
        )
        server.pack(side="right", padx=10)

    # =========================================================
    # STATS CARDS
    # =========================================================
    def build_cards(self):
        cards_frame = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
        )
        cards_frame.pack(fill="x", padx=30, pady=10)

        stats = [
            ("Total Jobs", "184", "📄"),
            ("Completed", "174", "✅"),
            ("Pending", "7", "⏳"),
            ("Printers", "12", "🖨"),
        ]

        for title, value, icon in stats:
            card = ctk.CTkFrame(
                cards_frame,
                fg_color=self.colors["card"],
                corner_radius=26,
                height=150,
            )
            card.pack(side="left", fill="both", expand=True, padx=10)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=20, pady=(18, 0))

            ctk.CTkLabel(
                top,
                text=icon,
                font=("Segoe UI Emoji", 28),
            ).pack(side="left")

            ctk.CTkLabel(
                top,
                text=title,
                text_color=self.colors["muted"],
                font=("Segoe UI", 15),
            ).pack(side="right")

            ctk.CTkLabel(
                card,
                text=value,
                font=("Segoe UI", 42, "bold"),
            ).pack(anchor="w", padx=20, pady=(10, 0))

    # =========================================================
    # MAIN AREA
    # =========================================================
    def build_main_area(self):
        area = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
        )
        area.pack(fill="both", expand=True, padx=30, pady=20)

        self.build_jobs_table(area)
        self.build_right_panel(area)

    # =========================================================
    # JOBS TABLE
    # =========================================================
    def build_jobs_table(self, parent):
        table_card = ctk.CTkFrame(
            parent,
            fg_color=self.colors["card"],
            corner_radius=28,
        )
        table_card.pack(side="left", fill="both", expand=True, padx=(0, 15))

        topbar = ctk.CTkFrame(table_card, fg_color="transparent")
        topbar.pack(fill="x", padx=25, pady=20)

        ctk.CTkLabel(
            topbar,
            text="Recent Jobs",
            font=("Segoe UI", 26, "bold"),
        ).pack(side="left")

        self.search_var = tk.StringVar()

        search = ctk.CTkEntry(
            topbar,
            placeholder_text="Search jobs...",
            width=250,
            height=42,
            textvariable=self.search_var,
        )
        search.pack(side="right")

        # HEADERS
        headers = ctk.CTkFrame(table_card, fg_color="transparent")
        headers.pack(fill="x", padx=25)

        columns = [
            "ID",
            "STATUS",
            "TYPE",
            "PRINTER",
            "FILENAME",
            "CREATED",
            "ACTIONS",
        ]

        widths = [60, 140, 100, 260, 240, 140, 120]

        for i, col in enumerate(columns):
            lbl = ctk.CTkLabel(
                headers,
                text=col,
                font=("Segoe UI", 13, "bold"),
                text_color=self.colors["muted"],
                width=widths[i],
                anchor="w",
            )
            lbl.pack(side="left", padx=5, pady=10)

        divider = ctk.CTkFrame(
            table_card,
            height=1,
            fg_color=self.colors["border"],
        )
        divider.pack(fill="x", padx=20, pady=(0, 10))

        self.scroll = ctk.CTkScrollableFrame(
            table_card,
            fg_color="transparent",
        )
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.load_jobs()

        # clickable header actions: refresh every time
        self.root.after(5000, lambda: threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start())

    # =========================================================
    # LOAD JOBS
    # =========================================================
    def load_jobs(self):
        # prefer jobs fetched from backend; fallback to static list
        for job in getattr(self, 'jobs', self.jobs):
            row = ctk.CTkFrame(
                self.scroll,
                fg_color=self.colors["bg"],
                corner_radius=18,
                height=70,
            )
            row.pack(fill="x", pady=8)

            ctk.CTkLabel(
                row,
                text=f"#{job['id']}",
                width=60,
                anchor="w",
                font=("Segoe UI", 13, "bold"),
            ).pack(side="left", padx=10)

            # STATUS
            status_colors = {
                "Completed": ("#14532D", "#22C55E"),
                "Pending": ("#78350F", "#F59E0B"),
                "Failed": ("#7F1D1D", "#EF4444"),
            }

            bg, fg = status_colors.get(job["status"], ("gray", "white"))

            status = ctk.CTkLabel(
                row,
                text=job["status"],
                fg_color=bg,
                text_color=fg,
                width=110,
                height=32,
                corner_radius=100,
                font=("Segoe UI", 12, "bold"),
            )
            status.pack(side="left", padx=8)

            ctk.CTkLabel(
                row,
                text=job["type"],
                width=100,
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=job["printer"],
                width=260,
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=job["filename"],
                width=240,
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=job["created"],
                width=140,
                anchor="w",
            ).pack(side="left")

            action_frame = ctk.CTkFrame(row, fg_color="transparent")
            action_frame.pack(side="left", padx=5)

            restart_btn = ctk.CTkButton(
                action_frame,
                text="↻",
                width=38,
                height=38,
                corner_radius=12,
                command=lambda j=job: self.restart_job(j),
            )
            restart_btn.pack(side="left", padx=4)

            delete_btn = ctk.CTkButton(
                action_frame,
                text="✕",
                width=38,
                height=38,
                corner_radius=12,
                fg_color="#DC2626",
                hover_color="#B91C1C",
                command=lambda j=job: self.delete_job(j),
            )
            delete_btn.pack(side="left", padx=4)

    # =========================================================
    # RIGHT PANEL
    # =========================================================
    def build_right_panel(self, parent):
        right = ctk.CTkFrame(
            parent,
            fg_color="transparent",
            width=320,
        )
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # QUICK ACTIONS
        actions = ctk.CTkFrame(
            right,
            fg_color=self.colors["card"],
            corner_radius=28,
        )
        actions.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            actions,
            text="Quick Actions",
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w", padx=20, pady=20)

        action_buttons = [
            "Restart Server",
            "Add Printer",
            "Export Logs",
            "Clear Queue",
        ]

        for action in action_buttons:
            btn = ctk.CTkButton(
                actions,
                text=action,
                height=50,
                corner_radius=16,
                font=("Segoe UI", 14, "bold"),
            )
            btn.pack(fill="x", padx=20, pady=8)

        # HEALTH CARD
        health = ctk.CTkFrame(
            right,
            fg_color=self.colors["card"],
            corner_radius=28,
        )
        health.pack(fill="both", expand=True)

        ctk.CTkLabel(
            health,
            text="System Health",
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w", padx=20, pady=20)

        stats = [
            ("Server Status", "RUNNING"),
            ("API Status", "ONLINE"),
            ("Queue Size", "12 Jobs"),
            ("Uptime", "2h 45m"),
            ("CPU Usage", "32%"),
            ("Memory", "58%"),
        ]

        for label, value in stats:
            item = ctk.CTkFrame(
                health,
                fg_color=self.colors["bg"],
                corner_radius=18,
                height=65,
            )
            item.pack(fill="x", padx=20, pady=8)

            ctk.CTkLabel(
                item,
                text=label,
                font=("Segoe UI", 13),
                text_color=self.colors["muted"],
            ).pack(anchor="w", padx=16, pady=(10, 0))

            ctk.CTkLabel(
                item,
                text=value,
                font=("Segoe UI", 17, "bold"),
            ).pack(anchor="w", padx=16)

    # =========================================================
    # ACTIONS
    # =========================================================
    def restart_job(self, job):
        # Try to restart via local DB first
        try:
            if os.path.exists(self.db_path):
                conn = sqlite3.connect(self.db_path)
                conn.execute("UPDATE jobs SET status='pending', retries=0 WHERE id=?", (job['id'],))
                conn.commit()
                conn.close()
                messagebox.showinfo("Restart", f"Restarted job #{job['id']}")
                threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start()
                return
        except Exception as exc:
            print("DB restart failed:", exc)

        # Fallback: try calling backend admin endpoint (if available)
        try:
            r = requests.post(f"{self.api_base}/jobs/{job['id']}/restart", timeout=5)
            if r.status_code in (200, 204):
                messagebox.showinfo("Restart", f"Restarted job #{job['id']}")
                threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start()
                return
        except Exception:
            pass

        messagebox.showwarning("Restart", "Unable to restart job (no DB or API endpoint available)")

    def delete_job(self, job):
        answer = messagebox.askyesno("Delete Job", f"Delete job #{job['id']}?")
        if not answer:
            return

        try:
            if os.path.exists(self.db_path):
                conn = sqlite3.connect(self.db_path)
                conn.execute("DELETE FROM jobs WHERE id=?", (job['id'],))
                conn.commit()
                conn.close()
                messagebox.showinfo("Deleted", "Job deleted successfully")
                threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start()
                return
        except Exception as exc:
            print("DB delete failed:", exc)

        try:
            r = requests.delete(f"{self.api_base}/jobs/{job['id']}", timeout=5)
            if r.status_code in (200, 204):
                messagebox.showinfo("Deleted", "Job deleted successfully")
                threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start()
                return
        except Exception:
            pass

        messagebox.showwarning("Delete", "Unable to delete job (no DB or API endpoint available)")

    # =========================================================
    # BACKEND INTEGRATION
    # =========================================================
    def _on_resize(self, event):
        try:
            new_width = max(200, int(event.width * 0.25))
            self.sidebar.configure(width=new_width)
        except Exception:
            pass

    def _manual_refresh(self):
        threading.Thread(target=self._fetch_and_load_jobs, daemon=True).start()

    def _background_refresh(self):
        while True:
            try:
                self._fetch_status()
                self._fetch_and_load_jobs()
            except Exception:
                pass
            time.sleep(5)

    def _fetch_status(self):
        try:
            r = requests.get(f"{self.api_base}/", timeout=3)
            if r.status_code == 200:
                data = r.json()
                # update status label if present
                try:
                    status_label = getattr(self, 'status_label', None)
                    if status_label:
                        status_label.configure(text=("● RUNNING" if data.get('status') == 'running' else "● IDLE"))
                except Exception:
                    pass
        except Exception:
            pass

    def _fetch_and_load_jobs(self):
        try:
            r = requests.get(f"{self.api_base}/jobs", timeout=5)
            if r.status_code == 200:
                payload = r.json()
                jobs = payload.get('jobs') if isinstance(payload, dict) else payload
                # normalize to simple dicts
                self.jobs = []
                for j in jobs:
                    self.jobs.append({
                        'id': j.get('id'),
                        'status': j.get('status'),
                        'type': j.get('type'),
                        'printer': j.get('printer'),
                        'filename': j.get('filename'),
                        'created': j.get('created')
                    })
                # refresh the UI on main thread
                try:
                    self.root.after(0, self._reload_jobs_ui)
                except Exception:
                    pass
        except Exception:
            # fallback: try reading DB directly
            try:
                if os.path.exists(self.db_path):
                    conn = sqlite3.connect(self.db_path)
                    rows = conn.execute("SELECT id, status, retries, created, data FROM jobs ORDER BY id DESC LIMIT 50").fetchall()
                    conn.close()
                    self.jobs = []
                    for r in rows:
                        d = json.loads(r[4]) if r[4] else {}
                        self.jobs.append({
                            'id': r[0], 'status': r[1], 'type': d.get('type','?'),
                            'printer': d.get('printer','?'), 'filename': d.get('filename','?'), 'created': r[3]
                        })
                    self.root.after(0, self._reload_jobs_ui)
            except Exception:
                pass

    def _reload_jobs_ui(self):
        # clear existing rows in scroll frame
        for child in self.scroll.winfo_children():
            child.destroy()
        self.load_jobs()

    # =========================================================
    # THEME TOGGLE
    # =========================================================
    def toggle_theme(self):
        if self.theme_switch.get() == 1:
            ctk.set_appearance_mode("light")
            self.current_theme = "light"
            self.colors = self.light_colors
        else:
            ctk.set_appearance_mode("dark")
            self.current_theme = "dark"
            self.colors = self.dark_colors

    # =========================================================
    # RUN
    # =========================================================
    def run(self):
        self.root.mainloop()


# =============================================================
# START APP
# =============================================================
if __name__ == "__main__":
    app = ModernPrintServer()
    app.run()
