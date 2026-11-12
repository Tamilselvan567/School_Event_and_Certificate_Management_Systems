"""Administrator settings: school details, logo, certificate design, uploads, backups."""
from __future__ import annotations

import streamlit as st

from config import HARD_MAX_UPLOAD_MB, SUPPORTED_EXTENSIONS, get_paths
from services import admin_service as adm
from services import certificate_service
from services.settings_store import get_all_settings
from utils import ui


def render(actor: dict) -> None:
    ui.hero("Settings", "Change how the school portal and certificates look and behave", "⚙️")
    ui.show_flash()
    s = get_all_settings()
    years = adm.list_years()
    t_school, t_cert, t_upload, t_system = st.tabs(["🏫 School", "🏅 Certificates", "⬆️ Uploads", "🛡️ Backups & security"])

    with t_school:
        with st.form("settings_school"):
            name = st.text_input("School name", value=s["school_name"], key="set_name")
            principal = st.text_input("Principal name", value=s["principal_name"], key="set_principal")
            c1, c2 = st.columns(2)
            phone = c1.text_input("Contact phone", value=s["school_phone"], key="set_phone")
            email = c2.text_input("Contact email", value=s["school_email"], key="set_email")
            address = st.text_input("School address", value=s["school_address"], key="set_addr")
            ids = [y["id"] for y in years]
            cur = int(s["default_academic_year"]) if str(s["default_academic_year"]).isdigit() and int(s["default_academic_year"]) in ids else (ids[0] if ids else None)
            year = st.selectbox("Default academic year", ids, index=ids.index(cur) if cur in ids else 0, key="set_year",
                                format_func=lambda i: next(y["name"] for y in years if y["id"] == i)) if ids else None
            cats = st.text_input("Event categories (separated by commas)", value=s["event_categories"], key="set_cats")
            base_url = st.text_input("Public website address (used in certificate QR codes)", value=s["public_base_url"],
                                     placeholder="https://your-school-site.example.com", key="set_url")
            if st.form_submit_button("Save school settings", type="primary"):
                vals = {"school_name": name, "principal_name": principal, "school_phone": phone, "school_email": email,
                        "school_address": address, "event_categories": cats, "public_base_url": base_url}
                if year:
                    vals["default_academic_year"] = str(year)
                ok, _ = ui.attempt(lambda: adm.update_settings(actor, vals), "Settings saved.")
        st.markdown("#### School logo")
        _asset_block(actor, "school_logo", "logo_dir", s, adm.save_school_logo, "logo")

    with t_cert:
        with st.form("settings_cert"):
            c1, c2, c3 = st.columns(3)
            primary = c1.color_picker("Main colour", value=s["cert_primary_color"], key="set_c1")
            secondary = c2.color_picker("Second colour", value=s["cert_secondary_color"], key="set_c2")
            accent = c3.color_picker("Accent colour", value=s["cert_accent_color"], key="set_c3")
            ctype = st.selectbox("Default certificate type", ["Participation", "Achievement"],
                                 index=0 if s["cert_default_type"] != "Achievement" else 1, key="set_ctype",
                                 help="Teachers can choose a different type for each approval.")
            footer = st.text_input("Footer text (optional)", value=s["cert_footer_text"], key="set_footer")
            if st.form_submit_button("Save certificate design", type="primary"):
                ui.attempt(lambda: adm.update_settings(actor, {
                    "cert_primary_color": primary, "cert_secondary_color": secondary, "cert_accent_color": accent,
                    "cert_default_type": ctype, "cert_footer_text": footer}), "Certificate design saved.")
        st.markdown("#### Principal signature image (optional)")
        st.caption("Upload a scanned signature (PNG or JPG). Without it, a blank signature line is printed.")
        _asset_block(actor, "principal_signature", "signatures_dir", s, adm.save_principal_signature, "signature")
        ok, pdf = ui.attempt(lambda: certificate_service.sample_certificate_pdf(actor))
        if ok:
            st.download_button("👁️ Download a sample certificate to preview the design", pdf, file_name="sample_certificate.pdf",
                               mime="application/pdf", key="sample_cert")

    with t_upload:
        with st.form("settings_upload"):
            mb = st.number_input(f"Largest file a student may upload (MB, up to {HARD_MAX_UPLOAD_MB})", min_value=0.1,
                                 max_value=float(HARD_MAX_UPLOAD_MB), value=float(s["max_upload_mb"]), step=1.0, key="set_mb")
            exts = st.multiselect("Allowed file types", list(SUPPORTED_EXTENSIONS),
                                  default=[e for e in s["allowed_extensions"].split(",") if e in SUPPORTED_EXTENSIONS],
                                  format_func=str.upper, key="set_exts")
            if st.form_submit_button("Save upload settings", type="primary"):
                ui.attempt(lambda: adm.update_settings(actor, {"max_upload_mb": str(mb), "allowed_extensions": ",".join(exts)}),
                           "Upload settings saved.")

    with t_system:
        with st.form("settings_backup"):
            enabled = st.checkbox("Create automatic backups", value=s["backup_enabled"] == "1", key="set_bk_on")
            c1, c2 = st.columns(2)
            hours = c1.number_input("Make a backup every (hours)", min_value=1, max_value=720,
                                    value=int(float(s["backup_interval_hours"])), key="set_bk_h")
            keep = c2.number_input("Keep the newest automatic backups", min_value=1, max_value=365,
                                   value=int(float(s["backup_keep_count"])), key="set_bk_keep")
            files = st.checkbox("Include uploaded files and certificates in backups", value=s["backup_include_files"] == "1",
                                key="set_bk_files")
            timeout = st.number_input("Log people out after (minutes without activity)", min_value=5, max_value=1440,
                                      value=int(float(s["session_timeout_minutes"])), key="set_timeout")
            if st.form_submit_button("Save", type="primary"):
                ui.attempt(lambda: adm.update_settings(actor, {
                    "backup_enabled": "1" if enabled else "0", "backup_interval_hours": str(hours),
                    "backup_keep_count": str(keep), "backup_include_files": "1" if files else "0",
                    "session_timeout_minutes": str(timeout)}), "Saved.")
        p = get_paths()
        st.markdown("#### Where your data is stored")
        st.code(f"Database:     {p.db_path}\nUploads:      {p.uploads_dir}\nCertificates: {p.certificates_dir}\n"
                f"Backups:      {p.backups_dir}", language="text")


def _asset_block(actor, key: str, folder_attr: str, s: dict, saver, label: str) -> None:
    current = s.get(key, "")
    data = adm.read_asset(folder_attr, current) if current else None
    if data:
        st.image(data, width=160, caption=f"Current {label}")
    up = st.file_uploader(f"Upload {label} (PNG or JPG)", type=["png", "jpg", "jpeg"], key=f"up_{key}")
    c1, c2 = st.columns(2)
    if c1.button(f"Save {label}", key=f"save_{key}", disabled=up is None):
        ok, _ = ui.attempt(lambda: saver(actor, up.name, up.getvalue()))
        if ok:
            ui.flash(f"The {label} was saved.")
            st.rerun()
    if data and c2.button(f"Remove {label}", key=f"rm_{key}"):
        ok, _ = ui.attempt(lambda: adm.clear_asset_setting(actor, key))
        if ok:
            ui.flash(f"The {label} was removed.")
            st.rerun()
