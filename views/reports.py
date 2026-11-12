"""Reports with CSV export."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services import report_service as rep
from utils import ui
from utils.helpers import class_label


def _table(rows, title_map: dict, filename: str, key: str) -> None:
    if not rows:
        ui.empty_state("No data yet for this report.", "📊")
        return
    df = pd.DataFrame(rows)
    df = df[[c for c in title_map if c in df.columns]].rename(columns=title_map)
    st.dataframe(df, hide_index=True, width="stretch")
    csv_rows = [{title_map[k]: r.get(k) for k in title_map if k in r} for r in rows]   # same column order as on screen
    st.download_button("⬇️ Download CSV", rep.to_csv(csv_rows), file_name=filename, mime="text/csv", key=f"csv_{key}")


def render(actor: dict) -> None:
    ui.hero("Reports & Analytics", "Live numbers from the school database", "📊")
    tabs = st.tabs(["Event participation", "Class participation", "Submission status", "Pending reviews",
                    "Approved", "Rejected", "Certificates", "Deadlines"])
    with tabs[0]:
        rows = rep.event_participation(actor)
        _table(rows, {"event": "Event", "status": "Event status", "assigned_students": "Assigned students",
                      "submitted": "Submitted", "approved": "Approved", "rejected": "Rejected / corrections",
                      "pending": "Pending", "participation_pct": "Participation %"}, "event_participation.csv", "ev")
        if rows:
            st.bar_chart(pd.DataFrame(rows).set_index("event")[["assigned_students", "submitted", "approved"]])
    with tabs[1]:
        rows = rep.class_participation(actor)
        for r in rows:
            r["class_label"] = class_label(r["class_name"])
        _table(rows, {"class_label": "Class", "section_name": "Section", "students": "Students",
                      "participated": "Participated", "approved": "Approved", "participation_pct": "Participation %"},
               "class_participation.csv", "cls")
    with tabs[2]:
        rows = rep.status_summary(actor)
        _table(rows, {"status": "Status", "count": "Submissions"}, "submission_status.csv", "stat")
        if rows:
            st.bar_chart(pd.DataFrame(rows).set_index("status"))
    cols = {"student": "Student", "class_name": "Class", "section": "Section", "roll": "Roll", "event": "Event",
            "topic": "Topic", "status": "Status", "marks": "Marks", "updated_at": "Last updated (UTC)"}
    with tabs[3]:
        _table(rep.pending_reviews(actor), cols, "pending_reviews.csv", "pend")
    with tabs[4]:
        _table(rep.approved_projects(actor), cols, "approved_projects.csv", "appr")
    with tabs[5]:
        _table(rep.rejected_projects(actor), cols, "rejected_projects.csv", "rej")
    with tabs[6]:
        _table(rep.certificate_stats(actor), {"event": "Event", "issued": "Issued", "revoked": "Revoked",
                                              "achievement": "Achievement", "participation": "Participation"},
               "certificates.csv", "cert")
    with tabs[7]:
        _table(rep.deadline_completion(actor), {"event": "Event", "class_name": "Class", "section_name": "Section",
                                                "topic": "Topic", "deadline": "Deadline", "students": "Students",
                                                "submitted": "Submitted", "missing": "Not submitted",
                                                "deadline_passed": "Deadline passed", "completion_pct": "Completion %"},
               "deadline_completion.csv", "dl")
