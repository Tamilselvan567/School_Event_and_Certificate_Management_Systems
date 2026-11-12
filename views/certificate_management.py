"""Certificate management: list, download, revoke / restore, administrator regenerate."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import certificate_service, event_service
from utils import ui
from utils.helpers import class_label


def render(actor: dict) -> None:
    ui.hero("Certificate Management", "Certificates are created by students after you approve their work", "🏅")
    ui.show_flash()
    ok, events = ui.attempt(lambda: event_service.list_events(actor))
    c1, c2 = st.columns([2, 2])
    ev_id = c1.selectbox("Event", [0] + [e["id"] for e in (events or [])], key="cm_event",
                         format_func=lambda i: "All events" if i == 0 else next(e["name"] for e in events if e["id"] == i))
    search = c2.text_input("Search by student name or certificate ID", key="cm_search")
    ok, certs = ui.attempt(lambda: certificate_service.list_certificates(actor, ev_id or None, search))
    if not ok:
        return
    if not certs:
        ui.empty_state("No certificates have been generated yet. They appear here after approved students create them.", "🏅")
        return
    st.dataframe(pd.DataFrame([{"Certificate ID": c["certificate_code"], "Student": c["student_name"],
                                "Class": f"{class_label(c['class_name'])}-{c['section_name']}", "Roll": c["roll_number"],
                                "Event": c["event_name"], "Topic": c["topic"], "Type": c["cert_type"],
                                "Issued": c["issued_on"], "Status": c["status"].title()} for c in certs]),
                 hide_index=True, width="stretch")
    ids = [c["id"] for c in certs]
    sel = st.selectbox("Choose a certificate", ids, key="cm_select",
                       format_func=lambda i: next(f"{c['certificate_code']} · {c['student_name']} · {c['status']}"
                                                  for c in certs if c["id"] == i))
    cert = next(c for c in certs if c["id"] == sel)
    cols = st.columns(3)
    if cert["status"] == "valid":
        ok, pdf = ui.attempt(lambda: certificate_service.get_certificate_pdf(actor, sel))
        if ok:
            cols[0].download_button("⬇️ Download PDF", pdf[1], file_name=pdf[0], mime="application/pdf", key=f"cm_dl_{sel}")
        reason = st.text_input("Reason for revoking (required)", key=f"cm_reason_{sel}")
        if cols[1].button("⛔ Revoke certificate", key=f"cm_rev_{sel}"):
            ok, _ = ui.attempt(lambda: certificate_service.set_revoked(actor, sel, True, reason))
            if ok:
                ui.flash("Certificate revoked. It will no longer verify as valid.")
                st.rerun()
    else:
        st.error(f"Revoked: {cert['revoked_reason'] or 'no reason recorded'}")
        if cols[1].button("♻️ Restore certificate", key=f"cm_res_{sel}"):
            ok, _ = ui.attempt(lambda: certificate_service.set_revoked(actor, sel, False))
            if ok:
                ui.flash("Certificate restored.")
                st.rerun()
    if actor["role"] == "admin":
        if cols[2].button("🔄 Regenerate PDF (admin)", key=f"cm_regen_{sel}",
                          help="Rebuilds the PDF with the current logo, signatures and principal name. The ID stays the same."):
            ok, _ = ui.attempt(lambda: certificate_service.regenerate(actor, sel))
            if ok:
                ui.flash("Certificate PDF regenerated with the same certificate ID.")
                st.rerun()
    st.caption(f"Public verification link: {certificate_service.verification_url('<verification-token>')}")
