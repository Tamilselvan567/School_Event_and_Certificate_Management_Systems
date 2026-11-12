"""Student pages: dashboard, my events & tasks (with upload), my certificates."""
from __future__ import annotations

import streamlit as st

from services import certificate_service, event_service, submission_service
from utils import ui
from utils.helpers import (APPROVED, PENDING_STATUSES, REJECTED, RESUBMISSION_REQUIRED, fmt_local, fmt_date,
                           human_size, utc_to_local, class_label)


def _identity_line(actor: dict) -> str:
    return f"{class_label(actor['class_name'])} · Section {actor['section_name']} · Roll No. {actor['roll']}"


def render(actor: dict) -> None:
    ui.hero(f"Welcome, {actor['name']}! 👋", _identity_line(actor), "🎒")
    ui.show_flash()
    ok, tasks = ui.attempt(lambda: event_service.student_assignments(actor))
    if not ok:
        return
    pending = sum(1 for t in tasks if t["status_label"] in PENDING_STATUSES)
    approved = sum(1 for t in tasks if t["status_label"] == APPROVED)
    fix = sum(1 for t in tasks if t["status_label"] in (REJECTED, RESUBMISSION_REQUIRED))
    todo = sum(1 for t in tasks if t["status_label"] == "Not Started" and t["event_status"] == "published")
    ui.metric_cards([("My tasks", len(tasks), "indigo"), ("To do", todo, "pink"), ("Waiting for review", pending, "amber"),
                     ("Need correction", fix, "red"), ("Approved", approved, "green")])
    left, right = st.columns([3, 2])
    with left:
        st.subheader("⏰ Upcoming deadlines")
        upcoming = [t for t in tasks if t["status_label"] in ("Not Started", REJECTED, RESUBMISSION_REQUIRED)
                    and not t["deadline_passed"] and t["event_status"] == "published"]
        if not upcoming:
            ui.empty_state("No deadlines coming up. Well done!", "🎉")
        for t in upcoming[:6]:
            st.markdown(
                f'<div class="pcard"><h4>{ui.e(t["event_name"])} — {ui.e(t["topic"])}</h4>'
                f'<div class="muted">Deadline: <b>{ui.e(fmt_local(t["deadline"]))}</b></div>'
                f'<div style="margin-top:.4rem">{ui.status_badge(t["status_label"])}</div></div>', unsafe_allow_html=True)
    with right:
        st.subheader("💬 Teacher feedback")
        ok, feedback = ui.attempt(lambda: submission_service.student_recent_feedback(actor))
        if ok and not feedback:
            ui.empty_state("No feedback yet.", "💬")
        for f in (feedback or []):
            ui.feedback_box(f"{f['event_name']} — {f['new_status']}: {f['feedback'] or 'Approved. Great work!'}",
                            approved=f["new_status"] == APPROVED)
    st.info("Open **My Events & Tasks** in the left menu to read instructions and upload your work.")


# ------------------------------------------------------------------ tasks page
def render_events(actor: dict) -> None:
    ui.hero("My Events & Tasks", "Only the tasks assigned to your class and section are shown here", "🎯")
    ui.show_flash()
    ok, tasks = ui.attempt(lambda: event_service.student_assignments(actor))
    if not ok:
        return
    open_id = st.session_state.get("open_assignment")
    if open_id:
        match = next((t for t in tasks if t["assignment_id"] == open_id), None)
        if match:
            _detail(actor, match)
            return
        st.session_state.pop("open_assignment", None)
    if not tasks:
        ui.empty_state("No events have been assigned to your class yet. Please check again later.", "📭")
        return
    for t in tasks:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1.4])
            with c1:
                st.markdown(f"#### {t['event_name']}")
                st.markdown(f"**Topic:** {t['topic']}")
                st.markdown(
                    f'<span class="muted">{ui.e(t["category"])} · Deadline: <b>{ui.e(fmt_local(t["deadline"]))}</b>'
                    f'{" · ⏳ opens " + ui.e(fmt_date(t["opens_on"])) if t["not_open_yet"] else ""}'
                    f'{" · 🔒 closed" if t["event_status"] == "closed" else ""}</span>', unsafe_allow_html=True)
            with c2:
                st.markdown(ui.status_badge(t["status_label"]), unsafe_allow_html=True)
                if st.button("Open", key=f"open_{t['assignment_id']}", width="stretch"):
                    st.session_state["open_assignment"] = t["assignment_id"]
                    st.rerun()


