"""F: security boundaries, enforced on the server side."""
import pytest

import auth
from database import query_all, query_one
from helpers import make_pdf, make_png
from services import (admin_service as adm, certificate_service as cert, event_service as ev, report_service as rep,
                      submission_service as sub)
from utils import ui
from utils.errors import AppError, NotFound, PermissionDenied, ValidationError


def _submit(school, cls):
    sub.submit_work(school["actors"][cls], school["assignments"][cls], "w.pdf", make_pdf(cls))
    return [r for r in sub.list_review_queue(school["t1"]) if r["class_name"] == cls][0]["id"]


def test_student_cannot_use_staff_features(school):
    """F01 | Student cannot reach teacher features | Every staff-only action refuses a student"""
    s = school["actors"]["6"]
    data = dict(name="Hack", description="", category="Art", opens_on="2020-01-01", deadline="2030-01-01 10:00",
                academic_year_id=school["year"])
    sid = _submit(school, "6")
    calls = [lambda: ev.create_event(s, data), lambda: ev.list_events(s), lambda: ev.dashboard_stats(s),
             lambda: ev.set_event_status(s, school["event"], "close"), lambda: ev.delete_event(s, school["event"], "x"),
             lambda: ev.create_assignment(s, school["event"], dict(class_id=1, topic="t")),
             lambda: ev.list_assignments(s, school["event"]), lambda: sub.list_review_queue(s),
             lambda: sub.get_submission_for_review(s, sid), lambda: sub.review_action(s, sid, "approve", ""),
             lambda: sub.revert_approval(s, sid, "x"), lambda: rep.event_participation(s),
             lambda: cert.list_certificates(s), lambda: adm.create_class(s, "Hack"), lambda: adm.add_student(s, "Hack Kid", 1, 1, "99"),
             lambda: adm.list_students(s), lambda: adm.create_year(s, "2099-00"), lambda: cert.set_revoked(s, 1, True, "x")]
    for call in calls:
        with pytest.raises(PermissionDenied):
            call()
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] == "Submitted"


def test_student_cannot_approve_own_work(school):
    """F02 | Student cannot approve their own submission | No route lets a student change a status; status stays pending"""
    sid = _submit(school, "7")
    s = school["actors"]["7"]
    for action in ("approve", "reject", "request_corrections"):
        with pytest.raises(PermissionDenied):
            sub.review_action(s, sid, action, "self")
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(s, sid)
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] == "Submitted"
    assert query_one("SELECT COUNT(*) AS n FROM certificates")["n"] == 0


def test_student_cannot_see_other_students_work(school):
    """F03 | Student cannot download another student's private submission | Other students and other teachers are refused; the owner is allowed"""
    sid = _submit(school, "6")
    vid = sub.get_submission_for_review(school["t1"], sid, mark_in_review=False)["versions"][0]["id"]
    with pytest.raises(PermissionDenied):
        sub.download_version(school["actors"]["7"], vid)
    with pytest.raises(PermissionDenied):
        sub.download_version(school["t2"], vid)
    with pytest.raises(NotFound):
        sub.download_version(school["actors"]["6"], 99999)
    assert sub.download_version(school["actors"]["6"], vid)[1].startswith(b"%PDF")
    assert sub.download_version(school["admin"], vid)
    assert sub.student_submission(school["actors"]["7"], school["assignments"]["6"]) is None   # no peek at class 6's task


def test_student_cannot_submit_to_other_class(school):
    """F04 | Student cannot alter identity or class to reach another assignment | Submitting to another class's task is refused, forged session data is ignored"""
    with pytest.raises(PermissionDenied):
        sub.submit_work(school["actors"]["6"], school["assignments"]["7"], "w.pdf", make_pdf())
    forged = dict(school["actors"]["6"], class_id=school["classes"]["10"], section_id=school["sections"]["10"]["A"],
                  class_name="10", roll="5", name="Student Class10")
    mine = ev.student_assignments(forged)
    assert [m["topic"] for m in mine] == ["Basic Science Model"]                 # real class from the database, not from the dict
    with pytest.raises(PermissionDenied):
        sub.submit_work(forged, school["assignments"]["10"], "w.pdf", make_pdf())
    with pytest.raises(PermissionDenied):
        ev.read_reference(school["actors"]["6"], school["assignments"]["10"])
    assert query_one("SELECT COUNT(*) AS n FROM submissions")["n"] == 0


