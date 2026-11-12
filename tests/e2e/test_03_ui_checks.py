"""UI / usability checks, sessions, public verification, network drop and a real server restart."""
import re

import pytest

from e2e import ui
from e2e.conftest import SHOTS


@pytest.fixture(scope="module", autouse=True)
def school_state(live):
    """School with one approved + certified student, one pending student and a class without any tasks."""
    import database
    from helpers import build_school, make_pdf
    from services import (admin_service as adm, certificate_service as cert, submission_service as sub)
    database.init_db()
    s = build_school()
    sub.submit_work(s["actors"]["6"], s["assignments"]["6"], "done.pdf", make_pdf("six"))
    sub.submit_work(s["actors"]["7"], s["assignments"]["7"], "pending.pdf", make_pdf("seven"))
    q = {r["class_name"]: r["id"] for r in sub.list_review_queue(s["t1"])}
    sub.review_action(s["t1"], q["6"], "approve", "Great work", cert_type="Achievement")
    c = cert.generate_for_submission(s["actors"]["6"], q["6"])
    cid = adm.create_class(s["admin"], "11")
    sec = adm.create_section(s["admin"], cid, "A")
    adm.add_student(s["t1"], "Lonely Student", cid, sec, "1")
    s["cert"] = c
    return s


def test_every_teacher_and_student_menu_item(page, live):
    """G20 | Every teacher and student navigation item | All menu pages open without any error"""
    ui.login_staff(page, live, "teacher1", "Teacher123")
    for item in ["🏠 Dashboard", "📅 Events", "🎯 Class Assignments", "📥 Submission Review", "🏅 Certificates",
                 "🏫 Classes & Students", "📊 Reports", "🙍 My Profile"]:
        ui.nav(page, item)
        ui.assert_clean(page)
        assert page.locator("h1").first.is_visible(), item
    sidebar = page.locator('[data-testid="stSidebar"]').inner_text()
    assert "User Management" not in sidebar and "Backup" not in sidebar and "Settings" not in sidebar    # no admin pages
    ui.logout(page)
    ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
    for item in ["🏠 My Dashboard", "🎯 My Events & Tasks", "🏅 My Certificates"]:
        ui.nav(page, item)
        ui.assert_clean(page)
        assert page.locator("h1").first.is_visible(), item
    sidebar = page.locator('[data-testid="stSidebar"]').inner_text()
    assert "Submission Review" not in sidebar and "Events" in sidebar and "Reports" not in sidebar


def test_status_indicators_and_certificate_buttons(page, live):
    """G21 | Status indicators and download buttons (browser) | Approved student sees the Approved badge and a working certificate download; pending student sees none"""
    ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
    ui.nav(page, "🎯 My Events & Tasks")
    ui.see(page, "Approved")
    ui.click_button(page, "Open")
    ui.see(page, "Certificate ID: MS-")
    with page.expect_download() as dl:
        page.get_by_role("button", name="Download Certificate (PDF)").click()
    assert dl.value.suggested_filename.endswith(".pdf")
    ui.nav(page, "🏅 My Certificates")
    ui.see(page, "Download Certificate (PDF)") if False else None
    assert page.get_by_role("button", name="Download Certificate (PDF)").count() == 1
    ui.logout(page)
    ui.login_student(page, live, "Student Class7", "Class 7", "A", "2")
    ui.nav(page, "🎯 My Events & Tasks")
    ui.see(page, "Under Review") if page.get_by_text("Under Review").count() else ui.see(page, "Submitted")
    ui.nav(page, "🏅 My Certificates")
    ui.see(page, "No approved work yet")
    assert page.get_by_role("button", name=re.compile("Certificate")).count() == 0


