"""
Lightweight HTTP server daemon for PulseGuard.
Provides REST/webhook ingestion for heartbeats, status queries, and failure reports.
Uses standard library http.server (no external frameworks required).
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import threading
import time
from urllib.parse import urlparse, parse_qs
from typing import Optional

from .models import parse_duration_to_seconds
from .watchdog import Watchdog
from .storage import Storage

logger = logging.getLogger("pulseguard.server")


def make_request_handler(watchdog: Watchdog, storage: Storage):
    class PulseHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Suppress default noisy console access log, use standard logger
            logger.debug("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

        def _send_json(self, status_code: int, data: dict):
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            params = parse_qs(parsed.query)

            if path == "/health":
                return self._send_json(200, {"status": "ok", "time": time.time()})

            if path == "/api/status":
                jobs = storage.get_all_jobs()
                data = [
                    {
                        "name": j.name,
                        "status": j.status.value,
                        "interval_seconds": j.interval_seconds,
                        "grace_seconds": j.grace_seconds,
                        "last_ping_at": j.last_ping_at,
                        "last_duration_seconds": j.last_duration_seconds,
                        "last_exit_code": j.last_exit_code,
                        "last_message": j.last_message,
                        "alert_sent": j.alert_sent,
                    }
                    for j in jobs
                ]
                return self._send_json(200, {"jobs": data})

            # Check for /ping/<job_id>
            if path.startswith("/ping/"):
                job_id = path[len("/ping/"):].strip()
                if not job_id:
                    return self._send_json(400, {"error": "Missing job_id in path"})

                interval_sec = None
                if "interval" in params:
                    try:
                        interval_sec = parse_duration_to_seconds(params["interval"][0])
                    except ValueError:
                        pass

                grace_sec = None
                if "grace" in params:
                    try:
                        grace_sec = parse_duration_to_seconds(params["grace"][0])
                    except ValueError:
                        pass

                duration = None
                if "duration" in params:
                    try:
                        duration = float(params["duration"][0])
                    except ValueError:
                        pass

                msg = params.get("message", [None])[0]
                job = watchdog.record_ping(
                    job_name=job_id,
                    message=msg,
                    duration=duration,
                    interval_seconds=interval_sec,
                    grace_seconds=grace_sec
                )
                return self._send_json(200, {"status": "ok", "job": job.name, "job_status": job.status.value})

            self._send_json(404, {"error": "Not Found"})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            content_len = int(self.headers.get("Content-Length", 0))
            payload = {}
            if content_len > 0:
                try:
                    payload = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except Exception:
                    pass

            if path.startswith("/ping/"):
                job_id = path[len("/ping/"):].strip()
                if not job_id:
                    return self._send_json(400, {"error": "Missing job_id in path"})

                interval_sec = None
                if "interval" in payload:
                    try:
                        interval_sec = parse_duration_to_seconds(payload["interval"])
                    except ValueError:
                        pass

                grace_sec = None
                if "grace" in payload:
                    try:
                        grace_sec = parse_duration_to_seconds(payload["grace"])
                    except ValueError:
                        pass

                job = watchdog.record_ping(
                    job_name=job_id,
                    message=payload.get("message"),
                    duration=payload.get("duration"),
                    interval_seconds=interval_sec,
                    grace_seconds=grace_sec
                )
                return self._send_json(200, {"status": "ok", "job": job.name, "job_status": job.status.value})

            if path.startswith("/fail/"):
                job_id = path[len("/fail/"):].strip()
                if not job_id:
                    return self._send_json(400, {"error": "Missing job_id in path"})

                exit_code = int(payload.get("exit_code", 1))
                error_msg = payload.get("message", "Job reported execution error")
                duration = payload.get("duration")

                job = watchdog.record_failure(job_id, exit_code=exit_code, error_message=error_msg, duration=duration)
                return self._send_json(200, {"status": "failure_recorded", "job": job.name})

            self._send_json(404, {"error": "Not Found"})

    return PulseHTTPHandler


class PulseServer:
    def __init__(self, host: str, port: int, watchdog: Watchdog, storage: Storage):
        self.host = host
        self.port = port
        self.watchdog = watchdog
        self.storage = storage
        handler_cls = make_request_handler(watchdog, storage)
        self.server = HTTPServer((host, port), handler_cls)
        self._running = False
        self._watchdog_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True

        # Background watchdog loop
        def watchdog_loop():
            while self._running:
                try:
                    self.watchdog.check_all_jobs()
                except Exception as e:
                    logger.error(f"Error in watchdog cycle: {e}")
                time.sleep(5)

        self._watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        logger.info(f"PulseGuard server listening on http://{self.host}:{self.port}")
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self.server.server_close()
