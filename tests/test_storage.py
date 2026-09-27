"""Unit tests for SQLite storage persistence."""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from pulse_guard.models import JobRecord, JobStatus
from pulse_guard.storage import Storage


def test_storage_upsert_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        storage = Storage(db_path=tmp.name)
        now = time.time()
        job = JobRecord(
            name="etl-pipeline",
            interval_seconds=3600,
            grace_seconds=300,
            status=JobStatus.HEALTHY,
            last_ping_at=now,
            last_duration_seconds=12.5,
            last_exit_code=0,
            last_message="Synced 1,500 records"
        )
        storage.upsert_job(job)

        fetched = storage.get_job("etl-pipeline")
        assert fetched is not None
        assert fetched.name == "etl-pipeline"
        assert fetched.interval_seconds == 3600
        assert fetched.last_duration_seconds == 12.5
        assert fetched.last_message == "Synced 1,500 records"

        all_jobs = storage.get_all_jobs()
        assert len(all_jobs) == 1
        assert all_jobs[0].name == "etl-pipeline"
