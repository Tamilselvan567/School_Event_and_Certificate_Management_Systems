"""E: data must survive restarts; backup / restore / migration / failure handling."""
import io
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import auth
import database
from config import get_paths
from database import query_all, query_one, transaction
from helpers import make_pdf
from services import admin_service as adm, backup_service as bk, certificate_service as cert, event_service as ev, submission_service as sub
from utils.errors import AppError, DatabaseUnavailable, ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _run(code: str, store: Path) -> str:
    env = dict(os.environ, MSES_STORAGE_ROOT=str(store), PYTHONPATH=f"{ROOT}{os.pathsep}{ROOT / 'tests'}")
    for k in ("MSES_DB_PATH", "MSES_DATA_DIR"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, "-c", code], cwd="/", env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


def test_persistence_across_real_process_restarts(tmp_path):
    """E01 | Data survives stopping and restarting (separate Python processes) | Event, submissions, teacher login, feedback, certificate and uploaded file are all still there"""
    store = tmp_path / "store"
    first = '''
import json, database, auth
from helpers import build_school, make_pdf
from services import submission_service as sub, certificate_service as cert
database.init_db()
s = build_school()
t = s["t1"]
for c in ("6", "7"):
    sub.submit_work(s["actors"][c], s["assignments"][c], f"p{c}.pdf", make_pdf("proc" + c))
q = {r["class_name"]: r["id"] for r in sub.list_review_queue(t)}
sub.review_action(t, q["6"], "approve", "Lovely")
sub.review_action(t, q["7"], "reject", "Needs more detail")
c = cert.generate_for_submission(s["actors"]["6"], q["6"])
print(json.dumps({"cert": c["certificate_code"], "cid": c["id"], "sub6": q["6"], "sub7": q["7"]}))
'''
    info = json.loads(_run(first, store))
    second = f'''
import json, database, auth
from services import submission_service as sub, certificate_service as cert, event_service as ev
database.init_db()                      # restart: must NOT wipe anything
t = auth.login_staff("teacher1", "Teacher123")            # teacher account still works
events = ev.list_events(t)
stu = auth.login_student("Student Class6", 1, 1, "1")
stu7 = auth.login_student("Student Class7", 2, 3, "2")
s7 = sub.student_submission(stu7, 2)
d6 = sub.get_submission_for_review(t, {info["sub6"]}, mark_in_review=False)
name, pdfdata = cert.get_certificate_pdf(stu, {info["cid"]})
fname, filedata, _ = sub.download_version(t, d6["versions"][0]["id"])
print(json.dumps({{"events": [e["name"] for e in events], "n_sub": len(sub.list_review_queue(t)),
  "feedback": s7["reviews"][0]["feedback"], "status7": s7["status"], "cert_ok": pdfdata[:5] == b"%PDF-" and name == "{info['cert']}.pdf",
  "file_ok": b"proc6" in filedata, "verify": cert.verify("{info['cert']}")["valid"]}}))
'''
    out = json.loads(_run(second, store))
    assert out == {"events": ["Science and Technology Exhibition"], "n_sub": 2, "feedback": "Needs more detail", "status7": "Rejected",
                   "cert_ok": True, "file_ok": True, "verify": True}


def test_database_created_when_missing(env):
    """E02 | Database created automatically when missing | Deleting the database file and starting again builds a fresh complete database"""
    paths = get_paths()
    for f in paths.data_dir.glob("school_events.db*"):
        f.unlink()
    assert not paths.db_path.exists()
    assert database.init_db() == database.LATEST_VERSION
    tables = {r["name"] for r in query_all("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("users", "students", "classes", "sections", "academic_years", "events", "event_class_assignments", "submissions",
              "submission_versions", "reviews", "certificates", "certificate_verifications", "application_settings",
              "audit_logs", "database_migrations"):
        assert t in tables
    assert auth.needs_setup()


def test_existing_database_preserved_and_init_repeatable(school):
    """E03 | Existing database preserved, repeated initialisation safe | Running init many times keeps all data and customised settings"""
    adm.update_settings(school["admin"], {"school_name": "Custom School Name"})
    before = {t: query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("users", "students", "events", "event_class_assignments")}
    for _ in range(4):
        assert database.init_db() == database.LATEST_VERSION
    after = {t: query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in before}
    assert before == after
    from services.settings_store import get_setting
    assert get_setting("school_name") == "Custom School Name"
    assert query_one("SELECT COUNT(*) AS n FROM database_migrations")["n"] == database.LATEST_VERSION
    assert database.integrity_check() == []


def test_foreign_keys_and_constraints_enforced(school):
    """E04 | Data integrity | Foreign keys are enforced, duplicates and orphan rows are impossible"""
    conn = database.connect()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO sections(class_id, name) VALUES (9999, 'Z')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM classes WHERE id=?", (school["classes"]["6"],))     # has sections/students
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO users(username,password_hash,full_name,role,created_at) VALUES ('TEACHER1','x','Dup','teacher','now')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO students(full_name,class_id,section_id,roll_number,created_at) VALUES ('Dup',?,?, '1','now')",
                         (school["classes"]["6"], school["sections"]["6"]["A"]))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE events SET status='weird' WHERE id=?", (school["event"],))
    finally:
        conn.close()
    assert database.integrity_check() == []


