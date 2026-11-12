"""Motilal School Event Management System - run with:  streamlit run app.py"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make imports work from any folder

import streamlit as st

st.set_page_config(page_title="Motilal School Events", page_icon="🎓", layout="wide", initial_sidebar_state="auto")

import auth  # noqa: E402
from config import APP_NAME  # noqa: E402
from database import init_db  # noqa: E402
from services import backup_service  # noqa: E402
from services.settings_store import get_setting  # noqa: E402
from utils import ui  # noqa: E402
from utils.errors import AppError  # noqa: E402
from utils.helpers import setup_logging  # noqa: E402

log = logging.getLogger("mses.app")

NAV = {
    "admin": [("🏠 Dashboard", "admin_dashboard"), ("📅 Events", "event_management"),
              ("🎯 Class Assignments", "assignment_management"), ("📥 Submission Review", "submission_review"),
              ("🏅 Certificates", "certificate_management"), ("🏫 Classes & Students", "class_management"),
              ("📊 Reports", "reports"), ("👥 User Management", "user_management"),
              ("💾 Backup & Restore", "backup_restore"), ("⚙️ Settings", "settings"), ("🙍 My Profile", "profile")],
    "teacher": [("🏠 Dashboard", "teacher_dashboard"), ("📅 Events", "event_management"),
                ("🎯 Class Assignments", "assignment_management"), ("📥 Submission Review", "submission_review"),
                ("🏅 Certificates", "certificate_management"), ("🏫 Classes & Students", "class_management"),
                ("📊 Reports", "reports"), ("🙍 My Profile", "profile")],
    "student": [("🏠 My Dashboard", "student_dashboard"), ("🎯 My Events & Tasks", "student_events"),
                ("🏅 My Certificates", "student_certificates")],
}


@st.cache_resource(show_spinner=False)
def bootstrap() -> bool:
    """Runs once per server start: logging, database creation / upgrade."""
    setup_logging()
    init_db()
    return True


def logout(message: str | None = None) -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    if message:
        ui.flash(message, "info")
    st.rerun()


def render_page(role: str, page: str, actor: dict) -> None:
    if page == "student_dashboard":
        from views import student_dashboard as mod
        mod.render(actor)
    elif page == "student_events":
        from views import student_dashboard as mod
        mod.render_events(actor)
    elif page == "student_certificates":
        from views import student_dashboard as mod
        mod.render_certificates(actor)
    else:
        import importlib
        importlib.import_module(f"views.{page}").render(actor)


def main() -> None:
    ui.inject_css()
    try:
        bootstrap()
    except AppError as exc:
        st.error(str(exc))
        st.stop()
    except Exception:
        log.exception("Start-up failed")
        st.error("The application could not start. Please tell the administrator and check the logs folder.")
        st.stop()
    backup_service.auto_backup_if_due()

    token = st.query_params.get("verify")
    if token:
        from views import verify
        verify.render(str(token))
        st.stop()

    from views import login
    if auth.needs_setup():
        login.render_setup()
        return

    session = st.session_state.get("auth")
    if not session:
        login.render_login()
        return

    # session expiry after inactivity
    try:
        minutes = float(get_setting("session_timeout_minutes") or 60)
    except ValueError:
        minutes = 60
    if time.time() - session["last"] > minutes * 60:
        logout("Your session expired. Please log in again.")
    session["last"] = time.time()

    try:
        actor = auth.verify_actor(session["actor"])
    except AppError:
        logout("Please log in again.")
        return
    role = actor["role"]

    with st.sidebar:
        st.markdown(f'<div class="brand"><div class="logo">🎓</div><div><div class="name">'
                    f'{ui.e(get_setting("school_name") or "Motilal School")}</div>'
                    f'<div class="sub">Event Management</div></div></div>', unsafe_allow_html=True)
        who = {"admin": "Administrator", "teacher": "Teacher", "student": "Student"}[role]
        detail = f"{actor['class_name']}-{actor['section_name']}" if role == "student" else actor.get("username", "")
        st.markdown(f'<div class="userbox">👤 <b>{ui.e(actor["name"])}</b><br>{who} · {ui.e(detail)}</div>',
                    unsafe_allow_html=True)
        labels = [n[0] for n in NAV[role]]
        choice = st.radio("Navigate", labels, key="nav", label_visibility="collapsed")
        st.divider()
        if st.button("🚪 Log out", key="logout_btn", width="stretch"):
            logout("You have been logged out.")

    page = dict(NAV[role])[choice]
    try:
        render_page(role, page, actor)
    except AppError as exc:
        st.error(str(exc))
    except Exception:
        import uuid
        ref = uuid.uuid4().hex[:8]
        log.exception("Page error (ref %s) on %s", ref, page)
        st.error(f"Something went wrong on this page. Please try again. Reference for the administrator: {ref}")


main()
