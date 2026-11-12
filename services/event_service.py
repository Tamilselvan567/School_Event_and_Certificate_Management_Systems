"""Events and class-specific assignments (different topics for different classes)."""
from __future__ import annotations

import logging
import sqlite3

from auth import require_staff, require_student
from config import SUPPORTED_EXTENSIONS
from database import audit, query_all, query_one, scalar, transaction
from services import file_service
from services.settings_store import event_categories
from utils.errors import NotFound, PermissionDenied, ValidationError
from utils.helpers import (PENDING_STATUSES, APPROVED, REJECTED, RESUBMISSION_REQUIRED, STUDENT_CAN_UPLOAD,
                           local_now_str, local_today_str, utc_now_str)
from utils.validators import clean_text, parse_date, parse_datetime, parse_positive_float

log = logging.getLogger("mses.events")

TRANSITIONS = {  # action -> (allowed current statuses, new status)
    "publish": (("draft",), "published"),
    "unpublish": (("published",), "draft"),
    "close": (("published",), "closed"),
    "reopen": (("closed",), "published"),
    "archive": (("draft", "published", "closed"), "archived"),
    "unarchive": (("archived",), "closed"),
}


def _event_row(conn, event_id):
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not row:
        raise NotFound("Event not found.")
    return row


def _can_manage(staff: dict, event_row) -> None:
    if staff["role"] != "admin" and event_row["created_by"] != staff["id"]:
        raise PermissionDenied("You can only manage events that you created.")


def _clean_event(data: dict, existing=None) -> dict:
    name = clean_text(data.get("name"), "Event name", 150, required=True)
    description = clean_text(data.get("description"), "Description", 5000)
    category = clean_text(data.get("category"), "Category", 40) or "General"
    cats = event_categories()
    if category not in cats:
        raise ValidationError("Please choose one of the available categories.")
    instructions = clean_text(data.get("instructions"), "Instructions", 8000)
    event_date = parse_date(data["event_date"], "Event date") if data.get("event_date") else None
    opens_on = parse_date(data.get("opens_on"), "Opening date")
    deadline = parse_datetime(data.get("deadline"), "Submission deadline")
    if deadline[:10] < opens_on:
        raise ValidationError("The submission deadline cannot be before the opening date.")
    if (existing is None or existing["deadline"] != deadline) and deadline <= local_now_str():
        raise ValidationError("The submission deadline must be in the future.")
    year_id = data.get("academic_year_id")
    if not year_id or not query_one("SELECT 1 AS x FROM academic_years WHERE id=?", (year_id,)):
        raise ValidationError("Please choose an academic year.")
    return dict(name=name, description=description, category=category, instructions=instructions,
                event_date=event_date, opens_on=opens_on, deadline=deadline, academic_year_id=int(year_id))


# -------------------------------------------------------------------- events
def create_event(actor, data: dict, poster: tuple[str, bytes] | None = None) -> int:
    staff = require_staff(actor)
    clean = _clean_event(data)
    poster_rel = None
    if poster:
        poster_rel, _ = file_service.store_event_file("posters", poster[0], poster[1], ["png", "jpg", "jpeg"])
    now = utc_now_str()
    try:
        with transaction() as conn:
            eid = conn.execute(
                "INSERT INTO events(name, description, category, poster_path, event_date, opens_on, deadline,"
                " instructions, academic_year_id, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?, 'draft', ?,?,?)",
                (clean["name"], clean["description"], clean["category"], poster_rel, clean["event_date"],
                 clean["opens_on"], clean["deadline"], clean["instructions"], clean["academic_year_id"],
                 staff["id"], now, now)).lastrowid
            audit(conn, staff, "event_created", "event", eid, clean["name"])
        return eid
    except BaseException:
        file_service.delete_upload(poster_rel)
        raise


