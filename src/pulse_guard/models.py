"""
Data models and duration utilities for PulseGuard.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Optional


class JobStatus(str, Enum):
    HEALTHY = "healthy"
    LATE = "late"
    FAILED = "failed"
    PENDING = "pending"


def parse_duration_to_seconds(duration_str: str | int) -> int:
    """
    Parse duration strings like '30s', '15m', '2h', '1d' into integer seconds.
    If already an integer, returns as is.
    """
    if isinstance(duration_str, int):
        return duration_str
    
    clean_str = duration_str.strip().lower()
    if clean_str.isdigit():
        return int(clean_str)

    match = re.match(r"^(\d+)\s*([smhdw])$", clean_str)
    if not match:
        raise ValueError(f"Invalid duration format: '{duration_str}'. Use e.g. '30s', '15m', '2h', '1d'.")

    val, unit = match.groups()
    amount = int(val)
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
    }
    return amount * multipliers[unit]


@dataclass
class JobConfig:
    """Static or dynamically registered configuration for a tracked job."""
    name: str
    interval_seconds: int
    grace_seconds: int = 300  # Default 5-minute grace period
    description: str = ""
    notify_on_recovery: bool = True


@dataclass
class JobRecord:
    """Runtime state of a tracked job."""
    name: str
    interval_seconds: int
    grace_seconds: int
    status: JobStatus = JobStatus.PENDING
    last_ping_at: Optional[float] = None
    last_start_at: Optional[float] = None
    last_duration_seconds: Optional[float] = None
    last_exit_code: Optional[int] = None
    last_message: Optional[str] = None
    alert_sent: bool = False
    description: str = ""
