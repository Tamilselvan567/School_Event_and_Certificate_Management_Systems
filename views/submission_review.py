"""Teacher review: view uploads, give feedback, approve / reject / request corrections."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import admin_service as adm
from services import event_service, submission_service
from utils import ui
from utils.helpers import (APPROVED, ALL_STATUSES, class_label, fmt_local, human_size, utc_to_local, STORED_STATUSES)

IMAGE_EXT = (".png", ".jpg", ".jpeg")


def render(actor: dict) -> None:
    ui.hero("Submission Review", "Look at student work, give feedback and decide", "📥")
    ui.show_flash()
    ok, events = ui.attempt(lambda: event_service.list_events(actor))
    classes = adm.list_classes()
    c1, c2, c3, c4 = st.columns([2, 1.4, 1.4, 1.6])
    ev_id = c1.selectbox("Event", [0] + [e["id"] for e in (events or [])], key="rv_event",
                         format_func=lambda i: "All events" if i == 0 else next(e["name"] for e in events if e["id"] == i))
    status = c2.selectbox("Status", ["pending", "all"] + list(STORED_STATUSES), key="rv_status",
                          format_func=lambda s: {"pending": "Waiting for review", "all": "All statuses"}.get(s, s))
    class_id = c3.selectbox("Class", [0] + [c["id"] for c in classes], key="rv_class",
                            format_func=lambda i: "All classes" if i == 0 else class_label(
                                next(c["name"] for c in classes if c["id"] == i)))
    search = c4.text_input("Search student / roll", key="rv_search")
    ok, rows = ui.attempt(lambda: submission_service.list_review_queue(
        actor, ev_id or None, None if status == "all" else status, class_id or None, search))
    if not ok:
        return
    if not rows:
        ui.empty_state("Nothing to show here. When students submit work it will appear in this list.", "📥")
        return
    df = pd.DataFrame([{"ID": r["id"], "Student": r["student_name"],
                        "Class": f"{class_label(r['class_name'])}-{r['section_name']}", "Roll": r["roll_number"],
                        "Event": r["event_name"], "Topic": r["topic"], "Status": r["status"],
                        "Version": r["current_version"], "Uploaded": utc_to_local(r["uploaded_at"])} for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    ids = [r["id"] for r in rows]
    current = st.session_state.get("review_id")
    sel = st.selectbox("Choose a submission to review", ids, index=ids.index(current) if current in ids else 0,
                       key="rv_select",
                       format_func=lambda i: next(f"#{r['id']} · {r['student_name']} · {r['event_name']} · {r['status']}"
                                                  for r in rows if r["id"] == i))
    st.session_state["review_id"] = sel
    _detail(actor, sel)


def _detail(actor: dict, sub_id: int) -> None:
    ok, d = ui.attempt(lambda: submission_service.get_submission_for_review(actor, sub_id))
    if not ok:
        return
    st.markdown("---")
    st.markdown(f"### {d['student_name']}  {ui.status_badge(d['status'])}", unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].markdown(f"**Class**  \n{class_label(d['class_name'])} - {d['section_name']}")
    cols[1].markdown(f"**Roll number**  \n{d['roll_number']}")
    cols[2].markdown(f"**Event**  \n{d['event_name']}")
    cols[3].markdown(f"**Deadline**  \n{fmt_local(d['deadline'])}")
    st.markdown(f"**Assigned topic:** {d['topic']}")
    if d["task_description"]:
        st.caption(d["task_description"])
    if d["criteria"]:
        with st.expander("Evaluation criteria"):
            st.write(d["criteria"])

    st.markdown("#### 📎 Submitted file")
    latest = d["versions"][0]
    ok, f = ui.attempt(lambda: submission_service.download_version(actor, latest["id"]))
    if ok:
        st.markdown(f"Version {latest['version_no']} — **{f[0]}** ({human_size(latest['file_size'])}) · "
                    f"uploaded {utc_to_local(latest['uploaded_at'])}")
        st.download_button("⬇️ Download file", f[1], file_name=f[0], mime=f[2], key=f"rv_dl_{latest['id']}")
        if f[0].lower().endswith(IMAGE_EXT):
            st.image(f[1], caption="Preview", width=480)
        else:
            st.caption("Preview is shown for images. Download PDF, Word and PowerPoint files to open them.")
    if len(d["versions"]) > 1:
        with st.expander(f"Earlier versions ({len(d['versions']) - 1})"):
            for v in d["versions"][1:]:
                ok, pf = ui.attempt(lambda vid=v["id"]: submission_service.download_version(actor, vid))
                if ok:
                    st.markdown(f"Version {v['version_no']} — {pf[0]} · {utc_to_local(v['uploaded_at'])}")
                    st.download_button("Download", pf[1], file_name=pf[0], mime=pf[2], key=f"rv_dlold_{v['id']}")

    if d["reviews"]:
        with st.expander(f"📜 Review history ({len(d['reviews'])})", expanded=False):
            hist = pd.DataFrame([{"When": utc_to_local(r["created_at"]), "Reviewer": r["reviewer"], "Action": r["action"],
                                  "From": r["previous_status"], "To": r["new_status"], "Feedback": r["feedback"]}
                                 for r in d["reviews"]])
            st.dataframe(hist, hide_index=True, width="stretch")

    if d["status"] in ("Submitted", "Under Review", "Resubmitted"):
        st.markdown("#### ✍️ Your decision")
        with st.form(f"review_form_{sub_id}"):
            feedback = st.text_area("Feedback for the student", key=f"fb_{sub_id}",
                                    help="Required when you reject or ask for corrections.")
            c1, c2, c3 = st.columns(3)
            marks = c1.number_input(f"Marks (max {d['max_marks']:g})" if d["max_marks"] else "Marks (optional)",
                                    min_value=0.0, max_value=float(d["max_marks"] or 100000), value=0.0, step=1.0,
                                    key=f"mk_{sub_id}") if d["max_marks"] else None
            cert_type = c2.selectbox("Certificate type (if approved)", ["Participation", "Achievement"], key=f"ct_{sub_id}")
            remark = c3.text_input("Short remark on certificate (optional)", key=f"cr_{sub_id}")
            b1, b2, b3 = st.columns(3)
            approve = b1.form_submit_button("✅ Approve", type="primary", width="stretch")
            fix = b2.form_submit_button("🔁 Request corrections", width="stretch")
            reject = b3.form_submit_button("❌ Reject", width="stretch")
        action = "approve" if approve else "request_corrections" if fix else "reject" if reject else None
        if action:
            ok, _ = ui.attempt(lambda: submission_service.review_action(
                actor, sub_id, action, feedback, marks, cert_type, remark))
            if ok:
                ui.flash({"approve": "Approved. The student can now get the certificate.",
                          "request_corrections": "Corrections requested. The student can upload a new version.",
                          "reject": "Rejected. The student can see your feedback and upload a new version."}[action])
                st.rerun()
    elif d["status"] == APPROVED:
        st.success("This work is approved." + (f" Certificate: {d['certificate']['certificate_code']} "
                                              f"({d['certificate']['status']})" if d["certificate"] else
                                              " The student has not generated the certificate yet."))
        with st.expander("↩️ Undo this approval"):
            reason = st.text_input("Reason", key=f"revreason_{sub_id}")
            if st.button("Undo approval", key=f"revbtn_{sub_id}"):
                ok, _ = ui.attempt(lambda: submission_service.revert_approval(actor, sub_id, reason))
                if ok:
                    ui.flash("Approval undone. Any certificate was revoked.")
                    st.rerun()
    else:
        st.info(f"Waiting for the student: status is '{d['status']}'. A new upload will return it to your queue.")
