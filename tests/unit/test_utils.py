import io
import zipfile
from pathlib import Path

import pytest

from helpers import make_docx, make_jpg, make_pdf, make_png, make_pptx
from utils import security, validators
from utils.errors import ValidationError
from utils.helpers import csv_safe


def test_password_hash_roundtrip():
    """U01 | Password hashing | Hash is salted scrypt, never the plain text; correct password verifies, wrong one does not"""
    h = security.hash_password("Secret123")
    assert "Secret123" not in h and h.startswith("scrypt$")
    assert security.hash_password("Secret123") != h
    assert security.verify_password("Secret123", h)
    assert not security.verify_password("secret123", h)
    assert not security.verify_password("Secret123", "garbage")


@pytest.mark.parametrize("raw,expected_has", [
    ("../../etc/passwd", "passwd"), ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
    ("my report (final).pdf", "my report _final_.pdf"), ("a\x00b.pdf", "ab.pdf"), ("", "file"), ("....", "file"),
])
def test_sanitize_filename(raw, expected_has):
    """U02 | Unsafe file names | Folders, control characters and odd symbols are removed"""
    out = security.sanitize_filename(raw)
    assert "/" not in out and "\\" not in out and ".." not in out.replace("....", "")
    assert expected_has in out


def test_safe_join_blocks_traversal(tmp_path):
    """U03 | Path traversal guard | Paths that leave the base folder raise an error"""
    assert security.safe_join(tmp_path, "a", "b.txt").is_relative_to(tmp_path.resolve())
    for bad in ("../x", "a/../../x", "/etc/passwd"):
        with pytest.raises(ValueError):
            security.safe_join(tmp_path, bad)


def test_csv_formula_protection():
    """U04 | CSV export safety | Cells starting with = + - @ are neutralised"""
    for v in ("=1+1", "+cmd", "-2", "@SUM(A1)"):
        assert csv_safe(v).startswith("'")
    assert csv_safe("Normal") == "Normal" and csv_safe(5) == 5


def test_validators():
    """U05 | Input validators | Bad usernames, passwords, roll numbers, colours and dates are rejected with friendly errors"""
    assert validators.validate_username("teacher.one") == "teacher.one"
    for bad in ("ab", "has space", "x" * 40, "semi;colon"):
        with pytest.raises(ValidationError):
            validators.validate_username(bad)
    for bad in ("short1", "alllettersonly", "12345678", "x" * 200):
        with pytest.raises(ValidationError):
            validators.validate_password(bad)
    assert validators.validate_password("Good1234")
    with pytest.raises(ValidationError):
        validators.validate_roll("")
    with pytest.raises(ValidationError):
        validators.validate_roll("a b")
    assert validators.validate_color("#abc123") == "#ABC123"
    with pytest.raises(ValidationError):
        validators.validate_color("red")
    assert validators.parse_date("2026-02-03") == "2026-02-03"
    with pytest.raises(ValidationError):
        validators.parse_date("31/12/2026")
    with pytest.raises(ValidationError):
        validators.parse_datetime("2026-13-40 10:00")
    with pytest.raises(ValidationError):
        validators.validate_person_name("12345")


def test_upload_signature_validation(env):
    """U06 | File content check | Real files pass; renamed, truncated or fake files are rejected"""
    from services import file_service as fs
    assert fs.validate_upload("a.pdf", make_pdf())[0] == "pdf"
    assert fs.validate_upload("a.docx", make_docx())[0] == "docx"
    assert fs.validate_upload("a.pptx", make_pptx())[0] == "pptx"
    assert fs.validate_upload("a.png", make_png())[0] == "png"
    assert fs.validate_upload("a.jpg", make_jpg())[0] == "jpg"
    assert fs.validate_upload("a.jpeg", make_jpg())[0] == "jpeg"
    with pytest.raises(ValidationError):
        fs.validate_upload("fake.pdf", b"just some text")
    with pytest.raises(ValidationError):
        fs.validate_upload("fake.png", make_jpg())
    with pytest.raises(ValidationError):
        fs.validate_upload("cut.pdf", make_pdf()[:20])
    with pytest.raises(ValidationError):
        fs.validate_upload("bad.docx", b"PK\x03\x04 not a real zip")
    with pytest.raises(ValidationError):
        fs.validate_upload("wrong.pptx", make_docx())      # a Word file renamed to .pptx
    with pytest.raises(ValidationError):
        fs.validate_upload("empty.pdf", b"")


def test_zip_bomb_guard(env):
    """U07 | Zip bomb guard | A DOCX that would unpack to a huge size is rejected"""
    from services import file_service as fs
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", b"0" * (310 * 1024 * 1024))
    data = buf.getvalue()
    assert len(data) < 5 * 1024 * 1024
    with pytest.raises(ValidationError):
        fs.validate_upload("bomb.docx", data, max_bytes=10 * 1024 * 1024)
