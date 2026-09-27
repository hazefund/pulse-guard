"""
CLI command wrapper for PulseGuard.
Executes arbitrary subprocess commands, tracks runtime, and auto-pings
PulseGuard server on success or failure.
"""

import json
import subprocess
import sys
import time
import urllib.request
from typing import Optional


def execute_and_pulse(
    job_name: str,
    command: list[str],
    server_url: str = "http://localhost:8080",
    interval: Optional[str] = None,
    grace: Optional[str] = None
) -> int:
    """
    Executes a shell command.
    Reports execution duration and exit code to PulseGuard.
    Returns the command's exit code.
    """
    base_url = server_url.rstrip("/")
    start_time = time.time()

    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        duration = round(time.time() - start_time, 2)
        exit_code = proc.returncode

        # Echo stdout & stderr so user script output is preserved in logs/cron
        if proc.stdout:
            sys.stdout.write(proc.stdout)
            sys.stdout.flush()
        if proc.stderr:
            sys.stderr.write(proc.stderr)
            sys.stderr.flush()

        if exit_code == 0:
            # Report successful ping
            payload = {
                "duration": duration,
                "message": f"Completed successfully in {duration}s"
            }
            if interval:
                payload["interval"] = interval
            if grace:
                payload["grace"] = grace
            _notify_server(f"{base_url}/ping/{job_name}", payload)
        else:
            # Report failure
            tail_stderr = proc.stderr[-400:] if proc.stderr else f"Exited with code {exit_code}"
            payload = {
                "exit_code": exit_code,
                "duration": duration,
                "message": tail_stderr.strip()
            }
            _notify_server(f"{base_url}/fail/{job_name}", payload)

        return exit_code

    except Exception as e:
        duration = round(time.time() - start_time, 2)
        _notify_server(f"{base_url}/fail/{job_name}", {
            "exit_code": 1,
            "duration": duration,
            "message": f"Execution exception: {str(e)}"
        })
        raise


def _notify_server(endpoint_url: str, payload: dict) -> None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "PulseGuard-Runner/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        # Avoid crashing the user command if the heartbeat server is temporarily unreachable
        sys.stderr.write(f"\n[PulseGuard] Warning: Failed to send pulse to {endpoint_url}: {e}\n")
