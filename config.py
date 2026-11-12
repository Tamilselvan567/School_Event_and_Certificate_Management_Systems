"""Central configuration for the Motilal School Event Management System.

Every folder the application uses is resolved to an ABSOLUTE path from this file,
so the app behaves the same no matter which folder your terminal is in.

You normally do not need to change anything here. For hosting, set the
environment variable MSES_STORAGE_ROOT to the folder of your persistent disk
(for example /var/data) and everything (database, uploads, certificates,
backups, logs) will be stored there.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "Motilal School Event Management System"
APP_VERSION = "1.0.0"

# File types students may ever upload (admins can restrict this list further).
SUPPORTED_EXTENSIONS = ("pdf", "docx", "pptx", "jpg", "jpeg", "png")
# The web server never accepts uploads larger than this (see .streamlit/config.toml).
HARD_MAX_UPLOAD_MB = 50

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

# Default values for settings that the administrator can change in the app.
DEFAULT_SETTINGS = {
    "school_name": "Motilal School",
    "principal_name": "",
    "school_address": "",
    "school_phone": "",
    "school_email": "",
    "school_logo": "",
    "principal_signature": "",
    "default_academic_year": "",
    "max_upload_mb": "10",
    "allowed_extensions": ",".join(SUPPORTED_EXTENSIONS),
    "event_categories": "Science,Art,Sports,Technology,Environment,Mathematics,Cultural,General",
    "cert_primary_color": "#1E3A8A",
    "cert_secondary_color": "#0EA5E9",
    "cert_accent_color": "#F59E0B",
    "cert_footer_text": "",
    "cert_default_type": "Participation",
    "backup_enabled": "1",
    "backup_interval_hours": "24",
    "backup_keep_count": "14",
    "backup_include_files": "1",
    "session_timeout_minutes": "60",
    "public_base_url": "",
}


def _resolve(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


@dataclass(frozen=True)
class Paths:
    root: Path
    data_dir: Path
    db_path: Path
    uploads_dir: Path
    certificates_dir: Path
    backups_dir: Path
    assets_dir: Path
    logs_dir: Path

    @property
    def logo_dir(self) -> Path:
        return self.assets_dir / "school_logo"

    @property
    def signatures_dir(self) -> Path:
        return self.assets_dir / "signatures"

    @property
    def submissions_dir(self) -> Path:
        return self.uploads_dir / "submissions"

    @property
    def event_files_dir(self) -> Path:
        return self.uploads_dir / "events"

    def ensure(self) -> None:
        """Create every folder the app needs. Safe to call again and again.

        Only the folders needed to open the database are essential. If another folder
        (for example backups) cannot be created, the app keeps working and the problem
        shows up when that feature is used."""
        essential = (self.root, self.data_dir, self.db_path.parent)
        optional = (self.uploads_dir, self.submissions_dir, self.event_files_dir, self.certificates_dir,
                    self.backups_dir, self.assets_dir, self.logo_dir, self.signatures_dir, self.logs_dir)
        for folder in essential:
            folder.mkdir(parents=True, exist_ok=True)
        for folder in optional:
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass


def get_paths() -> Paths:
    """Resolve all storage locations from environment variables (read each call)."""
    root = _resolve("MSES_STORAGE_ROOT", BASE_DIR)
    data_dir = _resolve("MSES_DATA_DIR", root / "data")
    return Paths(
        root=root,
        data_dir=data_dir,
        db_path=_resolve("MSES_DB_PATH", data_dir / "school_events.db"),
        uploads_dir=_resolve("MSES_UPLOADS_DIR", root / "uploads"),
        certificates_dir=_resolve("MSES_CERTIFICATES_DIR", root / "certificates"),
        backups_dir=_resolve("MSES_BACKUPS_DIR", root / "backups"),
        assets_dir=_resolve("MSES_ASSETS_DIR", root / "assets"),
        logs_dir=_resolve("MSES_LOGS_DIR", root / "logs"),
    )
