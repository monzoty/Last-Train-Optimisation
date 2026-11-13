"""LastTrain: decision-support prototype for last-train timetabling + bus bridging (Kang et al., Omega 2019).

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import testcases
import ui
from charts import (BUS, MISS, OK, network_map, station_board, timetable_gantt, transfer_explainer,
                    window_chart)
from model import (Scenario, Train, dwell_estimate, fmt_time, kpis, parse_time, run_algorithm1, solve_bus,
                   solve_timetable, transfer_slack)
from scenarios import SCENARIOS

HERE = Path(__file__).parent
st.set_page_config(page_title="LastTrain · Night connections planner", page_icon=str(HERE / "assets/icon.svg"),
                   layout="wide")
ui.inject_css()
st.logo(str(HERE / "assets/logo.svg"), size="large", icon_image=str(HERE / "assets/icon.svg"))

PAPER_URL = "https://doi.org/10.1016/j.omega.2018.04.003"
TIME_OPTIONS = list(range(-30, 121))


# ======================================================== scenario state
# One source of truth: st.session_state.sc_json (the working scenario).
# Every input writes into it through `mutate`, and every page re-solves from it (cached).
def sc_to_json(sc: Scenario) -> str:
    return json.dumps(dataclasses.asdict(sc), sort_keys=True)


def sc_from_json(s: str) -> Scenario:
    d = json.loads(s)
    d["trains"] = {k: Train(**v) for k, v in d["trains"].items()}
    return Scenario(**d)


def bump():
    """Give every input widget a fresh key so it re-reads the scenario (after a reset or network change)."""
    st.session_state.ver = st.session_state.get("ver", 0) + 1


def load_scenario(name: str):
    sc = SCENARIOS[name]()
    st.session_state.loaded = name
    st.session_state.base_json = st.session_state.sc_json = sc_to_json(sc)
    bump()


def mutate(fn, msg: str | None = None):
    sc = sc_from_json(st.session_state.sc_json)
    fn(sc)
    st.session_state.sc_json = sc_to_json(sc)
    if msg:
        st.session_state.toast = msg


def k(name: str) -> str:
    return f"{name}__{st.session_state.ver}"


def current_scenario() -> tuple[Scenario, str]:
    """Working scenario; its JSON is the cache key for every solve."""
    return sc_from_json(st.session_state.sc_json), st.session_state.sc_json


# ================================================================ solving
@st.cache_data(show_spinner=False)
def solve(key: str, optimise: bool) -> dict:
    return run_algorithm1(sc_from_json(key), optimise_timetable=optimise)


@st.cache_data(show_spinner=False)
def uncapped_buses(key: str) -> int:
    sc = sc_from_json(key)
    tt = solve_timetable(sc)
    return len(solve_bus(sc, tt["deps"], tt["connect"], fleet=None)["buses"]) if tt["status"] != "INFEASIBLE" else 0


@st.cache_data(show_spinner=False)
def fleet_sweep(key: str, max_n: int) -> pd.DataFrame:
    sc = sc_from_json(key)
    tt = solve_timetable(sc)
    rows = []
    for n in range(max_n + 1):
        kk = kpis(sc, tt["deps"], solve_bus(sc, tt["deps"], tt["connect"], fleet=n))
        rows.append({"Buses (N)": n, "Bridged passengers": kk["Carried by bridging bus"],
                     "Transfer rate train + bus (%)": kk["Transfer rate - train + bus (%)"]})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def run_tests() -> pd.DataFrame:
    return pd.DataFrame(testcases.run_all())


def results(key: str):
    return solve(key, False), solve(key, True)


def three_kpis(sc, cur, opt):
    return (kpis(sc, cur["timetable"]["deps"], None), kpis(sc, opt["timetable"]["deps"], None),
            kpis(sc, opt["timetable"]["deps"], opt["bus"]))


# ================================================================ helpers
def direction_table(sc: Scenario, cur: dict, opt: dict) -> pd.DataFrame:
    s_cur, _, _ = transfer_slack(sc, cur["timetable"]["deps"])
    s_opt, _, _ = transfer_slack(sc, opt["timetable"]["deps"])
    pax = sc.direction_pax()
    bridged = {}
    for b in opt["bus"]["buses"]:
        for gid in b["riders"]:
            g = sc.od[gid]
            bridged.setdefault((g["from_train"], g["to_train"], g["transfer"]), []).append(b["name"])
    rows = []
    for d in sorted(s_cur, key=lambda d: (d[2], d[0], d[1])):
        f, c, kk = d
        outcome = ("Connected" if s_opt[d] >= -1e-6 else
                   ("Bus: " + ", ".join(sorted(set(bridged[d])))) if d in bridged else
                   ("No demand" if not pax[d] else "Stranded"))
        rows.append({"Station": kk, "From": f, "To": c, "Passengers": pax[d],
                     "Slack today": s_cur[d], "Today": "✅" if s_cur[d] >= -1e-6 else "❌",
                     "Slack optimised": s_opt[d], "Optimised": "✅" if s_opt[d] >= -1e-6 else "❌",
                     "Outcome": outcome})
    return pd.DataFrame(rows)


def bus_table(sc: Scenario, bus: dict) -> pd.DataFrame:
    return pd.DataFrame([{"Bus": b["name"], "Serves": "; ".join(f"{g['origin']}→{g['dest']} ({g['pax']:.0f})"
                                                                for g in (sc.od[i] for i in b["riders"]))}
                         for b in bus["buses"]])


def timetable_table(sc: Scenario, deps: dict) -> pd.DataFrame:
    return pd.DataFrame([{"Train": tid, "Line": t.line, "From": t.stations[0], "To": t.stations[-1],
                          "Window": f"{fmt_time(t.earliest_dep)} – {fmt_time(t.latest_dep)}",
                          "Today": fmt_time(t.current_dep), "Optimised": fmt_time(deps[tid]),
                          "Shift (min)": int(deps[tid] - t.current_dep)} for tid, t in sc.trains.items()])


def header_chips(sc: Scenario) -> str:
    edited = st.session_state.sc_json != st.session_state.base_json
    return (ui.pill(sc.name, "indigo", "hub")
            + (ui.pill("Edited", "violet", "edit") if edited else ui.pill("Example data", "amber", "science")))


def need_ok(res: dict) -> bool:
    if res["status"] != "OK":
        st.error(f"The model could not be solved: {res.get('message')}", icon=":material/error:")
        st.info("Check the departure windows on the Inputs page. Earliest must be before latest.",
                icon=":material/lightbulb:")
        return False
    return True


def headline(sc, cur, opt):
    """The three numbers the whole project is about: today → re-timed trains → + buses."""
    kc, ko, kb = three_kpis(sc, cur, opt)
    ui.flow_kpis([
        ("Today's timetable", f"{kc['Transfer rate - train only (%)']:.0f}%",
         f"{kc['Connected by last train']:.0f} of {kc['Transfer passengers (total)']:.0f} passengers", "slate"),
        ("① Re-time the last trains", f"{ko['Transfer rate - train only (%)']:.0f}%",
         ui.delta_pill(ko["Transfer rate - train only (%)"] - kc["Transfer rate - train only (%)"], suffix=" pts")
         + "<span>no extra vehicles</span>", "indigo"),
        (f"② Add {kb['Buses deployed']} bridging buses", f"{kb['Transfer rate - train + bus (%)']:.0f}%",
         ui.delta_pill(kb["Transfer rate - train + bus (%)"] - kc["Transfer rate - train only (%)"], suffix=" pts")
         + f"<span>{kb['Stranded']:.0f} still stranded</span>", "green"),
    ])


def make_insights(sc: Scenario, cur: dict, opt: dict, unc: int) -> list[tuple[str, str, str]]:
    kc, ko, kb = three_kpis(sc, cur, opt)
    items = []
    dc = ko["Transfer directions connected"] - kc["Transfer directions connected"]
    dp = ko["Connected by last train"] - kc["Connected by last train"]
    if dp > 0:
        items.append(("schedule", "indigo", f"Re-timing the last trains connects <b>{dc:+d} transfer directions</b> and "
                                            f"<b>{dp:.0f} more passengers</b>, with no extra vehicles."))
    else:
        items.append(("schedule", "slate", "Today's timetable is already the best possible inside these windows. "
                                           "Widen the departure windows to gain more."))
    shifts = {tid: opt["timetable"]["deps"][tid] - t.current_dep for tid, t in sc.trains.items()}
    tid = max(shifts, key=lambda t: abs(shifts[t]))
    if shifts[tid]:
        items.append(("swap_horiz", "violet",
                      f"Biggest change: <b>{tid}</b> leaves <b>{abs(shifts[tid]):.0f} min "
                      f"{'later' if shifts[tid] > 0 else 'earlier'}</b> "
                      f"({fmt_time(sc.trains[tid].current_dep)} → {fmt_time(opt['timetable']['deps'][tid])})."))
    nb = kb["Buses deployed"]
    if nb:
        items.append(("directions_bus", "amber", f"<b>{nb} bridging bus{'es' * (nb > 1)}</b> carry "
                                                 f"<b>{kb['Carried by bridging bus']:.0f} passengers</b>, "
                                                 f"each waiting about {kb['Avg bus wait (min)']:.1f} min."))
    fleet = sc.params["fleet"]
    if unc > fleet:
        items.append(("garage", "red", f"The fleet is the bottleneck: <b>{unc} buses</b> would bridge everyone, but "
                                       f"only <b>{fleet}</b> are available (see the Fleet size tab)."))
    left = [g for g in opt["bus"]["groups"] if g["gid"] not in opt["bus"]["served"]]
    if not left:
        items.append(("celebration", "green", "<b>Nobody is stranded tonight.</b> Every transfer passenger reaches their "
                                              "line by train or bus."))
    return items


def toast_once():
    msg = st.session_state.pop("toast", None)
    if msg:
        st.toast(msg, icon=":material/bolt:")


# ================================================================ sidebar
if "loaded" not in st.session_state:
    load_scenario(list(SCENARIOS)[0])
    st.session_state.scenario_pick = st.session_state.loaded

with st.sidebar:
    ui.side_label("Network")
    st.selectbox("Network", list(SCENARIOS), key="scenario_pick", label_visibility="collapsed",
                 on_change=lambda: load_scenario(st.session_state.scenario_pick),
                 help="Metro City: a 3-line city. Two-line crossing: a tiny network you can check by hand.")
    st.button("Reset to example data", icon=":material/restart_alt:", width="stretch",
              on_click=lambda: (load_scenario(st.session_state.loaded),
                                st.session_state.__setitem__("toast", "Back to the example data")))
    st.write("")
    ui.note(f"Prototype for <b>Kang et al. (2019)</b>, <i>Omega</i> 84. Network and demand data are illustrative. "
            f"<a href='{PAPER_URL}' target='_blank'>Read the paper ↗</a>")


# ================================================================== pages
def page_home():
    toast_once()
    sc, key = current_scenario()
    cur, opt = results(key)
    ui.hero("Nobody should be stranded by the last train.",
            "At midnight, passengers changing metro lines often arrive just after the connecting line's last train "
            "has gone. <b>LastTrain</b> re-times the last trains so more of them meet, then plans a few bridging "
            "buses for everyone still left behind.",
            chips=ui.pill("MILP · OR-Tools", "slate", "memory") + ui.pill("Kang et al. 2019, Omega", "slate", "menu_book"))
    if not need_ok(opt):
        return
    ui.section("Tonight on " + sc.name, "Share of last-train transfer passengers who reach their connecting line.",
               "query_stats")
    headline(sc, cur, opt)
    left, right = st.columns([1.4, 1], gap="medium")
    with left, ui.card():
        ui.section("The optimised plan", "Lines in colour, transfer stations as rings. Dotted amber arrows are "
                                         "bridging buses.", "map")
        ui.chart(network_map(sc, opt["bus"]["buses"], height=440))
    with right, ui.card():
        ui.section("How it works", ic="route")
        ui.steps([
            ("The problem", "Each line runs one last train per direction. If yours arrives after the connecting "
                            "line's last train has left, you are stranded."),
            ("Step 1 · re-time the trains (MILP-1)", "Move each last train a few minutes inside an allowed window "
                                                     "so the busiest transfers meet. Costs nothing extra."),
            ("Step 2 · send buses (MILP-2)", "For transfers that still fail, pick which bus routes to run and when, "
                                             "with a limited fleet."),
            ("You try it", "Change inputs on the Inputs page and see the new plan on Results."),
        ])
        c1, c2 = st.columns(2)
        c1.page_link(PAGES["inputs"], label="Change inputs", icon=":material/edit:")
        c2.page_link(PAGES["results"], label="See results", icon=":material/insights:")

    with ui.card():
        ui.section("The one rule the model is built on: will you make your connection?",
                   "Move the sliders.", "touch_app")
        c1, c2, c3 = st.columns(3, gap="large")
        arrive = c1.select_slider("Your last train arrives at", TIME_OPTIONS[30:61], value=20, format_func=fmt_time)
        walk = c2.slider("Walk to the other platform (min)", 0.5, 8.0, 3.0, 0.5)
        leave = c3.select_slider("Connecting last train leaves at", TIME_OPTIONS[30:61], value=22,
                                 format_func=fmt_time)
        ui.chart(transfer_explainer(arrive, walk, leave))
        slack = leave - (arrive + walk)
        if slack >= 0:
            st.success(f"You make it with **{slack:.1f} min** to spare. The model counts this transfer as "
                       "**connected**.", icon=":material/check_circle:")
        else:
            st.error(f"You miss it by **{-slack:.1f} min**. Either the timetable moves one of the trains, or a "
                     "**bridging bus** picks you up.", icon=":material/cancel:")
        st.caption("Slack = connecting train's departure − (your arrival + walking time). Slack ≥ 0 means connected. "
                   "The model checks this for every transfer in the network.")


SECTIONS = {"trains": ":material/train: Train times", "stations": ":material/directions_walk: Stations",
            "pax": ":material/groups: Passengers", "buses": ":material/directions_bus: Buses"}


def edit(fn, msg: str):
    """Apply a change from the Inputs page and refresh every widget so they all show the new value."""
    mutate(fn, msg)
    bump()


def impact_strip(sc: Scenario, opt: dict):
    """One line comparing the current inputs with the example data."""
    if st.session_state.sc_json == st.session_state.base_json:
        ui.note("You are looking at the <b>example data</b>. Change anything below and the numbers above update "
                "straight away.")
        return
    base = sc_from_json(st.session_state.base_json)
    bo = solve(st.session_state.base_json, True)
    if bo["status"] != "OK" or opt["status"] != "OK":
        return
    b = kpis(base, bo["timetable"]["deps"], bo["bus"])
    n = kpis(sc, opt["timetable"]["deps"], opt["bus"])
    rb, rn = b["Transfer rate - train + bus (%)"], n["Transfer rate - train + bus (%)"]
    c1, c2 = st.columns([5, 1])
    c1.markdown(
        f"<div class='impact'>{ui.icon('compare_arrows', 18, '#6D28D9')}<span>Compared with the example data: "
        f"<b>{rb:.0f}% → {rn:.0f}%</b> {ui.delta_pill(rn - rb, suffix=' pts')} of transfer passengers make it · "
        f"stranded <b>{b['Stranded']:.0f} → {n['Stranded']:.0f}</b></span></div>", unsafe_allow_html=True)
    c2.button("Undo all", icon=":material/restart_alt:", width="stretch", key="undo_all",
              on_click=lambda: (load_scenario(st.session_state.loaded),
                                st.session_state.__setitem__("toast", "Back to the example data")))


def changed_badge(changed: bool) -> str:
    return ui.pill("changed", "violet", "edit") if changed else ""


def inputs_trains(sc: Scenario, base: Scenario, opt: dict):
    with ui.card():
        ui.section("When may each last train leave?",
                   "Drag the ends of each slider below to set the earliest and latest departure planners allow. The "
                   "model picks the best time inside that range. Wider ranges usually connect more people.",
                   "schedule")
        ui.chart(window_chart(sc, opt["timetable"]["deps"] if opt["status"] == "OK" else None))
        st.caption("Shaded bar = allowed range · ○ = today's departure · ◆ = the model's choice")
    lines: dict[str, list] = {}
    for tid, t in sc.trains.items():
        lines.setdefault(t.line, []).append(tid)
    cols = st.columns(len(lines), gap="small")
    for col, (line, tids) in zip(cols, lines.items()):
        with col, ui.card():
            st.markdown(f"<div class='line-head'><span class='line-dot' style='background:{sc.line_colors[line]}'>"
                        f"</span>{line} line</div>", unsafe_allow_html=True)
            for tid in tids:
                t, b = sc.trains[tid], base.trains[tid]
                pick = opt["timetable"]["deps"][tid] if opt["status"] == "OK" else None
                ch = (t.earliest_dep, t.latest_dep, t.current_dep) != (b.earliest_dep, b.latest_dep, b.current_dep)
                st.markdown(
                    f"<div class='train-row'><div><b>{tid}</b> {changed_badge(ch)}<div class='train-sub'>"
                    f"{t.stations[0]} → {t.stations[-1]}</div></div><div class='train-times'>"
                    f"<span>today <b>{fmt_time(t.current_dep)}</b></span>"
                    + (f"<span class='pick'>model <b>{fmt_time(pick)}</b></span>" if pick is not None else "")
                    + "</div></div>", unsafe_allow_html=True)
                full = k(f"win_{tid}")

                def set_window(full=full, tid=tid):
                    lo, hi = st.session_state[full]

                    def fn(sc_):
                        sc_.trains[tid].earliest_dep, sc_.trains[tid].latest_dep = int(lo), int(hi)
                    edit(fn, f"{tid} may leave {fmt_time(lo)} – {fmt_time(hi)}")

                st.select_slider(f"Allowed departure range for {tid}", TIME_OPTIONS,
                                 value=(int(t.earliest_dep), int(t.latest_dep)), format_func=fmt_time, key=full,
                                 label_visibility="collapsed", on_change=set_window)
    with st.expander("Change today's departure times", icon=":material/edit_calendar:"):
        st.caption("Today's departures are the timetable the model starts from (the ○ markers). Type times as HH:MM.")
        ids = list(sc.trains)
        df = pd.DataFrame([{"Train": tid, "Today's departure": fmt_time(t.current_dep)} for tid, t in sc.trains.items()])
        ek = k("ed_today")

        def apply_today():
            edits = st.session_state[ek]["edited_rows"]

            def fn(sc_):
                for r, ch_ in edits.items():
                    if ch_.get("Today's departure"):
                        sc_.trains[ids[int(r)]].current_dep = parse_time(ch_["Today's departure"])
            try:
                edit(fn, "Today's departure updated")
            except Exception:  # noqa: BLE001
                st.session_state.toast = "Could not read a time. Use HH:MM, e.g. 00:25"

        st.data_editor(df, hide_index=True, disabled=["Train"], key=ek, on_change=apply_today)


def inputs_stations(sc: Scenario, base: Scenario):
    names = [s for s, d in sc.stations.items() if d["walk_transfer"] is not None]
    ui.note("At a <b>transfer station</b> people walk from one platform to the other. Longer walks break tight "
            "connections. <b>Dwell</b> is how long a train stands at the platform: we store the times seen on past "
            "nights, and the model turns them into one robust value (the paper's defuzzification).")
    st.write("")
    for row in range(0, len(names), 3):
        cols = st.columns(3, gap="small")
        for col, s in zip(cols, names[row:row + 3]):
            d, b = sc.stations[s], base.stations[s]
            with col, ui.card():
                ch = (d["walk_transfer"], d["walk_bus"], d["dwell_samples"]) != (b["walk_transfer"], b["walk_bus"],
                                                                                 b["dwell_samples"])
                st.markdown(f"<div class='line-head'>{ui.icon('transfer_within_a_station', 20, '#6366F1')}{s} "
                            f"{changed_badge(ch)}</div>", unsafe_allow_html=True)
                for label, field, lo, hi in [("Walk between platforms", "walk_transfer", 0.5, 8.0),
                                             ("Walk to the bus stop", "walk_bus", 0.0, 10.0)]:
                    full = k(f"{field}_{s}")

                    def set_walk(full=full, s=s, field=field, label=label):
                        v = float(st.session_state[full])
                        edit(lambda sc_: sc_.stations[s].__setitem__(field, v), f"{s}: {label.lower()} {v} min")

                    st.slider(label, lo, hi, float(d[field]), 0.5, format="%.1f min", key=full, on_change=set_walk)
                smp = d["dwell_samples"]
                c1, c2 = st.columns([1.4, 1])
                c1.markdown(f"<div class='dwell'><span>Train stands</span><b>{dwell_estimate(smp, 'defuzzified'):.0f} s"
                            f"</b><small>from {len(smp)} past nights</small></div>", unsafe_allow_html=True)
                with c2.popover("Edit", icon=":material/tune:", width="stretch"):
                    st.markdown(f"**Dwell times seen at {s}** (seconds, comma separated)")
                    full = k(f"dwell_{s}")

                    def set_dwell(full=full, s=s):
                        vals = [float(x) for x in str(st.session_state[full]).replace(";", ",").split(",")
                                if x.strip()]
                        if vals:
                            edit(lambda sc_: sc_.stations[s].__setitem__("dwell_samples", vals),
                                 f"{s}: dwell samples updated")

                    st.text_area("Samples", ", ".join(f"{v:g}" for v in smp), key=full, height=120,
                                 label_visibility="collapsed", on_change=set_dwell)
                    st.caption(f"Mean {dwell_estimate(smp, 'mean'):.1f} s · median "
                               f"{dwell_estimate(smp, 'median'):.1f} s · used {dwell_estimate(smp, 'defuzzified'):.1f} s")


def inputs_pax(sc: Scenario, base: Scenario):
    stations = sorted({g["transfer"] for g in sc.od})
    totals = {s: sum(g["pax"] for g in sc.od if g["transfer"] == s) for s in stations}
    with ui.card():
        ui.section("How many people change lines tonight?",
                   "Each row is a group making the same trip. Pick a station, then type a new number in the "
                   "Passengers column, or scale them all at once.", "groups")
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            where = st.segmented_control("Station", ["All"] + stations, default="All", key="pax_where",
                                         format_func=lambda s: f"All · {sum(totals.values()):.0f}" if s == "All"
                                         else f"{s} · {totals[s]:.0f}", label_visibility="collapsed") or "All"
        rows = [i for i, g in enumerate(sc.od) if where == "All" or g["transfer"] == where]

        def scale(f):
            def fn(sc_):
                for i in rows:
                    sc_.od[i]["pax"] = round(sc_.od[i]["pax"] * f)
            edit(fn, f"Passengers {'+' if f > 1 else '−'}20% ({where})")

        c2.button("−20%", icon=":material/remove:", width="stretch", on_click=scale, args=(0.8,))
        c3.button("+20%", icon=":material/add:", width="stretch", on_click=scale, args=(1.2,))
        df = pd.DataFrame([{"From": sc.od[i]["origin"], "Arrives on": sc.od[i]["from_train"],
                            "Changes at": sc.od[i]["transfer"], "Continues on": sc.od[i]["to_train"],
                            "To": sc.od[i]["dest"], "Passengers": sc.od[i]["pax"], "Example": base.od[i]["pax"]}
                           for i in rows])
        ek = k(f"ed_od_{where}")

        def apply_od():
            edits = st.session_state[ek]["edited_rows"]

            def fn(sc_):
                for r, ch in edits.items():
                    if ch.get("Passengers") is not None:
                        sc_.od[rows[int(r)]]["pax"] = max(0.0, float(ch["Passengers"]))
            edit(fn, "Passenger numbers updated")

        st.data_editor(df, hide_index=True, key=ek, height=min(460, 36 * (len(df) + 1) + 2), on_change=apply_od,
                       disabled=[c for c in df.columns if c != "Passengers"],
                       column_config={"Passengers": st.column_config.NumberColumn("Passengers ✎", min_value=0, step=1,
                                                                                  format="%d"),
                                      "Example": st.column_config.NumberColumn(format="%d")})


def inputs_buses(sc: Scenario, base: Scenario, opt: dict):
    p, bp = sc.params, base.params

    def slider(label, field, lo=0, hi=0, fmt=None, help_=None, options=None):
        full = k(field)

        def cb():
            v = int(st.session_state[full])
            edit(lambda sc_: sc_.params.__setitem__(field, v), f"{label}: {fmt_time(v) if options else v}")

        if options:
            st.select_slider(label, options, value=int(p[field]), format_func=fmt_time, key=full, on_change=cb,
                             help=help_)
        else:
            st.slider(label, lo, hi, int(p[field]), format=fmt, key=full, on_change=cb, help=help_)

    c1, c2 = st.columns(2, gap="small")
    with c1, ui.card():
        ui.section("How many buses are available?", "Buses cost money, so the fleet is limited (paper constraint 10).",
                   "garage")
        slider("Bridging buses (N)", "fleet", 0, 20, fmt="%d buses")
        if opt["status"] == "OK":
            unc = uncapped_buses(st.session_state.sc_json)
            if unc > p["fleet"]:
                n = p["fleet"]
                st.warning(f"{'All ' + str(n) + ' buses are' if n > 1 else str(n) + ' bus is'} in use. **{unc}** "
                           "would be needed to bridge everyone.",
                           icon=":material/info:")
            else:
                st.success(f"{len(opt['bus']['buses'])} of {p['fleet']} buses used: enough to bridge every missed "
                           "transfer.", icon=":material/check_circle:")
    with c2, ui.card():
        ui.section("When can buses run?", "Passengers need time to reach the stop, and buses stop at a set time.",
                   "schedule")
        slider("Safety buffer before a bus leaves", "bus_buffer", 0, 10, fmt="%d min",
               help_="Extra minutes a bus waits after passengers reach the stop.")
        slider("Last bus may leave by", "bus_latest", options=list(range(15, 181, 5)), help_="Paper constraint 37.")
    with st.expander("Advanced: how the model weighs connections", icon=":material/settings:"):
        slider("Bonus per connected transfer (γ)", "gamma", 0, 30,
               help_="Step 1 maximises connected passengers + γ × number of connected transfers. The paper uses 12.")
        st.caption("Higher γ makes the model prefer connecting more transfers, even small ones. 0 = count passengers "
                   "only.")
    changed = [(f, n) for f, n in [("fleet", "buses"), ("bus_buffer", "buffer"), ("bus_latest", "last bus"),
                                   ("gamma", "γ")] if p[f] != bp[f]]
    if changed:
        st.caption("✎ Changed from the example: " + ", ".join(
            f"{n} {fmt_time(bp[f]) if f == 'bus_latest' else bp[f]} → {fmt_time(p[f]) if f == 'bus_latest' else p[f]}"
            for f, n in changed))


def page_inputs():
    toast_once()
    sc, key = current_scenario()
    base = sc_from_json(st.session_state.base_json)
    ui.page_header("Inputs", "Change anything below. The model re-solves straight away and the numbers at the top "
                             "update.", eyebrow="Step 1", eyebrow_icon="edit", right=header_chips(sc))
    cur, opt = results(key)
    with st.container(key="summary"):
        if opt["status"] == "OK":
            headline(sc, cur, opt)
        else:
            need_ok(opt)
        impact_strip(sc, opt)
    section = st.segmented_control("Section", list(SECTIONS), format_func=SECTIONS.get, default="trains",
                                   key="inputs_section", label_visibility="collapsed") or "trains"
    if section == "trains":
        inputs_trains(sc, base, opt)
    elif section == "stations":
        inputs_stations(sc, base)
    elif section == "pax":
        inputs_pax(sc, base)
    else:
        inputs_buses(sc, base, opt)


def page_results():
    toast_once()
    sc, key = current_scenario()
    cur, opt = results(key)
    ui.page_header("Results", "Tonight's plan: which transfers now connect, which buses run, and when.",
                   eyebrow="Step 2", eyebrow_icon="insights", right=header_chips(sc))
    if not need_ok(opt):
        return
    kc, _, kb = three_kpis(sc, cur, opt)
    ui.kpi_cards([
        dict(label="Connections", value=kb["Transfer directions connected"], unit=f"/ {kb['Transfer directions (total)']}",
             icon="link", tone="indigo",
             foot=ui.delta_pill(kb["Transfer directions connected"] - kc["Transfer directions connected"]) + "<span>vs today</span>"),
        dict(label="Connected by train", value=f"{kb['Connected by last train']:.0f}", unit="pax", icon="train",
             tone="blue", foot=ui.delta_pill(kb["Connected by last train"] - kc["Connected by last train"]) + "<span>vs today</span>"),
        dict(label="Bridged by bus", value=f"{kb['Carried by bridging bus']:.0f}", unit="pax", icon="directions_bus",
             tone="amber", foot=f"{kb['Buses deployed']} buses deployed"),
        dict(label="Stranded", value=f"{kb['Stranded']:.0f}", unit="pax", icon="person_off", tone="red",
             foot=ui.delta_pill(kb["Stranded"] - kc["Stranded"], good_if_up=False) + "<span>vs today</span>"),
    ])
    with ui.card():
        ui.section("What the model found", "Written automatically from the solution.", "auto_awesome")
        ui.insights(make_insights(sc, cur, opt, uncapped_buses(key)))

    tabs = st.tabs([":material/map: Bus plan", ":material/transfer_within_a_station: Transfer stations",
                    ":material/view_timeline: Timetable", ":material/list_alt: All transfers",
                    ":material/garage: Fleet size"])
    with tabs[0]:
        l, r = st.columns([1.55, 1], gap="medium")
        with l, ui.card():
            ui.section("Bridging plan", "Dotted amber arrows are buses, labelled with departure time.", "map")
            ui.chart(network_map(sc, opt["bus"]["buses"], height=500))
        with r, ui.card():
            ui.section("Bus schedule", "<b>Replacement</b> buses run along the missed line. <b>Direct</b> buses "
                                       "go from origin straight to destination.", "directions_bus")
            buses = opt["bus"]["buses"]
            if not buses:
                st.info("No buses needed: every transfer with demand connects by train.", icon=":material/celebration:")
            else:
                ui.bus_list([dict(b, wait=b["dep"] - b["ready"], dep_s=fmt_time(b["dep"]), arr_s=fmt_time(b["arr"]))
                             for b in buses])
                with st.expander("Passenger groups served", icon=":material/groups:"):
                    st.dataframe(bus_table(sc, opt["bus"]), hide_index=True)
    with tabs[1], ui.card():
        tx = [s for s, d in sc.stations.items() if d["walk_transfer"] is not None]
        c1, c2 = st.columns([1, 3])
        with c1:
            st_pick = st.selectbox("Transfer station", tx)
        with c2:
            st.markdown(
                f"<div class='sec-sub' style='margin-top:1.9rem'>Bars: each last train standing at <b>{st_pick}</b>. "
                f"Dotted lines: passengers walking <b>{sc.stations[st_pick]['walk_transfer']} min</b> to the other "
                f"platform. <span class='legend-dot' style='background:{OK}'></span>made it "
                f"<span class='legend-dot' style='background:{MISS}'></span>train already gone.</div>",
                unsafe_allow_html=True)
        l, r = st.columns(2, gap="medium")
        with l:
            ui.chart(station_board(sc, cur["timetable"]["deps"], st_pick, "Today"))
        with r:
            ui.chart(station_board(sc, opt["timetable"]["deps"], st_pick, "Optimised"))
    with tabs[2], ui.card():
        ui.section("Last-train timetable", "Grey outline = today, solid bar = optimised, ◇ = transfer station.",
                   "view_timeline")
        ui.chart(timetable_gantt(sc, cur["timetable"]["deps"], opt["timetable"]["deps"]))
        st.dataframe(timetable_table(sc, opt["timetable"]["deps"]), hide_index=True,
                     column_config={"Shift (min)": st.column_config.NumberColumn(format="%+d")})
    with tabs[3], ui.card():
        ui.section("Every transfer", "Slack = connecting departure − (arrival + walk). ≥ 0 means the transfer works.",
                   "list_alt")
        st.dataframe(direction_table(sc, cur, opt), hide_index=True, height=520,
                     column_config={"Slack today": st.column_config.NumberColumn(format="%.1f min"),
                                    "Slack optimised": st.column_config.NumberColumn(format="%.1f min"),
                                    "Passengers": st.column_config.NumberColumn(format="%d")})
    with tabs[4], ui.card():
        ui.section("How many buses are worth it?", "The model re-solved for every fleet size N (paper section 4.3). "
                                                   "The dark bar is the fleet set on the Inputs page. The amber line "
                                                   "shows how many passengers each extra bus adds: it falls, so each "
                                                   "bus helps less than the one before.", "garage")
        df = fleet_sweep(key, max(8, len(opt["bus"]["groups"])))
        gain = df["Bridged passengers"].diff().fillna(0)
        fig = go.Figure()
        fig.add_bar(x=df["Buses (N)"], y=df["Transfer rate train + bus (%)"], name="Transfer rate (%)",
                    marker=dict(color=["#4F46E5" if n == sc.params["fleet"] else "#C7D2FE" for n in df["Buses (N)"]],
                                cornerradius=6),
                    hovertemplate="N = %{x}<br>%{y:.1f}% transfer rate<extra></extra>")
        fig.add_scatter(x=df["Buses (N)"], y=gain, name="Passengers gained by this extra bus", yaxis="y2",
                        mode="lines+markers", line=dict(color=BUS, width=2.5, shape="spline"),
                        marker=dict(size=7, color="white", line=dict(color=BUS, width=2)),
                        hovertemplate="bus #%{x}: +%{y:.0f} pax<extra></extra>")
        fig.update_layout(height=380, yaxis=dict(title="transfer rate (%)", range=[0, 105]),
                          yaxis2=dict(title="passengers gained", overlaying="y", side="right", showgrid=False,
                                      rangemode="tozero", automargin=True, tickfont=dict(color="#64748B")),
                          xaxis=dict(title="bridging buses available (N)", dtick=1))
        ui.chart(fig)


FLOW = """
digraph G { rankdir=TB; bgcolor="transparent"; nodesep=0.3; ranksep=0.32;
  node [shape=box, style="rounded,filled", fontname="Inter", fontsize=11, color="#C7D2FE", fillcolor="#F5F7FF",
        fontcolor="#1E293B", penwidth=1.2, margin="0.18,0.08"];
  edge [color="#94A3B8", arrowsize=0.7, fontname="Inter", fontsize=10, fontcolor="#64748B"];
  a [label="Inputs\\ntrains · windows · walk & dwell · passengers"];
  c [label="MILP-1 · last-train timetable\\nmax connected passengers", fillcolor="#4F46E5", color="#4F46E5", fontcolor="white"];
  d [label="Transfers that still fail"];
  e [label="MILP-2 · bus bridging (no fleet cap)", fillcolor="#FFFBEB", color="#FCD34D"];
  f [label="buses ≤ N ?", shape=diamond, fillcolor="white", color="#CBD5E1"];
  g [label="MILP-2 with fleet cap", fillcolor="#FFFBEB", color="#FCD34D"];
  h [label="Plan: departures · connections · buses", fillcolor="#ECFDF5", color="#6EE7B7"];
  a->c->d->e->f; f->h [label=" yes"]; f->g [label=" no"]; g->h; }"""

MILP1 = [
    ("C1 · Departure window", "pEarliestDep(t) ≤ varLastDep(t) ≤ pLatestDep(t)",
     "A last train may only move inside the window planners allow.", "5"),
    ("C2 · Arrival time", "Arr(t,k) = varLastDep(t) + Sum of pRunTime up to k + Sum of pDwell before k",
     "When train t reaches station k.", "3"),
    ("C3 · Departure time", "Dep(t,k) = Arr(t,k) + pDwell(k)", "When train t leaves station k.", "4"),
    ("C4 · Transfer slack", "Slack(f,c,k) = Dep(c,k) − Arr(f,k) − pWalk(k)",
     "Spare minutes for passengers changing from f to c at k.", "7"),
    ("C5 · Connect only if slack ≥ 0", "Slack(d) ≥ −M(d) · (1 − varConnect(d))",
     "If we count a transfer as connected, its slack must be ≥ 0. M(d) is the smallest valid big-M.", "8–9"),
    ("C6 · Positive slack counts", "Slack(d) ≤ M'(d) · varConnect(d)",
     "If the slack is positive, the transfer must be counted as connected.", "9"),
    ("Objective", "Maximise Sum over d of pPax(d) · varConnect(d) + pConnWeight · Sum over d of varConnect(d)",
     "Connect as many passengers as possible, plus a bonus γ per connected transfer.", "32"),
]
MILP2 = [
    ("B1 · Bus leaves after passengers arrive", "varBusDep(r) ≥ (pReady(r) + pBusBuffer) · varBusRoute(r)",
     "pReady(r) = feeder arrival at the stop + walk to the bus stop.", "36"),
    ("B2 · Bus time window", "pBusEarliestDep ≤ varBusDep(r) ≤ pBusLatestDep", "Buses run only in the allowed hours.", "37"),
    ("B3 · Ride only a running bus", "varAssign(g,r) ≤ varBusRoute(r)", "A group can only use a bus that runs.", "11"),
    ("B4 · At most one bus per group", "Sum over r of varAssign(g,r) ≤ 1", "Each stranded group takes one bus.", "15–16"),
    ("B5 · Waiting time", "varWait(g) ≥ varBusDep(r) − pReady(r) − M · (1 − varAssign(g,r))",
     "Minutes a group waits at the bus stop (only counts for the bus it takes).", "36"),
    ("B6 · One bus per stop", "Sum over j of varBusRoute(f,i,c,j) ≤ 1 and Sum over i of varBusRoute(f,i,c,j) ≤ 1",
     "At most one bridging bus from each origin stop and to each destination stop.", "38–42"),
    ("B7 · Fleet size", "Sum over r of varBusRoute(r) ≤ pFleetSize", "No more buses than available.", "10"),
    ("Objective", "Minimise Sum over g of pPax(g) · varWait(g) + pStrandPenalty · Sum over g of pPax(g) · "
                  "(1 − Sum over r of varAssign(g,r))",
     "Strand as few people as possible first, then keep waits short.", "33"),
]


def formulation_table(rows):
    st.dataframe(pd.DataFrame(rows, columns=["Rule", "Formula", "In plain words", "Paper eq."]),
                 hide_index=True, column_config={"Formula": st.column_config.TextColumn(width="large"),
                                                 "In plain words": st.column_config.TextColumn(width="large")})


def page_model():
    toast_once()
    sc, key = current_scenario()
    opt = solve(key, True)
    ui.page_header("Model", "How the plan is computed: the paper's Algorithm 1 and both MILPs, one rule per row. "
                            "p = input parameter, var = decision variable.",
                   eyebrow="Method", eyebrow_icon="functions", right=header_chips(sc))
    if not need_ok(opt):
        return
    tt, bus = opt["timetable"], opt["bus"]
    c1, c2 = st.columns([1, 1.3], gap="medium")
    with c1, ui.card():
        ui.section("Algorithm 1 · two steps", "Solving the trains first and then the buses gives the same answer as "
                                              "solving both together (paper Proposition 1), much faster.",
                   "account_tree")
        st.graphviz_chart(FLOW)
        st.caption(f"This run: MILP-1 has {tt['n_vars']} variables, MILP-2 has {bus['n_vars']}. "
                   f"Solved in {tt['seconds'] + bus['seconds']:.2f} s with SCIP (Google OR-Tools).")
    with c2, ui.card():
        ui.section("Notation", ic="dictionary")
        st.markdown("""
