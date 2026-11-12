"""Authentication and server-side permission checks.

Every service function calls `verify_actor()` so permissions are enforced on
the server and never depend on which buttons the screen happens to show.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from database import audit, query_one, transaction
from utils.errors import AppError, PermissionDenied, ValidationError
from utils.helpers import utc_now_str
from utils.security import hash_password, verify_password
from utils.validators import (clean_text, parse_date, validate_password, validate_person_name,
                              validate_roll, validate_username)

log = logging.getLogger("mses.auth")

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
STAFF = ("admin", "teacher")
_DUMMY_HASH = hash_password("not-a-real-password-1")  # keeps timing similar for unknown users


def needs_setup() -> bool:
    return query_one("SELECT 1 AS x FROM users WHERE role='admin' LIMIT 1") is None


def setup_code_required() -> bool:
    return bool(os.environ.get("MSES_SETUP_CODE", "").strip())


def setup_admin(username, password, full_name, school_name, principal_name, academic_year_name,
                setup_code: str = "") -> dict:
    """First-run administrator setup. Works only while no administrator exists."""
    expected = os.environ.get("MSES_SETUP_CODE", "").strip()
    if expected and (setup_code or "").strip() != expected:
        raise PermissionDenied("The setup code is not correct.")
    username = validate_username(username)
    password = validate_password(password)
    full_name = validate_person_name(full_name, "Full name")
    school_name = clean_text(school_name, "School name", 120, required=True)
    principal_name = clean_text(principal_name, "Principal name", 100)
    year_name = clean_text(academic_year_name, "Academic year", 30, required=True)
    now = utc_now_str()
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            raise PermissionDenied("Setup has already been completed. Please log in.")
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, full_name, designation, role, created_at)"
            " VALUES (?,?,?,?, 'admin', ?)",
            (username, hash_password(password), full_name, "Administrator", now),
        )
        admin_id = cur.lastrowid
        year_id = conn.execute(
            "INSERT INTO academic_years(name) VALUES (?)", (year_name,)
        ).lastrowid
        for key, value in (("school_name", school_name), ("principal_name", principal_name),
                           ("default_academic_year", str(year_id))):
            conn.execute(
                "INSERT INTO application_settings(key, value, updated_at, updated_by) VALUES (?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at,"
                " updated_by=excluded.updated_by",
                (key, value, now, admin_id),
            )
        actor = {"role": "admin", "id": admin_id}
        audit(conn, actor, "admin_setup", "user", admin_id, f"username={username}")
    return {"role": "admin", "id": admin_id, "name": full_name, "username": username}


def login_staff(username, password) -> dict:
    """Teacher / administrator login. Locks the account briefly after repeated failures."""
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        raise ValidationError("Please enter both username and password.")
    error: AppError | None = None
    result = None
    now = datetime.now(timezone.utc)
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            error = AppError("Incorrect username or password.")
            audit(conn, None, "login_failed", "user", None, "unknown username")
        else:
            locked = row["locked_until"] and row["locked_until"] > now.strftime("%Y-%m-%d %H:%M:%S")
            if locked:
                error = AppError("Too many incorrect attempts. Please wait a few minutes and try again.")
                audit(conn, {"role": row["role"], "id": row["id"]}, "login_blocked", "user", row["id"])
            elif not verify_password(password, row["password_hash"]):
                attempts = row["failed_attempts"] + 1
                lock_until = None
                if attempts >= MAX_FAILED_ATTEMPTS:
                    lock_until = (now + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                    attempts = 0
                conn.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                             (attempts, lock_until, row["id"]))
                audit(conn, {"role": row["role"], "id": row["id"]}, "login_failed", "user", row["id"])
                error = AppError("Incorrect username or password.")
            elif not row["is_active"]:
                error = AppError("This account has been deactivated. Please contact the administrator.")
                audit(conn, {"role": row["role"], "id": row["id"]}, "login_inactive", "user", row["id"])
            else:
                conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login_at=? WHERE id=?",
                             (utc_now_str(), row["id"]))
                audit(conn, {"role": row["role"], "id": row["id"]}, "login", "user", row["id"])
                result = {"role": row["role"], "id": row["id"], "name": row["full_name"],
                          "username": row["username"]}
    if error:
        raise error
    return result


def login_student(name, class_id, section_id, roll) -> dict:
    """Password-free student login: name + class + section + roll number must all match."""
    name_text = " ".join(str(name or "").split())
    if not name_text:
        raise ValidationError("Please enter your name.")
    if not class_id:
        raise ValidationError("Please select your class.")
    if not section_id:
        raise ValidationError("Please select your section.")
    if not str(roll or "").strip():
        raise ValidationError("Please enter your roll number.")
    try:
        roll_text = validate_roll(roll)
        class_id = int(class_id)
        section_id = int(section_id)
    except (ValueError, TypeError, ValidationError):
        raise AppError(_STUDENT_NOT_FOUND) from None
    row = query_one(
        "SELECT st.id, st.full_name, st.roll_number, c.name AS class_name, sec.name AS section_name"
        " FROM students st JOIN classes c ON c.id = st.class_id JOIN sections sec ON sec.id = st.section_id"
        " WHERE st.is_active=1 AND c.is_active=1 AND sec.is_active=1"
        " AND st.class_id=? AND st.section_id=? AND st.roll_number=? AND lower(st.full_name)=lower(?)",
        (class_id, section_id, roll_text, name_text),
    )
    with transaction() as conn:
        audit(conn, {"role": "student", "id": row["id"] if row else None},
              "student_login" if row else "student_login_failed", "student", row["id"] if row else None)
    if not row:
        raise AppError(_STUDENT_NOT_FOUND)
    return {"role": "student", "id": row["id"], "name": row["full_name"], "username": None}


_STUDENT_NOT_FOUND = ("We could not find a student with these details. Please check your name, class, "
                      "section and roll number, or ask your teacher.")


def verify_actor(actor, roles=None) -> dict:
    """Re-check who the user is against the database on EVERY sensitive call."""
    if not isinstance(actor, dict) or actor.get("role") not in ("admin", "teacher", "student"):
        raise PermissionDenied("Please log in to continue.")
    role = actor["role"]
    if role in STAFF:
        row = query_one("SELECT id, username, full_name, designation, role, is_active FROM users WHERE id=?",
                        (actor.get("id"),))
        if not row or not row["is_active"] or row["role"] != role:
            raise PermissionDenied("Your account is not active. Please log in again.")
        fresh = {"role": row["role"], "id": row["id"], "name": row["full_name"],
                 "username": row["username"], "designation": row["designation"]}
    else:
        row = query_one(
            "SELECT st.id, st.full_name, st.roll_number, st.class_id, st.section_id,"
            " c.name AS class_name, sec.name AS section_name"
            " FROM students st JOIN classes c ON c.id = st.class_id JOIN sections sec ON sec.id = st.section_id"
            " WHERE st.id=? AND st.is_active=1 AND c.is_active=1 AND sec.is_active=1", (actor.get("id"),))
        if not row:
            raise PermissionDenied("Your student record is not active. Please log in again.")
        fresh = {"role": "student", "id": row["id"], "name": row["full_name"], "roll": row["roll_number"],
                 "class_id": row["class_id"], "section_id": row["section_id"],
                 "class_name": row["class_name"], "section_name": row["section_name"]}
    if roles and fresh["role"] not in roles:
        raise PermissionDenied("You do not have permission to do this.")
    return fresh


def require_staff(actor) -> dict:
    return verify_actor(actor, STAFF)


def require_admin(actor) -> dict:
    return verify_actor(actor, ("admin",))


def require_student(actor) -> dict:
    return verify_actor(actor, ("student",))
