"""Users (teachers), classes, sections, academic years, students and settings."""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3

from auth import require_admin, require_staff, verify_actor
from config import DEFAULT_SETTINGS, HARD_MAX_UPLOAD_MB, SUPPORTED_EXTENSIONS, get_paths
from database import audit, query_all, query_one, transaction
from services import file_service
from utils.errors import AppError, NotFound, PermissionDenied, ValidationError
from utils.helpers import utc_now_str
from utils.security import hash_password, safe_join, verify_password
from utils.validators import (clean_text, parse_date, validate_color, validate_password,
                              validate_person_name, validate_roll, validate_username)

log = logging.getLogger("mses.admin")


# ------------------------------------------------------------------ teachers
def list_users(actor) -> list[dict]:
    require_admin(actor)
    return query_all(
        "SELECT id, username, full_name, designation, role, is_active, created_at, last_login_at,"
        " (signature_path IS NOT NULL AND signature_path != '') AS has_signature"
        " FROM users ORDER BY role, full_name COLLATE NOCASE")


def list_teachers_simple(actor) -> list[dict]:
    require_staff(actor)
    return query_all("SELECT id, full_name FROM users WHERE is_active=1 ORDER BY full_name COLLATE NOCASE")


def create_user(actor, username, password, full_name, designation="", role="teacher") -> int:
    admin = require_admin(actor)
    if role not in ("teacher", "admin"):
        raise ValidationError("Role must be teacher or admin.")
    username = validate_username(username)
    password = validate_password(password)
    full_name = validate_person_name(full_name, "Full name")
    designation = clean_text(designation, "Designation", 80)
    try:
        with transaction() as conn:
            uid = conn.execute(
                "INSERT INTO users(username, password_hash, full_name, designation, role, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (username, hash_password(password), full_name, designation, role, utc_now_str())).lastrowid
            audit(conn, admin, "user_created", "user", uid, f"{role}:{username}")
    except sqlite3.IntegrityError:
        raise ValidationError("This username is already taken. Please choose another.") from None
    return uid


def update_user(actor, user_id, full_name, designation="") -> None:
    admin = require_admin(actor)
    full_name = validate_person_name(full_name, "Full name")
    designation = clean_text(designation, "Designation", 80)
    with transaction() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise NotFound("User not found.")
        conn.execute("UPDATE users SET full_name=?, designation=? WHERE id=?", (full_name, designation, user_id))
        audit(conn, admin, "user_updated", "user", user_id)


def set_user_active(actor, user_id, active: bool) -> None:
    admin = require_admin(actor)
    with transaction() as conn:
        row = conn.execute("SELECT id, role, is_active FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise NotFound("User not found.")
        if not active:
            if row["id"] == admin["id"]:
                raise ValidationError("You cannot deactivate your own account.")
            if row["role"] == "admin":
                others = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1 AND id != ?", (user_id,)).fetchone()[0]
                if others == 0:
                    raise ValidationError("At least one active administrator is required.")
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
        audit(conn, admin, "user_activated" if active else "user_deactivated", "user", user_id)


def reset_password(actor, user_id, new_password) -> None:
    admin = require_admin(actor)
    new_password = validate_password(new_password)
    with transaction() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise NotFound("User not found.")
        conn.execute("UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL WHERE id=?",
                     (hash_password(new_password), user_id))
        audit(conn, admin, "password_reset", "user", user_id)


def change_own_password(actor, old_password, new_password) -> None:
    me = require_staff(actor)
    new_password = validate_password(new_password)
    with transaction() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (me["id"],)).fetchone()
        if not row or not verify_password(str(old_password or ""), row["password_hash"]):
            raise ValidationError("Your current password is not correct.")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), me["id"]))
        audit(conn, me, "password_changed", "user", me["id"])


def reassign_events(actor, from_user_id, to_user_id) -> int:
    admin = require_admin(actor)
    with transaction() as conn:
        for uid in (from_user_id, to_user_id):
            if not conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                raise NotFound("User not found.")
        if not conn.execute("SELECT 1 FROM users WHERE id=? AND is_active=1", (to_user_id,)).fetchone():
            raise ValidationError("The new owner must be an active account.")
        cur = conn.execute("UPDATE events SET created_by=?, updated_at=? WHERE created_by=?",
                           (to_user_id, utc_now_str(), from_user_id))
        audit(conn, admin, "events_reassigned", "user", from_user_id, f"to={to_user_id} count={cur.rowcount}")
        return cur.rowcount


