"""Student submissions, version history and the teacher review workflow."""
from __future__ import annotations

import logging
import sqlite3

from auth import require_staff, require_student, verify_actor
from database import audit, query_all, query_one, transaction
from services import file_service
from utils.errors import AppError, NotFound, PermissionDenied, ValidationError
from utils.helpers import (APPROVED, PENDING_STATUSES, REJECTED, RESUBMISSION_REQUIRED, RESUBMITTED, SUBMITTED,
                           STUDENT_CAN_UPLOAD, UNDER_REVIEW, local_now_str, local_today_str, utc_now_str)
from utils.security import sha256_bytes
from utils.validators import clean_text

log = logging.getLogger("mses.submissions")

REVIEWABLE = (SUBMITTED, UNDER_REVIEW, RESUBMITTED)
ACTIONS = {"approve": APPROVED, "reject": REJECTED, "request_corrections": RESUBMISSION_REQUIRED}


# ------------------------------------------------------------------- student
def submit_work(actor, assignment_id, filename, data: bytes) -> dict:
    """Student uploads a file for THEIR OWN class assignment. Never auto-approves."""
    st = require_student(actor)
    paths_written: list[str] = []
    try:
        with transaction() as conn:
            a = conn.execute(
                "SELECT a.id, a.class_id, a.section_id, a.allowed_formats, COALESCE(a.deadline, e.deadline) AS deadline,"
                " e.status AS event_status, e.opens_on FROM event_class_assignments a JOIN events e ON e.id=a.event_id"
                " WHERE a.id=?", (assignment_id,)).fetchone()
            # A student can only ever submit to an assignment of their own class/section.
            if (not a or a["class_id"] != st["class_id"]
                    or (a["section_id"] is not None and a["section_id"] != st["section_id"])
                    or a["event_status"] == "draft"):
                raise PermissionDenied("This task is not assigned to you.")
            if a["event_status"] != "published":
                raise ValidationError("This event is closed. Submissions are no longer accepted.")
            if a["opens_on"] > local_today_str():
                raise ValidationError("Submissions for this event have not opened yet.")
            if a["deadline"] <= local_now_str():
                raise ValidationError("The deadline for this task has passed. Please contact your teacher.")
            ext, safe_name = file_service.validate_upload(filename, data, a["allowed_formats"].split(","))
            sub = conn.execute("SELECT id, status, current_version FROM submissions WHERE assignment_id=? AND student_id=?",
                               (assignment_id, st["id"])).fetchone()
            now = utc_now_str()
            if sub is None:
                sub_id = conn.execute(
                    "INSERT INTO submissions(assignment_id, student_id, status, current_version, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)", (assignment_id, st["id"], SUBMITTED, 1, now, now)).lastrowid
                version, previous, new_status = 1, None, SUBMITTED
            else:
                if sub["status"] not in STUDENT_CAN_UPLOAD:
                    if sub["status"] == APPROVED:
                        raise ValidationError("Your work has already been approved. No more uploads are needed.")
                    raise ValidationError("Your work is waiting for review. You can upload a new version "
                                          "only if your teacher asks for corrections.")
                sub_id, version = sub["id"], sub["current_version"] + 1
                previous, new_status = sub["status"], RESUBMITTED
            rel = file_service.store_submission_file(assignment_id, st["id"], version, ext, data)
            paths_written.append(rel)
            conn.execute(
                "INSERT INTO submission_versions(submission_id, version_no, original_filename, stored_path, file_size,"
                " sha256, uploaded_at) VALUES (?,?,?,?,?,?,?)",
                (sub_id, version, safe_name, rel, len(data), sha256_bytes(data), now))
            if previous is not None:
                conn.execute("UPDATE submissions SET status=?, current_version=?, updated_at=? WHERE id=?",
                             (new_status, version, now, sub_id))
            audit(conn, st, "submission_uploaded", "submission", sub_id, f"v{version} {safe_name}")
        return {"submission_id": sub_id, "version": version, "status": new_status, "filename": safe_name,
                "uploaded_at": now}
    except BaseException:
        for rel in paths_written:  # do not leave an unreferenced file behind
            file_service.delete_upload(rel)
        raise


