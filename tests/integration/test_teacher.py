import pytest

import auth
from database import query_one
from helpers import FUTURE, make_pdf, make_png
from services import admin_service as adm, event_service as ev, report_service as rep, submission_service as sub
from utils.errors import AppError, PermissionDenied, ValidationError


def _event_data(school, **over):
    d = dict(name="Drawing Competition", description="d", category="Art", opens_on="2020-01-01", deadline=FUTURE,
             academic_year_id=school["year"], instructions="x")
    d.update(over)
    return d


def test_teacher_login_invalid(school):
    """B01 | Teacher login / invalid login | Valid teacher logs in; wrong password or student-only data is refused"""
    assert auth.login_staff("teacher1", "Teacher123")["role"] == "teacher"
    with pytest.raises(AppError):
        auth.login_staff("teacher1", "nope12345")


def test_event_create_edit_validation(school):
    """B02 | Create / edit event | Event saved as draft and editable; empty name, past deadline, deadline before opening date refused"""
    t = school["t1"]
    eid = ev.create_event(t, _event_data(school))
    assert ev.get_event(t, eid)["status"] == "draft"
    ev.update_event(t, eid, _event_data(school, name="Drawing Contest 2026"))
    assert ev.get_event(t, eid)["name"] == "Drawing Contest 2026"
    for bad in (dict(name=""), dict(deadline="2020-01-01 10:00"), dict(opens_on="2031-01-01"),
                dict(deadline="not a date"), dict(category="Nonexistent"), dict(academic_year_id=9999),
                dict(event_date="31-12-2026")):
        with pytest.raises(ValidationError):
            ev.create_event(t, _event_data(school, **bad))


def test_event_poster(school):
    """B03 | Event poster | PNG poster is stored and returned; a PDF poster is refused"""
    t = school["t1"]
    eid = ev.create_event(t, _event_data(school), poster=("poster.png", make_png()))
    assert ev.read_poster(t, eid)
    with pytest.raises(ValidationError):
        ev.create_event(t, _event_data(school), poster=("poster.pdf", make_pdf()))


def test_event_lifecycle(school):
    """B04 | Publish / unpublish / close / reopen / archive | Allowed moves work, invalid moves are refused, publish needs an assignment"""
    t = school["t1"]
    eid = ev.create_event(t, _event_data(school))
    with pytest.raises(ValidationError):
        ev.set_event_status(t, eid, "publish")          # no class assignment yet
    ev.create_assignment(t, eid, dict(class_id=school["classes"]["6"], topic="Sketch", allowed_formats=["png"]))
    assert ev.set_event_status(t, eid, "publish") == "published"
    with pytest.raises(ValidationError):
        ev.set_event_status(t, eid, "reopen")
    assert ev.set_event_status(t, eid, "unpublish") == "draft"
    ev.set_event_status(t, eid, "publish")
    assert ev.set_event_status(t, eid, "close") == "closed"
    assert ev.set_event_status(t, eid, "reopen") == "published"
    ev.set_event_status(t, eid, "close")
    assert ev.set_event_status(t, eid, "archive") == "archived"
    with pytest.raises(ValidationError):
        ev.update_event(t, eid, _event_data(school))
    assert ev.set_event_status(t, eid, "unarchive") == "closed"


def test_different_topics_per_class(school):
    """B05 | Different topics for different classes | One event holds five class topics; each class sees only its own"""
    t = school["t1"]
    rows = ev.list_assignments(t, school["event"])
    assert {r["class_name"]: r["topic"] for r in rows} == school["topics"]
    for name, topic in school["topics"].items():
        mine = ev.student_assignments(school["actors"][name])
        assert [m["topic"] for m in mine] == [topic]
    with pytest.raises(ValidationError):   # same class twice in the same event
        ev.create_assignment(t, school["event"], dict(class_id=school["classes"]["6"], topic="Duplicate"))


def test_section_scoping(school):
    """B06 | Section-specific assignment | A topic for section A is not visible to section B students"""
    t = school["t1"]
    eid = ev.create_event(t, _event_data(school, name="Maths Exhibition", category="Mathematics"))
    c = school["classes"]["7"]
    ev.create_assignment(t, eid, dict(class_id=c, section_id=school["sections"]["7"]["A"], topic="Fractions"))
    with pytest.raises(ValidationError):   # cannot mix whole-class with per-section
        ev.create_assignment(t, eid, dict(class_id=c, section_id=None, topic="Whole class"))
    ev.create_assignment(t, eid, dict(class_id=c, section_id=school["sections"]["7"]["B"], topic="Geometry"))
    ev.set_event_status(t, eid, "publish")
    adm.add_student(t, "Section B Kid", c, school["sections"]["7"]["B"], "9")
    b = auth.login_student("Section B Kid", c, school["sections"]["7"]["B"], "9")
    topics_b = {x["topic"] for x in ev.student_assignments(b)}
    topics_a = {x["topic"] for x in ev.student_assignments(school["actors"]["7"])}
    assert "Geometry" in topics_b and "Fractions" not in topics_b
    assert "Fractions" in topics_a and "Geometry" not in topics_a