def update_event(actor, event_id, data: dict, poster: tuple[str, bytes] | None = None,
                 remove_poster: bool = False) -> None:
    staff = require_staff(actor)
    new_rel = None
    old_rel = None
    try:
        with transaction() as conn:
            row = _event_row(conn, event_id)
            _can_manage(staff, row)
            if row["status"] == "archived":
                raise ValidationError("Archived events cannot be edited. Restore the event first.")
            clean = _clean_event(data, existing=row)
            poster_rel = row["poster_path"]
            if poster:
                new_rel, _ = file_service.store_event_file("posters", poster[0], poster[1], ["png", "jpg", "jpeg"])
                old_rel, poster_rel = row["poster_path"], new_rel
            elif remove_poster:
                old_rel, poster_rel = row["poster_path"], None
            conn.execute(
                "UPDATE events SET name=?, description=?, category=?, event_date=?, opens_on=?, deadline=?,"
                " instructions=?, academic_year_id=?, poster_path=?, updated_at=? WHERE id=?",
                (clean["name"], clean["description"], clean["category"], clean["event_date"], clean["opens_on"],
                 clean["deadline"], clean["instructions"], clean["academic_year_id"], poster_rel,
                 utc_now_str(), event_id))
            audit(conn, staff, "event_updated", "event", event_id)
    except BaseException:
        file_service.delete_upload(new_rel)
        raise
    file_service.delete_upload(old_rel)


def set_event_status(actor, event_id, action: str) -> str:
    staff = require_staff(actor)
    if action not in TRANSITIONS:
        raise ValidationError("Unknown action.")
    allowed, new_status = TRANSITIONS[action]
    with transaction() as conn:
        row = _event_row(conn, event_id)
        _can_manage(staff, row)
        if row["status"] not in allowed:
            raise ValidationError(f"This action is not possible while the event is '{row['status']}'.")
        if action == "publish":
            if conn.execute("SELECT COUNT(*) FROM event_class_assignments WHERE event_id=?", (event_id,)).fetchone()[0] == 0:
                raise ValidationError("Add at least one class assignment before publishing this event.")
        if action == "unpublish":
            if conn.execute(
                "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
                " WHERE a.event_id=?", (event_id,)).fetchone()[0] > 0:
                raise ValidationError("Students have already submitted work. Close the event instead of unpublishing it.")
        conn.execute("UPDATE events SET status=?, updated_at=? WHERE id=?", (new_status, utc_now_str(), event_id))
        audit(conn, staff, f"event_{action}", "event", event_id, f"{row['status']} -> {new_status}")
    return new_status


def delete_event(actor, event_id, confirm_name: str) -> None:
    """Delete only draft/archived events that have no student submissions, after typing the name."""
    staff = require_staff(actor)
    poster = None
    refs: list[str] = []
    with transaction() as conn:
        row = _event_row(conn, event_id)
        _can_manage(staff, row)
        if row["status"] not in ("draft", "archived"):
            raise ValidationError("Only draft or archived events can be deleted. Archive the event first.")
        if (confirm_name or "").strip() != row["name"]:
            raise ValidationError("To delete, type the exact event name in the confirmation box.")
        if conn.execute(
            "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
            " WHERE a.event_id=?", (event_id,)).fetchone()[0] > 0:
            raise ValidationError("This event has student submissions and cannot be deleted. Keep it archived.")
        poster = row["poster_path"]
        refs = [r[0] for r in conn.execute(
            "SELECT reference_path FROM event_class_assignments WHERE event_id=? AND reference_path IS NOT NULL",
            (event_id,)).fetchall()]
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        audit(conn, staff, "event_deleted", "event", event_id, row["name"])
    file_service.delete_upload(poster)
    for r in refs:
        file_service.delete_upload(r)


def get_event(actor, event_id) -> dict:
    staff = require_staff(actor)
    row = query_one(
        "SELECT e.*, u.full_name AS creator_name, ay.name AS year_name FROM events e"
        " JOIN users u ON u.id=e.created_by JOIN academic_years ay ON ay.id=e.academic_year_id WHERE e.id=?",
        (event_id,))
    if not row:
        raise NotFound("Event not found.")
    _can_manage(staff, row)
    return row


