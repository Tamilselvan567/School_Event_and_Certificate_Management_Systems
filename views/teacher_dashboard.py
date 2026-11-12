"""Teacher (and shared admin) dashboard with summary cards."""
from __future__ import annotations

import streamlit as st

from services import event_service
from utils import ui
from utils.helpers import fmt_local


def render_stats(actor: dict) -> None:
    ok, s = ui.attempt(lambda: event_service.dashboard_stats(actor))
    if not ok:
        return
    ui.metric_cards([
        ("Total events", s["total_events"], "indigo"), ("Active events", s["active_events"], "green"),
        ("Assigned students", s["assigned_students"], "sky"), ("Total submissions", s["total_submissions"], "violet"),
        ("Pending reviews", s["pending_reviews"], "amber"), ("Approved", s["approved"], "green"),
        ("Rejected / corrections", s["rejected"], "red")])
    st.subheader("⏰ Upcoming deadlines")
    if not s["upcoming_deadlines"]:
        ui.empty_state("No upcoming deadlines. Publish an event to see it here.", "⏰")
    for e in s["upcoming_deadlines"]:
        st.markdown(f'<div class="pcard"><h4>{ui.e(e["name"])}</h4>'
                    f'<div class="muted">Deadline: <b>{ui.e(fmt_local(e["deadline"]))}</b></div></div>',
                    unsafe_allow_html=True)


def render(actor: dict) -> None:
    ui.hero(f"Welcome, {actor['name']}!", "Here is what is happening with your events", "👩‍🏫")
    ui.show_flash()
    render_stats(actor)
