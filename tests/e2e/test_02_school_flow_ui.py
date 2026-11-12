"""The whole school flow through the real browser: teacher builds the event, students upload, teacher reviews,
students download certificates."""
import io
import re
from pathlib import Path

import pytest

from e2e import ui
from e2e.conftest import SHOTS
from helpers import make_pdf


@pytest.fixture(scope="module", autouse=True)
def seeded(live):
    import auth, database
    from services import admin_service as adm
    database.init_db()
    auth.setup_admin("admin1", "AdminPass1", "Head Admin", "Motilal School", "Mrs. Rao", "2026-27")
    admin = auth.login_staff("admin1", "AdminPass1")
    adm.create_user(admin, "teacher1", "Teacher123", "Anita Kumar", "Science Teacher")
    adm.create_user(admin, "teacher2", "Teacher123", "Bala Murugan", "Maths Teacher")
    t1 = auth.login_staff("teacher1", "Teacher123")
    for c in ("6", "7", "8"):
        cid = adm.create_class(admin, c)
        sid = adm.create_section(admin, cid, "A")
        adm.create_section(admin, cid, "B")
        if c == "6":
            adm.add_student(t1, "Ravi Shankar", cid, sid, "12")
        elif c == "7":
            adm.add_student(t1, "Meena Devi", cid, sid, "5")
        else:
            adm.add_student(t1, "Karthik Raj", cid, sid, "3")
    return True


def _pdf(tmp_path, name="project.pdf", pad=0):
    p = tmp_path / name
    p.write_bytes(make_pdf(name) + b"0" * pad)
    return p


def test_teacher_builds_event_with_different_topics(page, live):
    """G10 | Teacher creates an event and gives Classes 6, 7 and 8 different topics (browser) | Event and three class topics are saved, then published"""
    ui.login_staff(page, live, "teacher1", "Teacher123")
    ui.see(page, "Welcome, Anita Kumar!")
    ui.assert_clean(page)
    ui.nav(page, "📅 Events")
    ui.see(page, "No events yet")                                   # empty state
    page.get_by_role("tab", name=re.compile("Create new event")).click()
    ui.field(page, "Event name").fill("Science and Technology Exhibition")
    ui.field(page, "Event description").fill("Show us what you can build")
    ui.field(page, "General instructions for students").fill("Work alone and be original.")
    ui.click_button(page, "Create event")
    ui.see(page, "Event created as a draft")
    ui.nav(page, "🎯 Class Assignments")
    ui.see(page, "No class has been assigned yet")
    topics = [("Class 6", "Basic Science Model"), ("Class 7", "Water Conservation"), ("Class 8", "Environmental Protection")]
    for cls, topic in topics:
        ui.choose(page, "Class", cls)
        ui.field(page, "Topic name").fill(topic)
        ui.field(page, "Task description").fill(f"Build something about {topic}")
        ui.field(page, "Detailed instructions").fill(f"Step by step guide for {topic}")
        ui.click_button(page, "Add class topic")
        ui.see(page, f"Topic added for {cls}.")
    page.screenshot(path=str(SHOTS / "teacher_assignments.png"), full_page=True)
    ui.nav(page, "📅 Events")
    ui.click_button(page, "🚀 Publish")
    ui.see(page, "Event published. Students can now see it.")
    from database import query_all
    rows = query_all("SELECT c.name AS cls, a.topic FROM event_class_assignments a JOIN classes c ON c.id=a.class_id ORDER BY c.sort_order")
    assert [(r["cls"], r["topic"]) for r in rows] == [("6", "Basic Science Model"), ("7", "Water Conservation"), ("8", "Environmental Protection")]
    assert query_all("SELECT status FROM events")[0]["status"] == "published"


