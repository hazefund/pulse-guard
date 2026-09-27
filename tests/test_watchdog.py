"""Unit tests for Watchdog state machine, alerts, and recovery."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from pulse_guard.models import JobStatus
from pulse_guard.notifiers import BaseNotifier
from pulse_guard.storage import Storage
from pulse_guard.watchdog import Watchdog


class MockNotifier(BaseNotifier):
    def __init__(self):
        self.sent_alerts = []

    def send(self, title: str, message: str, level: str = "warning") -> bool:
        self.sent_alerts.append({"title": title, "message": message, "level": level})
        return True


def test_watchdog_healthy_ping_and_late_transition():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        storage = Storage(db_path=tmp.name)
        notifier = MockNotifier()
        watchdog = Watchdog(storage=storage, notifiers=[notifier])

        t0 = 1000.0
        # 1. Record healthy ping with 60s interval and 10s grace
        job = watchdog.record_ping("backup", interval_seconds=60, grace_seconds=10)
        assert job.status == JobStatus.HEALTHY
        assert job.alert_sent is False
        assert len(notifier.sent_alerts) == 0

        # 2. Check at t = t0 + 50s (Still within 60s + 10s deadline = 70s)
        late_jobs = watchdog.check_all_jobs(current_time=job.last_ping_at + 50)
        assert len(late_jobs) == 0
        assert len(notifier.sent_alerts) == 0

        # 3. Check at t = t0 + 75s (Past deadline of 70s)
        late_jobs = watchdog.check_all_jobs(current_time=job.last_ping_at + 75)
        assert len(late_jobs) == 1
        assert late_jobs[0].status == JobStatus.LATE
        assert late_jobs[0].alert_sent is True
        assert len(notifier.sent_alerts) == 1
        assert notifier.sent_alerts[0]["level"] == "danger"
        assert "is late" in notifier.sent_alerts[0]["title"]

        # 4. Check again at t = t0 + 90s - should NOT fire duplicate alert
        late_jobs_repeat = watchdog.check_all_jobs(current_time=job.last_ping_at + 90)
        assert len(late_jobs_repeat) == 0
        assert len(notifier.sent_alerts) == 1

        # 5. Job recovers by sending new ping
        recovered_job = watchdog.record_ping("backup")
        assert recovered_job.status == JobStatus.HEALTHY
        assert recovered_job.alert_sent is False
        # Should have sent recovery alert!
        assert len(notifier.sent_alerts) == 2
        assert notifier.sent_alerts[1]["level"] == "success"
        assert "heartbeat restored" in notifier.sent_alerts[1]["title"]
