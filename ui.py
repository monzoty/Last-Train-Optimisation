"""Design system for the dashboard: global CSS + small HTML components (header, KPI cards, badges, steps)."""
from __future__ import annotations

import html
import itertools

import plotly.io as pio
import streamlit as st

import charts  # noqa: F401  (registers the "saas" Plotly template)

INDIGO, SLATE, MUTED = "#4F46E5", "#0F172A", "#64748B"
TONES = {  # text, background
    "indigo": ("#4338CA", "#EEF2FF"), "green": ("#047857", "#ECFDF5"), "red": ("#B91C1C", "#FEF2F2"),
    "amber": ("#B45309", "#FFFBEB"), "blue": ("#1D4ED8", "#EFF6FF"), "slate": ("#475569", "#F1F5F9"),
    "violet": ("#6D28D9", "#F5F3FF"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..600,0..1,0');

/* ---------- layout ---------- */
header[data-testid="stHeader"] { background: transparent; }
/* hide the menu/deploy items but keep the toolbar: it holds the button that re-opens a collapsed sidebar */
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stDecoration"],
[data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stExpandSidebarButton"] { display: inline-flex !important; visibility: visible !important; }
.block-container, [data-testid="stMainBlockContainer"] { padding-top: 2rem !important; padding-bottom: 3rem !important; max-width: 1380px; }
[data-testid="stSidebar"] { box-shadow: 1px 0 0 #E4E7EF; }
[data-testid="stSidebarHeader"] { padding-bottom: .25rem; }
[data-testid="stSidebarNav"] a { border-radius: 8px; margin: 1px 0; }
[data-testid="stSidebarNav"] a span { font-weight: 500; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: #EEF2FF; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: #4338CA; font-weight: 600; }
[data-testid="stSidebarNavSeparator"] { margin: .5rem 0; }

/* ---------- cards (ui.card -> st.container(border=True, key="card-n")) ---------- */
[class*="st-key-card-"] {
  background: #FFFFFF; padding: 18px 20px !important;
  box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 2px 6px rgba(16,24,40,.03);
}

/* ---------- tabs as a segmented control ---------- */
[data-testid="stTabs"] [role="tablist"] { overflow-x: auto; max-width: 100%; gap: 2px; background: #E9ECF4; padding: 4px; border-radius: 11px;
  width: fit-content; border: none !important; box-shadow: none !important; }
[data-testid="stTabs"] [role="tablist"]::after, [data-testid="stTabs"] [role="tablist"]::before { display: none !important; }
[data-testid="stTab"] { height: 34px; padding: 0 12px !important; border-radius: 8px; background: transparent;
  border: none !important; box-shadow: none; transition: background .15s ease; }
[data-testid="stTab"] p { font-weight: 500; color: #475569; font-size: 13.5px; }
[data-testid="stTab"]:hover { background: rgba(255,255,255,.55); }
[data-testid="stTab"][aria-selected="true"] { background: #FFFFFF !important; box-shadow: 0 1px 3px rgba(16,24,40,.10) !important; }
[data-testid="stTab"][aria-selected="true"] p { color: #0F172A !important; font-weight: 600; }
[data-testid="stTabs"] [role="tablist"] ~ div { border: none !important; }
[data-testid="stTabs"] [role="tabpanel"] { padding-top: 1rem; }

/* ---------- hero, insights, flow ---------- */
.hero { background: radial-gradient(1200px 300px at 85% -40%, rgba(255,255,255,.22), transparent 60%),
        linear-gradient(135deg, #4338CA 0%, #6D28D9 55%, #7C3AED 100%);
        border-radius: 18px; padding: 30px 32px 28px 32px; color: #fff; margin-bottom: 1rem;
        box-shadow: 0 10px 30px -12px rgba(79,70,229,.55); }
.hero-chips { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
.hero-chips .pill { background: rgba(255,255,255,.16) !important; color: #fff !important; }
.hero-title { font-size: 2rem; font-weight: 800; letter-spacing: -0.025em; line-height: 1.15; max-width: 820px; }
.hero-text { font-size: 15.5px; line-height: 1.6; color: rgba(255,255,255,.88); margin-top: 10px; max-width: 760px; }
.ins-list { display: flex; flex-direction: column; gap: 10px; }
.ins { display: flex; gap: 10px; align-items: flex-start; }
.ins-ic { flex: 0 0 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.ins-t { font-size: 13.5px; color: #334155; line-height: 1.5; padding-top: 4px; }
.flow { display: flex; align-items: stretch; gap: 6px; margin-bottom: 1rem; }
.flow-step { flex: 1; background: #fff; border: 1px solid #E4E7EF; border-radius: 14px; padding: 14px 16px;
             box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.flow-val { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; margin: 2px 0; }
.flow-arrow { display: flex; align-items: center; }

/* ---------- bus list ---------- */
.bus-list { display: flex; flex-direction: column; gap: 8px; }
.bus { display: grid; grid-template-columns: 40px 1fr auto; gap: 12px; align-items: center; padding: 10px 12px;
       border: 1px solid #EEF0F5; border-radius: 12px; background: #FCFCFE; }
.bus-id { width: 40px; height: 40px; border-radius: 11px; background: #FFFBEB; color: #B45309; font-weight: 750;
          display: flex; align-items: center; justify-content: center; font-size: 13px; border: 1px solid #FDE68A; }
.bus-route { font-weight: 600; color: #0F172A; font-size: 13.5px; }
.bus-meta { color: #64748B; font-size: 12px; margin-top: 2px; }
.bus-time { text-align: right; }
.bus-time b { font-size: 15px; color: #0F172A; font-variant-numeric: tabular-nums; }
.bus-time div { color: #64748B; font-size: 12px; }
.bar { height: 5px; border-radius: 99px; background: #F1F5F9; margin-top: 6px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: linear-gradient(90deg, #F59E0B, #FBBF24); border-radius: 99px; }

/* ---------- inputs page ---------- */
.st-key-summary .flow { margin-bottom: .6rem; }
.st-key-summary .flow-step { padding: 10px 14px; }
.st-key-summary .flow-val { font-size: 1.55rem; }
.impact { display: flex; align-items: center; gap: 8px; background: #F5F3FF; border: 1px solid #DDD6FE; color: #4C1D95;
          border-radius: 10px; padding: 8px 12px; font-size: 13.5px; flex-wrap: wrap; }
.line-head { display: flex; align-items: center; gap: 8px; font-weight: 700; color: #0F172A; font-size: 15px; margin-bottom: 6px; }
.line-dot { width: 12px; height: 12px; border-radius: 99px; display: inline-block; }
.train-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-top: 10px;
             padding-top: 10px; border-top: 1px solid #F1F5F9; font-size: 14px; color: #0F172A; margin-bottom: 22px; }
.train-sub { color: #94A3B8; font-size: 12px; margin-top: 1px; }
.train-times { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 12px; color: #64748B; }
.train-times b { color: #0F172A; font-variant-numeric: tabular-nums; }
.train-times .pick b { color: #4F46E5; }
.dwell { display: flex; flex-direction: column; line-height: 1.25; }
.dwell span { font-size: 12.5px; color: #64748B; }
.dwell b { font-size: 1.25rem; color: #0F172A; }
.dwell small { font-size: 11.5px; color: #94A3B8; }
[data-testid="stSegmentedControl"] button p, [data-testid="stButtonGroup"] button p { font-weight: 550; }

/* ---------- widgets ---------- */
.stButton button, .stFormSubmitButton button, .stDownloadButton button { font-weight: 600; }
[data-testid="stExpander"] details { background: #FFFFFF; border-radius: 12px; }
[data-testid="stCode"] pre { font-size: 12.5px; line-height: 1.6; }
h1, h2, h3 { letter-spacing: -0.01em; }

/* ---------- components ---------- */
.ms { font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal; line-height: 1;
      letter-spacing: normal; text-transform: none; display: inline-block; white-space: nowrap;
      font-feature-settings: 'liga'; -webkit-font-smoothing: antialiased; font-variation-settings: 'FILL' 0, 'wght' 500; }
.ph { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; margin: 0 0 1.25rem 0; }
.ph-eyebrow { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: #6366F1; margin-bottom: .35rem; display: flex; align-items: center; gap: .4rem; }
.ph-title { font-size: 1.75rem; font-weight: 750; color: #0F172A; letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.ph-sub { color: #64748B; font-size: 14.5px; margin-top: .4rem; max-width: 780px; line-height: 1.55; }
.ph-right { display: flex; gap: .5rem; flex-wrap: wrap; justify-content: flex-end; }

.kpi-grid { display: grid; gap: 14px; margin: 0 0 1.1rem 0; }
.kpi { background: #FFFFFF; border: 1px solid #E4E7EF; border-radius: 14px; padding: 16px 18px;
       box-shadow: 0 1px 2px rgba(16,24,40,.04); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.kpi.hero { background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%); border: none; }
.kpi.hero .kpi-label, .kpi.hero .kpi-foot { color: rgba(255,255,255,.82); }
.kpi.hero .kpi-value { color: #FFFFFF; }
.kpi.hero .kpi-icon { background: rgba(255,255,255,.18); color: #FFFFFF; }
.kpi-top { display: flex; align-items: center; justify-content: space-between; }
.kpi-label { font-size: 13px; color: #64748B; font-weight: 500; }
.kpi-icon { width: 32px; height: 32px; border-radius: 9px; display: flex; align-items: center; justify-content: center; font-size: 19px; }
.kpi-value { font-size: 1.65rem; font-weight: 750; color: #0F172A; letter-spacing: -0.02em; line-height: 1.15; }
.kpi-value small { font-size: .9rem; font-weight: 600; color: #94A3B8; margin-left: 3px; }
.kpi-foot { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: #64748B; flex-wrap: wrap; }
.pill { display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.pill .ms { font-size: 15px; }

.sec { margin: .4rem 0 .6rem 0; }
.sec-title { font-size: 1.02rem; font-weight: 650; color: #0F172A; display: flex; align-items: center; gap: .45rem; }
.sec-title .ms { color: #6366F1; font-size: 20px; }
.sec-sub { color: #64748B; font-size: 13px; margin-top: 2px; line-height: 1.5; }

.steps { display: flex; flex-direction: column; gap: 12px; }
.step { display: flex; gap: 12px; align-items: flex-start; }
.step-n { flex: 0 0 28px; height: 28px; border-radius: 8px; background: #EEF2FF; color: #4338CA; font-weight: 700;
          display: flex; align-items: center; justify-content: center; font-size: 13px; }
.step-t { font-weight: 600; color: #0F172A; font-size: 14px; }
.step-d { color: #64748B; font-size: 13px; line-height: 1.5; }

.side-label { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: #94A3B8; margin: .6rem 0 .1rem 0; }
.note { background: #F8FAFC; border: 1px dashed #CBD5E1; border-radius: 10px; padding: 10px 12px; color: #64748B; font-size: 12.5px; line-height: 1.5; }
.legend-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin: 0 4px 0 10px; vertical-align: middle; }
</style>
"""


def inject_css():
    st.html(CSS)


def icon(name: str, size: int = 18, color: str | None = None) -> str:
    style = f"font-size:{size}px;" + (f"color:{color};" if color else "")
    return f'<span class="ms" style="{style}">{name}</span>'


def pill(text: str, tone: str = "slate", ic: str | None = None) -> str:
    fg, bg = TONES[tone]
    return f'<span class="pill" style="color:{fg};background:{bg}">{icon(ic, 15) if ic else ""}{html.escape(text)}</span>'


def page_header(title: str, subtitle: str = "", eyebrow: str = "", eyebrow_icon: str = "", right: str = ""):
    eb = f'<div class="ph-eyebrow">{icon(eyebrow_icon, 16) if eyebrow_icon else ""}{html.escape(eyebrow)}</div>' if eyebrow else ""
    sub = f'<div class="ph-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="ph"><div>{eb}<div class="ph-title">{html.escape(title)}</div>{sub}</div>'
                f'<div class="ph-right">{right}</div></div>', unsafe_allow_html=True)


def delta_pill(delta: float | None, fmt: str = "{:+.0f}", good_if_up: bool = True, suffix: str = "") -> str:
    if delta is None or abs(delta) < 1e-9:
        return pill("no change", "slate")
    up = delta > 0
    good = up == good_if_up
    return pill(fmt.format(delta) + suffix, "green" if good else "red", "arrow_upward" if up else "arrow_downward")


def kpi_cards(cards: list[dict], cols: int | None = None):
    """cards: label, value, unit?, icon, tone, foot (html), hero?"""
    parts = []
    for c in cards:
        fg, bg = TONES[c.get("tone", "indigo")]
        unit = f"<small>{html.escape(c['unit'])}</small>" if c.get("unit") else ""
        parts.append(
            f'<div class="kpi{" hero" if c.get("hero") else ""}">'
            f'<div class="kpi-top"><span class="kpi-label">{html.escape(c["label"])}</span>'
            f'<span class="kpi-icon" style="color:{fg};background:{bg}">{icon(c.get("icon", "insights"), 19)}</span></div>'
            f'<div class="kpi-value">{c["value"]}{unit}</div>'
            f'<div class="kpi-foot">{c.get("foot", "")}</div></div>')
    n = cols or len(cards)
    st.markdown(f'<div class="kpi-grid" style="grid-template-columns:repeat({n}, minmax(0,1fr))">{"".join(parts)}</div>',
                unsafe_allow_html=True)


def section(title: str, subtitle: str = "", ic: str = ""):
    sub = f'<div class="sec-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="sec"><div class="sec-title">{icon(ic, 20) if ic else ""}{html.escape(title)}</div>{sub}</div>',
                unsafe_allow_html=True)


def steps(items: list[tuple[str, str]]):
    body = "".join(f'<div class="step"><div class="step-n">{i}</div><div><div class="step-t">{html.escape(t)}</div>'
                   f'<div class="step-d">{d}</div></div></div>' for i, (t, d) in enumerate(items, 1))
    st.markdown(f'<div class="steps">{body}</div>', unsafe_allow_html=True)


def side_label(text: str):
    st.markdown(f'<div class="side-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def note(text: str):
    st.markdown(f'<div class="note">{text}</div>', unsafe_allow_html=True)


def hero(title: str, text: str, chips: str = ""):
    st.markdown(
        f'<div class="hero"><div class="hero-chips">{chips}</div><div class="hero-title">{html.escape(title)}</div>'
        f'<div class="hero-text">{text}</div></div>', unsafe_allow_html=True)


def insights(items: list[tuple[str, str, str]]):
    """items: (icon, tone, html text)."""
    rows = "".join(
        f'<div class="ins"><span class="ins-ic" style="color:{TONES[t][0]};background:{TONES[t][1]}">{icon(i, 17)}</span>'
        f'<div class="ins-t">{txt}</div></div>' for i, t, txt in items)
    st.markdown(f'<div class="ins-list">{rows}</div>', unsafe_allow_html=True)


def flow_kpis(steps_: list[tuple[str, str, str, str]]):
    """Horizontal 'today -> optimised -> + buses' flow. steps: (label, value, sub, tone)."""
    parts = []
    for i, (label, value, sub, tone) in enumerate(steps_):
        fg, bg = TONES[tone]
        if i:
            parts.append(f'<div class="flow-arrow">{icon("arrow_forward", 22, "#A5B4FC")}</div>')
        parts.append(f'<div class="flow-step" style="border-top:3px solid {fg}"><div class="kpi-label">{html.escape(label)}</div>'
                     f'<div class="flow-val" style="color:{fg}">{value}</div><div class="kpi-foot">{sub}</div></div>')
    st.markdown(f'<div class="flow">{"".join(parts)}</div>', unsafe_allow_html=True)


_card_ids = itertools.count()


def card():
    """White rounded card; use as `with ui.card():`."""
    return st.container(border=True, key=f"card-{next(_card_ids)}")


def bus_list(buses: list[dict]):
    if not buses:
        return
    top = max(b["pax"] for b in buses) or 1
    rows = []
    for b in buses:
        rows.append(
            f'<div class="bus"><div class="bus-id">{html.escape(b["name"].replace("Bus ", "B"))}</div>'
            f'<div><div class="bus-route">{html.escape(b["from_stop"])} → {html.escape(b["to_stop"])}</div>'
            f'<div class="bus-meta">{b["kind"].title()} · waits {b["wait"]:.1f} min · {b["pax"]:.0f} passengers</div>'
            f'<div class="bar"><span style="width:{100 * b["pax"] / top:.0f}%"></span></div></div>'
            f'<div class="bus-time"><b>{b["dep_s"]}</b><div>arr. {b["arr_s"]}</div></div></div>')
    st.markdown(f'<div class="bus-list">{"".join(rows)}</div>', unsafe_allow_html=True)


def chart(fig, **kw):
    """Render a Plotly figure with our template (Streamlit's own theme would override it)."""
    fig.layout.template = pio.templates["saas"]  # assign, don't merge into Streamlit's default template
    fig.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False}, **kw)
