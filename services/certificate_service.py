"""Certificate generation (A4 landscape PDF), storage and public verification."""
from __future__ import annotations

import io
import logging
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

import qrcode
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from auth import require_admin, require_staff, verify_actor
from config import get_paths
from database import audit, query_all, query_one, transaction
from services import file_service
from services.admin_service import read_asset
from services.settings_store import get_all_settings, get_setting
from utils.errors import AppError, NotFound, PermissionDenied, ValidationError
from utils.helpers import APPROVED, class_label, now_local, utc_now_str
from utils.security import safe_join, sha256_bytes

log = logging.getLogger("mses.certs")
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _new_code(year: int) -> str:
    return f"MS-{year}-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def public_base_url() -> str:
    import os
    return (os.environ.get("MSES_PUBLIC_URL", "").strip() or get_setting("public_base_url")).rstrip("/")


def verification_url(token: str) -> str:
    base = public_base_url() or "http://localhost:8501"
    return f"{base}/?verify={token}"


# ------------------------------------------------------------------ PDF drawing
def _draw_image(c, data: bytes | None, x, y, w, h) -> bool:
    if not data:
        return False
    try:
        c.drawImage(ImageReader(io.BytesIO(data)), x, y, width=w, height=h, preserveAspectRatio=True,
                    anchor="c", mask="auto")
        return True
    except Exception:
        log.warning("Could not draw an image on the certificate")
        return False