def test_certificate_access_rules(school):
    """F05 | Certificate access | No certificate before approval; only the owner, the event's teacher and admin may download; revoked ones are blocked"""
    sid = _submit(school, "6")
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(school["actors"]["6"], sid)
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(school["t1"], sid)                       # even the teacher: not approved yet
    sub.review_action(school["t1"], sid, "approve", "")
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(school["actors"]["7"], sid)
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(school["t2"], sid)
    c = cert.generate_for_submission(school["actors"]["6"], sid)
    for who in (school["actors"]["7"], school["t2"]):
        with pytest.raises(PermissionDenied):
            cert.get_certificate_pdf(who, c["id"])
    for who in (school["actors"]["6"], school["t1"], school["admin"]):
        assert cert.get_certificate_pdf(who, c["id"])[1].startswith(b"%PDF")
    cert.set_revoked(school["t1"], c["id"], True, "Issued in error")
    with pytest.raises(PermissionDenied):
        cert.get_certificate_pdf(school["actors"]["6"], c["id"])
    v = cert.verify(c["certificate_code"])
    assert v["found"] and not v["valid"] and v["status"] == "revoked"
    with pytest.raises(ValidationError):
        cert.set_revoked(school["t1"], c["id"], False) if False else cert.set_revoked(school["t1"], c["id"], True, "")
    cert.set_revoked(school["t1"], c["id"], False)
    assert cert.verify(c["certificate_code"])["valid"]


def test_teacher_isolation(school):
    """F06 | One teacher cannot touch another teacher's data | Other teacher's events, assignments, reviews, files and reports are off limits"""
    sid = _submit(school, "6")
    t2 = school["t2"]
    vid = sub.get_submission_for_review(school["t1"], sid, mark_in_review=False)["versions"][0]["id"]
    checks = [lambda: ev.get_event(t2, school["event"]), lambda: ev.set_event_status(t2, school["event"], "close"),
              lambda: ev.update_event(t2, school["event"], dict(name="x")), lambda: ev.list_assignments(t2, school["event"]),
              lambda: ev.update_assignment(t2, school["assignments"]["6"], dict(topic="Stolen")),
              lambda: ev.delete_assignment(t2, school["assignments"]["6"]),
              lambda: ev.create_assignment(t2, school["event"], dict(class_id=school["classes"]["6"], topic="x")),
              lambda: sub.get_submission_for_review(t2, sid), lambda: sub.review_action(t2, sid, "approve", ""),
              lambda: sub.revert_approval(t2, sid, "x"), lambda: sub.download_version(t2, vid)]
    for c in checks:
        with pytest.raises(PermissionDenied):
            c()
    assert ev.list_events(t2) == [] and sub.list_review_queue(t2) == [] and cert.list_certificates(t2) == []
    assert rep.event_participation(t2) == [] and rep.pending_reviews(t2) == []
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] == "Submitted"
    assert query_one("SELECT topic FROM event_class_assignments WHERE id=?", (school["assignments"]["6"],))["topic"] == "Basic Science Model"
    assert sub.review_action(school["admin"], sid, "approve", "")["status"] == "Approved"   # admin may act on any event


