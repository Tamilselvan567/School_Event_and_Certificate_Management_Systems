"""Reusable Streamlit UI pieces: styling, cards, badges, friendly error handling."""
from __future__ import annotations

import html
import logging
import uuid

import streamlit as st

from utils.errors import AppError
from utils.helpers import EVENT_STATUS_META, STATUS_META

log = logging.getLogger("mses.ui")

CSS = """
<style>
#MainMenu, [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], footer {visibility: hidden;}
/* NOTE: do not hide [data-testid="stToolbar"] - on phones the button that opens the menu lives inside it. */
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px;}
html, body, [class*="css"] {font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;}
/* Sidebar */
[data-testid="stSidebar"] {background: linear-gradient(180deg, #312E81 0%, #4338CA 55%, #6D28D9 100%);}
[data-testid="stSidebar"] * {color: #EEF2FF;}
[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,.25);}
[data-testid="stSidebar"] .stRadio label {padding: .35rem .5rem; border-radius: 10px; width: 100%;}
[data-testid="stSidebar"] .stRadio label:hover {background: rgba(255,255,255,.14);}
[data-testid="stSidebar"] .stButton button {background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35); color: #fff;}
.brand {display:flex; gap:.6rem; align-items:center; margin:.2rem 0 .6rem 0;}
.brand .logo {font-size: 2rem;}
.brand .name {font-weight: 800; font-size: 1.05rem; line-height: 1.1;}
.brand .sub {font-size: .72rem; opacity: .8;}
.userbox {background: rgba(255,255,255,.12); border-radius: 12px; padding: .6rem .8rem; font-size: .85rem; margin-bottom: .6rem;}
/* Hero */
.hero {background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #EC4899 100%); color: #fff; border-radius: 20px;
       padding: 1.4rem 1.6rem; margin-bottom: 1.2rem; box-shadow: 0 10px 30px rgba(79,70,229,.25);}
.hero h1 {color:#fff; font-size: 1.75rem; margin: 0 0 .15rem 0; padding: 0;}
.hero p {margin: 0; opacity: .92; font-size: .98rem;}
/* Metric cards */
.metrics {display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .8rem; margin-bottom: 1.1rem;}
.metric {border-radius: 16px; padding: .95rem 1rem; color: #fff; box-shadow: 0 6px 16px rgba(15,23,42,.12);}
.metric .v {font-size: 1.9rem; font-weight: 800; line-height: 1.1;}
.metric .l {font-size: .82rem; opacity: .95; margin-top: .15rem;}
.m-indigo {background: linear-gradient(135deg,#6366F1,#4338CA);} .m-pink {background: linear-gradient(135deg,#F472B6,#DB2777);}
.m-green {background: linear-gradient(135deg,#34D399,#059669);} .m-amber {background: linear-gradient(135deg,#FBBF24,#D97706);}
.m-sky {background: linear-gradient(135deg,#38BDF8,#0284C7);} .m-red {background: linear-gradient(135deg,#FB7185,#E11D48);}
.m-violet {background: linear-gradient(135deg,#A78BFA,#6D28D9);} .m-slate {background: linear-gradient(135deg,#64748B,#334155);}
/* Badges + cards */
.badge {display:inline-block; padding: .15rem .65rem; border-radius: 999px; font-size: .78rem; font-weight: 700; white-space: nowrap;}
.pcard {background:#fff; border:1px solid #E2E8F0; border-radius: 16px; padding: 1rem 1.1rem; margin-bottom:.8rem;
        box-shadow: 0 2px 8px rgba(15,23,42,.05);}
.pcard h4 {margin: 0 0 .25rem 0; font-size: 1.05rem; color:#1E1B4B;}
.pcard .muted, .muted {color:#64748B; font-size:.86rem;}
.empty {text-align:center; padding: 2rem 1rem; color:#64748B; background:#fff; border:2px dashed #CBD5E1; border-radius:16px;}
.empty .ic {font-size: 2.3rem;}
.fb-box {background:#FFF7ED; border-left: 5px solid #F97316; border-radius: 10px; padding:.7rem .9rem; margin:.4rem 0;}
.ok-box {background:#ECFDF5; border-left: 5px solid #10B981; border-radius: 10px; padding:.7rem .9rem; margin:.4rem 0;}
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {border-radius: 12px; font-weight: 600; min-height: 2.6rem;}
button[kind="primary"] {background: linear-gradient(120deg,#4F46E5,#7C3AED); border: 0;}
[data-testid="stDataFrame"] {border-radius: 12px; overflow: hidden;}
@media (max-width: 640px) {
  .block-container {padding: 3.8rem .7rem 3rem .7rem;}
  .hero {padding: 1rem 1.05rem; border-radius: 16px;} .hero h1 {font-size: 1.3rem;}
  .metrics {grid-template-columns: repeat(2, 1fr);} .metric .v {font-size: 1.5rem;}
  .stButton > button, .stDownloadButton > button {min-height: 3rem; width: 100%;}
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def e(text) -> str:
    """HTML-escape any user text before placing it in custom HTML."""
    return html.escape(str(text if text is not None else ""))


def hero(title: str, subtitle: str = "", icon: str = "") -> None:
    st.markdown(f'<div class="hero"><h1>{e(icon)} {e(title)}</h1><p>{e(subtitle)}</p></div>', unsafe_allow_html=True)


def metric_cards(items: list[tuple[str, object, str]]) -> None:
    cells = "".join(f'<div class="metric m-{c}"><div class="v">{e(v)}</div><div class="l">{e(l)}</div></div>'
                    for l, v, c in items)
    st.markdown(f'<div class="metrics">{cells}</div>', unsafe_allow_html=True)


def status_badge(status: str) -> str:
    icon, fg, bg = STATUS_META.get(status, STATUS_META["Not Started"])
    return f'<span class="badge" style="color:{fg};background:{bg}">{icon} {e(status)}</span>'


def event_badge(status: str) -> str:
    icon, fg, bg, label = EVENT_STATUS_META.get(status, EVENT_STATUS_META["draft"])
    return f'<span class="badge" style="color:{fg};background:{bg}">{icon} {e(label)}</span>'


def empty_state(message: str, icon: str = "📭") -> None:
    st.markdown(f'<div class="empty"><div class="ic">{icon}</div><div>{e(message)}</div></div>', unsafe_allow_html=True)


def feedback_box(text: str, approved: bool = False) -> None:
    css = "ok-box" if approved else "fb-box"
    st.markdown(f'<div class="{css}">{e(text)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------- friendly error handling
def attempt(fn, success: str | None = None, flash_success: bool = False):
    """Run an action. Shows a clear message on failure; hides technical details.

    Returns (ok, result)."""
    try:
        result = fn()
    except AppError as exc:
        st.error(str(exc))
        return False, None
    except Exception:
        ref = uuid.uuid4().hex[:8]
        log.exception("Unexpected error (ref %s)", ref)
        st.error(f"Something went wrong. Please try again. If it keeps happening, tell the administrator "
                 f"this reference: {ref}")
        return False, None
    if success:
        if flash_success:
            flash(success)
        else:
            st.success(success)
    return True, result


def flash(message: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    """Show one-time messages. The container is ALWAYS created (even when empty) so that the page layout
    below it - especially tab bars - keeps the same position and does not jump back to the first tab."""
    box = st.container()
    for kind, message in st.session_state.pop("_flash", []):
        with box:
            {"success": st.success, "error": st.error, "info": st.info, "warning": st.warning}.get(kind, st.info)(message)


def confirm_checkbox(label: str, key: str) -> bool:
    return st.checkbox(label, key=key)


# ---- forms that empty themselves only after a SUCCESSFUL save --------------------
def form_gen(name: str) -> int:
    """Number used inside widget keys. It changes after a successful save, which brings the form back empty;
    after a failed save it stays the same, so the person keeps what they typed."""
    return st.session_state.get(f"_formgen_{name}", 0)


def form_done(name: str) -> None:
    st.session_state[f"_formgen_{name}"] = form_gen(name) + 1
