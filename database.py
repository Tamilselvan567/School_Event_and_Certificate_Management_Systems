"""SQLite database layer: connection, automatic schema creation and migrations.

Nothing here needs to be run by hand. `init_db()` is called when the app starts.
It creates the folders and the database file if they are missing, applies any
pending migrations, and NEVER deletes or recreates existing data. It is safe to
run as many times as you like.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager

from config import DEFAULT_SETTINGS, get_paths
from utils.errors import DatabaseUnavailable
from utils.helpers import utc_now_str

log = logging.getLogger("mses.db")


def _busy_ms() -> int:
    try:
        return int(os.environ.get("MSES_DB_TIMEOUT_MS", "15000"))
    except ValueError:
        return 15000


def _translate(exc: sqlite3.Error) -> DatabaseUnavailable:
    log.error("Database error: %s", exc)
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return DatabaseUnavailable("The system is busy right now. Please wait a moment and try again.")
    return DatabaseUnavailable("The database is temporarily unavailable. Please try again.")


def connect(path=None) -> sqlite3.Connection:
    """Open a connection with foreign keys, a busy timeout and durable writes."""
    paths = get_paths()
    paths.ensure()
    try:
        conn = sqlite3.connect(str(path or paths.db_path), timeout=_busy_ms() / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {_busy_ms()}")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:  # some network drives do not support WAL; fall back silently
            pass
        conn.execute("PRAGMA synchronous = FULL")
        return conn
    except sqlite3.Error as exc:
        raise _translate(exc) from exc


@contextmanager
def transaction():
    """All-or-nothing write block. Commits on success, rolls back on any error."""
    conn = connect()
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise _translate(exc) from exc
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        conn.close()


def query_all(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        raise _translate(exc) from exc
    finally:
        conn.close()


def query_one(sql: str, params=()) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        raise _translate(exc) from exc
    finally:
        conn.close()


def scalar(sql: str, params=(), default=0):
    row = query_one(sql, params)
    if not row:
        return default
    value = list(row.values())[0]
    return default if value is None else value


def audit(conn, actor, action: str, entity: str | None = None, entity_id=None, details: str | None = None) -> None:
    """Write one line to the audit trail (inside the caller's transaction)."""
    role = actor.get("role") if isinstance(actor, dict) else None
    actor_id = actor.get("id") if isinstance(actor, dict) else None
    conn.execute(
        "INSERT INTO audit_logs(actor_role, actor_id, action, entity, entity_id, details, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (role, actor_id, action, entity, None if entity_id is None else str(entity_id),
         (details or "")[:1000], utc_now_str()),
    )