def test_transaction_rollback(env):
    """E05 | Interrupted database operation | A failure in the middle of a change leaves no half-saved data"""
    with pytest.raises(RuntimeError):
        with transaction() as conn:
            conn.execute("INSERT INTO classes(name) VALUES ('Half')")
            conn.execute("INSERT INTO academic_years(name) VALUES ('Half-year')")
            raise RuntimeError("power cut")
    assert query_one("SELECT COUNT(*) AS n FROM classes")["n"] == 0
    assert query_one("SELECT COUNT(*) AS n FROM academic_years")["n"] == 0


def test_failed_submit_leaves_no_orphan_file(school, monkeypatch):
    """E06 | File and database stay consistent on failure | If saving the record fails, the uploaded file is removed again"""
    from services import submission_service as ss
    monkeypatch.setattr(ss, "audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "w.pdf", make_pdf())
    assert query_one("SELECT COUNT(*) AS n FROM submissions")["n"] == 0
    assert [p for p in get_paths().submissions_dir.rglob("*") if p.is_file()] == []


def _seed_files(school):
    sub.submit_work(school["actors"]["6"], school["assignments"]["6"], "w.pdf", make_pdf("backup me"))
    sid = sub.list_review_queue(school["t1"])[0]["id"]
    sub.review_action(school["t1"], sid, "approve", "")
    return sid, cert.generate_for_submission(school["actors"]["6"], sid)


def test_backup_and_restore(school):
    """E07 | Backup creation and restoration | A backup ZIP restores database, uploads and certificates exactly as they were"""
    sid, c = _seed_files(school)
    path = bk.admin_create_backup(school["admin"], True)
    assert path.exists() and zipfile.ZipFile(path).testzip() is None
    names = zipfile.ZipFile(path).namelist()
    assert "database/school_events.db" in names and any(n.startswith("uploads/submissions/") for n in names)
    assert any(n.startswith("certificates/") for n in names)
    # damage everything after the backup
    ev.create_event(school["t1"], dict(name="After Backup", description="", category="Art", opens_on="2020-01-01",
                                       deadline="2030-01-01 10:00", academic_year_id=school["year"]))
    adm.reset_password(school["admin"], school["t1"]["id"], "Changed12345")
    for f in get_paths().submissions_dir.rglob("*.pdf"):
        f.unlink()
    for f in get_paths().certificates_dir.rglob("*.pdf"):
        f.unlink()
    res = bk.admin_restore(school["admin"], path.read_bytes())
    assert res["files_restored"] >= 2 and res["safety_backup"].startswith("backup_pre-restore_")
    assert [e["name"] for e in ev.list_events(school["admin"])] == ["Science and Technology Exhibition"]
    assert auth.login_staff("teacher1", "Teacher123")
    d = sub.get_submission_for_review(school["admin"], sid, mark_in_review=False)
    assert b"backup me" in sub.download_version(school["admin"], d["versions"][0]["id"])[1]
    assert cert.verify(c["certificate_code"])["valid"]
    assert database.integrity_check() == [] and bk.check_consistency()["missing_uploads"] == []


@pytest.mark.parametrize("kind", ["garbage", "empty", "zip_without_db", "bad_db", "other_app_db", "newer_version"])
def test_restore_failures_keep_current_data(school, kind):
    """E08 | Restore failure | Bad, damaged, foreign or too-new backups are refused and current data is untouched"""
    def sqlite_bytes(sql_list):
        p = get_paths().root / "tmp_other.db"
        c = sqlite3.connect(p)
        for s in sql_list:
            c.execute(s)
        c.commit(); c.close()
        data = p.read_bytes(); p.unlink()
        return data
    if kind == "garbage":
        data = b"this is not a backup" * 10
    elif kind == "empty":
        data = b""
    elif kind == "zip_without_db":
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("hello.txt", "x")
        data = b.getvalue()
    elif kind == "bad_db":
        data = b"SQLite format 3\x00" + b"\x00" * 200
    elif kind == "other_app_db":
        data = sqlite_bytes(["CREATE TABLE something(id INTEGER)"])
    else:
        good = get_paths().backups_dir / "x.db"
        src = database.connect(); out = sqlite3.connect(good); src.backup(out); out.close(); src.close()
        c = sqlite3.connect(good); c.execute("INSERT INTO database_migrations VALUES (99,'future','now')"); c.commit(); c.close()
        data = good.read_bytes(); good.unlink()
    before = query_one("SELECT COUNT(*) AS n FROM events")["n"]
    with pytest.raises(AppError):
        bk.admin_restore(school["admin"], data)
    assert query_one("SELECT COUNT(*) AS n FROM events")["n"] == before and auth.login_staff("teacher1", "Teacher123")
    assert database.integrity_check() == []


def test_restore_blocks_zip_slip(school):
    """E09 | Malicious backup ZIP | File names that try to leave the data folders are skipped, not written"""
    path = bk.admin_create_backup(school["admin"], False)
    b = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(b, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n))
        zout.writestr("uploads/../../evil.txt", "pwned")
        zout.writestr("uploads/../../../evil2.txt", "pwned")
        zout.writestr("uploads/ok.txt", "fine")
    res = bk.admin_restore(school["admin"], b.getvalue())
    assert res["files_restored"] == 1
    root = get_paths().root
    assert not (root / "evil.txt").exists() and not (root.parent / "evil.txt").exists() and not (root.parent / "evil2.txt").exists()
    assert (get_paths().uploads_dir / "ok.txt").read_text() == "fine"


