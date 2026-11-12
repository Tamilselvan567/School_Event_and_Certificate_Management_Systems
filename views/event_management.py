"""Event management: create, edit, publish, close, archive, delete."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from services import admin_service as adm
from services import event_service
from services.settings_store import event_categories
from utils import ui
from utils.helpers import EVENT_STATUS_META, fmt_date, fmt_local, now_local

ACTION_BUTTONS = {
    "draft": [("publish", "🚀 Publish", "primary"), ("archive", "🗄️ Archive", "secondary")],
    "published": [("unpublish", "↩️ Unpublish", "secondary"), ("close", "🔒 Close", "secondary"),
                  ("archive", "🗄️ Archive", "secondary")],
    "closed": [("reopen", "🔓 Reopen", "primary"), ("archive", "🗄️ Archive", "secondary")],
    "archived": [("unarchive", "♻️ Restore", "primary")],
}
ACTION_DONE = {"publish": "Event published. Students can now see it.", "unpublish": "Event moved back to draft.",
               "close": "Event closed. No new submissions are accepted.", "reopen": "Event reopened.",
               "archive": "Event archived.", "unarchive": "Event restored (now closed)."}


def _event_form(prefix: str, years: list[dict], default: dict | None = None, submit_label: str = "Save"):
    d = default or {}
    today = now_local()
    cats = event_categories()
    deadline_dt = datetime.strptime(d["deadline"], "%Y-%m-%d %H:%M") if d.get("deadline") else (
        datetime.combine((today + timedelta(days=14)).date(), time(17, 0)))
    with st.form(f"{prefix}_form"):
        name = st.text_input("Event name", value=d.get("name", ""), key=f"{prefix}_name")
        description = st.text_area("Event description", value=d.get("description", ""), key=f"{prefix}_desc")
        c1, c2 = st.columns(2)
        category = c1.selectbox("Event category", cats, index=cats.index(d["category"]) if d.get("category") in cats else 0,
                                key=f"{prefix}_cat")
        year_ids = [y["id"] for y in years]
        year_idx = year_ids.index(d["academic_year_id"]) if d.get("academic_year_id") in year_ids else (
            year_ids.index(adm.default_year_id()) if adm.default_year_id() in year_ids else 0)
        year_id = c2.selectbox("Academic year", year_ids, index=year_idx,
                               format_func=lambda i: next(y["name"] for y in years if y["id"] == i), key=f"{prefix}_year")
        c3, c4 = st.columns(2)
        event_date = c3.date_input("Event date", value=datetime.strptime(d["event_date"], "%Y-%m-%d").date()
                                   if d.get("event_date") else (today + timedelta(days=21)).date(), key=f"{prefix}_edate")
        opens_on = c4.date_input("Submissions open on", value=datetime.strptime(d["opens_on"], "%Y-%m-%d").date()
                                 if d.get("opens_on") else today.date(), key=f"{prefix}_opens")
        c5, c6 = st.columns(2)
        dl_date = c5.date_input("Submission deadline (date)", value=deadline_dt.date(), key=f"{prefix}_dldate")
        dl_time = c6.time_input("Submission deadline (time)", value=deadline_dt.time(), key=f"{prefix}_dltime")
        instructions = st.text_area("General instructions for students", value=d.get("instructions", ""),
                                    key=f"{prefix}_instr")
        poster = st.file_uploader("Event poster or image (optional, PNG or JPG)", type=["png", "jpg", "jpeg"],
                                  key=f"{prefix}_poster")
        remove = st.checkbox("Remove the current poster", key=f"{prefix}_rmposter") if d.get("poster_path") else False
        submitted = st.form_submit_button(submit_label, type="primary")
    data = dict(name=name, description=description, category=category, academic_year_id=year_id,
                event_date=event_date, opens_on=opens_on, instructions=instructions,
                deadline=datetime.combine(dl_date, dl_time.replace(second=0, microsecond=0)))
    poster_t = (poster.name, poster.getvalue()) if poster is not None else None
    return submitted, data, poster_t, remove


def render(actor: dict) -> None:
    ui.hero("Event Management", "Create events, then add class-specific topics under Class Assignments", "📅")
    ui.show_flash()
    years = adm.list_years(include_inactive=False)
    if not years:
        st.warning("Please add an academic year first (Classes & Students → Academic years).")
        return
    tab_list, tab_new = st.tabs(["📋 Events", "➕ Create new event"])
    with tab_new:
        submitted, data, poster, _ = _event_form("new_ev", years, submit_label="Create event")
        if submitted:
            ok, eid = ui.attempt(lambda: event_service.create_event(actor, data, poster))
            if ok:
                ui.flash("Event created as a draft. Next: add class assignments, then publish it.")
                st.session_state["selected_event"] = eid
                st.rerun()
    with tab_list:
        c1, c2 = st.columns([1, 2])
        status = c1.selectbox("Show", ["All", "draft", "published", "closed", "archived"], key="ev_filter",
                              format_func=lambda s: "All events" if s == "All" else EVENT_STATUS_META[s][3])
        search = c2.text_input("Search by name", key="ev_search")
        ok, events = ui.attempt(lambda: event_service.list_events(actor, None if status == "All" else status, search))
        if not ok:
            return
        if not events:
            ui.empty_state("No events yet. Use the 'Create new event' tab to add your first one.", "📅")
            return
        df = pd.DataFrame([{"Event": e["name"], "Category": e["category"], "Status": EVENT_STATUS_META[e["status"]][3],
                            "Deadline": fmt_local(e["deadline"]), "Classes": e["assignment_count"],
                            "Submissions": e["submission_count"], "Created by": e["creator_name"]} for e in events])
        st.dataframe(df, hide_index=True, width="stretch")
        ids = [e["id"] for e in events]
        current = st.session_state.get("selected_event")
        sel = st.selectbox("Select an event to manage", ids, index=ids.index(current) if current in ids else 0,
                           format_func=lambda i: next(f"{e['name']} ({EVENT_STATUS_META[e['status']][3]})"
                                                      for e in events if e["id"] == i), key="ev_select")
        st.session_state["selected_event"] = sel
        _manage(actor, next(e for e in events if e["id"] == sel), years)


def _manage(actor, ev: dict, years: list[dict]) -> None:
    st.markdown("---")
    st.markdown(f"### {ev['name']}  {ui.event_badge(ev['status'])}", unsafe_allow_html=True)
    st.caption(f"{ev['category']} · {ev['year_name']} · Opens {fmt_date(ev['opens_on'])} · "
               f"Deadline {fmt_local(ev['deadline'])} · {ev['assignment_count']} class assignment(s) · "
               f"{ev['submission_count']} submission(s) · created by {ev['creator_name']}")
    if ev["poster_path"]:
        poster = event_service.read_poster(actor, ev["id"])
        if poster:
            st.image(poster, width=280)
    buttons = ACTION_BUTTONS[ev["status"]]
    cols = st.columns(len(buttons))
    for col, (action, label, kind) in zip(cols, buttons):
        if col.button(label, key=f"evact_{action}_{ev['id']}", type=kind, width="stretch"):
            ok, _ = ui.attempt(lambda a=action: event_service.set_event_status(actor, ev["id"], a))
            if ok:
                ui.flash(ACTION_DONE[action])
                st.rerun()
    if ev["status"] != "archived":
        with st.expander("✏️ Edit event details"):
            submitted, data, poster, remove = _event_form(f"edit_ev_{ev['id']}", years, ev, "Save changes")
            if submitted:
                ok, _ = ui.attempt(lambda: event_service.update_event(actor, ev["id"], data, poster, remove))
                if ok:
                    ui.flash("Event updated.")
                    st.rerun()
    if ev["status"] in ("draft", "archived"):
        with st.expander("🗑️ Delete this event"):
            if ev["submission_count"]:
                st.info("This event has student submissions, so it cannot be deleted. Keep it archived instead.")
            else:
                st.warning("Deleting removes the event and its class assignments permanently. "
                           "Type the exact event name to confirm.")
                confirm = st.text_input("Event name", key=f"del_confirm_{ev['id']}")
                if st.button("Delete permanently", key=f"del_btn_{ev['id']}"):
                    ok, _ = ui.attempt(lambda: event_service.delete_event(actor, ev["id"], confirm))
                    if ok:
                        st.session_state.pop("selected_event", None)
                        ui.flash("Event deleted.")
                        st.rerun()
