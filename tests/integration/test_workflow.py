"""D: the complete realistic school scenario, step by step."""
import io

import pytest

import auth
from database import query_all, query_one
from helpers import SAMPLES, make_pdf
from services import (admin_service as adm, certificate_service as cert, event_service as ev, report_service as rep,
                      submission_service as sub)
from utils.errors import PermissionDenied


def test_full_school_scenario(school):
    """D01 | Complete end-to-end workflow (24 steps) | Admin, teachers, event, five class topics, uploads, review, rejection, resubmission, approval, certificates and verification all work together"""
    admin, t1, t2, actors, topics = school["admin"], school["t1"], school["t2"], school["actors"], school["topics"]
    # 1-6: admin created two teachers, classes 6-10 with sections, teacher created the event + five different topics, students exist
    assert len(adm.list_users(admin)) == 3
    assert [c["name"] for c in adm.list_classes()] == ["6", "7", "8", "9", "10"]
    assert {r["topic"] for r in ev.list_assignments(t1, school["event"])} == set(topics.values())
    # 7-8: each student logs in independently and sees only the correct assignment
    for c, topic in topics.items():
        who = auth.login_student(f"Student Class{c}", school["classes"][c], school["sections"][c]["A"], str(list(topics).index(c) + 1))
        assert [m["topic"] for m in ev.student_assignments(who)] == [topic]
    # 9-11: real files uploaded for all five classes, all saved and pending
    kinds = {"6": "pdf", "7": "docx", "8": "pptx", "9": "png", "10": "jpg"}
    for c, ext in kinds.items():
        sub.submit_work(actors[c], school["assignments"][c], f"project_class{c}.{ext}", SAMPLES[ext]())
    rows = query_all("SELECT status FROM submissions")
    assert len(rows) == 5 and {r["status"] for r in rows} == {"Submitted"}
    assert query_one("SELECT COUNT(*) AS n FROM submission_versions")["n"] == 5
    # 12: teacher reviews (second teacher sees nothing and cannot touch them)
    assert sub.list_review_queue(t2) == []
    queue = {r["class_name"]: r for r in sub.list_review_queue(t1)}
    assert len(queue) == 5
    for r in queue.values():
        with pytest.raises(PermissionDenied):
            sub.get_submission_for_review(t2, r["id"])
    # 13-14: approve one, reject another with feedback
    sub.get_submission_for_review(t1, queue["6"]["id"])
    sub.review_action(t1, queue["6"]["id"], "approve", "Well done!", marks=19, cert_type="Achievement", cert_remark="First prize")
    sub.review_action(t1, queue["7"]["id"], "reject", "Add water-saving data.")
    # 15-16: rejected student logs in again, sees feedback, uploads corrected version
    again = auth.login_student("Student Class7", school["classes"]["7"], school["sections"]["7"]["A"], "2")
    s = sub.student_submission(again, school["assignments"]["7"])
    assert s["reviews"][0]["feedback"] == "Add water-saving data."
    sub.submit_work(again, school["assignments"]["7"], "corrected.docx", SAMPLES["docx"]())
    # 17: teacher approves the resubmission (and the others)
    q = {r["class_name"]: r for r in sub.list_review_queue(t1, status="pending")}
    assert q["7"]["status"] == "Resubmitted" and q["7"]["current_version"] == 2
    sub.review_action(t1, q["7"]["id"], "approve", "Much better")
    sub.review_action(t1, q["8"]["id"], "approve", "")
    # 18-19: approved students generate and download certificates; the unapproved cannot
    issued = {}
    for c in ("6", "7", "8"):
        sid = query_one("SELECT s.id FROM submissions s JOIN students st ON st.id=s.student_id WHERE st.full_name=?",
                        (f"Student Class{c}",))["id"]
        issued[c] = cert.generate_for_submission(actors[c], sid)
    for c in ("9", "10"):
        sid = query_one("SELECT s.id FROM submissions s JOIN students st ON st.id=s.student_id WHERE st.full_name=?",
                        (f"Student Class{c}",))["id"]
        with pytest.raises(PermissionDenied):
            cert.generate_for_submission(actors[c], sid)
    # 20-21: PDFs open, are A4 landscape and contain the right details
    from pypdf import PdfReader
    for c, row in issued.items():
        _, pdf = cert.get_certificate_pdf(actors[c], row["id"])
        reader = PdfReader(io.BytesIO(pdf))
        page = reader.pages[0]
        assert len(reader.pages) == 1
        assert round(float(page.mediabox.width)) == 842 and round(float(page.mediabox.height)) == 595     # A4 landscape
        text = page.extract_text()
        for must in ("MOTILAL SCHOOL", f"Student Class{c}", school["topics"][c], "Science and Technology Exhibition",
                     row["certificate_code"], f"Roll No. {list(topics).index(c) + 1}", "Section A", "Teacher", "Principal"):
            assert must in text, (c, must)
        assert ("Achievement" if c == "6" else "Participation") in text
    # 22: unique ids
    codes = [r["certificate_code"] for r in issued.values()]
    assert len(set(codes)) == 3 and all(x.startswith("MS-") for x in codes)
    # 23: access restrictions between students
    with pytest.raises(PermissionDenied):
        cert.get_certificate_pdf(actors["7"], issued["6"]["id"])
    # 24: public verification shows only the safe fields
    v = cert.verify(issued["6"]["certificate_code"])
    assert v["valid"] and v["student_name"] == "Student Class6" and v["topic"] == "Basic Science Model"
    assert not {"roll_number", "class_name", "section_name", "student_id", "file_path", "verification_token"} & set(v)
    assert cert.verify(issued["6"]["verification_token"])["valid"]
    assert cert.verify("MS-0000-NOPE0000") == {"found": False, "valid": False}
    # reports reflect it
    part = rep.event_participation(t1)[0]
    assert (part["submitted"], part["approved"], part["pending"]) == (5, 3, 2)
    assert [r["issued"] for r in rep.certificate_stats(t1)] == [3]
