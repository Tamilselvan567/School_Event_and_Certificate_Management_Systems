"""H: failures and unusual situations."""
import threading

import pytest

import auth
from database import query_all, query_one
from helpers import FUTURE, SAMPLES, make_pdf
from integration.conftest_helpers import set_deadline
from services import admin_service as adm, certificate_service as cert, event_service as ev, submission_service as sub
from utils.errors import AppError, PermissionDenied, ValidationError


def test_duplicate_student_identities(school):
    """H01 | Duplicate student identities | Same class+section+roll is refused; same names with different rolls log in correctly; deactivated roll can be reused"""
    t, c, sec = school["t1"], school["classes"]["6"], school["sections"]["6"]["A"]
    with pytest.raises(ValidationError):
        adm.add_student(t, "Another Child", c, sec, "1")
    with pytest.raises(ValidationError):
        adm.add_student(t, "Another Child", c, sec, " 1 ")
    a = adm.add_student(t, "Raj Kumar", c, sec, "21")
    b = adm.add_student(t, "Raj Kumar", c, sec, "22")
    assert auth.login_student("Raj Kumar", c, sec, "21")["id"] == a
    assert auth.login_student("raj kumar", c, sec, "22")["id"] == b
    adm.add_student(t, "Raj Kumar", c, school["sections"]["6"]["B"], "21")        # other section: fine
    adm.update_student(t, a, "Raj Kumar", c, sec, "21", False)
    new = adm.add_student(t, "New Raj", c, sec, "21")                              # roll reusable after deactivation
    assert auth.login_student("New Raj", c, sec, "21")["id"] == new
    with pytest.raises(ValidationError):
        adm.update_student(t, a, "Raj Kumar", c, sec, "21", True)                  # cannot reactivate into a clash
    with pytest.raises(ValidationError):
        adm.add_student(t, "Wrong Section", c, school["sections"]["7"]["A"], "55")


def test_duplicate_teacher_username(school):
    """H02 | Duplicate teacher usernames | Refused regardless of letter case"""
    for name in ("teacher1", "TEACHER1", "Teacher1"):
        with pytest.raises(ValidationError):
            adm.create_user(school["admin"], name, "Passw0rd123", "Dup", "")
    assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 3


def test_empty_forms(school):
    """H03 | Empty forms | Blank input gives friendly validation errors, never a crash"""
    a, t = school["admin"], school["t1"]
    for call in (lambda: adm.create_user(a, "", "", "", ""), lambda: adm.create_class(t, "  "), lambda: adm.create_section(t, school["classes"]["6"], ""),
                 lambda: adm.add_student(t, "", 1, 1, ""), lambda: adm.create_year(t, ""), lambda: adm.update_settings(a, {"school_name": " "}),
                 lambda: ev.create_event(t, {}), lambda: ev.create_assignment(t, school["event"], {}),
                 lambda: sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "", b""),
                 lambda: auth.login_student("", None, None, ""), lambda: auth.login_staff("", ""),
                 lambda: auth.setup_admin("", "", "", "", "", "")):
        with pytest.raises(AppError):
            call()


def test_invalid_and_past_dates(school):
    """H04 | Invalid dates and past deadlines | Impossible dates, reversed ranges and past deadlines are refused"""
    t = school["t1"]
    base = dict(name="E", description="", category="Art", academic_year_id=school["year"])
    for kw in (dict(opens_on="2026-02-30", deadline=FUTURE), dict(opens_on="2020-01-01", deadline="2020-01-01 09:00"),
               dict(opens_on="2031-01-01", deadline="2030-01-01 10:00"), dict(opens_on="abc", deadline=FUTURE),
               dict(opens_on="2020-01-01", deadline="2030-01-01 25:00"), dict(opens_on="", deadline="")):
        with pytest.raises(ValidationError):
            ev.create_event(t, {**base, **kw})


def test_submission_after_deadline(school):
    """H05 | Submission after the deadline | Refused with a clear message; earlier work stays safe"""
    a = school["actors"]["8"]
    sub.submit_work(a, school["assignments"]["8"], "ok.pdf", make_pdf())
    sid = sub.list_review_queue(school["t1"])[0]["id"]
    sub.review_action(school["t1"], sid, "reject", "again")
    set_deadline(assignment_id=school["assignments"]["8"])
    with pytest.raises(ValidationError) as e:
        sub.submit_work(a, school["assignments"]["8"], "late.pdf", make_pdf())
    assert "deadline" in str(e.value).lower()
    assert query_one("SELECT COUNT(*) AS n FROM submission_versions")["n"] == 1


