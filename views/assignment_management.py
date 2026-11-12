"""Class-specific assignments: a different topic, instructions and deadline for each class."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import streamlit as st

from config import SUPPORTED_EXTENSIONS
from services import admin_service as adm
from services import event_service
from utils import ui
from utils.helpers import EVENT_STATUS_META, class_label, fmt_local, now_local


def _fields(prefix: str, d: dict | None, event: dict):
    """The shared assignment fields (used inside a form)."""
    d = d or {}
    topic = st.text_input("Topic name", value=d.get("topic", ""), key=f"{prefix}_topic")
    description = st.text_area("Task description", value=d.get("description", ""), key=f"{prefix}_desc")
    instructions = st.text_area("Detailed instructions", value=d.get("instructions", ""), key=f"{prefix}_instr")
    formats = st.multiselect("Required submission format(s)", list(SUPPORTED_EXTENSIONS),
                             default=d["allowed_formats"].split(",") if d.get("allowed_formats") else list(SUPPORTED_EXTENSIONS),
                             format_func=str.upper, key=f"{prefix}_fmt")
    own_deadline = st.checkbox(f"Use a different deadline for this class (event deadline: {fmt_local(event['deadline'])})",
                               value=bool(d.get("deadline")), key=f"{prefix}_owndl")
    base = datetime.strptime(d["deadline"], "%Y-%m-%d %H:%M") if d.get("deadline") else datetime.strptime(
        event["deadline"], "%Y-%m-%d %H:%M")
    c1, c2 = st.columns(2)
    dl_date = c1.date_input("Class deadline (date)", value=base.date(), key=f"{prefix}_dldate")
    dl_time = c2.time_input("Class deadline (time)", value=base.time(), key=f"{prefix}_dltime")
    criteria = st.text_area("Evaluation criteria", value=d.get("criteria", ""), key=f"{prefix}_crit")
    max_marks = st.number_input("Maximum marks (0 = not marked)", min_value=0.0, max_value=100000.0,
                                value=float(d.get("max_marks") or 0), step=1.0, key=f"{prefix}_marks")
    ref = st.file_uploader("Reference material (optional)", type=list(SUPPORTED_EXTENSIONS), key=f"{prefix}_ref")
    data = dict(topic=topic, description=description, instructions=instructions, allowed_formats=formats,
                deadline=datetime.combine(dl_date, dl_time.replace(second=0, microsecond=0)) if own_deadline else None,
                criteria=criteria, max_marks=max_marks or None)
    return data, (ref.name, ref.getvalue()) if ref is not None else None


def render(actor: dict) -> None:
    ui.hero("Class Assignments", "Give each class its own topic, instructions, format and deadline", "🎯")
    ui.show_flash()
    ok, events = ui.attempt(lambda: event_service.list_events(actor))
    events = [e for e in (events or []) if e["status"] != "archived"]
    if not events:
        ui.empty_state("Create an event first (Events page), then come back to add class topics.", "🎯")
        return
    ids = [e["id"] for e in events]
    current = st.session_state.get("selected_event")
    ev_id = st.selectbox("Choose an event", ids, index=ids.index(current) if current in ids else 0, key="asg_event",
                         format_func=lambda i: next(f"{e['name']} ({EVENT_STATUS_META[e['status']][3]})" for e in events if e["id"] == i))
    st.session_state["selected_event"] = ev_id
    event = next(e for e in events if e["id"] == ev_id)

    ok, assignments = ui.attempt(lambda: event_service.list_assignments(actor, ev_id))
    if not ok:
        return
    st.subheader(f"Topics for “{event['name']}”")
    if not assignments:
        ui.empty_state("No class has been assigned yet. Add the first class topic below.", "🎯")
    for a in assignments:
        scope = f"{class_label(a['class_name'])} — " + (f"Section {a['section_name']}" if a["section_name"] else "All sections")
        with st.container(border=True):
            st.markdown(f"**{scope}**  ·  🎯 {a['topic']}")
            st.caption(f"Deadline: {fmt_local(a['deadline'] or event['deadline'])} · Formats: "
                       f"{', '.join(f.upper() for f in a['allowed_formats'].split(','))} · "
                       f"{a['student_count']} student(s) · {a['submission_count']} submission(s)"
                       + (f" · Max marks {a['max_marks']:g}" if a["max_marks"] else ""))
            with st.expander("Edit or delete"):
                with st.form(f"edit_asg_{a['id']}"):
                    data, ref = _fields(f"ea{a['id']}", a, event)
                    remove_ref = st.checkbox("Remove current reference material", key=f"rmref_{a['id']}") \
                        if a["reference_path"] else False
                    saved = st.form_submit_button("Save changes", type="primary")
                if saved:
                    ok, _ = ui.attempt(lambda: event_service.update_assignment(actor, a["id"], data, ref, remove_ref))
                    if ok:
                        ui.flash("Assignment updated.")
                        st.rerun()
                if a["submission_count"] == 0:
                    sure = st.checkbox("Yes, delete this class assignment", key=f"delchk_{a['id']}")
                    if st.button("Delete assignment", key=f"delasg_{a['id']}", disabled=not sure):
                        ok, _ = ui.attempt(lambda: event_service.delete_assignment(actor, a["id"]))
                        if ok:
                            ui.flash("Assignment deleted.")
                            st.rerun()
                else:
                    st.caption("Students have submitted work, so this assignment cannot be deleted.")

    st.subheader("➕ Add a class topic")
    classes = adm.list_classes(include_inactive=False)
    if not classes:
        st.warning("Please create classes first (Classes & Students).")
        return
    class_id = st.selectbox("Class", [c["id"] for c in classes], key="new_asg_class",
                            format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)))
    sections = adm.list_sections(class_id, include_inactive=False)
    section_choice = st.selectbox("Section", [0] + [s["id"] for s in sections], key=f"new_asg_section_{class_id}",
                                  format_func=lambda i: "All sections" if i == 0 else next(
                                      f"Section {s['name']}" for s in sections if s["id"] == i))
    g = ui.form_gen("new_asg")
    with st.form("new_assignment_form"):
        data, ref = _fields(f"na{g}", None, event)
        submitted = st.form_submit_button("Add class topic", type="primary")
    if submitted:
        payload = dict(data, class_id=class_id, section_id=section_choice or None)
        ok, _ = ui.attempt(lambda: event_service.create_assignment(actor, ev_id, payload, ref))
        if ok:
            ui.form_done("new_asg")
            ui.flash(f"Topic added for {class_label(next(c['name'] for c in classes if c['id'] == class_id))}.")
            st.rerun()