def render_pdf(cert: dict, settings: dict, logo: bytes | None, teacher_sig: bytes | None,
               principal_sig: bytes | None) -> bytes:
    """Draw the certificate. `cert` holds the saved snapshot so reprints always match the original."""
    W, H = landscape(A4)  # 841.89 x 595.28 pt
    primary = HexColor(settings.get("cert_primary_color") or "#1E3A8A")
    secondary = HexColor(settings.get("cert_secondary_color") or "#0EA5E9")
    accent = HexColor(settings.get("cert_accent_color") or "#F59E0B")
    ink = HexColor("#1F2937")
    soft = HexColor("#F8FAFC")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"Certificate {cert['certificate_code']}")
    c.setAuthor(cert["school_name"])
    c.setSubject(f"{cert['event_name']} - {cert['student_name']}")

    # --- background and colourful frame
    c.setFillColor(soft)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(primary)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(white)
    c.rect(14, 14, W - 28, H - 28, stroke=0, fill=1)
    c.setStrokeColor(accent)
    c.setLineWidth(3)
    c.rect(24, 24, W - 48, H - 48, stroke=1, fill=0)
    c.setStrokeColor(secondary)
    c.setLineWidth(1)
    c.rect(30, 30, W - 60, H - 60, stroke=1, fill=0)

    # --- decorative corner triangles
    for (cx, cy, sx, sy) in ((14, 14, 1, 1), (W - 14, 14, -1, 1), (14, H - 14, 1, -1), (W - 14, H - 14, -1, -1)):
        for size, col in ((120, secondary), (86, accent), (52, primary)):
            c.setFillColor(col)
            p = c.beginPath()
            p.moveTo(cx, cy)
            p.lineTo(cx + sx * size, cy)
            p.lineTo(cx, cy + sy * size)
            p.close()
            c.drawPath(p, stroke=0, fill=1)
    # light dots band under the heading
    c.setFillColor(accent)
    for i in range(9):
        c.circle(W / 2 - 80 + i * 20, H - 188, 2.2, stroke=0, fill=1)

    # --- header: logo + school name
    if _draw_image(c, logo, 62, H - 118, 72, 72):
        pass
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(W / 2, H - 82, cert["school_name"].upper())
    c.setFillColor(ink)
    c.setFont("Helvetica", 10)
    address = settings.get("school_address", "")
    if address:
        c.drawCentredString(W / 2, H - 100, address[:110])
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, H - 122, "- - -  EVENTS & ACTIVITIES  - - -")

    # --- title
    c.setFillColor(accent)
    c.setFont("Times-BoldItalic", 38)
    c.drawCentredString(W / 2, H - 168, f"Certificate of {cert['cert_type']}")

    # --- body
    c.setFillColor(ink)
    c.setFont("Helvetica", 13)
    c.drawCentredString(W / 2, H - 212, "This certificate is proudly presented to")
    name = cert["student_name"]
    size = 40
    while size > 20 and c.stringWidth(name, "Times-BoldItalic", size) > W - 220:
        size -= 2
    c.setFillColor(primary)
    c.setFont("Times-BoldItalic", size)
    c.drawCentredString(W / 2, H - 258, name)
    c.setStrokeColor(accent)
    c.setLineWidth(1.5)
    nw = min(c.stringWidth(name, "Times-BoldItalic", size) + 40, W - 200)
    c.line(W / 2 - nw / 2, H - 268, W / 2 + nw / 2, H - 268)

    c.setFillColor(ink)
    c.setFont("Helvetica", 12.5)
    c.drawCentredString(W / 2, H - 292, f"{class_label(cert['class_name'])}  |  Section {cert['section_name']}  |  "
                                         f"Roll No. {cert['roll_number']}")
    if cert["cert_type"] == "Achievement":
        verb = "for outstanding achievement and excellent work in"
    else:
        verb = "for active participation and successful completion of the project in"
    c.setFont("Helvetica", 13)
    c.drawCentredString(W / 2, H - 322, verb)
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 22)
    ev_lines = simpleSplit(cert["event_name"], "Helvetica-Bold", 22, W - 220)[:2]
    y = H - 350
    for line in ev_lines:
        c.drawCentredString(W / 2, y, line)
        y -= 26
    c.setFillColor(ink)
    c.setFont("Helvetica-Oblique", 13)
    topic_lines = simpleSplit(f"Project topic: {cert['topic']}", "Helvetica-Oblique", 13, W - 240)[:2]
    for line in topic_lines:
        c.drawCentredString(W / 2, y - 2, line)
        y -= 17
    if cert.get("remark"):
        c.setFont("Helvetica", 11)
        c.drawCentredString(W / 2, y - 6, simpleSplit(cert["remark"], "Helvetica", 11, W - 260)[0])

    # --- signatures
    base_y = 112
    line_w = 170
    for cx, label, who, sub, sig in (
        (170, "Teacher", cert.get("teacher_name") or "", cert.get("teacher_designation") or "", teacher_sig),
        (W - 170, "Principal", cert.get("principal_name") or "", "", principal_sig),
    ):
        _draw_image(c, sig, cx - 55, base_y + 4, 110, 40)
        c.setStrokeColor(ink)
        c.setLineWidth(0.8)
        c.line(cx - line_w / 2, base_y, cx + line_w / 2, base_y)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawCentredString(cx, base_y - 14, who or f"{label} signature")
        c.setFont("Helvetica", 9)
        c.drawCentredString(cx, base_y - 26, sub or label)

    # --- QR code + ids
    qr_img = qrcode.make(cert["verify_url"], box_size=4, border=1)
    qb = io.BytesIO()
    qr_img.save(qb, format="PNG")
    c.drawImage(ImageReader(io.BytesIO(qb.getvalue())), W / 2 - 34, 52, width=68, height=68)
    c.setFillColor(ink)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, 44, "Scan to verify")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(112, 62, f"Certificate ID: {cert['certificate_code']}")
    c.setFont("Helvetica", 9)
    c.drawString(112, 50, f"Issued on: {cert['issued_on']}")
    footer = settings.get("cert_footer_text", "")
    if footer:
        c.setFont("Helvetica-Oblique", 8)
        c.drawRightString(W - 112, 50, footer[:70])
    c.showPage()
    c.save()
    return buf.getvalue()


def _snapshot_settings() -> dict:
    return get_all_settings()