def test_assignment_validation(school):
    """B07 | Assignment deadlines and formats | Invalid formats, past deadlines and inactive classes are refused; custom deadline is kept"""
    t = school["t1"]
    eid = ev.create_event(t, _event_data(school, name="Coding"))
    cid = school["classes"]["8"]
    for bad in (dict(allowed_formats=["exe"]), dict(deadline="2020-01-01 10:00"), dict(topic=""), dict(max_marks="abc"),
                dict(max_marks=-5)):
        with pytest.raises(ValidationError):
            payload = {"class_id": cid, "topic": "T", "allowed_formats": ["pdf"], **bad}
            ev.create_assignment(t, eid, payload)
    aid = ev.create_assignment(t, eid, dict(class_id=cid, topic="Scratch", allowed_formats=["pdf", "pptx"],
                                            deadline="2029-05-05 10:30", max_marks=50, criteria="Creativity"))
    row = [r for r in ev.list_assignments(t, eid) if r["id"] == aid][0]
    assert row["deadline"] == "2029-05-05 10:30" and row["allowed_formats"] == "pdf,pptx" and row["max_marks"] == 50
    with pytest.raises(ValidationError):   # wrong section for class
        ev.create_assignment(t, eid, dict(class_id=school["classes"]["9"], section_id=school["sections"]["6"]["A"], topic="X"))


def test_reference_material(school):
    """B08 | Reference materials | Reference file is stored; only that class's students and the owner can fetch it"""
    t = school["t1"]
    aid = school["assignments"]["6"]
    ev.update_assignment(t, aid, dict(topic="Basic Science Model", allowed_formats=["pdf"]), reference=("guide.pdf", make_pdf("guide")))
    name, data = ev.read_reference(school["actors"]["6"], aid)
    assert name == "guide.pdf" and data.startswith(b"%PDF")
    assert ev.read_reference(t, aid)
    with pytest.raises(PermissionDenied):
        ev.read_reference(school["actors"]["7"], aid)
    with pytest.raises(PermissionDenied):
        ev.read_reference(school["t2"], aid)


def _submit(school, cls="6", name="work.pdf", data=None):
    return sub.submit_work(school["actors"][cls], school["assignments"][cls], name, data or make_pdf())


def test_view_and_download_submissions(school):
    """B09 | View submissions + download | Teacher sees student, event and topic details and downloads the exact uploaded file"""
    t = school["t1"]
    pdf = make_pdf("exact bytes")
    _submit(school, data=pdf)
    q = sub.list_review_queue(t)
    assert len(q) == 1 and q[0]["student_name"] == "Student Class6" and q[0]["topic"] == "Basic Science Model"
    d = sub.get_submission_for_review(t, q[0]["id"])
    assert d["event_name"] == "Science and Technology Exhibition" and d["roll_number"] == "1"
    name, data, mime = sub.download_version(t, d["versions"][0]["id"])
    assert data == pdf and mime == "application/pdf" and name == "work.pdf"


def test_approve_reject_feedback(school):
    """B10 | Approve / reject / request corrections | Each action sets the right status, stores feedback, and needs feedback when rejecting"""
    t = school["t1"]
    for c in ("6", "7", "8"):
        _submit(school, c)
    ids = {r["class_name"]: r["id"] for r in sub.list_review_queue(t)}
    assert sub.review_action(t, ids["6"], "approve", "Excellent", marks=18, cert_type="Achievement")["status"] == "Approved"
    with pytest.raises(ValidationError):
        sub.review_action(t, ids["7"], "reject", "")
    with pytest.raises(ValidationError):
        sub.review_action(t, ids["7"], "request_corrections", "   ")
    assert sub.review_action(t, ids["7"], "reject", "Too short")["status"] == "Rejected"
    assert sub.review_action(t, ids["8"], "request_corrections", "Add diagrams")["status"] == "Resubmission Required"
    s = sub.student_submission(school["actors"]["7"], school["assignments"]["7"])
    assert s["reviews"][0]["feedback"] == "Too short" and s["status"] == "Rejected"


def test_marks_validation(school):
    """B11 | Marks validation | Marks above the maximum, negative or non-numeric are refused"""
    t = school["t1"]
    _submit(school)
    sid = sub.list_review_queue(t)[0]["id"]
    for bad in (21, -1, "abc"):
        with pytest.raises(ValidationError):
            sub.review_action(t, sid, "approve", "ok", marks=bad)
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] in ("Submitted", "Under Review")


