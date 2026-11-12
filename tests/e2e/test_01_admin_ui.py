import re

import pytest

from e2e import ui


def test_first_run_setup_screen(page, live):
    """G01 | First-run administrator setup in the browser | Setup form creates the admin and opens the dashboard; mismatched passwords are refused"""
    ui.open_app(page, live)
    assert page.get_by_text("Welcome! Let's set up your school").is_visible()
    page.get_by_label("Principal name (printed on certificates)").fill("Mrs. Rao")
    page.get_by_label("Your full name").fill("Head Admin")
    page.get_by_label("Choose a username").fill("admin1")
    page.get_by_label("Choose a password", exact=True).fill("AdminPass1")
    page.get_by_label("Type the password again").fill("Different1")
    page.keyboard.press("Tab")
    ui.click_button(page, "Create administrator account")
    assert page.get_by_text("The two passwords do not match.").is_visible()
    page.get_by_label("Type the password again").fill("AdminPass1")
    page.keyboard.press("Tab")
    ui.click_button(page, "Create administrator account")
    ui.see(page, "Administrator Dashboard")
    ui.assert_clean(page)


def test_admin_login_wrong_and_right(page, live):
    """G02 | Staff login screen | Wrong password shows a friendly message; right password opens the administrator dashboard; logout returns to login"""
    ui.login_staff(page, live, "admin1", "wrongpass1")
    assert page.get_by_text("Incorrect username or password.").is_visible()
    ui.login_staff(page, live, "admin1", "AdminPass1")
    ui.see(page, "Administrator Dashboard")
    assert page.get_by_text("Teacher accounts").is_visible()
    ui.logout(page)
    ui.see(page, "Event & Project Management Portal")
    assert page.get_by_text("Administrator Dashboard").count() == 0


def test_admin_creates_teacher_class_section_student(page, live):
    """G03 | Admin forms: create teacher, class, section, student | Each form saves and the new record appears in its list"""
    ui.login_staff(page, live, "admin1", "AdminPass1")
    ui.nav(page, "👥 User Management")
    page.get_by_role("tab", name=re.compile("Create account")).click()
    ui.field(page, "Full name").fill("Anita Kumar")
    ui.field(page, "Designation (optional)").fill("Science Teacher")
    ui.field(page, "Username").fill("teacher1")
    ui.field(page, "Temporary password").fill("Teacher123")
    page.keyboard.press("Tab")
    ui.click_button(page, "Create account")
    ui.see(page, "Account 'teacher1' created.")
    # duplicate
    page.get_by_role("tab", name=re.compile("Create account")).click()
    ui.field(page, "Full name").fill("Dup")
    ui.field(page, "Username").fill("TEACHER1")
    ui.field(page, "Temporary password").fill("Teacher123")
    page.keyboard.press("Tab")
    ui.click_button(page, "Create account")
    ui.see(page, "This username is already taken")
    # classes and sections
    ui.nav(page, "🏫 Classes & Students")
    page.get_by_label("New class name (for example 6, 7 or Nursery)").fill("6")
    page.keyboard.press("Tab")
    ui.click_button(page, "Add class")
    ui.see(page, "Class added.")
    page.get_by_role("tab", name=re.compile("Sections")).click()
    page.get_by_label("New section name (for example A)").fill("A")
    page.keyboard.press("Tab")
    ui.click_button(page, "Add section")
    ui.see(page, "Section added.")
    page.get_by_role("tab", name=re.compile("Students")).click()
    ui.field(page, "Student full name").fill("Ravi Shankar")
    ui.field(page, "Roll number").fill("12")
    page.keyboard.press("Tab")
    ui.click_button(page, "Add student")
    ui.see(page, "Student added.")
    from database import query_all
    assert [r["full_name"] for r in query_all("SELECT full_name FROM students")] == ["Ravi Shankar"]
    assert [r["username"] for r in query_all("SELECT username FROM users WHERE role='teacher'")] == ["teacher1"]
    assert [r["name"] for r in query_all("SELECT name FROM classes")] == ["6"]
    ui.assert_clean(page)


def test_every_admin_navigation_item(page, live):
    """G04 | Every administrator navigation item | All 11 menu pages open without an error"""
    ui.login_staff(page, live, "admin1", "AdminPass1")
    items = ["🏠 Dashboard", "📅 Events", "🎯 Class Assignments", "📥 Submission Review", "🏅 Certificates",
             "🏫 Classes & Students", "📊 Reports", "👥 User Management", "💾 Backup & Restore", "⚙️ Settings", "🙍 My Profile"]
    for item in items:
        ui.nav(page, item)
        ui.assert_clean(page)
        assert page.locator("h1").first.is_visible(), item
    ui.nav(page, "📊 Reports")
    for tab in page.get_by_role("tab").all():
        tab.click()
        ui.wait_idle(page)
        ui.assert_clean(page)