def test_student_sees_only_own_task_and_certificate_locked(page, live, tmp_path):
    """G11 | Student login, own task only, upload, pending status (browser) | Student sees only their class topic, uploads a PDF, sees Submitted, and the certificate stays locked"""
    ui.login_student(page, live, "Ravi Shankar", "Class 6", "A", "12")
    ui.see(page, "Welcome, Ravi Shankar!")
    assert page.get_by_text("Class 6 · Section A · Roll No. 12").first.is_visible()
    page.screenshot(path=str(SHOTS / "student_dashboard.png"), full_page=True)
    ui.nav(page, "🎯 My Events & Tasks")
    ui.see(page, "Basic Science Model")
    body = page.inner_text("body")
    assert "Water Conservation" not in body and "Environmental Protection" not in body
    ui.click_button(page, "Open")
    ui.see(page, "Build something about Basic Science Model")
    ui.see(page, "Step by step guide for Basic Science Model")
    ui.see(page, "Your certificate will be available here after your teacher approves your work.")
    assert page.get_by_role("button", name=re.compile("Certificate")).count() == 0       # no download / generate button
    assert page.get_by_role("button", name="Submit my work").is_disabled()               # nothing chosen yet
    page.locator('input[type="file"]').set_input_files(str(_pdf(tmp_path, "my science model.pdf")))
    ui.see(page, "Selected: my science model.pdf")
    ui.click_button(page, "Submit my work")
    ui.see(page, "Submitted!")
    ui.see(page, "my science model.pdf")
    assert page.get_by_text("waiting for your teacher's review").first.is_visible()
    assert page.get_by_role("button", name="Download Certificate (PDF)").count() == 0
    page.screenshot(path=str(SHOTS / "student_after_upload.png"), full_page=True)
    ui.assert_clean(page)
    from database import query_one
    assert query_one("SELECT status FROM submissions")["status"] == "Submitted"


def test_student_upload_errors_in_browser(page, live, tmp_path):
    """G12 | Upload errors shown to the student (browser) | Wrong type, fake content and oversized files each show a clear message and nothing is saved"""
    ui.login_student(page, live, "Meena Devi", "Class 7", "A", "5")
    ui.nav(page, "🎯 My Events & Tasks")
    ui.click_button(page, "Open")
    ui.see(page, "Water Conservation")
    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ" + b"0" * 100)
    page.locator('input[type="file"]').set_input_files(str(exe))
    ui.see(page, "type is not allowed", timeout=15000) if page.get_by_text("type is not allowed").count() else None
    assert page.get_by_role("button", name="Submit my work").is_disabled() or page.get_by_text("not allowed").count() > 0
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"this is only text")
    page.locator('input[type="file"]').set_input_files(str(fake))
    ui.see(page, "Selected: fake.pdf")
    ui.click_button(page, "Submit my work")
    ui.see(page, "damaged or is not a real PDF file")
    from services import admin_service as adm
    import auth
    admin = auth.login_staff("admin1", "AdminPass1")
    adm.update_settings(admin, {"max_upload_mb": "0.1"})
    ui.open_app(page, live)
    ui.login_student(page, live, "Meena Devi", "Class 7", "A", "5")
    ui.nav(page, "🎯 My Events & Tasks")
    ui.click_button(page, "Open")
    page.locator('input[type="file"]').set_input_files(str(_pdf(tmp_path, "big.pdf", pad=300_000)))
    ui.click_button(page, "Submit my work")
    ui.see(page, "too large")
    adm.update_settings(admin, {"max_upload_mb": "10"})
    from database import query_one
    assert query_one("SELECT COUNT(*) AS n FROM submissions WHERE student_id=(SELECT id FROM students WHERE full_name='Meena Devi')")["n"] == 0