def student_submission(actor, assignment_id) -> dict | None:
    """The student's own submission with version history and teacher feedback."""
    st = require_student(actor)
    sub = query_one("SELECT * FROM submissions WHERE assignment_id=? AND student_id=?", (assignment_id, st["id"]))
    if not sub:
        return None
    sub["versions"] = query_all(
        "SELECT id, version_no, original_filename, file_size, uploaded_at FROM submission_versions"
        " WHERE submission_id=? ORDER BY version_no DESC", (sub["id"],))
    sub["reviews"] = query_all(
        "SELECT r.action, r.feedback, r.new_status, r.marks, r.created_at, u.full_name AS reviewer"
        " FROM reviews r JOIN users u ON u.id=r.reviewer_id WHERE r.submission_id=?"
        " AND r.action != 'start_review' ORDER BY r.id DESC", (sub["id"],))
    return sub


def student_recent_feedback(actor, limit: int = 5) -> list[dict]:
    """Latest teacher feedback on this student's own work."""
    st = require_student(actor)
    return query_all(
        "SELECT r.action, r.feedback, r.new_status, r.created_at, e.name AS event_name, a.topic, u.full_name AS reviewer"
        " FROM reviews r JOIN submissions s ON s.id=r.submission_id JOIN event_class_assignments a ON a.id=s.assignment_id"
        " JOIN events e ON e.id=a.event_id JOIN users u ON u.id=r.reviewer_id"
        " WHERE s.student_id=? AND r.action != 'start_review' ORDER BY r.id DESC LIMIT ?", (st["id"], int(limit)))


# ------------------------------------------------------------------ staff side
def _context(conn_or_none, submission_id) -> dict:
    sql = ("SELECT s.*, st.full_name AS student_name, st.roll_number, st.class_id AS student_class_id,"
           " st.section_id AS student_section_id, c.name AS class_name, sec.name AS section_name,"
           " a.id AS assignment_id_x, a.topic, a.description AS task_description, a.instructions AS task_instructions,"
           " a.criteria, a.max_marks, a.allowed_formats, COALESCE(a.deadline, e.deadline) AS deadline,"
           " e.id AS event_id, e.name AS event_name, e.created_by AS event_owner, e.status AS event_status"
           " FROM submissions s JOIN students st ON st.id=s.student_id"
           " JOIN event_class_assignments a ON a.id=s.assignment_id JOIN events e ON e.id=a.event_id"
           " JOIN classes c ON c.id=a.class_id JOIN sections sec ON sec.id=st.section_id WHERE s.id=?")
    if conn_or_none is None:
        row = query_one(sql, (submission_id,))
    else:
        r = conn_or_none.execute(sql, (submission_id,)).fetchone()
        row = dict(r) if r else None
    if not row:
        raise NotFound("Submission not found.")
    return row


def _staff_can_review(staff, ctx) -> None:
    if staff["role"] != "admin" and ctx["event_owner"] != staff["id"]:
        raise PermissionDenied("You can only review submissions for events that you created.")


def list_review_queue(actor, event_id=None, status=None, class_id=None, search="") -> list[dict]:
    staff = require_staff(actor)
    sql = ("SELECT s.id, s.status, s.current_version, s.marks, s.updated_at, st.full_name AS student_name,"
           " st.roll_number, c.name AS class_name, sec.name AS section_name, e.id AS event_id, e.name AS event_name,"
           " a.topic, v.uploaded_at, v.original_filename"
           " FROM submissions s JOIN students st ON st.id=s.student_id"
           " JOIN event_class_assignments a ON a.id=s.assignment_id JOIN events e ON e.id=a.event_id"
           " JOIN classes c ON c.id=a.class_id JOIN sections sec ON sec.id=st.section_id"
           " JOIN submission_versions v ON v.submission_id=s.id AND v.version_no=s.current_version"
           " WHERE (? = 1 OR e.created_by = ?)")
    params: list = [1 if staff["role"] == "admin" else 0, staff["id"]]
    if event_id:
        sql += " AND e.id=?"
        params.append(event_id)
    if status == "pending":
        sql += f" AND s.status IN ({','.join('?' * len(PENDING_STATUSES))})"
        params += list(PENDING_STATUSES)
    elif status:
        sql += " AND s.status=?"
        params.append(status)
    if class_id:
        sql += " AND a.class_id=?"
        params.append(class_id)
    if search:
        sql += " AND (st.full_name LIKE ? ESCAPE '\\' OR st.roll_number LIKE ? ESCAPE '\\')"
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like]
    sql += (" ORDER BY CASE WHEN s.status IN ('Submitted','Resubmitted') THEN 0 WHEN s.status='Under Review' THEN 1"
            " ELSE 2 END, v.uploaded_at")
    return query_all(sql, params)