def test_event_without_assignments_and_empty_assignment(school):
    """H06 | Event with no assignments / assignment with no students | Publishing an empty event is refused; an assignment with no students shows 0 students"""
    t = school["t1"]
    eid = ev.create_event(t, dict(name="Empty", description="", category="Art", opens_on="2020-01-01", deadline=FUTURE, academic_year_id=school["year"]))
    with pytest.raises(ValidationError):
        ev.set_event_status(t, eid, "publish")
    cid = adm.create_class(t, "12")
    adm.create_section(t, cid, "A")
    aid = ev.create_assignment(t, eid, dict(class_id=cid, topic="Nobody's topic"))
    ev.set_event_status(t, eid, "publish")
    row = [r for r in ev.list_assignments(t, eid) if r["id"] == aid][0]
    assert row["student_count"] == 0 and row["submission_count"] == 0
    from services import report_service as rep
    assert [r for r in rep.event_participation(t) if r["event"] == "Empty"][0]["participation_pct"] == 0.0


def test_simultaneous_submissions(school):
    """H07 | Two (or five) students submitting at the same moment | Every submission is saved with its own file; nothing is lost or mixed up"""
    errors, results = [], {}

    def go(cls):
        try:
            results[cls] = sub.submit_work(school["actors"][cls], school["assignments"][cls], f"{cls}.pdf", make_pdf("simul" + cls))
        except Exception as exc:       # noqa
            errors.append(repr(exc))
    threads = [threading.Thread(target=go, args=(c,)) for c in ("6", "7", "8", "9", "10")]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors and len(results) == 5
    assert query_one("SELECT COUNT(*) AS n FROM submissions")["n"] == 5
    for c in ("6", "7", "8", "9", "10"):
        vid = query_one("SELECT v.id FROM submission_versions v JOIN submissions s ON s.id=v.submission_id JOIN students st ON st.id=s.student_id WHERE st.full_name=?", (f"Student Class{c}",))["id"]
        assert f"simul{c}".encode() in sub.download_version(school["actors"][c], vid)[1]


def test_same_student_double_click_upload(school):
    """H08 | One student double-clicking Submit | Exactly one upload is accepted; no duplicate version or stray file"""
    from config import get_paths
    res, errs = [], []

    def go():
        try:
            res.append(sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "x.pdf", make_pdf()))
        except ValidationError as exc:
            errs.append(exc)
    th = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in th]; [t.join() for t in th]
    assert len(res) == 1 and len(errs) == 3
    assert query_one("SELECT COUNT(*) AS n FROM submission_versions")["n"] == 1
    assert len([p for p in get_paths().submissions_dir.rglob("*") if p.is_file()]) == 1


def test_review_twice_and_double_click_approval(school):
    """H09 | Reviewing the same submission twice / double-clicking Approve | Only the first decision counts; the second changes nothing"""
    t = school["t1"]
    sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "x.pdf", make_pdf())
    sid = sub.list_review_queue(t)[0]["id"]
    outcomes = []

    def go():
        try:
            outcomes.append(sub.review_action(t, sid, "approve", "ok")["status"])
        except ValidationError as exc:
            outcomes.append("refused")
    th = [threading.Thread(target=go) for _ in range(5)]
    [x.start() for x in th]; [x.join() for x in th]
    assert outcomes.count("Approved") == 1 and outcomes.count("refused") == 4
    assert query_one("SELECT COUNT(*) AS n FROM reviews WHERE action='approve'")["n"] == 1
    with pytest.raises(ValidationError):
        sub.review_action(t, sid, "reject", "changed my mind")
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] == "Approved"


