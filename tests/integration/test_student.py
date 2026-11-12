import pytest

import auth
from database import query_all, query_one
from helpers import SAMPLES, make_pdf, make_png
from integration.conftest_helpers import set_deadline
from services import admin_service as adm, certificate_service as cert, event_service as ev, submission_service as sub
from services.settings_store import max_upload_bytes
from utils.errors import AppError, PermissionDenied, ValidationError

NOT_FOUND = "We could not find a student with these details"


def _login(school, name="Student Class6", cls="6", sec="A", roll="1"):
    return auth.login_student(name, school["classes"][cls], school["sections"][cls][sec], roll)


def test_student_login_ok(school):
    """C01 | Student login with correct details | Works without a password; name is not case or spacing sensitive"""
    a = _login(school, "  student   CLASS6 ")
    assert a["role"] == "student" and a["name"] == "Student Class6"
    assert auth.verify_actor(a)["class_name"] == "6"


@pytest.mark.parametrize("kw", [dict(name="Someone Else"), dict(cls="6", sec="B"), dict(roll="2"), dict(roll="01")])
def test_student_login_wrong(school, kw):
    """C02 | Student login with incorrect details | A wrong name, section or roll number gives one generic 'not found' message"""
    cls = kw.get("cls", "6")
    with pytest.raises(AppError) as e:
        auth.login_student(kw.get("name", "Student Class6"), school["classes"][cls], school["sections"][cls][kw.get("sec", "A")],
                           kw.get("roll", "1"))
    assert NOT_FOUND in str(e.value)


def test_student_login_wrong_class(school):
    """C03 | Right name/roll but wrong class | Refused (identity is name + class + section + roll)"""
    with pytest.raises(AppError):
        auth.login_student("Student Class6", school["classes"]["7"], school["sections"]["6"]["A"], "1")
    with pytest.raises(AppError):
        auth.login_student("Student Class6", school["classes"]["7"], school["sections"]["7"]["A"], "1")


@pytest.mark.parametrize("missing", ["name", "class", "section", "roll"])
def test_student_login_missing_fields(school, missing):
    """C04 | Missing name / class / section / roll | Each missing field gives a clear message asking for it"""
    args = dict(name="Student Class6", class_id=school["classes"]["6"], section_id=school["sections"]["6"]["A"], roll="1")
    key = {"name": "name", "class": "class_id", "section": "section_id", "roll": "roll"}[missing]
    args[key] = ""
    with pytest.raises(ValidationError) as e:
        auth.login_student(**args)
    assert missing in str(e.value).lower()


def test_student_login_inactive_and_injection(school):
    """C05 | Inactive student / hostile input | Deactivated students cannot log in; SQL-looking input just fails safely"""
    adm.update_student(school["t1"], school["students"]["6"], "Student Class6", school["classes"]["6"],
                       school["sections"]["6"]["A"], "1", False)
    with pytest.raises(AppError):
        _login(school)
    with pytest.raises(AppError):
        auth.login_student("' OR '1'='1", school["classes"]["6"], school["sections"]["6"]["A"], "1' OR '1'='1")
    with pytest.raises(AppError):
        auth.login_student("x", "6 OR 1=1", "abc", "1")
    assert query_one("SELECT COUNT(*) AS n FROM students")["n"] == 5


def test_students_see_only_their_class(school):
    """C06 | Only assigned events visible | Each student sees exactly one task (their class's topic); unrelated classes are hidden"""
    for c, topic in school["topics"].items():
        mine = ev.student_assignments(school["actors"][c])
        assert [m["topic"] for m in mine] == [topic]
        others = {t for k, t in school["topics"].items() if k != c}
        assert not others & {m["topic"] for m in mine}