def save_my_signature(actor, filename, data) -> None:
    me = require_staff(actor)
    name = file_service.save_image_asset(get_paths().signatures_dir, f"teacher{me['id']}", filename, data)
    with transaction() as conn:
        conn.execute("UPDATE users SET signature_path=? WHERE id=?", (name, me["id"]))
        audit(conn, me, "signature_uploaded", "user", me["id"])


def remove_my_signature(actor) -> None:
    me = require_staff(actor)
    with transaction() as conn:
        conn.execute("UPDATE users SET signature_path=NULL WHERE id=?", (me["id"],))
        audit(conn, me, "signature_removed", "user", me["id"])


# ------------------------------------------------------------- academic years
def list_years(include_inactive=True) -> list[dict]:
    sql = "SELECT * FROM academic_years"
    if not include_inactive:
        sql += " WHERE is_active=1"
    return query_all(sql + " ORDER BY name DESC")


def default_year_id() -> int | None:
    from services.settings_store import get_setting
    raw = get_setting("default_academic_year")
    if raw and raw.isdigit() and query_one("SELECT 1 AS x FROM academic_years WHERE id=?", (int(raw),)):
        return int(raw)
    row = query_one("SELECT id FROM academic_years WHERE is_active=1 ORDER BY name DESC LIMIT 1")
    return row["id"] if row else None


def _year_dates(start, end):
    s = parse_date(start, "Start date") if start else None
    e = parse_date(end, "End date") if end else None
    if s and e and e < s:
        raise ValidationError("The end date cannot be before the start date.")
    return s, e


def create_year(actor, name, start=None, end=None) -> int:
    me = require_staff(actor)
    name = clean_text(name, "Academic year", 30, required=True)
    s, e = _year_dates(start, end)
    try:
        with transaction() as conn:
            yid = conn.execute("INSERT INTO academic_years(name, start_date, end_date) VALUES (?,?,?)",
                               (name, s, e)).lastrowid
            audit(conn, me, "year_created", "academic_year", yid, name)
    except sqlite3.IntegrityError:
        raise ValidationError("This academic year already exists.") from None
    return yid


def update_year(actor, year_id, name, start=None, end=None, is_active=True) -> None:
    me = require_staff(actor)
    name = clean_text(name, "Academic year", 30, required=True)
    s, e = _year_dates(start, end)
    try:
        with transaction() as conn:
            cur = conn.execute("UPDATE academic_years SET name=?, start_date=?, end_date=?, is_active=? WHERE id=?",
                               (name, s, e, 1 if is_active else 0, year_id))
            if cur.rowcount == 0:
                raise NotFound("Academic year not found.")
            audit(conn, me, "year_updated", "academic_year", year_id)
    except sqlite3.IntegrityError:
        raise ValidationError("This academic year already exists.") from None


# --------------------------------------------------------- classes & sections
def _auto_sort(name: str) -> int:
    m = re.search(r"\d+", name)
    return int(m.group()) if m else 1000


def list_classes(include_inactive=True) -> list[dict]:
    sql = "SELECT * FROM classes"
    if not include_inactive:
        sql += " WHERE is_active=1"
    return query_all(sql + " ORDER BY sort_order, name COLLATE NOCASE")


def create_class(actor, name, sort_order=None) -> int:
    me = require_staff(actor)
    name = clean_text(name, "Class name", 40, required=True)
    order = int(sort_order) if sort_order not in (None, "") else _auto_sort(name)
    try:
        with transaction() as conn:
            cid = conn.execute("INSERT INTO classes(name, sort_order) VALUES (?,?)", (name, order)).lastrowid
            audit(conn, me, "class_created", "class", cid, name)
    except sqlite3.IntegrityError:
        raise ValidationError("This class already exists.") from None
    return cid


def update_class(actor, class_id, name, sort_order, is_active=True) -> None:
    me = require_staff(actor)
    name = clean_text(name, "Class name", 40, required=True)
    try:
        with transaction() as conn:
            cur = conn.execute("UPDATE classes SET name=?, sort_order=?, is_active=? WHERE id=?",
                               (name, int(sort_order), 1 if is_active else 0, class_id))
            if cur.rowcount == 0:
                raise NotFound("Class not found.")
            audit(conn, me, "class_updated", "class", class_id, f"active={is_active}")
    except sqlite3.IntegrityError:
        raise ValidationError("Another class already has this name.") from None