def _build_pdf(cert: dict) -> bytes:
    s = _snapshot_settings()
    logo = read_asset("logo_dir", s.get("school_logo", ""))
    psig = read_asset("signatures_dir", s.get("principal_signature", ""))
    tsig = None
    if cert.get("teacher_id"):
        row = query_one("SELECT signature_path FROM users WHERE id=?", (cert["teacher_id"],))
        if row and row["signature_path"]:
            tsig = read_asset("signatures_dir", row["signature_path"])
    cert = dict(cert, verify_url=verification_url(cert["verification_token"]))
    return render_pdf(cert, s, logo, tsig, psig)


def _store_pdf(code: str, issued_year: str, pdf: bytes) -> str:
    rel = f"{issued_year}/{code}.pdf"
    file_service.write_atomic(safe_join(get_paths().certificates_dir, rel), pdf)
    return rel


# -------------------------------------------------------------- generate / get
def generate_for_submission(actor, submission_id) -> dict:
    """Create (or return the existing) certificate. Only for APPROVED submissions.

    Students may do this for their own work. Staff may do it for events they own."""
    who = verify_actor(actor)
    with transaction() as conn:
        row = conn.execute(
            "SELECT s.id, s.status, s.student_id, s.cert_type, s.cert_remark, s.last_reviewed_by,"
            " st.full_name, st.roll_number, c.name AS class_name, sec.name AS section_name,"
            " a.topic, e.id AS event_id, e.name AS event_name, e.created_by AS event_owner"
            " FROM submissions s JOIN students st ON st.id=s.student_id"
            " JOIN event_class_assignments a ON a.id=s.assignment_id JOIN events e ON e.id=a.event_id"
            " JOIN classes c ON c.id=a.class_id JOIN sections sec ON sec.id=st.section_id WHERE s.id=?",
            (submission_id,)).fetchone()
        if not row:
            raise NotFound("Submission not found.")
        if who["role"] == "student":
            if row["student_id"] != who["id"]:
                raise PermissionDenied("You can only get certificates for your own work.")
        elif who["role"] != "admin" and row["event_owner"] != who["id"]:
            raise PermissionDenied("You can only issue certificates for events that you created.")
        if row["status"] != APPROVED:
            raise PermissionDenied("A certificate is available only after your teacher approves your work.")
        existing = conn.execute("SELECT * FROM certificates WHERE submission_id=?", (submission_id,)).fetchone()
        if existing:
            return dict(existing)
        teacher = None
        if row["last_reviewed_by"]:
            teacher = conn.execute("SELECT id, full_name, designation FROM users WHERE id=?",
                                   (row["last_reviewed_by"],)).fetchone()
        settings = get_all_settings()
        issued = now_local()
        code = None
        for _ in range(10):
            candidate = _new_code(issued.year)
            if not conn.execute("SELECT 1 FROM certificates WHERE certificate_code=?", (candidate,)).fetchone():
                code = candidate
                break
        if not code:
            raise AppError("A certificate number could not be created. Please try again.")
        cert = {
            "certificate_code": code, "verification_token": secrets.token_urlsafe(18),
            "submission_id": submission_id, "student_id": row["student_id"], "event_id": row["event_id"],
            "student_name": row["full_name"], "class_name": row["class_name"], "section_name": row["section_name"],
            "roll_number": row["roll_number"], "event_name": row["event_name"], "topic": row["topic"],
            "cert_type": row["cert_type"] or settings.get("cert_default_type") or "Participation",
            "remark": row["cert_remark"] or "", "school_name": settings.get("school_name") or "Motilal School",
            "principal_name": settings.get("principal_name") or "",
            "teacher_name": teacher["full_name"] if teacher else "",
            "teacher_designation": (teacher["designation"] or "") if teacher else "",
            "teacher_id": teacher["id"] if teacher else None,
            "issued_on": issued.strftime("%d %B %Y"), "status": "valid",
        }
        pdf = _build_pdf(cert)
        rel = _store_pdf(code, str(issued.year), pdf)
        try:
            cid = conn.execute(
                "INSERT INTO certificates(certificate_code, verification_token, submission_id, student_id, event_id,"
                " student_name, class_name, section_name, roll_number, event_name, topic, cert_type, remark,"
                " school_name, principal_name, teacher_name, teacher_designation, teacher_id, issued_on, status,"
                " file_path, file_sha256, generated_by_role, generated_by_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cert["certificate_code"], cert["verification_token"], submission_id, cert["student_id"],
                 cert["event_id"], cert["student_name"], cert["class_name"], cert["section_name"],
                 cert["roll_number"], cert["event_name"], cert["topic"], cert["cert_type"], cert["remark"],
                 cert["school_name"], cert["principal_name"], cert["teacher_name"], cert["teacher_designation"],
                 cert["teacher_id"], cert["issued_on"], "valid", rel, sha256_bytes(pdf), who["role"], who["id"],
                 utc_now_str())).lastrowid
        except sqlite3.IntegrityError:
            file_service_cleanup = safe_join(get_paths().certificates_dir, rel)
            try:
                file_service_cleanup.unlink()
            except OSError:
                pass
            raise
        audit(conn, who, "certificate_generated", "certificate", cid, code)
        return dict(conn.execute("SELECT * FROM certificates WHERE id=?", (cid,)).fetchone())