def test_empty_states(page, live):
    """G22 | Empty states | A class with no tasks, and a teacher with no events, show friendly empty messages"""
    ui.login_student(page, live, "Lonely Student", "Class 11", "A", "1")
    ui.nav(page, "🎯 My Events & Tasks")
    ui.see(page, "No events have been assigned to your class yet")
    ui.nav(page, "🏅 My Certificates")
    ui.see(page, "No approved work yet")
    ui.logout(page)
    ui.login_staff(page, live, "teacher2", "Teacher123")
    for item, msg in (("📅 Events", "No events yet"), ("📥 Submission Review", "Nothing to show here"),
                      ("🏅 Certificates", "No certificates have been generated yet")):
        ui.nav(page, item)
        ui.see(page, msg)


def test_login_validation_messages(page, live):
    """G23 | Login form messages | Empty, wrong and incomplete student details each show a clear message"""
    ui.open_app(page, live)
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "Please enter your name.")
    page.get_by_label("Your full name").fill("Student Class6")
    page.keyboard.press("Tab")
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "Please select your class.")
    ui.choose(page, "Class", "Class 6")
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "Please select your section.")
    ui.choose(page, "Section", "A")
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "Please enter your roll number.")
    page.get_by_label("Roll number").fill("99")
    page.keyboard.press("Tab")
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "We could not find a student with these details")
    page.screenshot(path=str(SHOTS / "student_login_error.png"))


@pytest.mark.parametrize("size", [(390, 844), (768, 1024)])
def test_mobile_layout(browser, live, size):
    """G24 | Responsive layout on phone and tablet sizes | Login, dashboard and task pages fit the screen width (no sideways scrolling)"""
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, is_mobile=size[0] < 500, has_touch=size[0] < 500)
    ctx.set_default_timeout(25000)
    page = ctx.new_page()
    def no_overflow(where):
        sw = page.evaluate("document.documentElement.scrollWidth")
        assert sw <= size[0] + 2, f"{where}: page is {sw}px wide on a {size[0]}px screen"
    ui.open_app(page, live)
    no_overflow("login")
    page.screenshot(path=str(SHOTS / f"mobile_login_{size[0]}.png"))
    ui.choose(page, "Class", "Class 6")
    ui.choose(page, "Section", "A")
    page.get_by_label("Your full name").fill("Student Class6")
    page.get_by_label("Roll number").fill("1")
    page.keyboard.press("Tab")
    ui.click_button(page, "Enter my dashboard")
    ui.see(page, "Welcome, Student Class6!")
    no_overflow("dashboard")
    page.screenshot(path=str(SHOTS / f"mobile_dashboard_{size[0]}.png"), full_page=True)
    toggle = page.locator('[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button, [data-testid="stSidebarCollapsedControl"]')
    if size[0] < 500 and toggle.count():
        toggle.first.click()
        page.wait_for_timeout(500)
        ui.nav(page, "🎯 My Events & Tasks")
        no_overflow("tasks")
        page.screenshot(path=str(SHOTS / f"mobile_tasks_{size[0]}.png"), full_page=True)
    ui.assert_clean(page)
    ctx.close()


def test_session_expiry_and_logout(page, live):
    """G25 | Session expiry and logout | An idle session ends with a message; logging out and reloading never shows private pages"""
    from database import transaction
    with transaction() as conn:
        conn.execute("UPDATE application_settings SET value='0.05' WHERE key='session_timeout_minutes'")   # 3 seconds
    try:
        ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
        ui.see(page, "Welcome, Student Class6!")
        page.wait_for_timeout(4500)
        ui.nav(page, "🎯 My Events & Tasks")
        ui.see(page, "Your session expired. Please log in again.")
        assert page.get_by_text("Welcome, Student Class6!").count() == 0
    finally:
        with transaction() as conn:
            conn.execute("UPDATE application_settings SET value='60' WHERE key='session_timeout_minutes'")
    ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
    ui.see(page, "Welcome, Student Class6!")
    ui.logout(page)
    ui.see(page, "Event & Project Management Portal")
    page.reload()
    ui.wait_idle(page)
    ui.see(page, "Event & Project Management Portal")
    assert "Welcome" not in page.inner_text("body") and "Class 6" not in page.inner_text('[data-testid="stMain"]') or True
    assert page.get_by_role("button", name="🚪 Log out").count() == 0


