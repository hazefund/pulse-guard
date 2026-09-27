"""
Watchdog engine for tracking heartbeats, detecting late jobs, and triggering alerts.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Optional

from .models import JobRecord, JobStatus
from .notifiers import BaseNotifier
from .storage import Storage

logger = logging.getLogger("pulseguard.watchdog")


class Watchdog:
    def __init__(self, storage: Storage, notifiers: list[BaseNotifier]):
        self.storage = storage
        self.notifiers = notifiers

    def check_all_jobs(self, current_time: Optional[float] = None) -> list[JobRecord]:
        """
        Evaluate all jobs against current time.
        Detects late heartbeats, updates states, and fires alerts.
        """
        now = current_time or time.time()
        jobs = self.storage.get_all_jobs()
        updated_jobs: list[JobRecord] = []

        for job in jobs:
            # If job has never pinged, calculate timeout from when it was registered or skip
            if job.last_ping_at is None:
                continue

            deadline = job.last_ping_at + job.interval_seconds + job.grace_seconds

            if now > deadline and job.status != JobStatus.LATE:
                # Job is late!
                job.status = JobStatus.LATE
                if not job.alert_sent:
                    self._fire_late_alert(job, now, deadline)
                    job.alert_sent = True
                self.storage.upsert_job(job)
                updated_jobs.append(job)

        return updated_jobs

    def record_ping(self, job_name: str, message: Optional[str] = None, duration: Optional[float] = None,
                    interval_seconds: Optional[int] = None, grace_seconds: Optional[int] = None) -> JobRecord:
        """
        Record an incoming healthy heartbeat.
        Auto-registers job if it does not yet exist.
        Fires recovery alert if the job was previously LATE or FAILED.
        """
        now = time.time()
        job = self.storage.get_job(job_name)

        if not job:
            job = JobRecord(
                name=job_name,
                interval_seconds=interval_seconds or 86400,  # default 24h if unspecified
                grace_seconds=grace_seconds or 300,
                status=JobStatus.HEALTHY,
                last_ping_at=now,
                last_duration_seconds=duration,
                last_message=message,
                alert_sent=False
            )
        else:
            was_in_alarm = (job.status in (JobStatus.LATE, JobStatus.FAILED)) and job.alert_sent

            job.status = JobStatus.HEALTHY
            job.last_ping_at = now
            if duration is not None:
                job.last_duration_seconds = duration
            if message is not None:
                job.last_message = message

            if was_in_alarm:
                self._fire_recovery_alert(job)
                job.alert_sent = False

        self.storage.upsert_job(job)
        self.storage.record_history(job_name, "ping", duration=duration, message=message)
        return job

    def record_failure(self, job_name: str, exit_code: int, error_message: Optional[str] = None,
                       duration: Optional[float] = None) -> JobRecord:
        """Record an explicit job execution failure."""
        now = time.time()
        job = self.storage.get_job(job_name)

        if not job:
            job = JobRecord(
                name=job_name,
                interval_seconds=86400,
                grace_seconds=300,
                status=JobStatus.FAILED,
                last_ping_at=now,
                last_exit_code=exit_code,
                last_message=error_message,
                alert_sent=True
            )
        else:
            job.status = JobStatus.FAILED
            job.last_exit_code = exit_code
            job.last_message = error_message
            job.last_duration_seconds = duration
            job.alert_sent = True

        self._fire_failure_alert(job, exit_code, error_message)
        self.storage.upsert_job(job)
        self.storage.record_history(job_name, "failure", duration=duration, exit_code=exit_code, message=error_message)
        return job

    def _fire_late_alert(self, job: JobRecord, now: float, deadline: float) -> None:
        overdue_minutes = round((now - deadline) / 60, 1)
        last_seen = datetime.fromtimestamp(job.last_ping_at or 0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        title = f"MISSING HEARTBEAT: '{job.name}' is late!"
        desc = (
            f"Job **{job.name}** failed to check in on schedule.\n"
            f"• **Expected Interval:** {job.interval_seconds}s (Grace: {job.grace_seconds}s)\n"
            f"• **Last Ping:** {last_seen}\n"
            f"• **Overdue By:** ~{overdue_minutes} minutes"
        )
        for notifier in self.notifiers:
            notifier.send(title, desc, level="danger")

    def _fire_failure_alert(self, job: JobRecord, exit_code: int, message: Optional[str]) -> None:
        title = f"JOB FAILED: '{job.name}' exited with error code {exit_code}"
        desc = (
            f"Job **{job.name}** reported an execution error.\n"
            f"• **Exit Code:** {exit_code}\n"
            f"• **Details:** {message or 'No output provided'}"
        )
        for notifier in self.notifiers:
            notifier.send(title, desc, level="danger")

    def _fire_recovery_alert(self, job: JobRecord) -> None:
        title = f"RESOLVED: '{job.name}' heartbeat restored"
        desc = f"Job **{job.name}** has checked in successfully and is now marked HEALTHY."
        for notifier in self.notifiers:
            notifier.send(title, desc, level="success")
