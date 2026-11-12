"""Small shared helpers: time, formatting, status labels, logging, CSV safety."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

try:  # zoneinfo needs the tzdata package on Windows (it is in requirements.txt)
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def school_tz():
    name = os.environ.get("MSES_TIMEZONE", "Asia/Kolkata")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    if name == "Asia/Kolkata":
        return timezone(timedelta(hours=5, minutes=30))
    return timezone.utc


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def now_local() -> datetime:
    return datetime.now(school_tz()).replace(tzinfo=None)


def local_now_str() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M")


def local_today_str() -> str:
    return now_local().strftime("%Y-%m-%d")


def utc_to_local(ts: str | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Convert a stored UTC timestamp to the school's local time for display."""
    if not ts:
        return "-"
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(school_tz()).strftime(fmt)
    except ValueError:
        return str(ts)


def fmt_local(ts: str | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format a school-local 'YYYY-MM-DD HH:MM' value."""
    if not ts:
        return "-"
    for src in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[:16] if src.endswith("%M") else ts[:10], src).strftime(
                fmt if src.endswith("%M") else "%d %b %Y"
            )
        except ValueError:
            continue
    return str(ts)


def fmt_date(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.strptime(ts[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return str(ts)


def human_size(num: int | float) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def class_label(name: str) -> str:
    name = str(name or "")
    return f"Class {name}" if name.isdigit() else name


# ---- submission statuses -------------------------------------------------
NOT_STARTED = "Not Started"
SUBMITTED = "Submitted"
UNDER_REVIEW = "Under Review"
APPROVED = "Approved"
REJECTED = "Rejected"
RESUBMISSION_REQUIRED = "Resubmission Required"
RESUBMITTED = "Resubmitted"

ALL_STATUSES = (NOT_STARTED, SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED,
                RESUBMISSION_REQUIRED, RESUBMITTED)
STORED_STATUSES = ALL_STATUSES[1:]
PENDING_STATUSES = (SUBMITTED, UNDER_REVIEW, RESUBMITTED)      # waiting for a teacher
STUDENT_CAN_UPLOAD = (None, NOT_STARTED, REJECTED, RESUBMISSION_REQUIRED)

STATUS_META = {
    NOT_STARTED: ("⚪", "#475569", "#E2E8F0"),
    SUBMITTED: ("📤", "#1D4ED8", "#DBEAFE"),
    UNDER_REVIEW: ("🔍", "#B45309", "#FEF3C7"),
    APPROVED: ("✅", "#047857", "#D1FAE5"),
    REJECTED: ("❌", "#B91C1C", "#FEE2E2"),
    RESUBMISSION_REQUIRED: ("🔁", "#C2410C", "#FFEDD5"),
    RESUBMITTED: ("📨", "#6D28D9", "#EDE9FE"),
}

EVENT_STATUS_META = {
    "draft": ("📝", "#475569", "#E2E8F0", "Draft"),
    "published": ("🟢", "#047857", "#D1FAE5", "Published"),
    "closed": ("🔒", "#B45309", "#FEF3C7", "Closed"),
    "archived": ("🗄️", "#6B7280", "#F3F4F6", "Archived"),
}


# ---- CSV safety -----------------------------------------------------------
def csv_safe(value):
    """Stop spreadsheet programs from running text that starts with = + - @ as a formula."""
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


# ---- logging --------------------------------------------------------------
_LOGGING_READY = False


def setup_logging() -> None:
    global _LOGGING_READY
    if _LOGGING_READY:
        return
    from config import get_paths

    paths = get_paths()
    paths.ensure()
    handler = RotatingFileHandler(
        paths.logs_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("mses")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _LOGGING_READY = True
