import pytest

import auth
from database import query_all, query_one, transaction
from services import admin_service as adm, backup_service, certificate_service
from services.settings_store import get_setting
from utils.errors import AppError, PermissionDenied, ValidationError


def test_initial_setup(env):
    """A01 | Initial administrator setup | First run asks for setup; after it, setup is closed and settings are saved"""
    assert auth.needs_setup()
    a = auth.setup_admin("boss", "BossPass1", "The Boss", "Motilal School", "Mrs. Rao", "2026-27")
    assert a["role"] == "admin" and not auth.needs_setup()
    assert get_setting("principal_name") == "Mrs. Rao"
    with pytest.raises(PermissionDenied):
        auth.setup_admin("boss2", "BossPass2", "Other", "X", "Y", "2026-27")
    assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 1


def test_setup_code(env, monkeypatch):
    """A02 | Setup code on public sites | When MSES_SETUP_CODE is set, setup needs the right code"""
    monkeypatch.setenv("MSES_SETUP_CODE", "letmein")
    assert auth.setup_code_required()
    with pytest.raises(PermissionDenied):
        auth.setup_admin("boss", "BossPass1", "The Boss", "S", "P", "2026-27", "wrong")
    assert auth.needs_setup()
    auth.setup_admin("boss", "BossPass1", "The Boss", "S", "P", "2026-27", "letmein")
    assert not auth.needs_setup()


def test_admin_login_and_wrong_password(school):
    """A03 | Admin login + incorrect password | Right password logs in; wrong password and unknown user give the same generic message"""
    assert auth.login_staff("admin1", "AdminPass1")["role"] == "admin"
    with pytest.raises(AppError) as e1:
        auth.login_staff("admin1", "WrongPass9")
    with pytest.raises(AppError) as e2:
        auth.login_staff("nobody", "WrongPass9")
    assert str(e1.value) == str(e2.value) == "Incorrect username or password."
    with pytest.raises(ValidationError):
        auth.login_staff("", "")


def test_account_lockout(school):
    """A04 | Brute-force protection | After 5 wrong passwords the account is locked even for the right password"""
    for _ in range(5):
        with pytest.raises(AppError):
            auth.login_staff("teacher1", "Wrong12345")
    with pytest.raises(AppError) as e:
        auth.login_staff("teacher1", "Teacher123")
    assert "Too many" in str(e.value)
    adm.reset_password(school["admin"], school["t1"]["id"], "Fresh12345")  # admin reset unlocks
    assert auth.login_staff("teacher1", "Fresh12345")["role"] == "teacher"


def test_create_teacher_and_duplicates(school):
    """A05 | Create teacher | Teacher is created; duplicate username (any letter case) is refused; weak password refused"""
    uid = adm.create_user(school["admin"], "newteach", "Newteach1", "New Teacher", "Art")
    assert auth.login_staff("newteach", "Newteach1")["id"] == uid
    with pytest.raises(ValidationError):
        adm.create_user(school["admin"], "NEWTEACH", "Another123", "Dup", "")
    with pytest.raises(ValidationError):
        adm.create_user(school["admin"], "weakone", "abc", "Weak", "")


def test_edit_teacher(school):
    """A06 | Edit teacher | Name and designation change and persist"""
    adm.update_user(school["admin"], school["t1"]["id"], "Anita K. Sharma", "HOD Science")
    row = query_one("SELECT full_name, designation FROM users WHERE id=?", (school["t1"]["id"],))
    assert row == {"full_name": "Anita K. Sharma", "designation": "HOD Science"}


def test_deactivate_teacher(school):
    """A07 | Deactivate teacher | Cannot log in, and an already-open session stops working immediately"""
    adm.set_user_active(school["admin"], school["t2"]["id"], False)
    with pytest.raises(AppError):
        auth.login_staff("teacher2", "Teacher123")
    with pytest.raises(PermissionDenied):
        auth.verify_actor(school["t2"])
    adm.set_user_active(school["admin"], school["t2"]["id"], True)
    assert auth.login_staff("teacher2", "Teacher123")


def test_reset_password(school):
    """A08 | Reset teacher password | Old password stops working, new one works"""
    adm.reset_password(school["admin"], school["t1"]["id"], "BrandNew123")
    with pytest.raises(AppError):
        auth.login_staff("teacher1", "Teacher123")
    assert auth.login_staff("teacher1", "BrandNew123")


def test_cannot_remove_last_admin(school):
    """A09 | Admin safety | An administrator cannot deactivate themselves or the last administrator"""
    with pytest.raises(ValidationError):
        adm.set_user_active(school["admin"], school["admin"]["id"], False)


def test_classes_sections_years(school):
    """A10 | Classes, sections, academic years | Add, duplicate refusal, edit, deactivate and hide from login lists"""
    admin = school["admin"]
    cid = adm.create_class(admin, "11")
    with pytest.raises(ValidationError):
        adm.create_class(admin, "11")
    sid = adm.create_section(admin, cid, "Science")
    with pytest.raises(ValidationError):
        adm.create_section(admin, cid, "science")
    adm.update_class(admin, cid, "XI", 11, True)
    assert "XI" in [c["name"] for c in adm.list_classes()]
    adm.update_section(admin, sid, "Science-1", False)
    assert sid not in [s["id"] for s in adm.list_sections(cid, include_inactive=False)]
    adm.update_class(admin, cid, "XI", 11, False)
    assert cid not in [c["id"] for c in adm.list_classes(include_inactive=False)]
    y = adm.create_year(admin, "2027-28", "2027-04-01", "2028-03-31")
    with pytest.raises(ValidationError):
        adm.create_year(admin, "2027-28")
    with pytest.raises(ValidationError):
        adm.create_year(admin, "2030-31", "2031-03-31", "2030-04-01")
    adm.update_year(admin, y, "2027-28", "2027-04-01", "2028-03-31", False)
    assert y not in [x["id"] for x in adm.list_years(include_inactive=False)]