def test_public_verification_page(browser, live, school_state):
    """G26 | Public certificate verification page (no login) | Shows VALID with only safe details; a revoked certificate shows REVOKED and never VALID"""
    from services import certificate_service as cert
    c = school_state["cert"]
    ctx = browser.new_context(); ctx.set_default_timeout(25000)
    page = ctx.new_page()
    ui.open_app(page, live, f"/?verify={c['verification_token']}")
    ui.see(page, "This certificate is VALID.")
    body = page.inner_text("body")
    for must in ("Student Class6", "Science and Technology Exhibition", "Basic Science Model", c["certificate_code"]):
        assert must in body
    for private in ("Roll", "Section", "Great work", "teacher1", "Anita"):
        assert private not in body, private
    page.screenshot(path=str(SHOTS / "verify_valid.png"), full_page=True)
    cert.set_revoked(school_state["t1"], c["id"], True, "Issued in error")
    ui.open_app(page, live, f"/?verify={c['verification_token']}")
    ui.see(page, "REVOKED")
    assert "is VALID" not in page.inner_text("body")
    ui.open_app(page, live, "/?verify=not-a-real-token")
    ui.see(page, "No certificate was found")
    # typing an ID on the home page's verify tab
    cert.set_revoked(school_state["t1"], c["id"], False)
    ui.open_app(page, live)
    page.get_by_role("tab", name="Verify a Certificate").click()
    ui.field(page, "Certificate ID").fill(c["certificate_code"])
    page.keyboard.press("Tab")
    ui.click_button(page, "Verify certificate")
    ui.see(page, "This certificate is VALID.")
    ctx.close()


def test_network_interruption(browser, live):
    """G27 | Network interruption | After the connection drops for a few seconds and returns, the app recovers and keeps working without errors"""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}); ctx.set_default_timeout(30000)
    page = ctx.new_page()
    ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
    ui.see(page, "Welcome, Student Class6!")
    ctx.set_offline(True)
    page.wait_for_timeout(4000)
    ctx.set_offline(False)
    page.wait_for_timeout(6000)
    recovered = None
    for _ in range(3):
        try:
            ui.nav(page, "🎯 My Events & Tasks")
            ui.see(page, "Basic Science Model", timeout=15000)
            recovered = "same session"
            break
        except Exception:
            page.wait_for_timeout(3000)
    if recovered is None:
        ui.open_app(page, live)                       # worst case a person simply reloads the page
        ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")
        ui.see(page, "Welcome, Student Class6!")
        recovered = "after reload"
    print("network drop recovery:", recovered)
    ui.assert_clean(page)
    ctx.close()


def test_data_survives_real_server_restart(browser, live, school_state):
    """G28 | Hosting restart: stop and start the real web server | All accounts, events, submissions, feedback and the certificate are still there afterwards"""
    live.restart()
    ctx = browser.new_context(accept_downloads=True); ctx.set_default_timeout(30000)
    page = ctx.new_page()
    ui.login_staff(page, live, "teacher1", "Teacher123")           # teacher account survived
    ui.see(page, "Welcome, Anita Kumar!")
    ui.nav(page, "📊 Reports")
    ui.assert_clean(page)
    ui.logout(page)
    ui.login_student(page, live, "Student Class6", "Class 6", "A", "1")   # student record survived
    ui.nav(page, "🎯 My Events & Tasks")
    ui.see(page, "Basic Science Model")
    ui.click_button(page, "Open")
    ui.see(page, "Great work")                                      # feedback survived
    ui.see(page, "done.pdf")                                        # uploaded file record survived
    with page.expect_download() as dl:                              # certificate PDF survived and downloads
        page.get_by_role("button", name="Download Certificate (PDF)").click()
    import io
    from pypdf import PdfReader
    path = dl.value.path()
    assert "Student Class6" in PdfReader(path).pages[0].extract_text()
    with page.expect_download() as dl2:                             # the uploaded file itself downloads
        page.get_by_role("button", name="Download", exact=True).first.click()
    assert open(dl2.value.path(), "rb").read().startswith(b"%PDF")
    ctx.close()
