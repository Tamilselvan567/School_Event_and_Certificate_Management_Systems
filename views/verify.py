"""Public certificate verification page (no login needed, shows only non-private details)."""
from __future__ import annotations

import streamlit as st

from services import certificate_service
from utils import ui


def _show_result(result: dict) -> None:
    if not result["found"]:
        st.error("❌ No certificate was found with this ID. Please check the ID and try again.")
        return
    if result["valid"]:
        st.success("✅ This certificate is VALID.")
    else:
        st.error("⛔ This certificate has been REVOKED and is not valid.")
    st.markdown(
        f"""<div class="pcard"><h4>{ui.e(result['school_name'])}</h4>
        <div><b>Student:</b> {ui.e(result['student_name'])}</div>
        <div><b>Event:</b> {ui.e(result['event_name'])}</div>
        <div><b>Project topic:</b> {ui.e(result['topic'])}</div>
        <div><b>Certificate type:</b> {ui.e(result['cert_type'])}</div>
        <div><b>Issue date:</b> {ui.e(result['issued_on'])}</div>
        <div><b>Certificate ID:</b> {ui.e(result['certificate_code'])}</div></div>""",
        unsafe_allow_html=True)


def render_lookup(key_prefix: str = "verify") -> None:
    code = st.text_input("Certificate ID", placeholder="MS-2026-XXXXXXXX", key=f"{key_prefix}_code")
    if st.button("Verify certificate", key=f"{key_prefix}_btn", type="primary"):
        ok, result = ui.attempt(lambda: certificate_service.verify(code))
        if ok:
            _show_result(result)


def render(token: str) -> None:
    ui.hero("Certificate Verification", "Check whether a certificate is genuine", "🔎")
    ok, result = ui.attempt(lambda: certificate_service.verify(token))
    if ok:
        _show_result(result)
    st.divider()
    st.caption("Have another certificate? Enter its ID below.")
    render_lookup("verify_page")