def test_settings_roundtrip_and_validation(school):
    """A11 | Settings updates | Valid settings persist; invalid values and unknown keys are refused"""
    admin = school["admin"]
    adm.update_settings(admin, {"school_name": "Motilal Public School", "max_upload_mb": "4", "cert_primary_color": "#112233",
                                "allowed_extensions": "pdf,png", "backup_interval_hours": "12"})
    assert get_setting("school_name") == "Motilal Public School"
    assert get_setting("max_upload_mb") == "4" and get_setting("cert_primary_color") == "#112233"
    from services.settings_store import allowed_extensions, max_upload_bytes
    assert allowed_extensions() == ["pdf", "png"] and max_upload_bytes() == 4 * 1024 * 1024
    for bad in ({"max_upload_mb": "0"}, {"max_upload_mb": "9999"}, {"cert_primary_color": "blue"},
                {"allowed_extensions": "exe"}, {"nonsense": "1"}, {"school_name": ""}, {"public_base_url": "javascript:alert(1)"},
                {"cert_default_type": "Gold"}):
        with pytest.raises(ValidationError):
            adm.update_settings(admin, bad)


def test_logo_and_signature_upload(school):
    """A12 | Logo and signature images | Valid PNG is saved and used; non-images are refused"""
    from helpers import make_png, make_pdf
    adm.save_school_logo(school["admin"], "logo.png", make_png())
    name = get_setting("school_logo")
    assert name and adm.read_asset("logo_dir", name)
    with pytest.raises(ValidationError):
        adm.save_school_logo(school["admin"], "logo.png", b"not an image")
    with pytest.raises(ValidationError):
        adm.save_school_logo(school["admin"], "logo.pdf", make_pdf())
    adm.save_principal_signature(school["admin"], "sig.png", make_png())
    adm.save_my_signature(school["t1"], "mine.png", make_png())
    assert query_one("SELECT signature_path FROM users WHERE id=?", (school["t1"]["id"],))["signature_path"]


def test_teacher_cannot_use_admin_functions(school):
    """A13 | Unauthorized admin operations | Teachers and students are refused every administrator-only action"""
    t = school["t1"]
    stu = school["actors"]["6"]
    calls = [
        lambda a: adm.list_users(a), lambda a: adm.create_user(a, "hack1", "Hackpass1", "Hacker", ""),
        lambda a: adm.reset_password(a, 1, "Hackpass1"), lambda a: adm.set_user_active(a, 1, False),
        lambda a: adm.update_settings(a, {"school_name": "Hacked"}), lambda a: adm.recent_audit(a),
        lambda a: adm.save_school_logo(a, "x.png", b"x"), lambda a: backup_service.admin_create_backup(a),
        lambda a: backup_service.admin_list_backups(a), lambda a: backup_service.admin_restore(a, b"x"),
        lambda a: backup_service.admin_read_backup(a, "backup_x.zip"), lambda a: backup_service.admin_check_consistency(a),
        lambda a: adm.reassign_events(a, 1, 2), lambda a: certificate_service.regenerate(a, 1),
        lambda a: certificate_service.sample_certificate_pdf(a),
    ]
    for actor in (t, stu, None, {"role": "admin", "id": t["id"]}, {"role": "root", "id": 1}):
        for call in calls:
            with pytest.raises(PermissionDenied):
                call(actor)
    assert get_setting("school_name") == "Motilal School"


def test_passwords_never_plain(school):
    """A14 | Passwords stored securely | No plain-text password appears anywhere in the database file"""
    from config import get_paths
    rows = query_all("SELECT password_hash FROM users")
    assert all(r["password_hash"].startswith("scrypt$") for r in rows)
    raw = b"".join(p.read_bytes() for p in get_paths().data_dir.glob("school_events.db*"))
    for pw in (b"AdminPass1", b"Teacher123"):
        assert pw not in raw


def test_change_own_password(school):
    """A15 | Change own password | Needs the current password; new password works afterwards"""
    t = school["t1"]
    with pytest.raises(ValidationError):
        adm.change_own_password(t, "WrongOld123", "NewPass1234")
    adm.change_own_password(t, "Teacher123", "NewPass1234")
    assert auth.login_staff("teacher1", "NewPass1234")


def test_csv_student_import(school):
    """A16 | Student CSV import | Valid rows are added; duplicates and unknown classes are reported per row"""
    csv_text = ("name,class,section,roll\nAsha Verma,6,A,50\nBad Row,99,A,1\nAsha Verma,6,A,50\n"
                "New Kid,12,Z,1\n=cmd|' /C calc'!A0,6,B,7\n")
    res = adm.import_students_csv(school["admin"], csv_text)
    assert res["added"] == 2 and len(res["errors"]) == 3, res
    res2 = adm.import_students_csv(school["admin"], "name,class,section,roll\nNew Kid,12,Z,1\n", create_missing=True)
    assert res2["added"] == 1
    with pytest.raises(ValidationError):
        adm.import_students_csv(school["admin"], "a,b\n1,2\n")