def test_malicious_filenames(school):
    """F07 | Malicious file names | Traversal, null bytes and HTML in names are neutralised; files stay inside the uploads folder"""
    from config import get_paths
    evil = ["../../../../etc/cron.d/x.pdf", "..\\..\\boot.pdf", "a\x00.exe.pdf", "<script>alert(1)</script>.pdf",
            "CON.pdf", "x" * 400 + ".pdf", "name;rm -rf.pdf"]
    classes = ["6", "7", "8", "9", "10"]
    for i, name in enumerate(evil):
        cls = classes[i % 5]
        try:
            sub.submit_work(school["actors"][cls], school["assignments"][cls], name, make_pdf(str(i)))
        except ValidationError:
            continue
        # (one successful submission per class is enough for the stored-name check)
    root = get_paths().uploads_dir.resolve()
    stored = [p for p in root.rglob("*") if p.is_file()]
    assert stored and all(p.resolve().is_relative_to(root) for p in stored)
    assert not any("etc" in p.parts or p.name.startswith(".") for p in stored)
    names = [r["original_filename"] for r in query_all("SELECT original_filename FROM submission_versions")]
    assert names and all("/" not in n and "\\" not in n and "<" not in n and "\x00" not in n and len(n) <= 80 for n in names)
    assert ui.e("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert not (get_paths().root.parent / "etc").exists()


def test_no_sensitive_details_in_errors(school, monkeypatch):
    """F08 | Errors never reveal internals | Error messages contain no SQL, file paths or stack traces"""
    from config import get_paths
    leaks = ("sqlite", "traceback", "select ", "insert ", str(get_paths().root), ".py", "uploads/", "no such table")
    messages = []
    for call in (lambda: auth.login_staff("teacher1", "bad"), lambda: auth.login_student("x", 1, 1, "1"),
                 lambda: sub.submit_work(school["actors"]["6"], 99999, "w.pdf", make_pdf()),
                 lambda: sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "w.exe", b"x"),
                 lambda: cert.get_certificate_pdf(school["actors"]["6"], 12345),
                 lambda: sub.download_version(school["actors"]["6"], 12345),
                 lambda: adm.create_user(school["admin"], "teacher1", "Teacher123", "Dup", "")):
        with pytest.raises(AppError) as e:
            call()
        messages.append(str(e.value).lower())
    assert all(not any(l in m for l in leaks) for m in messages), messages
    # a raw database error is translated, never passed on
    import sqlite3, database
    monkeypatch.setattr(database.sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("unable to open database file /secret/path")))
    with pytest.raises(AppError) as e:
        database.query_one("SELECT 1")
    assert "secret" not in str(e.value) and "unable" not in str(e.value)


def test_sql_injection_attempts(school):
    """F09 | SQL injection | Hostile text in search boxes and forms is treated as plain text; tables stay intact"""
    t = school["t1"]
    for payload in ("'; DROP TABLE students;--", "' OR 1=1 --", "%", "_", "\\"):
        adm.list_students(t, search=payload)
        ev.list_events(t, search=payload)
        sub.list_review_queue(t, search=payload)
        cert.list_certificates(t, search=payload)
    adm.add_student(t, "Robert'); DROP TABLE students;--", school["classes"]["6"], school["sections"]["6"]["B"], "5")
    assert query_one("SELECT COUNT(*) AS n FROM students")["n"] == 6
    assert len(adm.list_students(t, search="%")) == 0 and len(adm.list_students(t, search="Robert")) == 1
    assert cert.verify("' OR '1'='1") == {"found": False, "valid": False}


def test_public_verification_exposes_only_safe_fields(school):
    """F10 | Verification page privacy | Only validity, student name, event, topic, date and ID are exposed"""
    sid = _submit(school, "6")
    sub.review_action(school["t1"], sid, "approve", "private feedback", marks=15)
    c = cert.generate_for_submission(school["actors"]["6"], sid)
    v = cert.verify(c["certificate_code"].lower())
    assert set(v) == {"found", "valid", "status", "certificate_code", "student_name", "event_name", "topic", "issued_on",
                      "school_name", "cert_type"}
    assert "private feedback" not in str(v) and "15" not in str(v.values())
    with pytest.raises(ValidationError):
        cert.verify("   ")
    assert query_one("SELECT COUNT(*) AS n FROM certificate_verifications")["n"] >= 1


def test_actor_verification_rechecks_database(school):
    """F11 | Server-side permission re-check | A deactivated student or a forged role is rejected immediately"""
    s = school["actors"]["6"]
    adm.update_student(school["t1"], school["students"]["6"], "Student Class6", school["classes"]["6"], school["sections"]["6"]["A"], "1", False)
    with pytest.raises(PermissionDenied):
        ev.student_assignments(s)
    for bad in ({"role": "teacher", "id": s["id"]}, {"role": "admin", "id": school["t1"]["id"]}, {"id": 1}, "admin", 5, {}):
        with pytest.raises(PermissionDenied):
            auth.verify_actor(bad)


def test_audit_log_records_sensitive_actions(school):
    """F12 | Audit logging | Logins, failed logins, user changes and reviews are recorded with actor and time"""
    with pytest.raises(AppError):
        auth.login_staff("teacher1", "wrong-pass-1")
    adm.reset_password(school["admin"], school["t1"]["id"], "Another12345")
    actions = {r["action"] for r in query_all("SELECT action FROM audit_logs")}
    assert {"admin_setup", "login_failed", "password_reset", "user_created", "event_created", "assignment_created",
            "event_publish", "student_login"} <= actions
    log = adm.recent_audit(school["admin"])
    assert log and all(r["created_at"] for r in log)