# ---------------------------------------------------------------------------
# Schema. Each migration is a list of SQL statements. NEVER edit an old
# migration after release - add a new one instead.
# ---------------------------------------------------------------------------
MIGRATION_1 = [
    """CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        designation TEXT,
        role TEXT NOT NULL CHECK (role IN ('admin','teacher')),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        signature_path TEXT,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    )""",
    """CREATE TABLE academic_years (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        start_date TEXT,
        end_date TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
    )""",
    """CREATE TABLE classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        sort_order INTEGER NOT NULL DEFAULT 1000,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
    )""",
    """CREATE TABLE sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
        name TEXT NOT NULL COLLATE NOCASE,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
        UNIQUE (class_id, name)
    )""",
    """CREATE TABLE students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
        section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE RESTRICT,
        roll_number TEXT NOT NULL COLLATE NOCASE,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
        created_at TEXT NOT NULL,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    )""",
    # Only one ACTIVE student may own a class + section + roll number.
    """CREATE UNIQUE INDEX ux_students_identity
        ON students(class_id, section_id, roll_number) WHERE is_active = 1""",
    """CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'General',
        poster_path TEXT,
        event_date TEXT,
        opens_on TEXT NOT NULL,
        deadline TEXT NOT NULL,
        instructions TEXT NOT NULL DEFAULT '',
        academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft','published','closed','archived')),
        created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE event_class_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
        section_id INTEGER REFERENCES sections(id) ON DELETE RESTRICT,
        topic TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        allowed_formats TEXT NOT NULL DEFAULT 'pdf,docx,pptx,jpg,jpeg,png',
        deadline TEXT,
        criteria TEXT NOT NULL DEFAULT '',
        max_marks REAL,
        reference_path TEXT,
        reference_name TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    # One assignment per event + class + section (section NULL = whole class).
    """CREATE UNIQUE INDEX ux_assignment_scope
        ON event_class_assignments(event_id, class_id, IFNULL(section_id, 0))""",
    """CREATE TABLE submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL REFERENCES event_class_assignments(id) ON DELETE RESTRICT,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK (status IN
            ('Submitted','Under Review','Approved','Rejected','Resubmission Required','Resubmitted')),
        current_version INTEGER NOT NULL DEFAULT 1,
        marks REAL,
        cert_type TEXT,
        cert_remark TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (assignment_id, student_id)
    )""",
    """CREATE TABLE submission_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
        version_no INTEGER NOT NULL,
        original_filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        UNIQUE (submission_id, version_no)
    )""",
    """CREATE TABLE reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
        version_id INTEGER REFERENCES submission_versions(id) ON DELETE RESTRICT,
        reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        action TEXT NOT NULL CHECK (action IN
            ('start_review','approve','reject','request_corrections','revert_approval')),
        feedback TEXT NOT NULL DEFAULT '',
        previous_status TEXT NOT NULL,
        new_status TEXT NOT NULL,
        marks REAL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE certificates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        certificate_code TEXT NOT NULL UNIQUE,
        verification_token TEXT NOT NULL UNIQUE,
        submission_id INTEGER NOT NULL UNIQUE REFERENCES submissions(id) ON DELETE RESTRICT,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
        student_name TEXT NOT NULL,
        class_name TEXT NOT NULL,
        section_name TEXT NOT NULL,
        roll_number TEXT NOT NULL,
        event_name TEXT NOT NULL,
        topic TEXT NOT NULL,
        cert_type TEXT NOT NULL,
        remark TEXT NOT NULL DEFAULT '',
        school_name TEXT NOT NULL,
        principal_name TEXT NOT NULL DEFAULT '',
        teacher_name TEXT NOT NULL DEFAULT '',
        teacher_designation TEXT NOT NULL DEFAULT '',
        teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        issued_on TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','revoked')),
        revoked_reason TEXT,
        revoked_at TEXT,
        file_path TEXT NOT NULL,
        file_sha256 TEXT,
        regenerated_count INTEGER NOT NULL DEFAULT 0,
        generated_by_role TEXT,
        generated_by_id INTEGER,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE certificate_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL,
        query_text TEXT,
        result TEXT NOT NULL,
        verified_at TEXT NOT NULL
    )""",
    """CREATE TABLE application_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_role TEXT,
        actor_id INTEGER,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX ix_sections_class ON sections(class_id)",
    "CREATE INDEX ix_students_class ON students(class_id, section_id)",
    "CREATE INDEX ix_events_status ON events(status)",
    "CREATE INDEX ix_events_creator ON events(created_by)",
    "CREATE INDEX ix_assign_event ON event_class_assignments(event_id)",
    "CREATE INDEX ix_assign_class ON event_class_assignments(class_id, section_id)",
    "CREATE INDEX ix_sub_status ON submissions(status)",
    "CREATE INDEX ix_sub_student ON submissions(student_id)",
    "CREATE INDEX ix_ver_sub ON submission_versions(submission_id)",
    "CREATE INDEX ix_rev_sub ON reviews(submission_id)",
    "CREATE INDEX ix_cert_student ON certificates(student_id)",
    "CREATE INDEX ix_cert_event ON certificates(event_id)",
    "CREATE INDEX ix_audit_created ON audit_logs(created_at)",
]

# Version 2: remember who reviewed last, speed up the review queue.
MIGRATION_2 = [
    "ALTER TABLE submissions ADD COLUMN last_reviewed_by INTEGER REFERENCES users(id)",
    "ALTER TABLE submissions ADD COLUMN last_reviewed_at TEXT",
    "CREATE INDEX ix_sub_assignment ON submissions(assignment_id, status)",
    "CREATE INDEX ix_verif_cert ON certificate_verifications(certificate_id)",
]

MIGRATIONS = [
    (1, "initial_schema", MIGRATION_1),
    (2, "review_tracking_and_indexes", MIGRATION_2),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def current_version(conn=None) -> int:
    own = conn is None
    conn = conn or connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='database_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute("SELECT MAX(version) FROM database_migrations").fetchone()
        return int(row[0] or 0)
    finally:
        if own:
            conn.close()


def init_db(target_version: int | None = None) -> int:
    """Create / upgrade the database. Idempotent. Returns the schema version."""
    paths = get_paths()
    paths.ensure()
    existed = paths.db_path.exists() and paths.db_path.stat().st_size > 0
    conn = connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS database_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {r[0] for r in conn.execute("SELECT version FROM database_migrations")}
        pending = [m for m in MIGRATIONS if m[0] not in applied and (target_version is None or m[0] <= target_version)]
        if pending and existed and applied:
            try:  # safety copy before touching an existing database
                from services import backup_service
                backup_service.create_backup(reason="pre-migration", include_files=False)
            except Exception:  # never block start-up because a safety copy failed
                log.exception("Pre-migration backup failed")
        for version, name, statements in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO database_migrations(version, name, applied_at) VALUES (?,?,?)",
                    (version, name, utc_now_str()),
                )
                conn.execute("COMMIT")
                log.info("Applied migration %s (%s)", version, name)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        if target_version is None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = utc_now_str()
                for key, value in DEFAULT_SETTINGS.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO application_settings(key, value, updated_at) VALUES (?,?,?)",
                        (key, value, now),
                    )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return current_version(conn)
    except sqlite3.Error as exc:
        raise _translate(exc) from exc
    finally:
        conn.close()


def integrity_check() -> list[str]:
    """Return a list of problems (empty list = database is healthy)."""
    conn = connect()
    try:
        problems = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall() if r[0] != "ok"]
        problems += [f"foreign key problem in {r[0]}" for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
        return problems
    finally:
        conn.close()