def _load_for_access(who, cert_id) -> dict:
    row = query_one(
        "SELECT c.*, e.created_by AS event_owner FROM certificates c JOIN events e ON e.id=c.event_id WHERE c.id=?",
        (cert_id,))
    if not row:
        raise NotFound("Certificate not found.")
    if who["role"] == "student":
        if row["student_id"] != who["id"]:
            raise PermissionDenied("You can only download your own certificate.")
    elif who["role"] != "admin" and row["event_owner"] != who["id"]:
        raise PermissionDenied("You can only manage certificates for events that you created.")
    return row


def get_certificate_pdf(actor, cert_id) -> tuple[str, bytes]:
    """Return the saved PDF. If the file went missing it is rebuilt from the saved record (same ID)."""
    who = verify_actor(actor)
    row = _load_for_access(who, cert_id)
    if row["status"] != "valid":
        raise PermissionDenied("This certificate has been revoked and can no longer be downloaded.")
    paths = get_paths()
    try:
        path = safe_join(paths.certificates_dir, row["file_path"])
    except ValueError:
        raise AppError("This certificate file cannot be opened.") from None
    if not path.is_file():
        log.warning("Certificate file missing, rebuilding %s", row["certificate_code"])
        pdf = _build_pdf(row)
        file_service.write_atomic(path, pdf)
    return f"{row['certificate_code']}.pdf", path.read_bytes()


def certificate_for_student_submission(actor, submission_id) -> dict | None:
    who = verify_actor(actor, ("student",))
    return query_one("SELECT id, certificate_code, status, issued_on FROM certificates"
                     " WHERE submission_id=? AND student_id=?", (submission_id, who["id"]))


def regenerate(actor, cert_id) -> None:
    """Administrator only: rebuild the PDF (same certificate ID) with the current logo/signatures."""
    admin = require_admin(actor)
    row = query_one("SELECT * FROM certificates WHERE id=?", (cert_id,))
    if not row:
        raise NotFound("Certificate not found.")
    s = get_all_settings()
    row["principal_name"] = s.get("principal_name") or row["principal_name"]
    row["school_name"] = s.get("school_name") or row["school_name"]
    pdf = _build_pdf(row)
    with transaction() as conn:
        rel = row["file_path"]
        file_service.write_atomic(safe_join(get_paths().certificates_dir, rel), pdf)
        conn.execute("UPDATE certificates SET file_sha256=?, regenerated_count=regenerated_count+1,"
                     " principal_name=?, school_name=? WHERE id=?",
                     (sha256_bytes(pdf), row["principal_name"], row["school_name"], cert_id))
        audit(conn, admin, "certificate_regenerated", "certificate", cert_id, row["certificate_code"])


