"""Shared test helpers: real sample files and a ready-made demo school."""
from __future__ import annotations

import io
import zipfile

from PIL import Image

FUTURE = "2030-01-01 17:00"
PASSWORD_ADMIN = "AdminPass1"
PASSWORD_TEACHER = "Teacher123"


def make_pdf(text: str = "hello") -> bytes:
    return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n"
            + f"% {text}\n".encode() + b"%%EOF\n")


def make_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def make_pptx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
    return buf.getvalue()


def make_png(size=(40, 30), color=(200, 30, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def make_jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 130, 200)).save(buf, "JPEG")
    return buf.getvalue()


SAMPLES = {"pdf": make_pdf, "docx": make_docx, "pptx": make_pptx, "png": make_png, "jpg": make_jpg}


def build_school() -> dict:
    """Admin + two teachers + classes 6-10 (sections A/B) + one student per class + a published event
    with a different topic for every class. Returns ids and logged-in actors."""
    import auth
    from services import admin_service as adm, event_service as ev

    auth.setup_admin("admin1", PASSWORD_ADMIN, "Head Admin", "Motilal School", "Mrs. Rao", "2026-27")
    admin = auth.login_staff("admin1", PASSWORD_ADMIN)
    adm.create_user(admin, "teacher1", PASSWORD_TEACHER, "Anita Kumar", "Science Teacher")
    adm.create_user(admin, "teacher2", PASSWORD_TEACHER, "Bala Murugan", "Maths Teacher")
    t1 = auth.login_staff("teacher1", PASSWORD_TEACHER)
    t2 = auth.login_staff("teacher2", PASSWORD_TEACHER)
    classes, sections = {}, {}
    for name in ("6", "7", "8", "9", "10"):
        cid = adm.create_class(admin, name)
        classes[name] = cid
        sections[name] = {"A": adm.create_section(admin, cid, "A"), "B": adm.create_section(admin, cid, "B")}
    students, actors = {}, {}
    for i, name in enumerate(("6", "7", "8", "9", "10"), start=1):
        sid = adm.add_student(t1, f"Student Class{name}", classes[name], sections[name]["A"], str(i))
        students[name] = sid
        actors[name] = auth.login_student(f"Student Class{name}", classes[name], sections[name]["A"], str(i))
    year = adm.default_year_id()
    eid = ev.create_event(t1, dict(name="Science and Technology Exhibition", description="Annual exhibition",
                                   category="Science", opens_on="2020-01-01", deadline=FUTURE,
                                   academic_year_id=year, instructions="Be original"))
    topics = {"6": "Basic Science Model", "7": "Water Conservation", "8": "Environmental Protection",
              "9": "Artificial Intelligence Awareness", "10": "Renewable Energy"}
    assignments = {}
    for name, topic in topics.items():
        assignments[name] = ev.create_assignment(t1, eid, dict(class_id=classes[name], section_id=None, topic=topic,
                                                                description=f"Do {topic}", max_marks=20,
                                                                allowed_formats=["pdf", "docx", "pptx", "jpg", "jpeg", "png"]))
    ev.set_event_status(t1, eid, "publish")
    return dict(admin=admin, t1=t1, t2=t2, classes=classes, sections=sections, students=students, actors=actors,
                year=year, event=eid, assignments=assignments, topics=topics)