def _detail(actor: dict, t: dict) -> None:
    if st.button("← Back to my events", key="back_events"):
        st.session_state.pop("open_assignment", None)
        st.rerun()
    st.markdown(f"## {t['event_name']}")
    st.markdown(ui.status_badge(t["status_label"]), unsafe_allow_html=True)
    if t["has_poster"]:
        poster = None
        try:
            poster = event_service.read_poster(actor, t["event_id"])
        except Exception:
            poster = None
        if poster:
            st.image(poster, width=360)
    if t["event_description"]:
        st.write(t["event_description"])
    if t["event_instructions"]:
        with st.expander("📋 General instructions for this event", expanded=False):
            st.write(t["event_instructions"])

    st.markdown("### 🎯 Your task")
    st.markdown(f"**Topic:** {t['topic']}")
    if t["task_description"]:
        st.write(t["task_description"])
    if t["task_instructions"]:
        st.markdown("**Detailed instructions**")
        st.write(t["task_instructions"])
    cols = st.columns(3)
    cols[0].markdown(f"**Deadline**  \n{fmt_local(t['deadline'])}")
    cols[1].markdown("**Accepted files**  \n" + ", ".join(f.upper() for f in t["allowed_formats"].split(",")))
    cols[2].markdown(f"**Maximum marks**  \n{t['max_marks']:g}" if t["max_marks"] else "**Maximum marks**  \nNot marked")
    if t["criteria"]:
        st.markdown("**How your work will be judged**")
        st.write(t["criteria"])
    if t["has_reference"]:
        ok, ref = ui.attempt(lambda: event_service.read_reference(actor, t["assignment_id"]))
        if ok:
            st.download_button(f"📎 Download reference material ({ref[0]})", ref[1], file_name=ref[0],
                               key=f"ref_{t['assignment_id']}")

    sub = submission_service.student_submission(actor, t["assignment_id"])
    st.markdown("### 📌 Status & feedback")
    if not sub:
        st.info("You have not submitted anything yet.")
    else:
        for r in sub["reviews"]:
            ui.feedback_box(f"{r['reviewer']} · {utc_to_local(r['created_at'])} · {r['new_status']}"
                            + (f" · Marks: {r['marks']:g}" if r["marks"] is not None else "")
                            + f"\n\n{r['feedback'] or 'Approved. Great work!'}", approved=r["new_status"] == APPROVED)
        st.markdown("**My uploads**")
        for v in sub["versions"]:
            c1, c2 = st.columns([4, 1.4])
            c1.markdown(f"Version {v['version_no']} — **{v['original_filename']}** ({human_size(v['file_size'])}) · "
                        f"uploaded {utc_to_local(v['uploaded_at'])}")
            with c2:
                ok, f = ui.attempt(lambda vid=v["id"]: submission_service.download_version(actor, vid))
                if ok:
                    st.download_button("Download", f[1], file_name=f[0], mime=f[2], key=f"dl_{v['id']}")

    # ---- upload area
    if t["can_submit"]:
        st.markdown("### ⬆️ Upload your work" if t["status_label"] == "Not Started" else "### ⬆️ Upload a corrected version")
        counter = st.session_state.get("upload_counter", 0)
        allowed = t["allowed_formats"].split(",")
        f = st.file_uploader("Choose your file", type=allowed, key=f"up_{t['assignment_id']}_{counter}",
                             help="Accepted: " + ", ".join(a.upper() for a in allowed))
        if f is not None:
            st.caption(f"Selected: **{f.name}** ({human_size(f.size)})")
        if st.button("Submit my work", type="primary", key=f"submit_{t['assignment_id']}", disabled=f is None):
            with st.spinner("Uploading your file…"):
                ok, res = ui.attempt(lambda: submission_service.submit_work(actor, t["assignment_id"], f.name, f.getvalue()))
            if ok:
                ui.flash(f"✅ Submitted! '{res['filename']}' was uploaded on {utc_to_local(res['uploaded_at'])}. "
                         "Your teacher will review it.")
                st.session_state["upload_counter"] = counter + 1
                st.rerun()
    else:
        reason = None
        if t["status_label"] in PENDING_STATUSES:
            reason = "Your work is waiting for your teacher's review."
        elif t["status_label"] == APPROVED:
            reason = None
        elif t["event_status"] == "closed":
            reason = "This event is closed, so new uploads are not accepted."
        elif t["not_open_yet"]:
            reason = f"Submissions open on {fmt_date(t['opens_on'])}."
        elif t["deadline_passed"]:
            reason = "The deadline has passed. Please talk to your teacher if you need more time."
        if reason:
            st.warning(reason)

    # ---- certificate (only after teacher approval)
    st.markdown("### 🏅 Certificate")
    if t["status_label"] != APPROVED:
        st.info("🔒 Your certificate will be available here after your teacher approves your work.")
    else:
        cert = certificate_service.certificate_for_student_submission(actor, t["submission_id"])
        if cert is None:
            if st.button("🏅 Generate my certificate", type="primary", key=f"gen_{t['submission_id']}"):
                ok, _ = ui.attempt(lambda: certificate_service.generate_for_submission(actor, t["submission_id"]))
                if ok:
                    ui.flash("Your certificate is ready. You can download it below.")
                    st.rerun()
        elif cert["status"] == "revoked":
            st.error("This certificate has been revoked. Please contact your teacher.")
        else:
            ok, pdf = ui.attempt(lambda: certificate_service.get_certificate_pdf(actor, cert["id"]))
            if ok:
                st.success(f"Certificate ID: {cert['certificate_code']}")
                st.download_button("⬇️ Download Certificate (PDF)", pdf[1], file_name=pdf[0], mime="application/pdf",
                                   key=f"cert_dl_{cert['id']}", type="primary")


