"""Reports built from real database data. Teachers see their own events; admins see all."""
from __future__ import annotations

import csv
import io

from auth import require_staff
from database import query_all
from utils.helpers import (APPROVED, PENDING_STATUSES, REJECTED, RESUBMISSION_REQUIRED, csv_safe, local_now_str)


def _scope(staff):
    return (1 if staff["role"] == "admin" else 0, staff["id"])


def event_participation(actor) -> list[dict]:
    """Per event: how many students were assigned, how many submitted, approved, etc."""
    s = require_staff(actor)
    rows = query_all(
        "SELECT e.id, e.name AS event, e.status,"
        " (SELECT COUNT(DISTINCT st.id) FROM students st JOIN event_class_assignments a ON a.class_id=st.class_id"
        "   AND (a.section_id IS NULL OR a.section_id=st.section_id) WHERE a.event_id=e.id AND st.is_active=1)"
        "   AS assigned_students,"
        " (SELECT COUNT(*) FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        "   WHERE a.event_id=e.id) AS submitted,"
        " (SELECT COUNT(*) FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        "   WHERE a.event_id=e.id AND x.status='Approved') AS approved,"
        " (SELECT COUNT(*) FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        "   WHERE a.event_id=e.id AND x.status IN ('Rejected','Resubmission Required')) AS rejected,"
        " (SELECT COUNT(*) FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        "   WHERE a.event_id=e.id AND x.status IN ('Submitted','Under Review','Resubmitted')) AS pending"
        " FROM events e WHERE (? = 1 OR e.created_by = ?) ORDER BY e.created_at DESC", _scope(s))
    for r in rows:
        r["participation_pct"] = round(100 * r["submitted"] / r["assigned_students"], 1) if r["assigned_students"] else 0.0
    return rows


def class_participation(actor) -> list[dict]:
    s = require_staff(actor)
    rows = query_all(
        "SELECT c.name AS class_name, sec.name AS section_name,"
        " COUNT(DISTINCT st.id) AS students,"
        " COUNT(DISTINCT x.student_id) AS participated,"
        " SUM(CASE WHEN x.status='Approved' THEN 1 ELSE 0 END) AS approved"
        " FROM students st JOIN classes c ON c.id=st.class_id JOIN sections sec ON sec.id=st.section_id"
        " LEFT JOIN (SELECT x.student_id, x.status FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        "   JOIN events e ON e.id=a.event_id WHERE (? = 1 OR e.created_by = ?)) x ON x.student_id=st.id"
        " WHERE st.is_active=1 GROUP BY c.id, sec.id ORDER BY c.sort_order, c.name, sec.name", _scope(s))
    for r in rows:
        r["approved"] = r["approved"] or 0
        r["participation_pct"] = round(100 * r["participated"] / r["students"], 1) if r["students"] else 0.0
    return rows


def status_summary(actor) -> list[dict]:
    s = require_staff(actor)
    return query_all(
        "SELECT x.status, COUNT(*) AS count FROM submissions x JOIN event_class_assignments a ON a.id=x.assignment_id"
        " JOIN events e ON e.id=a.event_id WHERE (? = 1 OR e.created_by = ?) GROUP BY x.status ORDER BY count DESC",
        _scope(s))


def submissions_by_status(actor, statuses: tuple[str, ...]) -> list[dict]:
    s = require_staff(actor)
    marks = ",".join("?" * len(statuses))
    return query_all(
        "SELECT st.full_name AS student, c.name AS class_name, sec.name AS section, st.roll_number AS roll,"
        " e.name AS event, a.topic, x.status, x.marks, x.updated_at"
        " FROM submissions x JOIN students st ON st.id=x.student_id JOIN event_class_assignments a ON a.id=x.assignment_id"
        " JOIN events e ON e.id=a.event_id JOIN classes c ON c.id=a.class_id JOIN sections sec ON sec.id=st.section_id"
        f" WHERE (? = 1 OR e.created_by = ?) AND x.status IN ({marks}) ORDER BY x.updated_at DESC",
        _scope(s) + tuple(statuses))


def pending_reviews(actor): return submissions_by_status(actor, PENDING_STATUSES)
def approved_projects(actor): return submissions_by_status(actor, (APPROVED,))
def rejected_projects(actor): return submissions_by_status(actor, (REJECTED, RESUBMISSION_REQUIRED))


def certificate_stats(actor) -> list[dict]:
    s = require_staff(actor)
    return query_all(
        "SELECT e.name AS event, COUNT(c.id) AS issued,"
        " SUM(CASE WHEN c.status='revoked' THEN 1 ELSE 0 END) AS revoked,"
        " SUM(CASE WHEN c.cert_type='Achievement' THEN 1 ELSE 0 END) AS achievement,"
        " SUM(CASE WHEN c.cert_type='Participation' THEN 1 ELSE 0 END) AS participation"
        " FROM events e LEFT JOIN certificates c ON c.event_id=e.id WHERE (? = 1 OR e.created_by = ?)"
        " GROUP BY e.id ORDER BY e.created_at DESC", _scope(s))


def deadline_completion(actor) -> list[dict]:
    """Per assignment: how many students handed in, how many are still missing, and whether the deadline passed."""
    s = require_staff(actor)
    now = local_now_str()
    rows = query_all(
        "SELECT e.name AS event, c.name AS class_name, sec.name AS section_name, a.topic,"
        " COALESCE(a.deadline, e.deadline) AS deadline,"
        " (SELECT COUNT(*) FROM students st WHERE st.is_active=1 AND st.class_id=a.class_id"
        "   AND (a.section_id IS NULL OR st.section_id=a.section_id)) AS students,"
        " (SELECT COUNT(*) FROM submissions x WHERE x.assignment_id=a.id) AS submitted"
        " FROM event_class_assignments a JOIN events e ON e.id=a.event_id JOIN classes c ON c.id=a.class_id"
        " LEFT JOIN sections sec ON sec.id=a.section_id WHERE (? = 1 OR e.created_by = ?)"
        " ORDER BY deadline", _scope(s))
    for r in rows:
        r["section_name"] = r["section_name"] or "All sections"
        r["missing"] = max(r["students"] - r["submitted"], 0)
        r["deadline_passed"] = "Yes" if r["deadline"] <= now else "No"
        r["completion_pct"] = round(100 * r["submitted"] / r["students"], 1) if r["students"] else 0.0
    return rows


def to_csv(rows: list[dict]) -> str:
    """CSV text with spreadsheet-formula protection."""
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        writer.writerow({k: csv_safe(v) for k, v in r.items()})
    return out.getvalue()
