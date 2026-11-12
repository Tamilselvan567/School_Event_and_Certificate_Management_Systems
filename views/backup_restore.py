"""Administrator: backups, restore, health checks, audit trail."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import database
from auth import require_admin
from services import admin_service as adm
from services import backup_service
from utils import ui
from utils.helpers import human_size, utc_to_local


def render(actor: dict) -> None:
    ui.hero("Backup & Restore", "Keep a safe copy of everything: database, uploads and certificates", "💾")
    ui.show_flash()
    ok, _ = ui.attempt(lambda: require_admin(actor))
    if not ok:
        return
    t_back, t_restore, t_health, t_audit = st.tabs(["💾 Backups", "♻️ Restore", "🩺 Health check", "📜 Activity log"])

    with t_back:
        include = st.checkbox("Include uploaded files and certificates (recommended)", value=True, key="bk_include")
        if st.button("Create a backup now", type="primary", key="bk_create"):
            with st.spinner("Creating backup…"):
                ok, path = ui.attempt(lambda: backup_service.admin_create_backup(actor, include))
            if ok:
                ui.flash(f"Backup created: {path.name}")
                st.rerun()
        ok, backups = ui.attempt(lambda: backup_service.admin_list_backups(actor))
        backups = backups or []
        if not backups:
            ui.empty_state("No backups yet. Click the button above to make your first one.", "💾")
        else:
            st.dataframe(pd.DataFrame([{"File": b["name"], "Size": human_size(b["size"]),
                                        "Created": utc_to_local(b["modified"])} for b in backups]),
                         hide_index=True, width="stretch")
            pick = st.selectbox("Download a backup to keep it somewhere safe", [b["name"] for b in backups], key="bk_pick")
            ok, data = ui.attempt(lambda: backup_service.admin_read_backup(actor, pick))
            if ok:
                st.download_button("⬇️ Download this backup", data, file_name=pick, mime="application/zip", key="bk_dl")
        st.caption("Tip: download a backup regularly and keep a copy on a different computer or cloud drive.")

    with t_restore:
        st.warning("Restoring replaces the school's current data with the data inside the backup. "
                   "A safety copy of the current database is made first.")
        up = st.file_uploader("Choose a backup file (.zip made by this application)", type=["zip", "db"], key="restore_file")
        sure = st.checkbox("I understand that current data will be replaced", key="restore_sure")
        word = st.text_input("Type RESTORE to confirm", key="restore_word")
        if st.button("Restore from this backup", key="restore_go", disabled=up is None or not sure or word.strip() != "RESTORE"):
            with st.spinner("Restoring…"):
                ok, res = ui.attempt(lambda: backup_service.admin_restore(actor, up.getvalue()))
            if ok:
                ui.flash(f"Restore finished. {res['files_restored']} file(s) restored. "
                         f"A safety copy was saved as {res['safety_backup']}.")
                st.rerun()

    with t_health:
        if st.button("Run health check", key="health_go"):
            problems = database.integrity_check()
            if problems:
                st.error("Database problems found: " + "; ".join(problems[:5]))
            else:
                st.success("The database is healthy.")
            report = backup_service.admin_check_consistency(actor)
            if report["missing_uploads"] or report["missing_certificates"]:
                st.warning(f"{len(report['missing_uploads'])} uploaded file(s) and "
                           f"{len(report['missing_certificates'])} certificate file(s) are missing on disk. "
                           "Missing certificates are rebuilt automatically when someone downloads them; "
                           "missing uploads must be restored from a backup or uploaded again.")
                if report["missing_uploads"]:
                    st.dataframe(pd.DataFrame(report["missing_uploads"]), hide_index=True, width="stretch")
            else:
                st.success("All uploaded files and certificates listed in the database are present.")
            st.caption(f"Files on disk that are not in the database: {report['orphan_files']}")

    with t_audit:
        ok, rows = ui.attempt(lambda: adm.recent_audit(actor, 300))
        if ok and rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        elif ok:
            ui.empty_state("No activity recorded yet.", "📜")