# ----------------------------------------------------------- certificates page
def render_certificates(actor: dict) -> None:
    ui.hero("My Certificates", "Certificates are available after your teacher approves your work", "🏅")
    ui.show_flash()
    ok, tasks = ui.attempt(lambda: event_service.student_assignments(actor))
    if not ok:
        return
    approved = [t for t in tasks if t["status_label"] == APPROVED]
    if not approved:
        ui.empty_state("No approved work yet. Keep going — your certificate will appear here!", "🏅")
        return
    for t in approved:
        cert = certificate_service.certificate_for_student_submission(actor, t["submission_id"])
        with st.container(border=True):
            st.markdown(f"#### {t['event_name']} — {t['topic']}")
            if cert is None:
                if st.button("🏅 Generate certificate", key=f"cgen_{t['submission_id']}", type="primary"):
                    ok, _ = ui.attempt(lambda: certificate_service.generate_for_submission(actor, t["submission_id"]))
                    if ok:
                        ui.flash("Your certificate is ready.")
                        st.rerun()
            elif cert["status"] == "revoked":
                st.error("This certificate has been revoked.")
            else:
                ok, pdf = ui.attempt(lambda: certificate_service.get_certificate_pdf(actor, cert["id"]))
                if ok:
                    st.caption(f"Certificate ID: {cert['certificate_code']} · Issued {cert['issued_on']}")
                    st.download_button("⬇️ Download Certificate (PDF)", pdf[1], file_name=pdf[0], mime="application/pdf",
                                       key=f"cdl_{cert['id']}", type="primary")