def sample_certificate_pdf(actor) -> bytes:
    """Administrator preview of the current certificate design (not saved, not a real certificate)."""
    require_admin(actor)
    s = get_all_settings()
    sample = {"certificate_code": "MS-0000-SAMPLE", "verification_token": "sample", "student_name": "Sample Student",
              "class_name": "6", "section_name": "A", "roll_number": "1", "event_name": "Science Exhibition",
              "topic": "Sample project topic", "cert_type": s.get("cert_default_type") or "Participation",
              "remark": "", "school_name": s.get("school_name") or "Motilal School",
              "principal_name": s.get("principal_name") or "", "teacher_name": "Class Teacher",
              "teacher_designation": "Teacher", "issued_on": now_local().strftime("%d %B %Y"),
              "verify_url": verification_url("sample")}
    return render_pdf(sample, s, read_asset("logo_dir", s.get("school_logo", "")), None,
                      read_asset("signatures_dir", s.get("principal_signature", "")))


def set_revoked(actor, cert_id, revoke: bool, reason: str = "") -> None:
    who = require_staff(actor)
    reason = (reason or "").strip()[:300]
    if revoke and not reason:
        raise ValidationError("Please give a reason for revoking the certificate.")
    row = _load_for_access(who, cert_id)
    with transaction() as conn:
        if revoke:
            conn.execute("UPDATE certificates SET status='revoked', revoked_reason=?, revoked_at=? WHERE id=?",
                         (reason, utc_now_str(), cert_id))
        else:
            sub = conn.execute("SELECT status FROM submissions WHERE id=?", (row["submission_id"],)).fetchone()
            if not sub or sub["status"] != APPROVED:
                raise ValidationError("The submission is no longer approved, so the certificate cannot be restored.")
            conn.execute("UPDATE certificates SET status='valid', revoked_reason=NULL, revoked_at=NULL WHERE id=?",
                         (cert_id,))
        audit(conn, who, "certificate_revoked" if revoke else "certificate_restored", "certificate", cert_id,
              row["certificate_code"])


def list_certificates(actor, event_id=None, search: str = "") -> list[dict]:
    staff = require_staff(actor)
    sql = ("SELECT c.id, c.certificate_code, c.student_name, c.class_name, c.section_name, c.roll_number,"
           " c.event_name, c.topic, c.cert_type, c.issued_on, c.status, c.revoked_reason, c.regenerated_count"
           " FROM certificates c JOIN events e ON e.id=c.event_id WHERE (? = 1 OR e.created_by = ?)")
    params: list = [1 if staff["role"] == "admin" else 0, staff["id"]]
    if event_id:
        sql += " AND c.event_id=?"
        params.append(event_id)
    if search:
        sql += " AND (c.student_name LIKE ? ESCAPE '\\' OR c.certificate_code LIKE ? ESCAPE '\\')"
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like]
    return query_all(sql + " ORDER BY c.id DESC", params)


# -------------------------------------------------------------- public verify
def verify(code_or_token: str) -> dict:
    """Public lookup. Returns ONLY non-private details; revoked certificates never show as valid."""
    text = (code_or_token or "").strip()[:80]
    if not text:
        raise ValidationError("Please enter a certificate ID.")
    row = query_one(
        "SELECT id, certificate_code, student_name, event_name, topic, issued_on, status, school_name, cert_type"
        " FROM certificates WHERE certificate_code=? COLLATE NOCASE OR verification_token=?", (text, text))
    with transaction() as conn:
        conn.execute("INSERT INTO certificate_verifications(certificate_id, query_text, result, verified_at)"
                     " VALUES (?,?,?,?)",
                     (row["id"] if row else None, text[:40], (row["status"] if row else "not_found"), utc_now_str()))
    if not row:
        return {"found": False, "valid": False}
    return {"found": True, "valid": row["status"] == "valid", "status": row["status"],
            "certificate_code": row["certificate_code"], "student_name": row["student_name"],
            "event_name": row["event_name"], "topic": row["topic"], "issued_on": row["issued_on"],
            "school_name": row["school_name"], "cert_type": row["cert_type"]}