| Name | Meaning |
|---|---|
| **t, f, c** | a last train; f = arriving (feeder), c = connecting |
| **k, i, j** | stations; k = transfer station, i = bus origin stop, j = bus destination stop |
| **d = (f, c, k)** | a transfer: from train f to train c at station k |
| **g** | a passenger group (origin, feeder, transfer station, destination, connecting train) |
| **r** | a possible bus route (replacement or direct) |
| **varLastDep(t)** | departure time of last train t (minutes) |
| **varConnect(d)** | 1 if transfer d works, else 0 |
| **varBusRoute(r), varBusDep(r)** | 1 if bus route r runs; its departure time |
| **varAssign(g,r), varWait(g)** | 1 if group g rides bus r; minutes g waits |
""")
    with ui.card():
        ui.section("Formulation", "Each rule with its formula, a plain-English meaning and the paper's equation "
                                  "number.", "functions")
        t1, t2 = st.tabs(["MILP-1 · trains", "MILP-2 · buses"])
        with t1:
            formulation_table(MILP1)
        with t2:
            formulation_table(MILP2)


def page_tests():
    toast_once()
    ui.page_header("Tests", "Small cases can be checked by hand, one rule at a time. Medium cases check properties. "
                            "A large case checks speed. The same cases run here and in <code>pytest</code>.",
                   eyebrow="Quality", eyebrow_icon="verified")
    df = run_tests()
    n_pass = int((df["Result"] == "PASS").sum())
    n_fail = int((df["Result"] == "FAIL").sum())
    n_open = len(df) - n_pass - n_fail
    ui.kpi_cards([
        dict(label="Passed", value=n_pass, unit=f"/ {len(df)}", icon="check_circle", tone="green"),
        dict(label="Failed", value=n_fail, icon="cancel", tone="red"),
        dict(label="Open issues", value=n_open, icon="help", tone="amber"),
    ])
    with ui.card():
        ui.section("Test cases", "Expected results were written before the run; Actual comes live from the model.",
                   "checklist")
        view = df.copy()
        view["Result"] = view["Result"].map({"PASS": "✅ Pass", "FAIL": "❌ Fail"}).fillna("🟡 Open issue")
        st.dataframe(view, hide_index=True, height=36 * (len(view) + 1) + 2,
                     column_order=["ID", "Result", "Size", "Requirement", "Description", "Expected", "Actual"],
                     column_config={"Description": st.column_config.TextColumn(width="medium"),
                                    "Expected": st.column_config.TextColumn(width="medium"),
                                    "Actual": st.column_config.TextColumn(width="medium")})
        ui.note("<b>Open issue TC12.</b> Read literally, the paper's eq. 26 reproduces its own 20-sample example "
                "(31 s). On the 100-sample set it gives 42.1 s instead of the published 37.7 s.")
    sc, key = current_scenario()
    cur, opt = results(key)
    if opt["status"] == "OK":
        kc, ko, kb = three_kpis(sc, cur, opt)
        with ui.card():
            ui.section("Sanity check against the paper", "Same pattern as the paper's Vienna case: re-timing helps, "
                                                         "and buses close most of the gap.", "compare_arrows")
            st.dataframe(pd.DataFrame({
                "Setting": ["Original timetable", "Optimised timetable", "Optimised + buses"],
                "Vienna (paper)": [44.1, 54.6, 88.5],
                sc.name: [kc["Transfer rate - train only (%)"], ko["Transfer rate - train only (%)"],
                          kb["Transfer rate - train + bus (%)"]],
            }), hide_index=True, column_config={
                c: st.column_config.ProgressColumn(c, format="%.0f%%", min_value=0, max_value=100)
                for c in ["Vienna (paper)", sc.name]})


PAGES = {
    "home": st.Page(page_home, title="Overview", icon=":material/home:", default=True),
    "inputs": st.Page(page_inputs, title="Inputs", icon=":material/edit:", url_path="inputs"),
    "results": st.Page(page_results, title="Results", icon=":material/insights:", url_path="results"),
    "model": st.Page(page_model, title="Model", icon=":material/functions:", url_path="model"),
    "tests": st.Page(page_tests, title="Tests", icon=":material/verified:", url_path="tests"),
}
pg = st.navigation(list(PAGES.values()))
pg.run()