def list_events(actor, status: str | None = None, search: str = "") -> list[dict]:
    staff = require_staff(actor)
    sql = ("SELECT e.*, u.full_name AS creator_name, ay.name AS year_name,"
           " (SELECT COUNT(*) FROM event_class_assignments a WHERE a.event_id=e.id) AS assignment_count,"
           " (SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
           "   WHERE a.event_id=e.id) AS submission_count"
           " FROM events e JOIN users u ON u.id=e.created_by JOIN academic_years ay ON ay.id=e.academic_year_id"
           " WHERE (? = 1 OR e.created_by = ?)")
    params: list = [1 if staff["role"] == "admin" else 0, staff["id"]]
    if status:
        sql += " AND e.status=?"
        params.append(status)
    if search:
        sql += " AND e.name LIKE ? ESCAPE '\\'"
        params.append("%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return query_all(sql + " ORDER BY e.created_at DESC, e.id DESC", params)


# --------------------------------------------------------------- assignments
def _clean_assignment(data: dict) -> dict:
    topic = clean_text(data.get("topic"), "Topic", 150, required=True)
    formats = [f.lower() for f in (data.get("allowed_formats") or SUPPORTED_EXTENSIONS)]
    if not formats or any(f not in SUPPORTED_EXTENSIONS for f in formats):
        raise ValidationError("Please choose valid submission formats.")
    formats = [f for f in SUPPORTED_EXTENSIONS if f in formats]
    deadline = parse_datetime(data["deadline"], "Assignment deadline") if data.get("deadline") else None
    return dict(topic=topic, description=clean_text(data.get("description"), "Task description", 5000),
                instructions=clean_text(data.get("instructions"), "Detailed instructions", 8000),
                criteria=clean_text(data.get("criteria"), "Evaluation criteria", 3000),
                max_marks=parse_positive_float(data.get("max_marks"), "Maximum marks"),
                allowed_formats=",".join(formats), deadline=deadline)


def create_assignment(actor, event_id, data: dict, reference: tuple[str, bytes] | None = None) -> int:
    staff = require_staff(actor)
    clean = _clean_assignment(data)
    if clean["deadline"] and clean["deadline"] <= local_now_str():
        raise ValidationError("The assignment deadline must be in the future.")
    class_id = data.get("class_id")
    section_id = data.get("section_id") or None
    ref_rel = ref_name = None
    if reference:
        ref_rel, ref_name = file_service.store_event_file(
            "references", reference[0], reference[1], list(SUPPORTED_EXTENSIONS))
    try:
        with transaction() as conn:
            ev = _event_row(conn, event_id)
            _can_manage(staff, ev)
            if ev["status"] == "archived":
                raise ValidationError("Archived events cannot be changed.")
            cls = conn.execute("SELECT is_active FROM classes WHERE id=?", (class_id,)).fetchone()
            if not cls or not cls["is_active"]:
                raise ValidationError("Please choose an active class.")
            if section_id:
                sec = conn.execute("SELECT class_id, is_active FROM sections WHERE id=?", (section_id,)).fetchone()
                if not sec or sec["class_id"] != int(class_id) or not sec["is_active"]:
                    raise ValidationError("The selected section does not belong to this class or is not active.")
            existing = conn.execute(
                "SELECT section_id FROM event_class_assignments WHERE event_id=? AND class_id=?",
                (event_id, class_id)).fetchall()
            if existing:
                if any(r["section_id"] is None for r in existing) or section_id is None:
                    raise ValidationError(
                        "This class already has an assignment in this event. Use either one assignment for the whole "
                        "class or separate assignments per section, not both.")
            now = utc_now_str()
            aid = conn.execute(
                "INSERT INTO event_class_assignments(event_id, class_id, section_id, topic, description, instructions,"
                " allowed_formats, deadline, criteria, max_marks, reference_path, reference_name, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, class_id, section_id, clean["topic"], clean["description"], clean["instructions"],
                 clean["allowed_formats"], clean["deadline"], clean["criteria"], clean["max_marks"],
                 ref_rel, ref_name, now, now)).lastrowid
            audit(conn, staff, "assignment_created", "assignment", aid, clean["topic"])
        return aid
    except sqlite3.IntegrityError:
        file_service.delete_upload(ref_rel)
        raise ValidationError("An assignment already exists for this class and section in this event.") from None
    except BaseException:
        file_service.delete_upload(ref_rel)
        raise


