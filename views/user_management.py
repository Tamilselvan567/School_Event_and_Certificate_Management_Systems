"""Administrator: manage teacher accounts."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import admin_service as adm
from utils import ui
from utils.helpers import utc_to_local


def render(actor: dict) -> None:
    ui.hero("User Management", "Create teacher accounts, edit details, reset passwords, deactivate", "👥")
    ui.show_flash()
    t_list, t_new = st.tabs(["👥 Accounts", "➕ Create account"])
    with t_new:
        g = ui.form_gen("create_user")
        with st.form("create_user_form"):
            c1, c2 = st.columns(2)
            full_name = c1.text_input("Full name", key=f"cu_name_{g}")
            designation = c2.text_input("Designation (optional)", key=f"cu_desig_{g}")
            c3, c4 = st.columns(2)
            username = c3.text_input("Username", key=f"cu_user_{g}")
            password = c4.text_input("Temporary password", type="password", key=f"cu_pass_{g}",
                                     help="At least 8 characters with letters and numbers.")
            role = st.selectbox("Role", ["teacher", "admin"], key=f"cu_role_{g}",
                                format_func=lambda r: "Teacher" if r == "teacher" else "Administrator")
            if st.form_submit_button("Create account", type="primary"):
                ok, _ = ui.attempt(lambda: adm.create_user(actor, username, password, full_name, designation, role))
                if ok:
                    ui.form_done("create_user")
                    ui.flash(f"Account '{username}' created. Share the username and password with the teacher privately.")
                    st.rerun()
    with t_list:
        ok, users = ui.attempt(lambda: adm.list_users(actor))
        if not ok:
            return
        st.dataframe(pd.DataFrame([{"Username": u["username"], "Name": u["full_name"], "Designation": u["designation"] or "",
                                    "Role": u["role"].title(), "Active": "Yes" if u["is_active"] else "No",
                                    "Last login": utc_to_local(u["last_login_at"])} for u in users]),
                     hide_index=True, width="stretch")
        uid = st.selectbox("Select an account", [u["id"] for u in users], key="um_select",
                           format_func=lambda i: next(f"{u['full_name']} ({u['username']})" for u in users if u["id"] == i))
        cur = next(u for u in users if u["id"] == uid)
        with st.expander("✏️ Edit details", expanded=True):
            with st.form(f"edit_user_{uid}"):
                n = st.text_input("Full name", value=cur["full_name"], key=f"eun_{uid}")
                d = st.text_input("Designation", value=cur["designation"] or "", key=f"eud_{uid}")
                if st.form_submit_button("Save details"):
                    ok, _ = ui.attempt(lambda: adm.update_user(actor, uid, n, d))
                    if ok:
                        ui.flash("Details saved.")
                        st.rerun()
        c1, c2 = st.columns(2)
        with c1:
            with st.expander("🔑 Reset password"):
                with st.form(f"reset_pw_{uid}"):
                    pw = st.text_input("New password", type="password", key=f"rp_{uid}")
                    if st.form_submit_button("Reset password"):
                        ok, _ = ui.attempt(lambda: adm.reset_password(actor, uid, pw))
                        if ok:
                            st.success("Password changed. Tell the teacher their new password privately.")
        with c2:
            with st.expander("⏻ Activate / deactivate"):
                if cur["is_active"]:
                    if st.button("Deactivate this account", key=f"deact_{uid}"):
                        ok, _ = ui.attempt(lambda: adm.set_user_active(actor, uid, False))
                        if ok:
                            ui.flash("Account deactivated. The person can no longer log in.")
                            st.rerun()
                else:
                    if st.button("Activate this account", key=f"act_{uid}", type="primary"):
                        ok, _ = ui.attempt(lambda: adm.set_user_active(actor, uid, True))
                        if ok:
                            ui.flash("Account activated.")
                            st.rerun()
        with st.expander("🔁 Move all events from this account to another teacher"):
            others = [u for u in users if u["id"] != uid and u["is_active"]]
            if others:
                target = st.selectbox("New owner", [u["id"] for u in others], key=f"mv_{uid}",
                                      format_func=lambda i: next(u["full_name"] for u in others if u["id"] == i))
                if st.button("Move events", key=f"mvbtn_{uid}"):
                    ok, n = ui.attempt(lambda: adm.reassign_events(actor, uid, target))
                    if ok:
                        ui.flash(f"{n} event(s) moved.")
                        st.rerun()
            else:
                st.caption("There is no other active account.")
