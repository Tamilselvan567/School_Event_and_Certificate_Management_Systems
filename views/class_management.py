"""Classes, sections, academic years and student records."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from services import admin_service as adm
from utils import ui
from utils.helpers import class_label, fmt_date


def render(actor: dict) -> None:
    ui.hero("Classes, Sections & Students", "Add new classes and sections any time — no code changes needed", "🏫")
    ui.show_flash()
    t_cls, t_sec, t_year, t_stu = st.tabs(["🏫 Classes", "🔤 Sections", "📆 Academic years", "🎒 Students"])
    with t_cls:
        _classes(actor)
    with t_sec:
        _sections(actor)
    with t_year:
        _years(actor)
    with t_stu:
        _students(actor)


def _classes(actor):
    classes = adm.list_classes()
    g = ui.form_gen("add_class")
    with st.form("add_class_form"):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("New class name (for example 6, 7 or Nursery)", key=f"new_class_name_{g}")
        order = c2.text_input("Order (optional)", key=f"new_class_order_{g}", help="Lower numbers are listed first.")
        if st.form_submit_button("Add class", type="primary"):
            ok, _ = ui.attempt(lambda: adm.create_class(actor, name, order or None))
            if ok:
                ui.form_done("add_class")
                ui.flash("Class added.")
                st.rerun()
    if not classes:
        ui.empty_state("No classes yet. Add your first class above.", "🏫")
        return
    st.dataframe(pd.DataFrame([{"Class": class_label(c["name"]), "Order": c["sort_order"],
                                "Active": "Yes" if c["is_active"] else "No"} for c in classes]), hide_index=True, width="stretch")
    with st.expander("✏️ Edit a class / deactivate an old class"):
        cid = st.selectbox("Class", [c["id"] for c in classes], key="edit_class_sel",
                           format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)))
        cur = next(c for c in classes if c["id"] == cid)
        with st.form(f"edit_class_{cid}"):
            n = st.text_input("Class name", value=cur["name"], key=f"ecn_{cid}")
            o = st.number_input("Order", value=int(cur["sort_order"]), step=1, key=f"eco_{cid}")
            a = st.checkbox("Active", value=bool(cur["is_active"]), key=f"eca_{cid}")
            if st.form_submit_button("Save class"):
                ok, _ = ui.attempt(lambda: adm.update_class(actor, cid, n, o, a))
                if ok:
                    ui.flash("Class updated.")
                    st.rerun()


def _sections(actor):
    classes = adm.list_classes()
    if not classes:
        st.info("Add a class first.")
        return
    g = ui.form_gen("add_section")
    with st.form("add_section_form"):
        c1, c2 = st.columns(2)
        cid = c1.selectbox("Class", [c["id"] for c in classes], key="new_sec_class",
                           format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)))
        name = c2.text_input("New section name (for example A)", key=f"new_sec_name_{g}")
        if st.form_submit_button("Add section", type="primary"):
            ok, _ = ui.attempt(lambda: adm.create_section(actor, cid, name))
            if ok:
                ui.form_done("add_section")
                ui.flash("Section added.")
                st.rerun()
    sections = adm.list_sections()
    if not sections:
        ui.empty_state("No sections yet. Add one above.", "🔤")
        return
    st.dataframe(pd.DataFrame([{"Class": class_label(s["class_name"]), "Section": s["name"],
                                "Active": "Yes" if s["is_active"] else "No"} for s in sections]), hide_index=True, width="stretch")
    with st.expander("✏️ Edit a section / deactivate"):
        sid = st.selectbox("Section", [s["id"] for s in sections], key="edit_sec_sel",
                           format_func=lambda i: next(f"{class_label(s['class_name'])} - {s['name']}" for s in sections if s["id"] == i))
        cur = next(s for s in sections if s["id"] == sid)
        with st.form(f"edit_sec_{sid}"):
            n = st.text_input("Section name", value=cur["name"], key=f"esn_{sid}")
            a = st.checkbox("Active", value=bool(cur["is_active"]), key=f"esa_{sid}")
            if st.form_submit_button("Save section"):
                ok, _ = ui.attempt(lambda: adm.update_section(actor, sid, n, a))
                if ok:
                    ui.flash("Section updated.")
                    st.rerun()


def _years(actor):
    years = adm.list_years()
    g = ui.form_gen("add_year")
    with st.form("add_year_form"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Academic year (for example 2026-27)", key=f"new_year_name_{g}")
        start = c2.date_input("Starts", value=date(date.today().year, 4, 1), key="new_year_start")
        end = c3.date_input("Ends", value=date(date.today().year + 1, 3, 31), key="new_year_end")
        if st.form_submit_button("Add academic year", type="primary"):
            ok, _ = ui.attempt(lambda: adm.create_year(actor, name, start, end))
            if ok:
                ui.form_done("add_year")
                ui.flash("Academic year added.")
                st.rerun()
    default_id = adm.default_year_id()
    st.dataframe(pd.DataFrame([{"Academic year": y["name"], "Starts": fmt_date(y["start_date"]),
                                "Ends": fmt_date(y["end_date"]), "Active": "Yes" if y["is_active"] else "No",
                                "Default": "⭐" if y["id"] == default_id else ""} for y in years]),
                 hide_index=True, width="stretch")
    if years:
        with st.expander("✏️ Edit an academic year"):
            yid = st.selectbox("Academic year", [y["id"] for y in years], key="edit_year_sel",
                               format_func=lambda i: next(y["name"] for y in years if y["id"] == i))
            cur = next(y for y in years if y["id"] == yid)
            with st.form(f"edit_year_{yid}"):
                n = st.text_input("Name", value=cur["name"], key=f"eyn_{yid}")
                a = st.checkbox("Active", value=bool(cur["is_active"]), key=f"eya_{yid}")
                if st.form_submit_button("Save academic year"):
                    ok, _ = ui.attempt(lambda: adm.update_year(actor, yid, n, cur["start_date"], cur["end_date"], a))
                    if ok:
                        ui.flash("Academic year updated.")
                        st.rerun()
        if actor["role"] == "admin":
            st.caption("The default academic year is chosen in Settings.")


def _students(actor):
    classes = adm.list_classes(include_inactive=False)
    if not classes:
        st.info("Add classes and sections first.")
        return
    st.markdown("#### Add a student")
    cid = st.selectbox("Class", [c["id"] for c in classes], key="stu_add_class",
                       format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)))
    sections = adm.list_sections(cid, include_inactive=False)
    if not sections:
        st.info("This class has no sections yet. Add one in the Sections tab.")
    else:
        g = ui.form_gen("add_student")
        with st.form("add_student_form"):
            sid = st.selectbox("Section", [s["id"] for s in sections], key=f"stu_add_sec_{cid}",
                               format_func=lambda i: next(s["name"] for s in sections if s["id"] == i))
            c1, c2 = st.columns([3, 1])
            name = c1.text_input("Student full name", key=f"stu_add_name_{g}")
            roll = c2.text_input("Roll number", key=f"stu_add_roll_{g}")
            if st.form_submit_button("Add student", type="primary"):
                ok, _ = ui.attempt(lambda: adm.add_student(actor, name, cid, sid, roll))
                if ok:
                    ui.form_done("add_student")
                    ui.flash("Student added.")
                    st.rerun()
    with st.expander("📄 Import many students from a CSV file"):
        st.caption("Columns required: name, class, section, roll. Example row: Asha Verma,6,A,12")
        create_missing = st.checkbox("Create classes and sections that do not exist yet", key="csv_create")
        up = st.file_uploader("CSV file", type=["csv"], key="csv_students")
        if up is not None and st.button("Import students", key="csv_go"):
            ok, res = ui.attempt(lambda: adm.import_students_csv(actor, up.getvalue().decode("utf-8-sig", "replace"), create_missing))
            if ok:
                st.success(f"{res['added']} student(s) added.")
                for err in res["errors"][:30]:
                    st.warning(err)
    st.markdown("#### Student list")
    f1, f2, f3 = st.columns(3)
    fc = f1.selectbox("Class", [0] + [c["id"] for c in classes], key="stu_f_class",
                      format_func=lambda i: "All classes" if i == 0 else class_label(next(c["name"] for c in classes if c["id"] == i)))
    search = f2.text_input("Search name or roll", key="stu_f_search")
    show_all = f3.checkbox("Include inactive", key="stu_f_inactive")
    ok, students = ui.attempt(lambda: adm.list_students(actor, fc or None, None, search, show_all))
    if not ok:
        return
    if not students:
        ui.empty_state("No students found.", "🎒")
        return
    st.dataframe(pd.DataFrame([{"Name": s["full_name"], "Class": class_label(s["class_name"]), "Section": s["section_name"],
                                "Roll": s["roll_number"], "Active": "Yes" if s["is_active"] else "No"} for s in students]),
                 hide_index=True, width="stretch")
    with st.expander("✏️ Edit a student"):
        sid_sel = st.selectbox("Student", [s["id"] for s in students], key="stu_edit_sel",
                               format_func=lambda i: next(f"{s['full_name']} ({class_label(s['class_name'])}-{s['section_name']}, #{s['roll_number']})"
                                                          for s in students if s["id"] == i))
        cur = next(s for s in students if s["id"] == sid_sel)
        e_cid = st.selectbox("Class", [c["id"] for c in classes], key=f"se_c_{sid_sel}",
                             index=[c["id"] for c in classes].index(cur["class_id"]) if cur["class_id"] in [c["id"] for c in classes] else 0,
                             format_func=lambda i: class_label(next(c["name"] for c in classes if c["id"] == i)))
        e_secs = adm.list_sections(e_cid, include_inactive=False)
        with st.form(f"edit_student_{sid_sel}"):
            name = st.text_input("Full name", value=cur["full_name"], key=f"sen_{sid_sel}")
            sec_ids = [s["id"] for s in e_secs]
            sec = st.selectbox("Section", sec_ids, key=f"ses_{sid_sel}_{e_cid}",
                               index=sec_ids.index(cur["section_id"]) if cur["section_id"] in sec_ids else 0,
                               format_func=lambda i: next(s["name"] for s in e_secs if s["id"] == i)) if e_secs else None
            roll = st.text_input("Roll number", value=cur["roll_number"], key=f"ser_{sid_sel}")
            active = st.checkbox("Active", value=bool(cur["is_active"]), key=f"sea_{sid_sel}")
            if st.form_submit_button("Save student"):
                ok, _ = ui.attempt(lambda: adm.update_student(actor, sid_sel, name, e_cid, sec, roll, active))
                if ok:
                    ui.flash("Student updated.")
                    st.rerun()
