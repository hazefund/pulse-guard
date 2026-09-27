"""
Persistent SQLite storage for PulseGuard jobs and execution logs.
"""

import os
import sqlite3
import time
from typing import Optional

from .models import JobRecord, JobStatus


class Storage:
    def __init__(self, db_path: str = "pulseguard.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True) if os.path.dirname(self.db_path) else None
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    name TEXT PRIMARY KEY,
                    interval_seconds INTEGER NOT NULL,
                    grace_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    last_ping_at REAL,
                    last_start_at REAL,
                    last_duration_seconds REAL,
                    last_exit_code INTEGER,
                    last_message TEXT,
                    alert_sent INTEGER NOT NULL DEFAULT 0,
                    description TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ping_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    duration_seconds REAL,
                    exit_code INTEGER,
                    message TEXT
                )
            """)
            conn.commit()

    def upsert_job(self, job: JobRecord) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    name, interval_seconds, grace_seconds, status,
                    last_ping_at, last_start_at, last_duration_seconds,
                    last_exit_code, last_message, alert_sent, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    interval_seconds = excluded.interval_seconds,
                    grace_seconds = excluded.grace_seconds,
                    status = excluded.status,
                    last_ping_at = excluded.last_ping_at,
                    last_start_at = excluded.last_start_at,
                    last_duration_seconds = excluded.last_duration_seconds,
                    last_exit_code = excluded.last_exit_code,
                    last_message = excluded.last_message,
                    alert_sent = excluded.alert_sent,
                    description = excluded.description
            """, (
                job.name, job.interval_seconds, job.grace_seconds, job.status.value,
                job.last_ping_at, job.last_start_at, job.last_duration_seconds,
                job.last_exit_code, job.last_message, 1 if job.alert_sent else 0, job.description
            ))
            conn.commit()

    def get_job(self, name: str) -> Optional[JobRecord]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE name = ?", (name,))
            row = cur.fetchone()
            if not row:
                return None
            return JobRecord(
                name=row["name"],
                interval_seconds=row["interval_seconds"],
                grace_seconds=row["grace_seconds"],
                status=JobStatus(row["status"]),
                last_ping_at=row["last_ping_at"],
                last_start_at=row["last_start_at"],
                last_duration_seconds=row["last_duration_seconds"],
                last_exit_code=row["last_exit_code"],
                last_message=row["last_message"],
                alert_sent=bool(row["alert_sent"]),
                description=row["description"] or ""
            )

    def get_all_jobs(self) -> list[JobRecord]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM jobs ORDER BY name ASC")
            rows = cur.fetchall()
            return [
                JobRecord(
                    name=r["name"],
                    interval_seconds=r["interval_seconds"],
                    grace_seconds=r["grace_seconds"],
                    status=JobStatus(r["status"]),
                    last_ping_at=r["last_ping_at"],
                    last_start_at=r["last_start_at"],
                    last_duration_seconds=r["last_duration_seconds"],
                    last_exit_code=r["last_exit_code"],
                    last_message=r["last_message"],
                    alert_sent=bool(r["alert_sent"]),
                    description=r["description"] or ""
                )
                for r in rows
            ]

    def record_history(self, job_name: str, event_type: str, duration: Optional[float] = None,
                       exit_code: Optional[int] = None, message: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO ping_history (job_name, timestamp, event_type, duration_seconds, exit_code, message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (job_name, time.time(), event_type, duration, exit_code, message))
            conn.commit()