def update_assignment(actor, assignment_id, data: dict, reference: tuple[str, bytes] | None = None,
                      remove_reference: bool = False) -> None:
    staff = require_staff(actor)
    clean = _clean_assignment(data)
    new_ref = old_ref = None
    try:
        with transaction() as conn:
            row = conn.execute("SELECT a.*, e.created_by, e.status AS event_status FROM event_class_assignments a"
                               " JOIN events e ON e.id=a.event_id WHERE a.id=?", (assignment_id,)).fetchone()
            if not row:
                raise NotFound("Assignment not found.")
            _can_manage(staff, {"created_by": row["created_by"]})
            if row["event_status"] == "archived":
                raise ValidationError("Archived events cannot be changed.")
            if clean["deadline"] and clean["deadline"] != row["deadline"] and clean["deadline"] <= local_now_str():
                raise ValidationError("The assignment deadline must be in the future.")
            ref_path, ref_name = row["reference_path"], row["reference_name"]
            if reference:
                new_ref, new_name = file_service.store_event_file(
                    "references", reference[0], reference[1], list(SUPPORTED_EXTENSIONS))
                old_ref, ref_path, ref_name = row["reference_path"], new_ref, new_name
            elif remove_reference:
                old_ref, ref_path, ref_name = row["reference_path"], None, None
            conn.execute(
                "UPDATE event_class_assignments SET topic=?, description=?, instructions=?, allowed_formats=?,"
                " deadline=?, criteria=?, max_marks=?, reference_path=?, reference_name=?, updated_at=? WHERE id=?",
                (clean["topic"], clean["description"], clean["instructions"], clean["allowed_formats"],
                 clean["deadline"], clean["criteria"], clean["max_marks"], ref_path, ref_name,
                 utc_now_str(), assignment_id))
            audit(conn, staff, "assignment_updated", "assignment", assignment_id)
    except BaseException:
        file_service.delete_upload(new_ref)
        raise
    file_service.delete_upload(old_ref)


def delete_assignment(actor, assignment_id) -> None:
    staff = require_staff(actor)
    ref = None
    with transaction() as conn:
        row = conn.execute("SELECT a.*, e.created_by FROM event_class_assignments a JOIN events e ON e.id=a.event_id"
                           " WHERE a.id=?", (assignment_id,)).fetchone()
        if not row:
            raise NotFound("Assignment not found.")
        _can_manage(staff, {"created_by": row["created_by"]})
        if conn.execute("SELECT COUNT(*) FROM submissions WHERE assignment_id=?", (assignment_id,)).fetchone()[0]:
            raise ValidationError("Students have already submitted work for this assignment, so it cannot be deleted.")
        ref = row["reference_path"]
        conn.execute("DELETE FROM event_class_assignments WHERE id=?", (assignment_id,))
        audit(conn, staff, "assignment_deleted", "assignment", assignment_id)
    file_service.delete_upload(ref)


def list_assignments(actor, event_id) -> list[dict]:
    staff = require_staff(actor)
    ev = query_one("SELECT created_by FROM events WHERE id=?", (event_id,))
    if not ev:
        raise NotFound("Event not found.")
    _can_manage(staff, ev)
    return query_all(
        "SELECT a.*, c.name AS class_name, sec.name AS section_name,"
        " (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id=a.id) AS submission_count,"
        " (SELECT COUNT(*) FROM students st WHERE st.is_active=1 AND st.class_id=a.class_id"
        "   AND (a.section_id IS NULL OR st.section_id=a.section_id)) AS student_count"
        " FROM event_class_assignments a JOIN classes c ON c.id=a.class_id"
        " LEFT JOIN sections sec ON sec.id=a.section_id WHERE a.event_id=?"
        " ORDER BY c.sort_order, c.name, sec.name", (event_id,))


def read_reference(actor, assignment_id) -> tuple[str, bytes]:
    """Reference material: staff who own the event, or students of that class/section."""
    from auth import verify_actor
    who = verify_actor(actor)
    row = query_one(
        "SELECT a.reference_path, a.reference_name, a.class_id, a.section_id, e.created_by, e.status"
        " FROM event_class_assignments a JOIN events e ON e.id=a.event_id WHERE a.id=?", (assignment_id,))
    if not row:
        raise NotFound("No reference material is attached.")
    # permission first, so nobody can probe which other tasks have attachments
    if who["role"] == "student":
        if (row["class_id"] != who["class_id"] or (row["section_id"] and row["section_id"] != who["section_id"])
                or row["status"] == "draft"):
            raise PermissionDenied("You do not have access to this file.")
    else:
        _can_manage(who, row)
    if not row["reference_path"]:
        raise NotFound("No reference material is attached.")
    return row["reference_name"] or "reference", file_service.read_upload(row["reference_path"])


def read_poster(actor, event_id) -> bytes | None:
    """Poster image for an event visible to this user (None when there is none)."""
    from auth import verify_actor
    who = verify_actor(actor)
    row = query_one("SELECT poster_path, created_by, status FROM events WHERE id=?", (event_id,))
    if not row or not row["poster_path"]:
        return None
    if who["role"] == "student":
        visible = query_one(
            "SELECT 1 AS x FROM event_class_assignments a WHERE a.event_id=? AND a.class_id=?"
            " AND (a.section_id IS NULL OR a.section_id=?)", (event_id, who["class_id"], who["section_id"]))
        if not visible or row["status"] == "draft":
            raise PermissionDenied("You do not have access to this file.")
    else:
        _can_manage(who, row)
    try:
        return file_service.read_upload(row["poster_path"])
    except Exception:
        return None


