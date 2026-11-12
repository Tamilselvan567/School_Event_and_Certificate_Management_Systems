"""Input validation helpers. All raise ValidationError with a friendly message."""
from __future__ import annotations

import re
from datetime import date, datetime

from utils.errors import ValidationError
from utils.security import MAX_PASSWORD_LENGTH

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/._-]{0,19}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def clean_text(value, field: str, max_len: int = 200, required: bool = False) -> str:
    text = _CONTROL.sub("", str(value or "")).strip()
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return text


def validate_username(value) -> str:
    text = str(value or "").strip()
    if not USERNAME_RE.match(text):
        raise ValidationError(
            "Username must be 3-32 characters: letters, numbers, dot, dash or underscore."
        )
    return text


def validate_password(value) -> str:
    text = str(value or "")
    if len(text) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if len(text) > MAX_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", text) or not re.search(r"\d", text):
        raise ValidationError("Password must contain at least one letter and one number.")
    return text


def validate_person_name(value, field: str = "Name") -> str:
    text = re.sub(r"\s+", " ", clean_text(value, field, 100, required=True))
    if not re.search(r"[^\W\d_]", text):
        raise ValidationError(f"{field} must contain letters.")
    return text


def validate_roll(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError("Roll number is required.")
    if not ROLL_RE.match(text):
        raise ValidationError("Roll number may contain letters, numbers, / . _ - (max 20 characters).")
    return text


def validate_color(value, field: str = "Colour") -> str:
    text = str(value or "").strip()
    if not COLOR_RE.match(text):
        raise ValidationError(f"{field} must look like #1E3A8A.")
    return text.upper()


def parse_date(value, field: str = "Date") -> str:
    """Accepts a date object or 'YYYY-MM-DD'; returns 'YYYY-MM-DD'."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{field} is not a valid date (use YYYY-MM-DD).") from None


def parse_datetime(value, field: str = "Date and time") -> str:
    """Accepts a datetime or 'YYYY-MM-DD HH:MM'; returns 'YYYY-MM-DD HH:MM'."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    raise ValidationError(f"{field} is not valid (use YYYY-MM-DD HH:MM).")


def parse_positive_float(value, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number.") from None
    if number <= 0 or number > 100000:
        raise ValidationError(f"{field} must be greater than 0.")
    return number
