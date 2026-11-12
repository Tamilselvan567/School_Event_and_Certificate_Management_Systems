"""Administrator dashboard: school overview plus system health."""
from __future__ import annotations

import streamlit as st

import database
from config import get_paths
from database import scalar
from services import backup_service
from utils import ui
from utils.helpers import human_size, utc_to_local
from views import teacher_dashboard


def render(actor: dict) -> None:
    ui.hero(f"Administrator Dashboard", f"Welcome, {actor['name']}. You can see every event in the school.", "🛠️")
    ui.show_flash()
    ui.metric_cards([
        ("Teacher accounts", scalar("SELECT COUNT(*) FROM users WHERE role='teacher' AND is_active=1"), "indigo"),
        ("Active students", scalar("SELECT COUNT(*) FROM students WHERE is_active=1"), "sky"),
        ("Classes", scalar("SELECT COUNT(*) FROM classes WHERE is_active=1"), "violet"),
        ("Certificates issued", scalar("SELECT COUNT(*) FROM certificates WHERE status='valid'"), "green")])
    teacher_dashboard.render_stats(actor)
    st.subheader("🩺 System health")
    paths = get_paths()
    backups = backup_service.list_backups()
    problems = database.integrity_check()
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Database**  \n{'✅ Healthy' if not problems else '⚠️ Needs attention'}  \n"
                f"{human_size(paths.db_path.stat().st_size) if paths.db_path.exists() else '-'}")
    c2.markdown(f"**Latest backup**  \n{utc_to_local(backups[0]['modified']) if backups else '⚠️ none yet'}")
    c3.markdown(f"**Schema version**  \n{database.current_version()}")
    if not backups:
        st.warning("No backup exists yet. Open **Backup & Restore** and create one.")
