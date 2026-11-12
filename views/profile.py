"""My profile: change password and upload a signature image for certificates."""
from __future__ import annotations

import streamlit as st

from services import admin_service as adm
from utils import ui
from database import query_one


def render(actor: dict) -> None:
    ui.hero("My Profile", f"{actor['name']} · {actor['role'].title()}", "🙍")
    ui.show_flash()
    st.subheader("🔑 Change my password")
    with st.form("change_pw_form", clear_on_submit=True):
        old = st.text_input("Current password", type="password", key="pw_old")
        new = st.text_input("New password", type="password", key="pw_new")
        again = st.text_input("New password again", type="password", key="pw_again")
        if st.form_submit_button("Change password", type="primary"):
            if new != again:
                st.error("The new passwords do not match.")
            else:
                ui.attempt(lambda: adm.change_own_password(actor, old, new), "Your password was changed.")
    st.subheader("✍️ My signature on certificates")
    st.caption("Optional. Upload a scan of your signature (PNG or JPG). It is printed above your name on certificates you approve.")
    row = query_one("SELECT signature_path FROM users WHERE id=?", (actor["id"],))
    data = adm.read_asset("signatures_dir", row["signature_path"]) if row and row["signature_path"] else None
    if data:
        st.image(data, width=200, caption="Current signature")
    up = st.file_uploader("Signature image", type=["png", "jpg", "jpeg"], key="my_sig")
    c1, c2 = st.columns(2)
    if c1.button("Save signature", key="sig_save", disabled=up is None):
        ok, _ = ui.attempt(lambda: adm.save_my_signature(actor, up.name, up.getvalue()))
        if ok:
            ui.flash("Signature saved.")
            st.rerun()
    if data and c2.button("Remove signature", key="sig_rm"):
        ok, _ = ui.attempt(lambda: adm.remove_my_signature(actor))
        if ok:
            ui.flash("Signature removed.")
            st.rerun()
