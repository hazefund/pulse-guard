"""
Main Command-Line Interface (CLI) for PulseGuard.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import sys
import time
import urllib.request
from typing import Optional

from .config import load_config, build_notifiers_from_config
from .models import parse_duration_to_seconds, JobStatus
from .server import PulseServer
from .storage import Storage
from .watchdog import Watchdog
from .wrapper import execute_and_pulse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def format_timestamp(ts: Optional[float]) -> str:
    if ts is None:
        return "Never"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(sec: Optional[float]) -> str:
    if sec is None:
        return "N/A"
    if sec < 60:
        return f"{sec:.1f}s"
    if sec < 3600:
        return f"{sec / 60:.1f}m"
    return f"{sec / 3600:.1f}h"


def handle_serve(args: argparse.Namespace) -> int:
    cfg = load_config(args.config) if args.config else {}
    server_cfg = cfg.get("server", {})
    host = args.host or server_cfg.get("host", "0.0.0.0")
    port = args.port or int(server_cfg.get("port", 8080))
    db_path = args.db or server_cfg.get("database_path", "pulseguard.db")

    notifiers = build_notifiers_from_config(cfg)
    storage = Storage(db_path=db_path)
    watchdog = Watchdog(storage=storage, notifiers=notifiers)

    server = PulseServer(host=host, port=port, watchdog=watchdog, storage=storage)

    print("╔══════════════════════════════════════════════════════════╗")
    print("║               🛡️  PulseGuard Heartbeat Daemon            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"📡 Webhook Ingestion API: http://{host}:{port}/ping/<job_id>")
    print(f"💾 Persistent Storage:    {db_path}")
    print(f"📢 Active Channels:       {[n.__class__.__name__ for n in notifiers]}")
    print("────────────────────────────────────────────────────────────\n")

    server.start()
    return 0


def handle_ping(args: argparse.Namespace) -> int:
    base_url = args.url.rstrip("/")
    url = f"{base_url}/ping/{args.job}"

    payload = {"message": args.message or "Manual ping from CLI"}
    if args.interval:
        payload["interval"] = args.interval
    if args.grace:
        payload["grace"] = args.grace

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "PulseGuard-CLI/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode())
            print(f"✅ Ping successfully sent to {args.job} (Status: {res.get('job_status', 'ok')})")
            return 0
    except Exception as e:
        print(f"❌ Failed to ping PulseGuard: {e}", file=sys.stderr)
        return 1


def handle_run(args: argparse.Namespace) -> int:
    if not args.command:
        print("❌ Error: No command provided after '--'", file=sys.stderr)
        return 1

    return execute_and_pulse(
        job_name=args.job,
        command=args.command,
        server_url=args.url,
        interval=args.interval,
        grace=args.grace
    )


def handle_status(args: argparse.Namespace) -> int:
    jobs = []
    # If URL provided and server running, query API
    try:
        req = urllib.request.Request(f"{args.url.rstrip('/')}/api/status", headers={"User-Agent": "PulseGuard-CLI/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            jobs = data.get("jobs", [])
    except Exception:
        # Fall back to local DB
        storage = Storage(db_path=args.db)
        local_jobs = storage.get_all_jobs()
        jobs = [
            {
                "name": j.name,
                "status": j.status.value,
                "interval_seconds": j.interval_seconds,
                "grace_seconds": j.grace_seconds,
                "last_ping_at": j.last_ping_at,
                "last_duration_seconds": j.last_duration_seconds,
                "last_exit_code": j.last_exit_code,
                "last_message": j.last_message,
            }
            for j in local_jobs
        ]

    print("\n╔════════════════════════════════════════════════════════════════════════════════════════════╗")
    print("║                              🛡️  PulseGuard Job Registry                                    ║")
    print("╚════════════════════════════════════════════════════════════════════════════════════════════╝\n")

    if not jobs:
        print("  No monitored jobs registered yet. Start a job or send a ping!\n")
        return 0

    print(f"  {'Job Name':<20} {'Status':<10} {'Interval':<10} {'Last Ping (UTC)':<22} {'Duration':<10} {'Exit'}")
    print("  " + "─" * 84)

    status_emojis = {
        "healthy": "🟢 HEALTHY",
        "late": "🔴 LATE",
        "failed": "💥 FAILED",
        "pending": "⚪ PENDING",
    }

    for j in jobs:
        st_text = status_emojis.get(j["status"], j["status"].upper())
        interval_str = f"{j['interval_seconds']}s"
        last_seen = format_timestamp(j["last_ping_at"])
        dur = format_duration(j["last_duration_seconds"])
        exit_c = str(j["last_exit_code"]) if j["last_exit_code"] is not None else "-"
        print(f"  {j['name'][:18]:<20} {st_text:<10} {interval_str:<10} {last_seen:<22} {dur:<10} {exit_c}")

    print("")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PulseGuard: Self-Hosted Deadman's Switch & Cron Heartbeat Monitor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the background HTTP heartbeat daemon")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    serve_parser.add_argument("--port", type=int, default=8080, help="Listen port")
    serve_parser.add_argument("--db", default="pulseguard.db", help="Path to SQLite database")
    serve_parser.add_argument("--config", default=None, help="Path to pulseguard.yaml config file")

    # ping
    ping_parser = subparsers.add_parser("ping", help="Send a manual heartbeat ping for a job")
    ping_parser.add_argument("job", help="Unique identifier for the job")
    ping_parser.add_argument("--interval", default="1d", help="Expected interval (e.g. 15m, 1h, 1d)")
    ping_parser.add_argument("--grace", default="10m", help="Grace period before declaring late")
    ping_parser.add_argument("--message", default=None, help="Optional log message or summary")
    ping_parser.add_argument("--url", default="http://localhost:8080", help="PulseGuard server URL")

    # run
    run_parser = subparsers.add_parser("run", help="Wrap and execute a command, reporting duration & exit status")
    run_parser.add_argument("--job", required=True, help="Unique identifier for the job")
    run_parser.add_argument("--interval", default="1d", help="Expected interval (e.g. 15m, 1h, 1d)")
    run_parser.add_argument("--grace", default="10m", help="Grace period before declaring late")
    run_parser.add_argument("--url", default="http://localhost:8080", help="PulseGuard server URL")
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command and arguments to execute")

    # status
    status_parser = subparsers.add_parser("status", help="Print table of monitored jobs and health states")
    status_parser.add_argument("--db", default="pulseguard.db", help="Local SQLite database fallback")
    status_parser.add_argument("--url", default="http://localhost:8080", help="PulseGuard server URL")

    args = parser.parse_args()

    if args.subcommand == "serve":
        return handle_serve(args)
    elif args.subcommand == "ping":
        return handle_ping(args)
    elif args.subcommand == "run":
        # Strip leading '--' if present in command
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        return handle_run(args)
    elif args.subcommand == "status":
        return handle_status(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
