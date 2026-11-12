"""Read application settings (stored in the database, with safe defaults)."""
from __future__ import annotations

from config import DEFAULT_SETTINGS, HARD_MAX_UPLOAD_MB, SUPPORTED_EXTENSIONS
from database import query_all, query_one


def get_setting(key: str, default: str | None = None) -> str:
    row = query_one("SELECT value FROM application_settings WHERE key=?", (key,))
    if row is not None:
        return row["value"]
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key, "")


def get_all_settings() -> dict:
    values = dict(DEFAULT_SETTINGS)
    for row in query_all("SELECT key, value FROM application_settings"):
        values[row["key"]] = row["value"]
    return values


def allowed_extensions() -> list[str]:
    raw = get_setting("allowed_extensions")
    chosen = [e.strip().lower() for e in raw.split(",") if e.strip()]
    result = [e for e in SUPPORTED_EXTENSIONS if e in chosen]
    return result or list(SUPPORTED_EXTENSIONS)


def max_upload_bytes() -> int:
    try:
        mb = float(get_setting("max_upload_mb") or 10)
    except ValueError:
        mb = 10
    mb = max(0.1, min(mb, HARD_MAX_UPLOAD_MB))
    return int(mb * 1024 * 1024)


def event_categories() -> list[str]:
    cats = [c.strip() for c in get_setting("event_categories").split(",") if c.strip()]
    return cats or ["General"]