def get_submission_for_review(actor, submission_id, mark_in_review: bool = True) -> dict:
    """Full detail for the teacher. Opening a fresh submission moves it to 'Under Review'."""
    staff = require_staff(actor)
    ctx = _context(None, submission_id)
    _staff_can_review(staff, ctx)
    if mark_in_review and ctx["status"] in (SUBMITTED, RESUBMITTED):
        with transaction() as conn:
            fresh = _context(conn, submission_id)
            if fresh["status"] in (SUBMITTED, RESUBMITTED):
                now = utc_now_str()
                ver = conn.execute("SELECT id FROM submission_versions WHERE submission_id=? AND version_no=?",
                                   (submission_id, fresh["current_version"])).fetchone()
                conn.execute("UPDATE submissions SET status=?, updated_at=?, last_reviewed_by=?, last_reviewed_at=?"
                             " WHERE id=? AND status IN (?,?)",
                             (UNDER_REVIEW, now, staff["id"], now, submission_id, SUBMITTED, RESUBMITTED))
                conn.execute(
                    "INSERT INTO reviews(submission_id, version_id, reviewer_id, action, feedback, previous_status,"
                    " new_status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (submission_id, ver["id"] if ver else None, staff["id"], "start_review", "",
                     fresh["status"], UNDER_REVIEW, now))
                audit(conn, staff, "review_started", "submission", submission_id)
        ctx = _context(None, submission_id)
    ctx["versions"] = query_all(
        "SELECT id, version_no, original_filename, file_size, sha256, uploaded_at FROM submission_versions"
        " WHERE submission_id=? ORDER BY version_no DESC", (submission_id,))
    ctx["reviews"] = query_all(
        "SELECT r.action, r.feedback, r.previous_status, r.new_status, r.marks, r.created_at, u.full_name AS reviewer,"
        " r.version_id FROM reviews r JOIN users u ON u.id=r.reviewer_id WHERE r.submission_id=? ORDER BY r.id DESC",
        (submission_id,))
    ctx["certificate"] = query_one("SELECT id, certificate_code, status FROM certificates WHERE submission_id=?",
                                   (submission_id,))
    return ctx