def list_sections(class_id=None, include_inactive=True) -> list[dict]:
    sql = ("SELECT s.*, c.name AS class_name FROM sections s JOIN classes c ON c.id = s.class_id WHERE 1=1")
    params = []
    if class_id:
        sql += " AND s.class_id=?"
        params.append(class_id)
    if not include_inactive:
        sql += " AND s.is_active=1 AND c.is_active=1"
    return query_all(sql + " ORDER BY c.sort_order, c.name COLLATE NOCASE, s.name COLLATE NOCASE", params)


def create_section(actor, class_id, name) -> int:
    me = require_staff(actor)
    name = clean_text(name, "Section name", 20, required=True)
    try:
        with transaction() as conn:
            if not conn.execute("SELECT 1 FROM classes WHERE id=?", (class_id,)).fetchone():
                raise NotFound("Class not found.")
            sid = conn.execute("INSERT INTO sections(class_id, name) VALUES (?,?)", (class_id, name)).lastrowid
            audit(conn, me, "section_created", "section", sid, name)
    except sqlite3.IntegrityError:
        raise ValidationError("This section already exists in that class.") from None
    return sid


def update_section(actor, section_id, name, is_active=True) -> None:
    me = require_staff(actor)
    name = clean_text(name, "Section name", 20, required=True)
    try:
        with transaction() as conn:
            cur = conn.execute("UPDATE sections SET name=?, is_active=? WHERE id=?",
                               (name, 1 if is_active else 0, section_id))
            if cur.rowcount == 0:
                raise NotFound("Section not found.")
            audit(conn, me, "section_updated", "section", section_id, f"active={is_active}")
    except sqlite3.IntegrityError:
        raise ValidationError("Another section in that class already has this name.") from None


# -------------------------------------------------------------------- students
def list_students(actor, class_id=None, section_id=None, search="", include_inactive=False) -> list[dict]:
    require_staff(actor)
    sql = ("SELECT st.id, st.full_name, st.roll_number, st.is_active, st.class_id, st.section_id,"
           " c.name AS class_name, sec.name AS section_name FROM students st"
           " JOIN classes c ON c.id=st.class_id JOIN sections sec ON sec.id=st.section_id WHERE 1=1")
    params: list = []
    if class_id:
        sql += " AND st.class_id=?"
        params.append(class_id)
    if section_id:
        sql += " AND st.section_id=?"
        params.append(section_id)
    if search:
        sql += " AND (st.full_name LIKE ? ESCAPE '\\' OR st.roll_number LIKE ? ESCAPE '\\')"
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like]
    if not include_inactive:
        sql += " AND st.is_active=1"
    return query_all(sql + " ORDER BY c.sort_order, c.name, sec.name, CAST(st.roll_number AS INTEGER), st.roll_number",
                     params)


def add_student(actor, full_name, class_id, section_id, roll) -> int:
    me = require_staff(actor)
    full_name = validate_person_name(full_name, "Student name")
    roll = validate_roll(roll)
    try:
        with transaction() as conn:
            sec = conn.execute("SELECT class_id, is_active FROM sections WHERE id=?", (section_id,)).fetchone()
            if not sec or sec["class_id"] != int(class_id):
                raise ValidationError("The selected section does not belong to the selected class.")
            if not sec["is_active"]:
                raise ValidationError("The selected section is not active.")
            sid = conn.execute(
                "INSERT INTO students(full_name, class_id, section_id, roll_number, created_at, created_by)"
                " VALUES (?,?,?,?,?,?)", (full_name, class_id, section_id, roll, utc_now_str(), me["id"])).lastrowid
            audit(conn, me, "student_created", "student", sid)
    except sqlite3.IntegrityError:
        raise ValidationError("A student with this class, section and roll number already exists.") from None
    return sid