def test_draft_events_hidden(school):
    """C07 | Draft events are hidden | Students never see unpublished events"""
    t = school["t1"]
    eid = ev.create_event(t, dict(name="Secret Draft", description="", category="Art", opens_on="2020-01-01",
                                  deadline="2030-01-01 10:00", academic_year_id=school["year"]))
    ev.create_assignment(t, eid, dict(class_id=school["classes"]["6"], topic="Hidden Topic"))
    names = [m["event_name"] for m in ev.student_assignments(school["actors"]["6"])]
    assert "Secret Draft" not in names
    ev.set_event_status(t, eid, "publish")
    assert "Secret Draft" in [m["event_name"] for m in ev.student_assignments(school["actors"]["6"])]


def test_open_task_details(school):
    """C08 | Open assigned topic + read instructions | Student sees topic, description, formats, deadline and marks"""
    m = ev.student_assignments(school["actors"]["9"])[0]
    assert m["topic"] == "Artificial Intelligence Awareness" and m["task_description"] == "Do Artificial Intelligence Awareness"
    assert m["event_instructions"] == "Be original" and m["max_marks"] == 20 and m["can_submit"] and m["status_label"] == "Not Started"
    assert "pdf" in m["allowed_formats"]


@pytest.mark.parametrize("ext", ["pdf", "docx", "pptx", "jpg", "png"])
def test_upload_each_supported_type(school, ext):
    """C09 | Upload PDF / DOCX / PPTX / JPG / PNG | Each supported real file is accepted, saved and set to Submitted"""
    data = SAMPLES[ext]()
    r = sub.submit_work(school["actors"]["6"], school["assignments"]["6"], f"my work.{ext}", data)
    assert r["status"] == "Submitted" and r["filename"] == f"my work.{ext}"
    v = query_one("SELECT * FROM submission_versions WHERE submission_id=?", (r["submission_id"],))
    assert v["file_size"] == len(data) and len(v["sha256"]) == 64
    _, back, _ = sub.download_version(school["actors"]["6"], v["id"])
    assert back == data


@pytest.mark.parametrize("name", ["virus.exe", "notes.txt", "page.html", "image.svg", "a.pdf.exe", "script.js", "archive.zip",
                                  "noext", "photo.gif", "macro.docm"])
def test_upload_unsupported_rejected(school, name):
    """C10 | Upload unsupported file | Unsupported or disguised file types are rejected and nothing is saved"""
    with pytest.raises(ValidationError) as e:
        sub.submit_work(school["actors"]["6"], school["assignments"]["6"], name, make_pdf())
    assert "not allowed" in str(e.value)
    assert query_one("SELECT COUNT(*) AS n FROM submissions")["n"] == 0


def test_upload_oversized(school):
    """C11 | Upload oversized file | A file over the size limit is rejected with a clear message"""
    adm.update_settings(school["admin"], {"max_upload_mb": "0.1"})
    big = make_pdf() + b"0" * (max_upload_bytes() + 10)
    with pytest.raises(ValidationError) as e:
        sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "big.pdf", big)
    assert "too large" in str(e.value)
    assert query_one("SELECT COUNT(*) AS n FROM submissions")["n"] == 0


@pytest.mark.parametrize("name,data", [("fake.pdf", b"not a pdf at all"), ("fake.png", b"GIF89a....."),
                                       ("broken.docx", b"PK\x03\x04junkjunk"), ("empty.pdf", b"")])
def test_upload_corrupt(school, name, data):
    """C12 | Corrupted / fake uploads | Files whose content does not match their type are rejected"""
    with pytest.raises(ValidationError):
        sub.submit_work(school["actors"]["6"], school["assignments"]["6"], name, data)


def test_submit_pending_status(school):
    """C13 | Submit work + pending status | Student sees Submitted with upload time; never auto-approved; certificate unavailable"""
    a = school["actors"]["6"]
    r = sub.submit_work(a, school["assignments"]["6"], "w.pdf", make_pdf())
    assert r["uploaded_at"]
    m = ev.student_assignments(a)[0]
    assert m["status_label"] == "Submitted" and not m["can_submit"]
    assert query_one("SELECT status FROM submissions WHERE id=?", (r["submission_id"],))["status"] == "Submitted"
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(a, r["submission_id"])
    assert cert.certificate_for_student_submission(a, r["submission_id"]) is None


