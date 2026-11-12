"""Safe file handling: validation, storage inside the uploads folder, safe reading."""
from __future__ import annotations

import io
import logging
import os
import uuid
import zipfile
from pathlib import Path

from config import MIME_TYPES, SUPPORTED_EXTENSIONS, get_paths
from services.settings_store import allowed_extensions, max_upload_bytes
from utils.errors import AppError, ValidationError
from utils.helpers import human_size
from utils.security import safe_join, sanitize_filename

log = logging.getLogger("mses.files")

_MAX_UNZIPPED = 300 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"


def extension_of(filename: str) -> str:
    name = sanitize_filename(filename)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _check_signature(ext: str, data: bytes) -> bool:
    """Make sure the file's real content matches its extension (stops renamed/corrupt files)."""
    if ext == "pdf":
        return data[:5] == b"%PDF-" and b"%%EOF" in data[-2048:]
    if ext == "png":
        return data[:8] == _PNG
    if ext in ("jpg", "jpeg"):
        return data[:3] == b"\xff\xd8\xff"
    if ext in ("docx", "pptx"):
        if not zipfile.is_zipfile(io.BytesIO(data)):
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                if "[Content_Types].xml" not in names:
                    return False
                prefix = "word/" if ext == "docx" else "ppt/"
                if not any(n.startswith(prefix) for n in names):
                    return False
                if sum(i.file_size for i in zf.infolist()) > _MAX_UNZIPPED:
                    return False
                return zf.testzip() is None
        except (zipfile.BadZipFile, OSError):
            return False
    return False


def validate_upload(filename: str, data: bytes, allowed: list[str] | None = None,
                    max_bytes: int | None = None) -> tuple[str, str]:
    """Return (extension, safe_display_name) or raise ValidationError with a clear message."""
    if not filename or not str(filename).strip():
        raise ValidationError("No file was selected.")
    if not data:
        raise ValidationError("The selected file is empty.")
    safe_name = sanitize_filename(filename)
    ext = extension_of(safe_name)
    global_allowed = allowed_extensions()
    permitted = [e for e in (allowed or global_allowed) if e in global_allowed]
    if ext not in SUPPORTED_EXTENSIONS or ext not in permitted:
        raise ValidationError(
            "This file type is not allowed. Please upload one of: "
            + ", ".join(e.upper() for e in permitted) + "."
        )
    limit = max_bytes if max_bytes is not None else max_upload_bytes()
    if len(data) > limit:
        raise ValidationError(
            f"This file is too large ({human_size(len(data))}). The maximum allowed size is {human_size(limit)}."
        )
    if not _check_signature(ext, data):
        raise ValidationError(
            f"This file looks damaged or is not a real {ext.upper()} file. Please check it and upload again."
        )
    return ext, safe_name


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def store_submission_file(assignment_id: int, student_id: int, version_no: int, ext: str, data: bytes) -> str:
    """Save an upload; returns the path relative to the uploads folder (stored in the database)."""
    paths = get_paths()
    rel = f"submissions/a{int(assignment_id)}/s{int(student_id)}/v{int(version_no)}_{uuid.uuid4().hex[:12]}.{ext}"
    write_atomic(safe_join(paths.uploads_dir, rel), data)
    return rel


def store_event_file(kind: str, filename: str, data: bytes, allowed: list[str]) -> tuple[str, str]:
    """Save a poster ('posters') or reference material ('references'); returns (relative path, display name)."""
    if kind not in ("posters", "references"):
        raise ValueError("bad kind")
    ext, safe_name = validate_upload(filename, data, allowed)
    paths = get_paths()
    rel = f"events/{kind}/{uuid.uuid4().hex[:16]}.{ext}"
    write_atomic(safe_join(paths.uploads_dir, rel), data)
    return rel, safe_name


def read_upload(relative_path: str) -> bytes:
    """Read a stored upload safely. Raises a friendly AppError if it is missing."""
    paths = get_paths()
    try:
        full = safe_join(paths.uploads_dir, relative_path)
    except ValueError:
        log.error("Refused unsafe stored path: %r", relative_path)
        raise AppError("This file cannot be opened.") from None
    if not full.is_file():
        log.error("Missing upload file: %s", relative_path)
        raise AppError("The stored file could not be found. Please ask the student to upload it again "
                       "or contact the administrator.")
    return full.read_bytes()


def delete_upload(relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        full = safe_join(get_paths().uploads_dir, relative_path)
        if full.is_file():
            full.unlink()
    except (ValueError, OSError):
        log.warning("Could not delete %s", relative_path)


def mime_for(filename: str) -> str:
    return MIME_TYPES.get(extension_of(filename), "application/octet-stream")


def save_image_asset(folder: Path, prefix: str, filename: str, data: bytes) -> str:
    """Validate and save a logo/signature image (PNG or JPG). Returns the file name."""
    ext, _ = validate_upload(filename, data, ["png", "jpg", "jpeg"], max_bytes=5 * 1024 * 1024)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception:
        raise ValidationError("This image could not be read. Please upload a valid PNG or JPG.") from None
    name = f"{prefix}_{uuid.uuid4().hex[:10]}.{ext}"
    write_atomic(safe_join(folder, name), data)
    return name