def review_action(actor, submission_id, action: str, feedback: str = "", marks=None,
                  cert_type: str | None = None, cert_remark: str = "") -> dict:
    """Approve / reject / request corrections. A deliberate teacher action, audited.

    Safe against double clicks: the status is re-checked inside the transaction, so a
    submission that was already decided cannot be decided a second time."""
    staff = require_staff(actor)
    if action not in ACTIONS:
        raise ValidationError("Unknown review action.")
    feedback = clean_text(feedback, "Feedback", 3000)
    if action in ("reject", "request_corrections") and not feedback:
        raise ValidationError("Please write feedback so the student knows what to correct.")
    new_status = ACTIONS[action]
    with transaction() as conn:
        ctx = _context(conn, submission_id)
        _staff_can_review(staff, ctx)
        if ctx["event_status"] == "archived":
            raise ValidationError("This event is archived.")
        if ctx["status"] not in REVIEWABLE:
            raise ValidationError(f"This submission has already been reviewed (status: {ctx['status']}). "
                                  "Nothing was changed.")
        mark_value = None
        if marks not in (None, ""):
            try:
                mark_value = float(marks)
            except (TypeError, ValueError):
                raise ValidationError("Marks must be a number.") from None
            if mark_value < 0 or (ctx["max_marks"] is not None and mark_value > ctx["max_marks"]):
                raise ValidationError("Marks must be between 0 and "
                                      f"{ctx['max_marks']:g}." if ctx["max_marks"] else "Marks cannot be negative.")
        ctype = remark = None
        if action == "approve":
            from services.settings_store import get_setting
            ctype = cert_type or get_setting("cert_default_type") or "Participation"
            if ctype not in ("Participation", "Achievement"):
                raise ValidationError("Certificate type must be Participation or Achievement.")
            remark = clean_text(cert_remark, "Certificate remark", 200)
        now = utc_now_str()
        ver = conn.execute("SELECT id FROM submission_versions WHERE submission_id=? AND version_no=?",
                           (submission_id, ctx["current_version"])).fetchone()
        cur = conn.execute(
            "UPDATE submissions SET status=?, marks=COALESCE(?, marks), cert_type=?, cert_remark=?, updated_at=?,"
            " last_reviewed_by=?, last_reviewed_at=? WHERE id=? AND status IN (?,?,?)",
            (new_status, mark_value, ctype, remark, now, staff["id"], now, submission_id, *REVIEWABLE))
        if cur.rowcount != 1:
            raise ValidationError("This submission was just reviewed by someone else. Nothing was changed.")
        conn.execute(
            "INSERT INTO reviews(submission_id, version_id, reviewer_id, action, feedback, previous_status,"
            " new_status, marks, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (submission_id, ver["id"] if ver else None, staff["id"], action, feedback, ctx["status"],
             new_status, mark_value, now))
        audit(conn, staff, f"submission_{action}", "submission", submission_id, f"{ctx['status']} -> {new_status}")
    return {"submission_id": submission_id, "status": new_status}


def revert_approval(actor, submission_id, reason: str) -> None:
    """Undo a mistaken approval: back to 'Under Review' and any certificate is revoked."""
    staff = require_staff(actor)
    reason = clean_text(reason, "Reason", 500, required=True)
    with transaction() as conn:
        ctx = _context(conn, submission_id)
        _staff_can_review(staff, ctx)
        if ctx["status"] != APPROVED:
            raise ValidationError("Only approved submissions can be reverted.")
        now = utc_now_str()
        conn.execute("UPDATE submissions SET status=?, updated_at=?, last_reviewed_by=?, last_reviewed_at=?,"
                     " cert_type=NULL, cert_remark=NULL WHERE id=?",
                     (UNDER_REVIEW, now, staff["id"], now, submission_id))
        conn.execute("UPDATE certificates SET status='revoked', revoked_reason=?, revoked_at=? WHERE submission_id=?"
                     " AND status='valid'", (f"Approval reverted: {reason}", now, submission_id))
        ver = conn.execute("SELECT id FROM submission_versions WHERE submission_id=? AND version_no=?",
                           (submission_id, ctx["current_version"])).fetchone()
        conn.execute(
            "INSERT INTO reviews(submission_id, version_id, reviewer_id, action, feedback, previous_status,"
            " new_status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (submission_id, ver["id"] if ver else None, staff["id"], "revert_approval", reason, APPROVED,
             UNDER_REVIEW, now))
        audit(conn, staff, "approval_reverted", "submission", submission_id, reason)


# ----------------------------------------------------------------- downloading
def download_version(actor, version_id) -> tuple[str, bytes, str]:
    """A file may be downloaded only by its own student, or by the teacher who owns the event (or an admin)."""
    who = verify_actor(actor)
    row = query_one(
        "SELECT v.original_filename, v.stored_path, s.student_id, e.created_by AS event_owner"
        " FROM submission_versions v JOIN submissions s ON s.id=v.submission_id"
        " JOIN event_class_assignments a ON a.id=s.assignment_id JOIN events e ON e.id=a.event_id WHERE v.id=?",
        (version_id,))
    if not row:
        raise NotFound("File not found.")
    if who["role"] == "student":
        if row["student_id"] != who["id"]:
            raise PermissionDenied("You can only download your own files.")
    elif who["role"] != "admin" and row["event_owner"] != who["id"]:
        raise PermissionDenied("You can only download files for events that you created.")
    data = file_service.read_upload(row["stored_path"])
    return row["original_filename"], data, file_service.mime_for(row["original_filename"])
