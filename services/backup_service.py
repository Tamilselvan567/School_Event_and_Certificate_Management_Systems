"""Database + file backups and restore (no SQL knowledge needed).

A backup is one ZIP file containing the database and (optionally) the uploads,
certificates and school assets. Backups live in the `backups/` folder.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import APP_VERSION, get_paths
from utils.errors import AppError, ValidationError
from utils.security import safe_join

log = logging.getLogger("mses.backup")

DB_NAME_IN_ZIP = "database/school_events.db"
FILE_FOLDERS = ("uploads", "certificates", "assets")
_last_auto_check = 0.0


def _folder_map():
    p = get_paths()
    return {"uploads": p.uploads_dir, "certificates": p.certificates_dir, "assets": p.assets_dir}


def _snapshot_db(dest: Path) -> None:
    """Consistent copy of the live database using SQLite's own backup feature."""
    from database import connect
    src = connect()
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def create_backup(reason: str = "manual", include_files: bool = True) -> Path:
    """Create a backup ZIP and return its path. Raises AppError if it fails."""
    paths = get_paths()
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:20] or "manual"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp_zip = None
    try:
        paths.ensure()
        paths.backups_dir.mkdir(parents=True, exist_ok=True)   # raises here if the folder is unusable
        target = paths.backups_dir / f"backup_{safe_reason}_{stamp}.zip"
        n = 1
        while target.exists():
            n += 1
            target = paths.backups_dir / f"backup_{safe_reason}_{stamp}_{n}.zip"
        tmp_zip = target.with_suffix(".zip.part")
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snapshot.db"
            _snapshot_db(snap)
            manifest = {"app": "motilal-school-event-system", "version": APP_VERSION, "reason": safe_reason,
                        "created_utc": datetime.now(timezone.utc).isoformat(), "includes_files": include_files}
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                zf.write(snap, DB_NAME_IN_ZIP)
                if include_files:
                    for label, folder in _folder_map().items():
                        if not folder.is_dir():
                            continue
                        for f in folder.rglob("*"):
                            if f.is_file() and not f.name.endswith(".tmp"):
                                zf.write(f, f"{label}/{f.relative_to(folder).as_posix()}")
        tmp_zip.replace(target)
        log.info("Backup created: %s", target.name)
        return target
    except AppError:
        raise
    except Exception as exc:
        log.exception("Backup failed")
        if tmp_zip is not None and tmp_zip.exists():
            tmp_zip.unlink()
        raise AppError("The backup could not be created. Please check that the disk has free space.") from exc


