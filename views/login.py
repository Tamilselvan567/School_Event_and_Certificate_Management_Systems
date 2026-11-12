"""First-run setup, staff login and password-free student login."""
from __future__ import annotations

import time
from datetime import date

import streamlit as st

import auth
from services import admin_service as adm
from services.settings_store import get_setting
from utils import ui
from utils.errors import AppError
from utils.helpers import class_label
from views import verify

STUDENT_MAX_FAILS = 8
STUDENT_LOCK_SECONDS = 300


def _start_session(actor: dict) -> None:
    st.session_state["auth"] = {"actor": actor, "last": time.time()}
    st.session_state.pop("nav", None)
    st.rerun()


def _default_year() -> str:
    today = date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def render_setup() -> None:
    ui.hero("Welcome! Let's set up your school", "Create the first administrator account. This is done only once.", "🎓")
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        with st.form("setup_form"):
            school = st.text_input("School name", value="Motilal School")
            principal = st.text_input("Principal name (printed on certificates)")
            year = st.text_input("Current academic year", value=_default_year())
            st.markdown("**Administrator account**")
            full_name = st.text_input("Your full name")
            username = st.text_input("Choose a username")
            password = st.text_input("Choose a password", type="password",
                                     help="At least 8 characters, with letters and numbers.")
            confirm = st.text_input("Type the password again", type="password")
            code = st.text_input("Setup code", type="password") if auth.setup_code_required() else ""
            submitted = st.form_submit_button("Create administrator account", type="primary", width="stretch")
        if submitted:
            if password != confirm:
                st.error("The two passwords do not match.")
            else:
                ok, actor = ui.attempt(lambda: auth.setup_admin(username, password, full_name, school, principal,
                                                                year, code))
                if ok:
                    ui.flash("Setup complete. Welcome!")
                    _start_session(actor)


def render_login() -> None:
    school = get_setting("school_name") or "Motilal School"
    ui.hero(school, "Event & Project Management Portal", "🎓")
    ui.show_flash()
    tab_student, tab_staff, tab_verify = st.tabs(["🎒 Student Login", "👩‍🏫 Teacher / Admin Login", "🔎 Verify a Certificate"])
    with tab_student:
        _student_login()
    with tab_staff:
        _staff_login()
    with tab_verify:
        verify.render_lookup(key_prefix="login_verify")


def _student_login() -> None:
    st.caption("No password needed. Enter the same details your teacher has on record.")
    classes = adm.list_classes(include_inactive=False)
    if not classes:
        ui.empty_state("Your school has not set up classes yet. Please ask your teacher.", "🏫")
        return
    c1, c2 = st.columns(2)
    class_id = c1.selectbox("Class", [c["id"] for c in classes], index=None, placeholder="Choose your class",
                            format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)),
                            key="stu_class")
    sections = adm.list_sections(class_id, include_inactive=False) if class_id else []
    section_id = c2.selectbox("Section", [s["id"] for s in sections], index=None, placeholder="Choose your section",
                              format_func=lambda i: next(s["name"] for s in sections if s["id"] == i), key="stu_section")
    name = st.text_input("Your full name", key="stu_name")
    roll = st.text_input("Roll number", key="stu_roll")
    if st.button("Enter my dashboard", type="primary", key="stu_go", width="stretch"):
        now = time.time()
        locked_until = st.session_state.get("_stu_locked", 0)
        if now < locked_until:
            st.error("Too many tries. Please wait a few minutes and ask your teacher for help.")
            return
        try:
            actor = auth.login_student(name, class_id, section_id, roll)
        except AppError as exc:
            fails = st.session_state.get("_stu_fails", 0) + 1
            st.session_state["_stu_fails"] = fails
            if fails >= STUDENT_MAX_FAILS:
                st.session_state["_stu_locked"] = now + STUDENT_LOCK_SECONDS
                st.session_state["_stu_fails"] = 0
            st.error(str(exc))
            return
        st.session_state["_stu_fails"] = 0
        _start_session(actor)


def _staff_login() -> None:
    with st.form("staff_login"):
        username = st.text_input("Username", key="staff_user")
        password = st.text_input("Password", type="password", key="staff_pass")
        submitted = st.form_submit_button("Log in", type="primary", width="stretch")
    if submitted:
        ok, actor = ui.attempt(lambda: auth.login_staff(username, password))
        if ok:
            _start_session(actor)