def update_student(actor, student_id, full_name, class_id, section_id, roll, is_active=True) -> None:
    me = require_staff(actor)
    full_name = validate_person_name(full_name, "Student name")
    roll = validate_roll(roll)
    try:
        with transaction() as conn:
            sec = conn.execute("SELECT class_id FROM sections WHERE id=?", (section_id,)).fetchone()
            if not sec or sec["class_id"] != int(class_id):
                raise ValidationError("The selected section does not belong to the selected class.")
            cur = conn.execute(
                "UPDATE students SET full_name=?, class_id=?, section_id=?, roll_number=?, is_active=? WHERE id=?",
                (full_name, class_id, section_id, roll, 1 if is_active else 0, student_id))
            if cur.rowcount == 0:
                raise NotFound("Student not found.")
            audit(conn, me, "student_updated", "student", student_id)
    except sqlite3.IntegrityError:
        raise ValidationError("Another active student already has this class, section and roll number.") from None


def import_students_csv(actor, text: str, create_missing: bool = False) -> dict:
    """CSV columns: name,class,section,roll. Valid rows are added; problems are reported per row."""
    me = require_staff(actor)
    if len(text) > 2_000_000:
        raise ValidationError("The CSV file is too large.")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValidationError("The CSV file is empty.")
    cols = {c.strip().lower(): c for c in reader.fieldnames if c}
    if not {"name", "class", "section", "roll"} <= set(cols):
        raise ValidationError("The CSV must have the columns: name, class, section, roll.")
    rows = list(reader)
    if len(rows) > 5000:
        raise ValidationError("Please import at most 5000 students at a time.")
    added, errors = 0, []
    with transaction() as conn:
        for i, raw in enumerate(rows, start=2):
            try:
                name = validate_person_name(raw[cols["name"]], "Name")
                roll = validate_roll(raw[cols["roll"]])
                cname = clean_text(raw[cols["class"]], "Class", 40, required=True)
                sname = clean_text(raw[cols["section"]], "Section", 20, required=True)
                c = conn.execute("SELECT id, is_active FROM classes WHERE name=?", (cname,)).fetchone()
                if not c:
                    if not create_missing:
                        raise ValidationError(f"class '{cname}' does not exist")
                    c = {"id": conn.execute("INSERT INTO classes(name, sort_order) VALUES (?,?)",
                                            (cname, _auto_sort(cname))).lastrowid, "is_active": 1}
                s = conn.execute("SELECT id, is_active FROM sections WHERE class_id=? AND name=?",
                                 (c["id"], sname)).fetchone()
                if not s:
                    if not create_missing:
                        raise ValidationError(f"section '{sname}' does not exist in class '{cname}'")
                    s = {"id": conn.execute("INSERT INTO sections(class_id, name) VALUES (?,?)",
                                            (c["id"], sname)).lastrowid, "is_active": 1}
                if not c["is_active"] or not s["is_active"]:
                    raise ValidationError("class or section is not active")
                conn.execute(
                    "INSERT INTO students(full_name, class_id, section_id, roll_number, created_at, created_by)"
                    " VALUES (?,?,?,?,?,?)", (name, c["id"], s["id"], roll, utc_now_str(), me["id"]))
                added += 1
            except ValidationError as exc:
                errors.append(f"Row {i}: {exc}")
            except sqlite3.IntegrityError:
                errors.append(f"Row {i}: this class/section/roll number already exists")
        audit(conn, me, "students_imported", "student", None, f"added={added} errors={len(errors)}")
    return {"added": added, "errors": errors}