# ------------------------------------------------------------ student's view
def student_assignments(actor) -> list[dict]:
    """Everything a student may see: ONLY events assigned to their own class and section."""
    st = require_student(actor)
    rows = query_all(
        "SELECT e.id AS event_id, e.name AS event_name, e.description AS event_description, e.category,"
        " e.event_date, e.opens_on, e.deadline AS event_deadline, e.instructions AS event_instructions,"
        " e.status AS event_status, e.poster_path,"
        " a.id AS assignment_id, a.topic, a.description AS task_description, a.instructions AS task_instructions,"
        " a.allowed_formats, COALESCE(a.deadline, e.deadline) AS deadline, a.criteria, a.max_marks,"
        " a.reference_name, a.reference_path,"
        " s.id AS submission_id, s.status AS submission_status, s.marks, s.current_version, s.cert_type"
        " FROM event_class_assignments a JOIN events e ON e.id=a.event_id"
        " LEFT JOIN submissions s ON s.assignment_id=a.id AND s.student_id=?"
        " WHERE a.class_id=? AND (a.section_id IS NULL OR a.section_id=?)"
        " AND (e.status IN ('published','closed') OR (e.status='archived' AND s.id IS NOT NULL))"
        " ORDER BY COALESCE(a.deadline, e.deadline), e.name",
        (st["id"], st["class_id"], st["section_id"]))
    today, now = local_today_str(), local_now_str()
    for r in rows:
        status = r["submission_status"]
        r["has_reference"] = bool(r.pop("reference_path"))
        r["has_poster"] = bool(r.pop("poster_path"))
        r["status_label"] = status or "Not Started"
        r["not_open_yet"] = r["opens_on"] > today
        r["deadline_passed"] = r["deadline"] <= now
        r["can_submit"] = (r["event_status"] == "published" and not r["not_open_yet"]
                           and not r["deadline_passed"] and status in STUDENT_CAN_UPLOAD)
    return rows


def dashboard_stats(actor) -> dict:
    staff = require_staff(actor)
    admin_flag = 1 if staff["role"] == "admin" else 0
    scope_params = (admin_flag, staff["id"])
    scope = "(? = 1 OR e.created_by = ?)"
    pend = ",".join("?" * len(PENDING_STATUSES))
    return {
        "total_events": scalar(f"SELECT COUNT(*) FROM events e WHERE {scope}", scope_params),
        "active_events": scalar(f"SELECT COUNT(*) FROM events e WHERE {scope} AND e.status='published'", scope_params),
        "assigned_students": scalar(
            "SELECT COUNT(DISTINCT st.id) FROM students st JOIN event_class_assignments a ON a.class_id=st.class_id"
            " AND (a.section_id IS NULL OR a.section_id=st.section_id) JOIN events e ON e.id=a.event_id"
            f" WHERE st.is_active=1 AND e.status IN ('published','closed') AND {scope}", scope_params),
        "total_submissions": scalar(
            "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
            f" JOIN events e ON e.id=a.event_id WHERE {scope}", scope_params),
        "pending_reviews": scalar(
            "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
            f" JOIN events e ON e.id=a.event_id WHERE {scope} AND s.status IN ({pend})",
            scope_params + tuple(PENDING_STATUSES)),
        "approved": scalar(
            "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
            f" JOIN events e ON e.id=a.event_id WHERE {scope} AND s.status=?", scope_params + (APPROVED,)),
        "rejected": scalar(
            "SELECT COUNT(*) FROM submissions s JOIN event_class_assignments a ON a.id=s.assignment_id"
            f" JOIN events e ON e.id=a.event_id WHERE {scope} AND s.status IN (?,?)",
            scope_params + (REJECTED, RESUBMISSION_REQUIRED)),
        "upcoming_deadlines": query_all(
            "SELECT e.id, e.name, e.deadline FROM events e WHERE (? = 1 OR e.created_by = ?)"
            " AND e.status='published' AND e.deadline > ? ORDER BY e.deadline LIMIT 8",
            scope_params + (local_now_str(),)),
    }