def test_revert_approval_revokes_certificate(school):
    """H10 | Undoing an approval | Status returns to review, any certificate is revoked, the student can no longer download it"""
    t = school["t1"]
    sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "x.pdf", make_pdf())
    sid = sub.list_review_queue(t)[0]["id"]
    sub.review_action(t, sid, "approve", "")
    c = cert.generate_for_submission(school["actors"]["6"], sid)
    with pytest.raises(ValidationError):
        sub.revert_approval(t, sid, "")
    sub.revert_approval(t, sid, "Approved the wrong file")
    assert query_one("SELECT status FROM submissions WHERE id=?", (sid,))["status"] == "Under Review"
    assert cert.verify(c["certificate_code"])["valid"] is False
    with pytest.raises(PermissionDenied):
        cert.get_certificate_pdf(school["actors"]["6"], c["id"])
    with pytest.raises(PermissionDenied):
        cert.generate_for_submission(school["actors"]["6"], sid)                   # not approved any more
    sub.review_action(t, sid, "approve", "now correct")
    with pytest.raises(ValidationError):
        cert.set_revoked(t, c["id"], True, "") 
    cert.set_revoked(t, c["id"], False)
    assert cert.verify(c["certificate_code"])["valid"]


def test_repeated_certificate_generation(school):
    """H11 | Repeated / simultaneous certificate generation | Always the same single certificate and ID; admin regenerate keeps the ID"""
    t = school["t1"]
    sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "x.pdf", make_pdf())
    sid = sub.list_review_queue(t)[0]["id"]
    sub.review_action(t, sid, "approve", "")
    out, errs = [], []

    def go():
        try:
            out.append(cert.generate_for_submission(school["actors"]["6"], sid)["certificate_code"])
        except Exception as exc:        # noqa
            errs.append(repr(exc))
    th = [threading.Thread(target=go) for _ in range(5)]
    [x.start() for x in th]; [x.join() for x in th]
    assert not errs and len(set(out)) == 1
    assert query_one("SELECT COUNT(*) AS n FROM certificates")["n"] == 1
    cid = query_one("SELECT id FROM certificates")["id"]
    before = query_one("SELECT certificate_code, regenerated_count FROM certificates")
    cert.regenerate(school["admin"], cid)
    after = query_one("SELECT certificate_code, regenerated_count FROM certificates")
    assert after["certificate_code"] == before["certificate_code"] and after["regenerated_count"] == 1
    with pytest.raises(PermissionDenied):
        cert.regenerate(t, cid)


def test_certificate_logo_and_signatures(school):
    """H12 | Logo, signature images and colours on the certificate | Configured images and colours are used without breaking the PDF"""
    from helpers import make_png
    from pypdf import PdfReader
    import io
    adm.save_school_logo(school["admin"], "logo.png", make_png((60, 60), (10, 90, 200)))
    adm.save_principal_signature(school["admin"], "sig.png", make_png((80, 30), (0, 0, 0)))
    adm.save_my_signature(school["t1"], "t.png", make_png((70, 35), (30, 30, 120)))
    adm.update_settings(school["admin"], {"cert_primary_color": "#7F1D1D", "cert_footer_text": "Be curious", "principal_name": "Dr. Sundar"})
    sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "x.pdf", make_pdf())
    sid = sub.list_review_queue(school["t1"])[0]["id"]
    sub.review_action(school["t1"], sid, "approve", "", cert_type="Achievement")
    c = cert.generate_for_submission(school["actors"]["6"], sid)
    pdf = cert.get_certificate_pdf(school["actors"]["6"], c["id"])[1]
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    text = page.extract_text()
    assert "Dr. Sundar" in text and "Be curious" in text and "Certificate of Achievement" in text
    assert len(list(page.images)) == 4                                   # logo + teacher signature + principal signature + QR code
    assert cert.sample_certificate_pdf(school["admin"]).startswith(b"%PDF")


def test_student_names_with_unicode(school):
    """H13 | Names in Tamil / Kannada letters | Non-English names work for login, review and certificates"""
    t = school["t1"]
    c, sec = school["classes"]["6"], school["sections"]["6"]["B"]
    adm.add_student(t, "தமிழ் செல்வன்", c, sec, "31")
    adm.add_student(t, "ಕನ್ನಡ ವಿದ್ಯಾರ್ಥಿ", c, sec, "32")
    for nm, roll in (("தமிழ் செல்வன்", "31"), ("ಕನ್ನಡ ವಿದ್ಯಾರ್ಥಿ", "32")):
        a = auth.login_student(nm, c, sec, roll)
        assert a["name"] == nm
    assert len(adm.list_students(t, search="தமிழ்")) == 1