def list_backups() -> list[dict]:
    paths = get_paths()
    items = []
    for f in sorted(paths.backups_dir.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append({"name": f.name, "size": f.stat().st_size,
                      "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                      "path": f})
    return items


def read_backup(name: str) -> bytes:
    try:
        path = safe_join(get_paths().backups_dir, name)
    except ValueError:
        raise AppError("Backup not found.") from None
    if not path.is_file() or not path.name.startswith("backup_"):
        raise AppError("Backup not found.")
    return path.read_bytes()


def prune_backups(keep: int) -> int:
    """Delete the oldest AUTOMATIC backups beyond `keep`. Manual backups are never removed."""
    autos = [b for b in list_backups() if b["name"].startswith("backup_auto_")]
    removed = 0
    for old in autos[max(keep, 1):]:
        try:
            old["path"].unlink()
            removed += 1
        except OSError:
            pass
    return removed


def auto_backup_if_due(force: bool = False) -> Path | None:
    """Create an automatic backup when the last one is older than the configured interval."""
    global _last_auto_check
    now = time.time()
    if not force and now - _last_auto_check < 600:
        return None
    _last_auto_check = now
    from services.settings_store import get_setting
    try:
        if get_setting("backup_enabled") != "1":
            return None
        hours = max(float(get_setting("backup_interval_hours") or 24), 0.1)
        keep = int(float(get_setting("backup_keep_count") or 14))
        autos = [b for b in list_backups() if b["name"].startswith("backup_auto_")]
        if autos and now - autos[0]["path"].stat().st_mtime < hours * 3600:
            return None
        path = create_backup("auto", include_files=get_setting("backup_include_files") == "1")
        prune_backups(keep)
        return path
    except Exception:
        log.exception("Automatic backup failed")
        return None


def _validate_db_file(path: Path) -> int:
    """Check a database file is healthy and belongs to this app. Returns its schema version."""
    from database import LATEST_VERSION
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        raise ValidationError("This is not a valid database backup.") from None
    try:
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if result != "ok" or not {"users", "events", "submissions", "database_migrations"} <= tables:
                raise ValidationError("This backup is damaged or does not belong to this application.")
            version = conn.execute("SELECT MAX(version) FROM database_migrations").fetchone()[0] or 0
        except sqlite3.Error:
            raise ValidationError("This backup is damaged or does not belong to this application.") from None
        if version > LATEST_VERSION:
            raise ValidationError("This backup was made by a newer version of the application. "
                                  "Please update the application first.")
        return version
    finally:
        conn.close()


def restore_backup(data: bytes) -> dict:
    """Restore from a backup ZIP (or a bare .db file). The live data is only replaced
    after the backup has been fully checked, and a safety copy of the current data is made first."""
    if not data:
        raise ValidationError("The backup file is empty.")
    from database import connect, init_db
    paths = get_paths()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        extract_dir = tmp_path / "x"
        extract_dir.mkdir()
        db_file = tmp_path / "restore.db"
        file_entries: list[tuple[zipfile.ZipInfo, str]] = []
        if zipfile.is_zipfile(io.BytesIO(data)):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
                if zf.testzip() is not None:
                    raise ValidationError("The backup file is damaged.")
                names = zf.namelist()
                if DB_NAME_IN_ZIP not in names:
                    raise ValidationError("This ZIP is not a backup made by this application.")
                db_file.write_bytes(zf.read(DB_NAME_IN_ZIP))
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    top, _, rest = info.filename.partition("/")
                    if top in FILE_FOLDERS and rest:
                        file_entries.append((info, info.filename))
            except zipfile.BadZipFile:
                raise ValidationError("The backup file is damaged.") from None
        elif data[:16] == b"SQLite format 3\x00":
            zf = None
            db_file.write_bytes(data)
        else:
            raise ValidationError("This is not a backup file. Please choose a backup ZIP created by this application.")

        _validate_db_file(db_file)
        # Safety copy of what is there right now (database only, quick).
        try:
            safety = create_backup("pre-restore", include_files=False)
        except AppError:
            raise AppError("Restore stopped: a safety copy of the current data could not be made.") from None

        src = sqlite3.connect(str(db_file))
        dest = connect()
        try:
            src.backup(dest)  # replaces live database content in one step
        except sqlite3.Error as exc:
            log.exception("Restore failed")
            raise AppError("The restore failed and your current data was kept. "
                           f"A safety copy is in the backups folder ({safety.name}).") from exc
        finally:
            src.close()
            dest.close()

        restored_files = 0
        if zf is not None:
            folders = _folder_map()
            for info, name in file_entries:
                top, _, rest = name.partition("/")
                try:
                    target = safe_join(folders[top], rest)
                except ValueError:
                    log.warning("Skipped unsafe path in backup: %s", name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src_f, open(target, "wb") as out_f:
                    shutil.copyfileobj(src_f, out_f)
                restored_files += 1
    init_db()  # bring an older backup up to the current schema
    log.info("Restore completed (%s files)", restored_files)
    return {"files_restored": restored_files, "safety_backup": safety.name}


def check_consistency() -> dict:
    """Compare the database with the files on disk (helps spot lost files)."""
    from database import query_all
    paths = get_paths()
    missing_uploads, missing_certs = [], []
    for r in query_all("SELECT id, submission_id, version_no, stored_path FROM submission_versions"):
        try:
            if not safe_join(paths.uploads_dir, r["stored_path"]).is_file():
                missing_uploads.append(r)
        except ValueError:
            missing_uploads.append(r)
    for r in query_all("SELECT id, certificate_code, file_path FROM certificates"):
        try:
            if not safe_join(paths.certificates_dir, r["file_path"]).is_file():
                missing_certs.append(r)
        except ValueError:
            missing_certs.append(r)
    known = {r["stored_path"] for r in query_all("SELECT stored_path FROM submission_versions")}
    orphans = 0
    if paths.submissions_dir.is_dir():
        for f in paths.submissions_dir.rglob("*"):
            if f.is_file() and f.relative_to(paths.uploads_dir).as_posix() not in known:
                orphans += 1
    return {"missing_uploads": missing_uploads, "missing_certificates": missing_certs, "orphan_files": orphans}


# --------------------------------------------------------------------------
# Administrator-checked entry points (these are what the screens use, so a
# non-administrator can never reach backup / restore even by calling them directly).
# --------------------------------------------------------------------------
def admin_create_backup(actor, include_files: bool = True) -> Path:
    from auth import require_admin
    require_admin(actor)
    return create_backup("manual", include_files)


def admin_list_backups(actor) -> list[dict]:
    from auth import require_admin
    require_admin(actor)
    return list_backups()


def admin_read_backup(actor, name: str) -> bytes:
    from auth import require_admin
    require_admin(actor)
    return read_backup(name)


def admin_restore(actor, data: bytes) -> dict:
    from auth import require_admin
    from database import audit, transaction
    admin = require_admin(actor)
    result = restore_backup(data)
    try:  # the restored database may not know this admin; logging is best-effort
        with transaction() as conn:
            audit(conn, admin, "backup_restored", "backup", None, result["safety_backup"])
    except Exception:
        log.warning("Could not write the restore audit entry")
    return result


def admin_check_consistency(actor) -> dict:
    from auth import require_admin
    require_admin(actor)
    return check_consistency()