def test_feedback_correct_and_resubmit(school):
    """C14 | View feedback, correct and resubmit | Student reads the teacher's feedback, uploads version 2; history keeps version 1"""
    a, t = school["actors"]["7"], school["t1"]
    sub.submit_work(a, school["assignments"]["7"], "v1.pdf", make_pdf("one"))
    sid = sub.list_review_queue(t)[0]["id"]
    sub.review_action(t, sid, "reject", "Please add a conclusion.")
    s = sub.student_submission(a, school["assignments"]["7"])
    assert s["status"] == "Rejected" and s["reviews"][0]["feedback"] == "Please add a conclusion."
    assert ev.student_assignments(a)[0]["can_submit"]
    r = sub.submit_work(a, school["assignments"]["7"], "v2.pdf", make_pdf("two"))
    assert r["version"] == 2 and r["status"] == "Resubmitted"
    s = sub.student_submission(a, school["assignments"]["7"])
    assert [v["original_filename"] for v in s["versions"]] == ["v2.pdf", "v1.pdf"]
    assert sub.download_version(a, s["versions"][1]["id"])[1].startswith(b"%PDF")      # old file still there
    assert query_one("SELECT COUNT(*) AS n FROM submission_versions")["n"] == 2


def test_cannot_upload_while_pending_or_approved(school):
    """C15 | No uploads while waiting or after approval | Pending and approved work cannot be replaced by the student"""
    a, t = school["actors"]["8"], school["t1"]
    sub.submit_work(a, school["assignments"]["8"], "w.pdf", make_pdf())
    with pytest.raises(ValidationError):
        sub.submit_work(a, school["assignments"]["8"], "w2.pdf", make_pdf())
    sid = sub.list_review_queue(t)[0]["id"]
    sub.review_action(t, sid, "approve", "")
    with pytest.raises(ValidationError):
        sub.submit_work(a, school["assignments"]["8"], "w3.pdf", make_pdf())
    assert query_one("SELECT COUNT(*) AS n FROM submission_versions")["n"] == 1


def test_certificate_only_after_approval(school):
    """C16 | Certificate unavailable before approval, available after | Download works only for approved work"""
    a, t = school["actors"]["9"], school["t1"]
    sub.submit_work(a, school["assignments"]["9"], "w.pdf", make_pdf())
    sid = sub.list_review_queue(t)[0]["id"]
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(a, sid)
    sub.review_action(t, sid, "approve", "Great")
    c = cert.generate_for_submission(a, sid)
    name, pdf = cert.get_certificate_pdf(a, c["id"])
    assert pdf.startswith(b"%PDF") and name == f"{c['certificate_code']}.pdf"


def test_deadline_closed_and_not_open(school):
    """C17 | Submission after deadline / closed / not yet open | Each case is refused with a clear message"""
    a, t = school["actors"]["10"], school["t1"]
    aid = school["assignments"]["10"]
    set_deadline(assignment_id=aid)
    with pytest.raises(ValidationError) as e:
        sub.submit_work(a, aid, "late.pdf", make_pdf())
    assert "deadline" in str(e.value).lower()
    assert ev.student_assignments(a)[0]["deadline_passed"] and not ev.student_assignments(a)[0]["can_submit"]
    set_deadline(assignment_id=aid, when="2031-01-01 10:00")
    ev.set_event_status(t, school["event"], "close")
    with pytest.raises(ValidationError) as e:
        sub.submit_work(a, aid, "x.pdf", make_pdf())
    assert "closed" in str(e.value).lower()
    assert ev.student_assignments(a)               # closed events stay visible
    ev.set_event_status(t, school["event"], "reopen")
    from database import transaction
    with transaction() as conn:
        conn.execute("UPDATE events SET opens_on='2099-01-01' WHERE id=?", (school["event"],))
    with pytest.raises(ValidationError) as e:
        sub.submit_work(a, aid, "x.pdf", make_pdf())
    assert "not opened" in str(e.value)