def test_resubmission_review(school):
    """B12 | Review resubmissions | A corrected upload returns to the teacher as 'Resubmitted' and can then be approved"""
    t = school["t1"]
    _submit(school)
    sid = sub.list_review_queue(t)[0]["id"]
    sub.review_action(t, sid, "reject", "Fix the title")
    r = sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "v2.pdf", make_pdf("v2"))
    assert r["status"] == "Resubmitted" and r["version"] == 2
    q = sub.list_review_queue(t, status="pending")
    assert [x["status"] for x in q] == ["Resubmitted"]
    sub.review_action(t, sid, "approve", "Better")
    assert sub.get_submission_for_review(t, sid, mark_in_review=False)["status"] == "Approved"


def test_audit_trail(school):
    """B13 | Review audit trail | Every decision records reviewer, action, time, feedback, previous and new status"""
    t = school["t1"]
    _submit(school)
    sid = sub.list_review_queue(t)[0]["id"]
    sub.get_submission_for_review(t, sid)
    sub.review_action(t, sid, "reject", "Redo it")
    d = sub.get_submission_for_review(t, sid, mark_in_review=False)
    actions = [(r["action"], r["previous_status"], r["new_status"], r["reviewer"]) for r in reversed(d["reviews"])]
    assert actions == [("start_review", "Submitted", "Under Review", "Anita Kumar"),
                       ("reject", "Under Review", "Rejected", "Anita Kumar")]
    assert d["reviews"][0]["feedback"] == "Redo it" and d["reviews"][0]["created_at"]
    assert query_one("SELECT COUNT(*) AS n FROM audit_logs WHERE action='submission_reject'")["n"] == 1


def test_reports_and_csv(school):
    """B14 | Reports and CSV export | Report numbers match the real data; CSV cells cannot run as spreadsheet formulas"""
    t = school["t1"]
    for c in ("6", "7", "8", "9"):
        _submit(school, c)
    ids = {r["class_name"]: r["id"] for r in sub.list_review_queue(t)}
    sub.review_action(t, ids["6"], "approve", "")
    sub.review_action(t, ids["7"], "reject", "no")
    part = rep.event_participation(t)[0]
    assert (part["assigned_students"], part["submitted"], part["approved"], part["rejected"], part["pending"]) == (5, 4, 1, 1, 2)
    assert part["participation_pct"] == 80.0
    st = {r["status"]: r["count"] for r in rep.status_summary(t)}
    assert st["Approved"] == 1 and st["Rejected"] == 1
    assert len(rep.pending_reviews(t)) == 2 and len(rep.approved_projects(t)) == 1 and len(rep.rejected_projects(t)) == 1
    cls = {(r["class_name"]): r for r in rep.class_participation(t)}
    assert cls["6"]["approved"] == 1 and cls["10"]["participated"] == 0
    dl = rep.deadline_completion(t)
    assert sum(r["submitted"] for r in dl) == 4 and sum(r["missing"] for r in dl) == 1
    adm.add_student(t, "=HYPERLINK(\"http://x\")", school["classes"]["6"], school["sections"]["6"]["B"], "77")
    csv_text = rep.to_csv([{"Student": "=1+1", "Roll": "5"}])
    assert "'=1+1" in csv_text
    assert rep.to_csv([]) == ""


def test_delete_event_safeguards(school):
    """B15 | Delete event safeguards | Only draft/archived events without submissions, after typing the exact name, can be deleted"""
    t = school["t1"]
    with pytest.raises(ValidationError):
        ev.delete_event(t, school["event"], "Science and Technology Exhibition")   # published
    eid = ev.create_event(t, _event_data(school, name="Temp Event"))
    with pytest.raises(ValidationError):
        ev.delete_event(t, eid, "wrong name")
    ev.delete_event(t, eid, "Temp Event")
    assert query_one("SELECT 1 AS x FROM events WHERE id=?", (eid,)) is None
    _submit(school)
    ev.set_event_status(t, school["event"], "close")
    ev.set_event_status(t, school["event"], "archive")
    with pytest.raises(ValidationError):
        ev.delete_event(t, school["event"], "Science and Technology Exhibition")   # has submissions


def test_dashboard_stats(school):
    """B16 | Teacher dashboard numbers | Totals for events, students, submissions, pending, approved, rejected and deadlines are correct"""
    t = school["t1"]
    _submit(school, "6"); _submit(school, "7")
    ids = {r["class_name"]: r["id"] for r in sub.list_review_queue(t)}
    sub.review_action(t, ids["6"], "approve", "")
    s = ev.dashboard_stats(t)
    assert (s["total_events"], s["active_events"], s["assigned_students"], s["total_submissions"]) == (1, 1, 5, 2)
    assert (s["pending_reviews"], s["approved"], s["rejected"]) == (1, 1, 0)
    assert s["upcoming_deadlines"][0]["name"] == "Science and Technology Exhibition"
    assert ev.dashboard_stats(school["t2"])["total_events"] == 0     # other teacher sees only their own
    assert ev.dashboard_stats(school["admin"])["total_events"] == 1
