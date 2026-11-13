"""Plotly figures for the decision-support prototype, all sharing one 'saas' template."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from model import Scenario, fmt_time, times_for

OK, MISS, BUS = "#10B981", "#EF4444", "#F59E0B"
INK, MUTED, GRID = "#0F172A", "#64748B", "#EEF1F6"
FONT = "Inter, -apple-system, Segoe UI, sans-serif"

pio.templates["saas"] = go.layout.Template(layout=dict(
    font=dict(family=FONT, size=12, color="#334155"),
    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
    colorway=["#4F46E5", "#10B981", "#F59E0B", "#EF4444", "#3B82F6", "#8B5CF6"],
    xaxis=dict(gridcolor=GRID, zeroline=False, linecolor="#E2E8F0", automargin=True, ticks="",
               tickfont=dict(color=MUTED), title=dict(font=dict(color=MUTED), standoff=10)),
    yaxis=dict(gridcolor=GRID, zeroline=False, linecolor="#E2E8F0", automargin=True, ticks="",
               tickfont=dict(color=MUTED), title=dict(font=dict(color=MUTED), standoff=10)),
    hoverlabel=dict(bgcolor="white", bordercolor="#E2E8F0", font=dict(family=FONT, size=12, color=INK)),
    legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=12, color="#475569"),
                bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=10, r=10, t=36, b=10), bargap=0.25,
))
pio.templates.default = "saas"


def _time_axis(fig, lo, hi, axis="xaxis", step=5):
    lo, hi = int(lo // step * step), int(hi // step * step + step)
    ticks = list(range(lo, hi + 1, step))
    fig.update_layout(**{axis: dict(tickvals=ticks, ticktext=[fmt_time(t) for t in ticks], title=None)})


def network_map(sc: Scenario, buses: list | None = None, height: int = 520) -> go.Figure:
    fig = go.Figure()
    seen = set()
    for tr in sc.trains.values():
        if tr.line in seen:
            continue
        seen.add(tr.line)
        col = sc.line_colors[tr.line]
        xs = [sc.stations[s]["x"] for s in tr.stations]
        ys = [sc.stations[s]["y"] for s in tr.stations]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=col, width=12), opacity=0.16,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=f"{tr.line} line",
                                 line=dict(color=col, width=5),
                                 marker=dict(size=9, color="white", line=dict(color=col, width=2.5)),
                                 text=tr.stations, hovertemplate="%{text}<extra></extra>"))
    tx = [s for s, d in sc.stations.items() if d.get("walk_transfer") is not None]
    fig.add_trace(go.Scatter(
        x=[sc.stations[s]["x"] for s in tx], y=[sc.stations[s]["y"] for s in tx], mode="markers+text",
        name="Transfer station", text=[f"<b>{s}</b>" for s in tx], textposition="top left",
        textfont=dict(size=12.5, color=INK),
        marker=dict(size=19, color="white", line=dict(color=INK, width=3)),
        hovertext=[f"<b>{s}</b><br>walk between platforms: {sc.stations[s]['walk_transfer']} min" for s in tx],
        hoverinfo="text"))
    pos = {}
    for tr in sc.trains.values():
        for a, b in zip(tr.stations, tr.stations[1:]):
            dx = abs(sc.stations[a]["x"] - sc.stations[b]["x"])
            dy = abs(sc.stations[a]["y"] - sc.stations[b]["y"])
            for s in (a, b):
                pos.setdefault(s, "bottom center" if dx >= dy else "middle right")
    others = [s for s in sc.stations if s not in tx]
    fig.add_trace(go.Scatter(x=[sc.stations[s]["x"] for s in others], y=[sc.stations[s]["y"] for s in others],
                             mode="text",
                             text=[f"<br>{s}" if pos.get(s) == "bottom center" else f"   {s}" for s in others],
                             textposition=[pos.get(s, "bottom center") for s in others],
                             textfont=dict(size=10.5, color=MUTED), showlegend=False, hoverinfo="skip"))
    for b in buses or []:
        a, z = sc.stations[b["from_stop"]], sc.stations[b["to_stop"]]
        hover = (f"<b>{b['name']}</b> · {b['kind']}<br>{b['from_stop']} → {b['to_stop']}<br>"
                 f"departs {fmt_time(b['dep'], True)} · {b['pax']:.0f} passengers")
        fig.add_trace(go.Scatter(x=[a["x"], z["x"]], y=[a["y"], z["y"]], mode="lines",
                                 line=dict(color=BUS, width=2.5, dash="dot"), showlegend=False,
                                 hovertext=hover, hoverinfo="text"))
        fig.add_annotation(x=z["x"], y=z["y"], ax=a["x"], ay=a["y"], xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=1.3, arrowcolor=BUS, arrowwidth=2, text="",
                           standoff=7)
        fig.add_annotation(x=a["x"] + 0.38 * (z["x"] - a["x"]), y=a["y"] + 0.38 * (z["y"] - a["y"]),
                           text=f"<b>{b['name'].replace('Bus ', 'B')}</b>  {fmt_time(b['dep'])}",
                           showarrow=False, bgcolor="#FFFBEB", bordercolor="#FCD34D", borderwidth=1, borderpad=3,
                           font=dict(size=10.5, color="#92400E"), hovertext=hover)
    if buses:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name="Bridging bus",
                                 line=dict(color=BUS, width=2.5, dash="dot")))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(orientation="h", y=-0.02, x=0.5, xanchor="center"),
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    return fig


def transfer_explainer(arrive: float, walk: float, leave: float) -> go.Figure:
    """One passenger, one transfer: arrive, walk, and does the connecting train wait?"""
    ready = arrive + walk
    ok = ready <= leave
    col = OK if ok else MISS
    fig = go.Figure()
    fig.add_shape(type="rect", x0=arrive, x1=ready, y0=0.35, y1=0.65, fillcolor="#E0E7FF", line_width=0, layer="below")
    fig.add_annotation(x=(arrive + ready) / 2, y=0.5, text=f"walk {walk:g} min", showarrow=False,
                       font=dict(color="#4338CA", size=12))
    fig.add_shape(type="rect", x0=min(ready, leave), x1=max(ready, leave), y0=0.38, y1=0.62,
                  fillcolor="#ECFDF5" if ok else "#FEF2F2", line_width=0, layer="below")
    for x, label, c, sym in [(arrive, "Your train<br>arrives", "#3B82F6", "circle"),
                             (ready, "You reach<br>the platform", INK, "diamond"),
                             (leave, "Connecting last<br>train leaves", "#EF4444" if not ok else "#10B981", "square")]:
        fig.add_trace(go.Scatter(x=[x], y=[0.5], mode="markers", marker=dict(size=16, color=c, symbol=sym,
                                 line=dict(color="white", width=2)), hoverinfo="skip", showlegend=False))
        fig.add_annotation(x=x, y=0.5, text=f"{label}<br><b>{fmt_time(x, True)}</b>", showarrow=False, yshift=46,
                           font=dict(size=11, color=MUTED))
    slack = leave - ready
    fig.add_annotation(x=(ready + leave) / 2, y=0.5, yshift=-30, showarrow=False,
                       text=f"<b>slack {slack:+.1f} min</b>", font=dict(color=col, size=13))
    lo, hi = min(arrive, leave) - 2, max(ready, leave) + 2
    _time_axis(fig, lo, hi, step=1 if hi - lo < 14 else 2)
    fig.update_layout(height=220, yaxis=dict(visible=False, range=[0, 1.25]), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(showgrid=False, range=[lo, hi]))
    return fig


def station_board(sc: Scenario, deps: dict, station: str, title: str) -> go.Figure:
    """Time view of one transfer station: when each last train is there, and whether each walk makes it."""
    arr, dep = times_for(sc, deps)
    walk = sc.stations[station]["walk_transfer"]
    trains = [t for t in sc.trains.values() if station in t.stations]
    ys = [t.id for t in trains]
    fig = go.Figure()
    for t in trains:
        a = arr.get((t.id, station))
        d = dep.get((t.id, station))
        color = sc.line_colors[t.line]
        if t.stations[0] == station:
            a = d
        if a is not None and d is not None:
            fig.add_trace(go.Scatter(x=[a, d], y=[t.id, t.id], mode="lines+markers", showlegend=False,
                                     line=dict(color=color, width=12), marker=dict(size=12, color=color),
                                     hovertext=f"<b>{t.id}</b><br>arrives {fmt_time(a, True)}<br>departs {fmt_time(d, True)}",
                                     hoverinfo="text"))
            fig.add_annotation(x=d, y=t.id, text=f"leaves {fmt_time(d, True)}", showarrow=False, xanchor="left",
                               xshift=10, yshift=12, font=dict(size=10.5, color=color))
        elif a is not None:
            fig.add_trace(go.Scatter(x=[a], y=[t.id], mode="markers", showlegend=False,
                                     marker=dict(size=13, color=color, symbol="square"),
                                     hovertext=f"<b>{t.id}</b><br>terminates {fmt_time(a, True)}", hoverinfo="text"))
    pax = sc.direction_pax()
    for (f, c, k), p in pax.items():
        if k != station:
            continue
        ready = arr[f, k] + walk
        ok = ready <= dep[c, k] + 1e-6
        col = OK if ok else MISS
        fig.add_trace(go.Scatter(
            x=[arr[f, k], ready], y=[f, c], mode="lines+markers", showlegend=False,
            line=dict(color=col, width=1.2 + p / 18, dash="dot"),
            marker=dict(size=[0, 12], symbol=["circle", "circle" if ok else "x-thin-open"], color=col,
                        line=dict(color=col, width=3)),
            hovertext=f"<b>{f} → {c}</b> · {p:.0f} pax<br>ready {fmt_time(ready, True)} · train leaves "
                      f"{fmt_time(dep[c, k], True)}<br><b>{'Connected' if ok else 'Missed'}</b>",
            hoverinfo="text"))
    xs = [v for (tid, st), v in list(arr.items()) + list(dep.items()) if st == station]
    _time_axis(fig, min(xs) - 2, max(xs) + walk + 2, step=4)
    fig.update_layout(title=dict(text=title, font=dict(size=13, color=INK), x=0, y=0.98),
                      height=120 + 64 * len(ys), margin=dict(l=8, r=8, t=36, b=8),
                      yaxis=dict(categoryorder="array", categoryarray=ys[::-1], gridcolor="#F1F5F9"))
    return fig


def timetable_gantt(sc: Scenario, current: dict, optimised: dict) -> go.Figure:
    arr_c, _ = times_for(sc, current)
    arr_o, _ = times_for(sc, optimised)
    fig = go.Figure()
    ys = list(sc.trains)
    lo, hi = 1e9, -1e9
    for t in sc.trains.values():
        end_c, end_o = arr_c[t.id, t.stations[-1]], arr_o[t.id, t.stations[-1]]
        lo, hi = min(lo, current[t.id], optimised[t.id]), max(hi, end_c, end_o)
        fig.add_trace(go.Bar(y=[t.id], x=[end_c - current[t.id]], base=[current[t.id]], orientation="h",
                             marker=dict(color="rgba(148,163,184,0.10)", line=dict(color="#94A3B8", width=1.5)),
                             width=0.78, name="Current", showlegend=t.id == ys[0],
                             hovertext=f"<b>{t.id}</b> current<br>{fmt_time(current[t.id])} → {fmt_time(end_c, True)}",
                             hoverinfo="text"))
        fig.add_trace(go.Bar(y=[t.id], x=[end_o - optimised[t.id]], base=[optimised[t.id]], orientation="h",
                             marker=dict(color=sc.line_colors[t.line], line=dict(width=0)), opacity=0.9, width=0.42,
                             name="Optimised", showlegend=t.id == ys[0],
                             hovertext=f"<b>{t.id}</b> optimised<br>{fmt_time(optimised[t.id])} → {fmt_time(end_o, True)}",
                             hoverinfo="text"))
        for st in t.stations:
            if sc.stations[st].get("walk_transfer") is not None:
                fig.add_trace(go.Scatter(x=[arr_o[t.id, st]], y=[t.id], mode="markers+text", text=[st],
                                         textposition="top center", textfont=dict(size=10.5, color=INK),
                                         marker=dict(symbol="diamond", size=9, color="white", line=dict(color=INK, width=2)),
                                         showlegend=False, hovertext=f"{t.id} at {st}: {fmt_time(arr_o[t.id, st], True)}",
                                         hoverinfo="text"))
    _time_axis(fig, lo - 1, hi + 1)
    fig.update_layout(barmode="overlay", height=90 + 58 * len(ys), margin=dict(l=8, r=8, t=30, b=8),
                      yaxis=dict(categoryorder="array", categoryarray=ys[::-1], showgrid=False))
    return fig


def window_chart(sc: Scenario, optimised: dict | None = None) -> go.Figure:
    """One row per last train: allowed departure window (bar), today's time (○) and the model's pick (◆)."""
    ids = list(sc.trains)[::-1]
    fig = go.Figure()
    for tid in ids:
        t = sc.trains[tid]
        col = sc.line_colors[t.line]
        fig.add_trace(go.Bar(y=[tid], x=[t.latest_dep - t.earliest_dep], base=[t.earliest_dep], orientation="h",
                             marker=dict(color=col, opacity=0.22, line=dict(color=col, width=1.5), cornerradius=6),
                             width=0.55, showlegend=False,
                             hovertemplate=f"{tid}<br>allowed {fmt_time(t.earliest_dep)} – {fmt_time(t.latest_dep)}"
                                           "<extra></extra>"))
    fig.add_trace(go.Scatter(y=ids, x=[sc.trains[i].current_dep for i in ids], mode="markers", name="Today",
                             marker=dict(symbol="circle-open", size=13, color=INK, line=dict(width=2.5)),
                             hovertemplate="%{y}: today %{customdata}<extra></extra>",
                             customdata=[fmt_time(sc.trains[i].current_dep) for i in ids]))
    if optimised:
        fig.add_trace(go.Scatter(y=ids, x=[optimised[i] for i in ids], mode="markers", name="Model's choice",
                                 marker=dict(symbol="diamond", size=12, color="#4F46E5",
                                             line=dict(color="white", width=1.5)),
                                 hovertemplate="%{y}: model picks %{customdata}<extra></extra>",
                                 customdata=[fmt_time(optimised[i]) for i in ids]))
    lo = min(min(t.earliest_dep, t.current_dep) for t in sc.trains.values()) - 3
    hi = max(max(t.latest_dep, t.current_dep) for t in sc.trains.values()) + 3
    _time_axis(fig, lo, hi)
    fig.update_layout(height=70 + 34 * len(ids), barmode="overlay", xaxis=dict(range=[lo, hi]),
                      yaxis=dict(gridcolor="rgba(0,0,0,0)"), margin=dict(l=10, r=10, t=30, b=10))
    return fig