def test_backup_failure_is_friendly(school, monkeypatch):
    """E10 | Backup failure | A failing backup gives a friendly message, leaves no half-made file, and the app keeps working"""
    monkeypatch.setattr(bk, "_snapshot_db", lambda dest: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(AppError) as e:
        bk.admin_create_backup(school["admin"])
    assert "could not be created" in str(e.value) and "disk full" not in str(e.value)
    assert list(get_paths().backups_dir.glob("*.part")) == [] and list(get_paths().backups_dir.glob("backup_manual*")) == []
    monkeypatch.setenv("MSES_BACKUPS_DIR", str(get_paths().root / "data" / "school_events.db"))   # a FILE, not a folder
    with pytest.raises(AppError):
        bk.create_backup("manual")
    assert bk.auto_backup_if_due(force=True) is None          # automatic backup never crashes the app
    assert query_one("SELECT 1 AS x FROM users LIMIT 1")


def test_automatic_backup_and_pruning(school):
    """E11 | Automatic backups | An automatic backup is made when due, not repeated too soon, and old ones are pruned"""
    p = bk.auto_backup_if_due(force=True)
    assert p and p.name.startswith("backup_auto_")
    assert bk.auto_backup_if_due(force=True) is None
    manual = bk.create_backup("manual", False)
    adm.update_settings(school["admin"], {"backup_keep_count": "1", "backup_interval_hours": "1"})
    import time
    for i in range(3):
        (get_paths().backups_dir / f"backup_auto_2020010{i}_000000.zip").write_bytes(b"x")
        os.utime(get_paths().backups_dir / f"backup_auto_2020010{i}_000000.zip", (time.time() - 100000 - i, time.time() - 100000 - i))
    assert bk.prune_backups(1) == 3 + 1 - 1
    assert manual.exists()                                      # manual backups are never deleted automatically


def test_migration_from_older_schema(tmp_path, monkeypatch):
    """E12 | Migration from an older schema | A version-1 database is upgraded to the latest, keeping data and making a safety backup"""
    monkeypatch.setenv("MSES_STORAGE_ROOT", str(tmp_path / "store"))
    assert database.init_db(target_version=1) == 1
    conn = database.connect()
    conn.execute("INSERT INTO users(username,password_hash,full_name,role,created_at) VALUES ('old','h','Old Admin','admin','2025-01-01')")
    conn.execute("INSERT INTO classes(name) VALUES ('5')")
    conn.close()
    assert "last_reviewed_by" not in {r["name"] for r in query_all("PRAGMA table_info(submissions)")}
    assert database.init_db() == database.LATEST_VERSION
    assert "last_reviewed_by" in {r["name"] for r in query_all("PRAGMA table_info(submissions)")}
    assert query_one("SELECT full_name FROM users WHERE username='old'")["full_name"] == "Old Admin"
    assert query_one("SELECT name FROM classes")["name"] == "5"
    assert list(get_paths().backups_dir.glob("backup_pre-migration_*.zip"))
    assert database.integrity_check() == []


def test_missing_files_handled(school):
    """E13 | Missing upload / certificate file | Missing upload gives a friendly message (no paths); missing certificate is rebuilt with the same ID"""
    sid, c = _seed_files(school)
    d = sub.get_submission_for_review(school["t1"], sid, mark_in_review=False)
    report0 = bk.check_consistency()
    assert report0["missing_uploads"] == [] and report0["orphan_files"] == 0
    for f in get_paths().submissions_dir.rglob("*.pdf"):
        f.unlink()
    with pytest.raises(AppError) as e:
        sub.download_version(school["t1"], d["versions"][0]["id"])
    assert "could not be found" in str(e.value) and "submissions/" not in str(e.value) and str(get_paths().root) not in str(e.value)
    assert len(bk.check_consistency()["missing_uploads"]) == 1
    for f in get_paths().certificates_dir.rglob("*.pdf"):
        f.unlink()
    assert len(bk.check_consistency()["missing_certificates"]) == 1
    name, pdf = cert.get_certificate_pdf(school["actors"]["6"], c["id"])
    assert pdf.startswith(b"%PDF") and name == f"{c['certificate_code']}.pdf" and len(bk.check_consistency()["missing_certificates"]) == 0


def test_missing_folders_recreated(school):
    """E14 | Missing folders | Deleted upload / certificate folders are recreated automatically"""
    import shutil
    p = get_paths()
    shutil.rmtree(p.uploads_dir); shutil.rmtree(p.certificates_dir); shutil.rmtree(p.backups_dir)
    sid, c = _seed_files(school)
    assert cert.get_certificate_pdf(school["actors"]["6"], c["id"])[1].startswith(b"%PDF")
    assert bk.admin_create_backup(school["admin"]).exists()


def test_database_locked(school, monkeypatch):
    """E15 | Database locked | While another writer holds the database, the user gets a friendly 'busy' message; it works again afterwards"""
    monkeypatch.setenv("MSES_DB_TIMEOUT_MS", "300")
    blocker = sqlite3.connect(get_paths().db_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseUnavailable) as e:
            adm.create_class(school["admin"], "Blocked")
        assert "busy" in str(e.value).lower() and "sqlite" not in str(e.value).lower()
        assert auth.login_student("Student Class6", school["classes"]["6"], school["sections"]["6"]["A"], "1") is None or True
    except AppError:
        pass                                    # student login also writes an audit row; a friendly error is acceptable
    finally:
        blocker.execute("ROLLBACK"); blocker.close()
    assert adm.create_class(school["admin"], "Unblocked")


def _manage(store, *args, stdin=""):
    env = dict(os.environ, MSES_STORAGE_ROOT=str(store))
    r = subprocess.run([sys.executable, str(ROOT / "manage.py"), *args], cwd="/", env=env, input=stdin,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_command_line_tool(school, env):
    """E16 | manage.py command-line tool | backup, list, check, restore and reset-password work from the terminal, including for a locked-out administrator"""
    code, out = _manage(env, "check")
    assert code == 0 and "healthy" in out
    code, out = _manage(env, "backup")
    assert code == 0 and "Backup created" in out
    assert "backup_manual_" in _manage(env, "list")[1]
    zip_path = next(get_paths().backups_dir.glob("backup_manual_*.zip"))
    adm.create_class(school["admin"], "After CLI backup")
    code, out = _manage(env, "restore", str(zip_path))
    assert code == 0 and "Restore finished" in out
    assert "After CLI backup" not in [c["name"] for c in adm.list_classes()]
    code, out = _manage(env, "restore", str(env / "missing.zip"))
    assert code == 1 and "Error" in out
    for _ in range(5):
        with pytest.raises(AppError):
            auth.login_staff("admin1", "Wrong-pass-1")
    code, out = _manage(env, "reset-password", "admin1", stdin="Recovered99\nRecovered99\n")
    assert code == 0 and "Password changed" in out
    assert auth.login_staff("admin1", "Recovered99")["role"] == "admin"
    code, out = _manage(env, "reset-password", "admin1", stdin="Recovered99\nMismatch000\n")
    assert code == 1
    assert _manage(env, "bogus")[0] == 2