def test_settings_page_saves(page, live):
    """G05 | Settings page | School name and principal change, persist after a page reload, and appear in the sidebar"""
    ui.login_staff(page, live, "admin1", "AdminPass1")
    ui.nav(page, "⚙️ Settings")
    page.get_by_label("School name").fill("Motilal Public School")
    page.get_by_label("Principal name").fill("Dr. Sundar")
    page.keyboard.press("Tab")
    ui.click_button(page, "Save school settings")
    ui.see(page, "Settings saved.")
    page.screenshot(path=str(__import__("e2e.conftest", fromlist=["SHOTS"]).SHOTS / "admin_settings.png"))
    ui.open_app(page, live)         # a reload starts a fresh session: log in again
    ui.login_staff(page, live, "admin1", "AdminPass1")
    assert page.locator('[data-testid="stSidebar"]').get_by_text("Motilal Public School").is_visible()
    ui.nav(page, "⚙️ Settings")
    assert page.get_by_label("Principal name").input_value() == "Dr. Sundar"


def test_backup_download_and_restore_in_browser(page, live, tmp_path):
    """G06 | Backup and restore through the screen (browser) | Backup is created and downloaded as a valid ZIP; restoring it brings back deleted data; a wrong file is refused"""
    import zipfile
    from database import query_all, transaction
    ui.login_staff(page, live, "admin1", "AdminPass1")
    ui.nav(page, "💾 Backup & Restore")
    assert list(__import__("config").get_paths().backups_dir.glob("backup_auto_*.zip"))     # the app already made an automatic backup
    ui.click_button(page, "Create a backup now")
    ui.see(page, "Backup created: backup_manual_")
    ui.choose_contains(page, "Download a backup to keep it somewhere safe", "backup_manual_")
    with page.expect_download() as dl:
        page.get_by_role("button", name="Download this backup").click()
    zip_path = tmp_path / "downloaded_backup.zip"
    dl.value.save_as(str(zip_path))
    z = zipfile.ZipFile(zip_path)
    assert z.testzip() is None and "database/school_events.db" in z.namelist()
    # damage the data after the backup, then restore through the page
    with transaction() as conn:
        conn.execute("INSERT INTO classes(name, sort_order) VALUES ('Added after backup', 99)")
    assert "Added after backup" in [r["name"] for r in query_all("SELECT name FROM classes")]
    page.get_by_role("tab", name="Restore").click()
    restore_btn = page.get_by_role("button", name="Restore from this backup")
    assert restore_btn.is_disabled()                                     # nothing chosen / confirmed yet
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a backup")
    page.locator('input[type="file"]').last.set_input_files(str(bad))
    page.get_by_text("I understand that current data will be replaced").click()
    ui.field(page, "Type RESTORE to confirm").fill("RESTORE")
    page.keyboard.press("Tab")
    ui.wait_idle(page)
    restore_btn.click()
    ui.see(page, "not a backup file")                                    # wrong file refused ...
    assert "Added after backup" in [r["name"] for r in query_all("SELECT name FROM classes")]   # ... data untouched
    page.locator('input[type="file"]').last.set_input_files(str(zip_path))
    ui.wait_idle(page)
    page.get_by_role("button", name="Restore from this backup").click()
    ui.see(page, "Restore finished.")
    assert "Added after backup" not in [r["name"] for r in query_all("SELECT name FROM classes")]
    assert [r["username"] for r in query_all("SELECT username FROM users WHERE role='teacher'")] == ["teacher1"]
    page.get_by_role("tab", name="Health check").click()
    ui.click_button(page, "Run health check")
    ui.see(page, "The database is healthy.")
    ui.assert_clean(page)


def test_report_csv_download(page, live, tmp_path):
    """G07 | Report CSV export (browser) | The class participation report downloads as a CSV with the real student numbers"""
    ui.login_staff(page, live, "admin1", "AdminPass1")
    ui.nav(page, "📊 Reports")
    page.get_by_role("tab", name="Class participation").click()
    ui.wait_idle(page)
    with page.expect_download() as dl:
        page.get_by_role("button", name="Download CSV").filter(visible=True).first.click()
    text = open(dl.value.path(), encoding="utf-8").read()
    lines = text.strip().splitlines()
    assert lines[0].startswith("Class,Section,Students,Participated,Approved")
    assert any(l.startswith("Class 6,A,1,0,0") for l in lines), lines