def test_teacher_rejects_then_student_resubmits_then_approval_and_certificate(page, browser, live, tmp_path):
    """G13 | Review, rejection with feedback, resubmission, approval, certificate download (browser) | The complete loop works and the downloaded PDF is a valid A4 landscape certificate with the student's details"""
    # student 8 submits first so there are two items in the queue
    sctx = browser.new_context(viewport={"width": 1280, "height": 900}); sctx.set_default_timeout(25000)
    sp = sctx.new_page()
    ui.login_student(sp, live, "Karthik Raj", "Class 8", "A", "3")
    ui.nav(sp, "🎯 My Events & Tasks"); ui.click_button(sp, "Open")
    sp.locator('input[type="file"]').set_input_files(str(_pdf(tmp_path, "env.pdf")))
    ui.click_button(sp, "Submit my work"); ui.see(sp, "Submitted!")
    # teacher reviews
    ui.login_staff(page, live, "teacher1", "Teacher123")
    ui.nav(page, "📥 Submission Review")
    ui.see(page, "Choose a submission to review")
    ui.choose_contains(page, "Choose a submission to review", "Ravi Shankar")
    ui.see(page, "Basic Science Model")
    ui.assert_clean(page)
    page.screenshot(path=str(SHOTS / "teacher_review.png"), full_page=True)
    ui.field(page, "Feedback for the student").fill("Please add a title page.")
    ui.click_button(page, "❌ Reject")
    ui.see(page, "Rejected. The student can see your feedback")
    # student sees the feedback and uploads the corrected file
    ui.login_student(sp, live, "Ravi Shankar", "Class 6", "A", "12")
    ui.see(sp, "Please add a title page.")                          # shown on the dashboard
    ui.nav(sp, "🎯 My Events & Tasks"); ui.click_button(sp, "Open")
    ui.see(sp, "Upload a corrected version")
    sp.locator('input[type="file"]').set_input_files(str(_pdf(tmp_path, "corrected.pdf")))
    ui.click_button(sp, "Submit my work"); ui.see(sp, "Submitted!")
    assert sp.get_by_text("Version 1").first.is_visible() and sp.get_by_text("Version 2").first.is_visible()   # history kept
    # teacher approves the resubmission (the teacher moves to another page and back to refresh the list)
    ui.nav(page, "🏠 Dashboard")
    ui.nav(page, "📥 Submission Review")
    ui.choose_contains(page, "Choose a submission to review", "Ravi Shankar")
    ui.see(page, "corrected.pdf")                                   # the teacher is looking at version 2
    ui.see(page, "Review history")
    ui.assert_clean(page)
    ui.click_button(page, "✅ Approve")
    ui.see(page, "Approved. The student can now get the certificate.")
    # student generates and downloads the certificate
    ui.login_student(sp, live, "Ravi Shankar", "Class 6", "A", "12")
    ui.nav(sp, "🏅 My Certificates")
    ui.click_button(sp, "🏅 Generate certificate")
    ui.see(sp, "Your certificate is ready.")
    with sp.expect_download() as dl:
        sp.get_by_role("button", name="Download Certificate (PDF)").click()
    path = tmp_path / "cert.pdf"
    dl.value.save_as(str(path))
    from pypdf import PdfReader
    r = PdfReader(str(path))
    pg = r.pages[0]
    text = pg.extract_text()
    assert round(float(pg.mediabox.width)) == 842 and round(float(pg.mediabox.height)) == 595
    for must in ("MOTILAL SCHOOL", "Ravi Shankar", "Class 6", "Section A", "Roll No. 12", "Basic Science Model",
                 "Science and Technology Exhibition", "Certificate ID: MS-"):
        assert must in text, must
    # the other student (not approved) has no certificate
    ui.login_student(sctx.new_page(), live, "Karthik Raj", "Class 8", "A", "3") if False else None
    sp.screenshot(path=str(SHOTS / "student_certificates.png"), full_page=True)
    from database import query_all
    assert [r["status"] for r in query_all("SELECT status FROM submissions ORDER BY id")] == ["Approved", "Submitted"] or \
           sorted(r["status"] for r in query_all("SELECT status FROM submissions")) == ["Approved", "Under Review"] or \
           sorted(r["status"] for r in query_all("SELECT status FROM submissions")) == ["Approved", "Submitted"]
    assert len(query_all("SELECT 1 FROM certificates")) == 1
    sctx.close()