# -------------------------------------------------------------------- settings
def update_settings(actor, values: dict) -> None:
    admin = require_admin(actor)
    clean: dict[str, str] = {}
    for key, raw in values.items():
        if key not in DEFAULT_SETTINGS or key in ("school_logo", "principal_signature"):
            raise ValidationError(f"Unknown setting: {key}")
        v = str(raw if raw is not None else "").strip()
        if key == "school_name":
            v = clean_text(v, "School name", 120, required=True)
        elif key in ("principal_name", "school_phone", "school_email", "cert_footer_text"):
            v = clean_text(v, key.replace("_", " ").title(), 150)
        elif key == "school_address":
            v = clean_text(v, "School address", 300)
        elif key == "max_upload_mb":
            try:
                mb = float(v)
            except ValueError:
                raise ValidationError("Upload size limit must be a number.") from None
            if not 0.1 <= mb <= HARD_MAX_UPLOAD_MB:
                raise ValidationError(f"Upload size limit must be between 0.1 and {HARD_MAX_UPLOAD_MB} MB.")
            v = str(mb).rstrip("0").rstrip(".") if "." in str(mb) else str(int(mb))
        elif key == "allowed_extensions":
            exts = [e.strip().lower().lstrip(".") for e in v.split(",") if e.strip()]
            if not exts or any(e not in SUPPORTED_EXTENSIONS for e in exts):
                raise ValidationError("Allowed file types must be chosen from: " + ", ".join(SUPPORTED_EXTENSIONS))
            v = ",".join(dict.fromkeys(exts))
        elif key in ("cert_primary_color", "cert_secondary_color", "cert_accent_color"):
            v = validate_color(v, "Colour")
        elif key == "cert_default_type":
            if v not in ("Participation", "Achievement"):
                raise ValidationError("Certificate type must be Participation or Achievement.")
        elif key in ("backup_enabled", "backup_include_files"):
            v = "1" if v in ("1", "true", "True") else "0"
        elif key in ("backup_interval_hours", "backup_keep_count", "session_timeout_minutes"):
            try:
                num = float(v)
            except ValueError:
                raise ValidationError(f"{key.replace('_', ' ').title()} must be a number.") from None
            low, high = {"backup_interval_hours": (0.1, 720), "backup_keep_count": (1, 365),
                         "session_timeout_minutes": (5, 1440)}[key]
            if not low <= num <= high:
                raise ValidationError(f"{key.replace('_', ' ').title()} must be between {low} and {high}.")
            v = str(int(num)) if num == int(num) else str(num)
        elif key == "default_academic_year":
            if not v.isdigit() or not query_one("SELECT 1 AS x FROM academic_years WHERE id=?", (int(v),)):
                raise ValidationError("Please choose an existing academic year.")
        elif key == "public_base_url":
            if v and not re.match(r"^https?://[^\s]+$", v):
                raise ValidationError("The public website address must start with http:// or https://")
            v = v.rstrip("/")
        elif key == "event_categories":
            cats = [clean_text(c, "Category", 40) for c in v.split(",") if c.strip()]
            if not cats:
                raise ValidationError("Please enter at least one event category.")
            v = ",".join(dict.fromkeys(cats))
        clean[key] = v
    now = utc_now_str()
    with transaction() as conn:
        for key, v in clean.items():
            conn.execute(
                "INSERT INTO application_settings(key, value, updated_at, updated_by) VALUES (?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at,"
                " updated_by=excluded.updated_by", (key, v, now, admin["id"]))
        audit(conn, admin, "settings_updated", "settings", None, ",".join(sorted(clean)))


def _save_asset_setting(actor, key, folder, prefix, filename, data) -> None:
    admin = require_admin(actor)
    name = file_service.save_image_asset(folder, prefix, filename, data)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO application_settings(key, value, updated_at, updated_by) VALUES (?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at,"
            " updated_by=excluded.updated_by", (key, name, utc_now_str(), admin["id"]))
        audit(conn, admin, f"{key}_uploaded", "settings", None)


def save_school_logo(actor, filename, data) -> None:
    _save_asset_setting(actor, "school_logo", get_paths().logo_dir, "logo", filename, data)


def save_principal_signature(actor, filename, data) -> None:
    _save_asset_setting(actor, "principal_signature", get_paths().signatures_dir, "principal", filename, data)


def clear_asset_setting(actor, key) -> None:
    admin = require_admin(actor)
    if key not in ("school_logo", "principal_signature"):
        raise ValidationError("Unknown setting.")
    with transaction() as conn:
        conn.execute("UPDATE application_settings SET value='', updated_at=?, updated_by=? WHERE key=?",
                     (utc_now_str(), admin["id"], key))
        audit(conn, admin, f"{key}_removed", "settings", None)


def read_asset(folder_attr: str, name: str) -> bytes | None:
    """Read a logo/signature image; returns None if missing."""
    if not name:
        return None
    try:
        path = safe_join(getattr(get_paths(), folder_attr), name)
        return path.read_bytes() if path.is_file() else None
    except (ValueError, OSError):
        return None


def recent_audit(actor, limit=200) -> list[dict]:
    require_admin(actor)
    return query_all(
        "SELECT a.created_at, a.actor_role, COALESCE(u.username, '') AS username, a.action, a.entity,"
        " a.entity_id, a.details FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_id AND a.actor_role != 'student'"
        " ORDER BY a.id DESC LIMIT ?", (int(limit),))
