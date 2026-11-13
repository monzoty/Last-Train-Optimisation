"""Test plan for the model. Each case returns expected vs actual so it can be shown in the app and run by pytest."""
from __future__ import annotations

import itertools
import statistics
import time

from model import (defuzzify, kpis, monte_carlo, run_algorithm1, solve_bus, solve_timetable,
                   transfer_slack)
from scenarios import grid_city, metro_city, two_line_crossing

PAPER_100_DWELLS = (
    [30] + [31] * 8 + [32] * 8 + [33] * 3 + [34] * 10 + [35] * 5 + [36] * 4 + [37] * 7 + [38] * 4
    + [39] * 7 + [40] * 8 + [41] * 9 + [42] * 7 + [43] * 4 + [44] * 13 + [90, 120]
)


def _case(cid, size, req, desc, data, expected, actual, passed, purpose):
    return dict(ID=cid, Size=size, Requirement=req, Description=desc, Input=data,
                Expected=expected, Actual=actual, Result="PASS" if passed is True else
                ("FAIL" if passed is False else passed), Purpose=purpose)


def _objective(sc, deps):
    slack, _, _ = transfer_slack(sc, deps)
    pax = sc.direction_pax()
    con = [d for d in slack if slack[d] >= -1e-6]
    return sum(pax[d] for d in con) + sc.params["gamma"] * len(con)


def tc01():
    sc = two_line_crossing()
    tt = solve_timetable(sc)
    n = sum(tt["connect"].values())
    return _case("TC01", "Small", "R2.1 transfer rule", "Two lines crossing at one station (paper App. B)",
                 "4 trains, 8 directions, walk 3 min > dwell 0.5 min", "at most 4 of 8 connect; optimum = 4",
                 f"{n} of 8 connect", n == 4, "Model respects the physical limit of a crossing")


def tc02():
    sc = two_line_crossing()
    for t in sc.trains.values():
        t.earliest_dep, t.latest_dep = 0, 12
    tt = solve_timetable(sc)
    ids = list(sc.trains)
    best = max(_objective(sc, dict(zip(ids, combo))) for combo in itertools.product(range(13), repeat=4))
    got = _objective(sc, tt["deps"])
    return _case("TC02", "Small", "Objective (32)", "MILP-1 vs brute-force enumeration",
                 "toy network, departures 00:00-00:12 (13^4 = 28,561 timetables)",
                 f"objective = {best:.0f}", f"objective = {got:.0f}", abs(best - got) < 1e-6,
                 "Solver does not exclude the best timetable")


def tc03():
    sc = two_line_crossing()
    sc.stations["X"]["walk_transfer"] = 2.5
    deps = {"A-East": 10, "A-West": 30, "B-South": 12, "B-North": 30}
    slack, _, _ = transfer_slack(sc, deps)
    s = slack["A-East", "B-South", "X"]
    tt = solve_timetable(sc, fixed=deps)
    x = tt["connect"]["A-East", "B-South", "X"]
    return _case("TC03", "Small", "Constraint (9) boundary", "Transfer slack exactly 0 min",
                 "A-East 00:10, B-South 00:12, walk 2.5 min", "slack = 0 -> connected (x = 1)",
                 f"slack = {s:.2f}, x = {x}", abs(s) < 1e-6 and x == 1, "Boundary of the big-M constraint")


def tc04():
    sc = two_line_crossing()
    deps = {"A-East": 10, "A-West": 30, "B-South": 12, "B-North": 30}
    slack, _, _ = transfer_slack(sc, deps)
    s = slack["A-East", "B-South", "X"]
    x = solve_timetable(sc, fixed=deps)["connect"]["A-East", "B-South", "X"]
    return _case("TC04", "Small", "Constraint (9)", "Passengers reach the platform 30 s after the train left",
                 "A-East 00:10, B-South 00:12, walk 3 min (B-South leaves X at 00:17:00, "
                 "passengers ready 00:14:30 + 3:00)", "slack = -0.5 -> missed (x = 0)",
                 f"slack = {s:.2f}, x = {x}", abs(s + 0.5) < 1e-6 and x == 0,
                 "Big-M must not let a missed transfer count")


def tc05():
    sc = two_line_crossing()
    sc.params["fleet"] = 0
    r = run_algorithm1(sc)
    k = kpis(sc, r["timetable"]["deps"], r["bus"])
    return _case("TC05", "Small", "Constraint (10)", "No buses available (N = 0)", "toy network, N = 0",
                 "0 buses; stranded = missed passengers (80)", f"{k['Buses deployed']} buses; stranded = {k['Stranded']:.0f}",
                 k["Buses deployed"] == 0 and abs(k["Stranded"] - 80) < 1e-6, "Fleet cap is hard")


def tc06():
    sc = two_line_crossing()
    sc.params["fleet"] = 1
    r = run_algorithm1(sc)
    missed = [g["pax"] for g in r["bus"]["groups"]]
    b = r["bus"]["buses"]
    return _case("TC06", "Small", "Constraint (10) binding", "One bus, several stranded groups",
                 f"toy network, N = 1, missed groups {sorted(missed, reverse=True)}",
                 f"1 bus carrying the largest group ({max(missed)} pax)",
                 f"{len(b)} bus carrying {b[0]['pax']:.0f} pax" if b else "no bus",
                 len(b) == 1 and b[0]["pax"] == max(missed), "Scarce buses go where most passengers are")


def tc07():
    sc = two_line_crossing()
    keep = {("A-East", "B-South"), ("B-South", "A-West"), ("A-West", "B-North"), ("A-East", "B-North")}
    sc.od = [g for g in sc.od if (g["from_train"], g["to_train"]) in keep]
    r = run_algorithm1(sc)
    k = kpis(sc, r["timetable"]["deps"], r["bus"])
    return _case("TC07", "Small", "Constraints (11), (14)", "Every transfer with demand can be connected",
                 "toy network, demand only on 4 compatible directions", "0 buses, transfer rate 100%",
                 f"{k['Buses deployed']} buses, rate {k['Transfer rate - train only (%)']:.0f}%",
                 k["Buses deployed"] == 0 and k["Transfer rate - train only (%)"] > 99.9,
                 "Buses only where trains fail")


def tc08():
    sc = two_line_crossing()
    sc.trains["A-East"].earliest_dep, sc.trains["A-East"].latest_dep = 20, 10
    r = run_algorithm1(sc)
    return _case("TC08", "Small", "Constraint (5)", "Earliest departure later than latest departure",
                 "A-East window 00:20-00:10", "reported as infeasible, no crash",
                 r["status"] + (f": {r.get('message', '')}" if r["status"] != "OK" else ""),
                 r["status"] == "INFEASIBLE", "Bad input is caught and explained")


def tc09():
    sc = two_line_crossing()
    sc.params["bus_latest"] = 5
    r = run_algorithm1(sc)
    k = kpis(sc, r["timetable"]["deps"], r["bus"])
    return _case("TC09", "Small", "Constraint (37)", "Bus service ends before passengers arrive",
                 "latest bus 00:05, last trains reach X after 00:10", "0 buses, missed passengers stranded",
                 f"{k['Buses deployed']} buses, stranded = {k['Stranded']:.0f}", k["Buses deployed"] == 0,
                 "Bus time window respected")


def tc10():
    sc = metro_city()
    tt = solve_timetable(sc)
    bus = solve_bus(sc, tt["deps"], tt["connect"], fleet=None)
    o = [(b["from_train"], b["to_train"], b["from_stop"]) for b in bus["buses"]]
    d = [(b["from_train"], b["to_train"], b["to_stop"]) for b in bus["buses"]]
    ok = len(o) == len(set(o)) and len(d) == len(set(d))
    return _case("TC10", "Medium", "Constraints (15), (16)", "At most one bus per origin and per destination stop",
                 "Metro City, unlimited fleet", "no repeated (line pair, stop)",
                 f"{len(bus['buses'])} buses, duplicates: {len(o) - len(set(o)) + len(d) - len(set(d))}", ok,
                 "Passengers are not confused by parallel buses")


def tc11():
    d = [30] * 10 + [32] * 10
    got = defuzzify(d)
    return _case("TC11", "Small", "Dwell estimate (25)", "Symmetric dwell sample (paper 2.2.2)",
                 "10 x 30 s, 10 x 32 s", "mean = median = defuzzified = 31 s",
                 f"mean {statistics.mean(d):.1f}, median {statistics.median(d):.1f}, defuzzified {got:.1f}",
                 abs(got - 31) < 1e-9, "Defuzzification matches the paper on symmetric data")


def tc12():
    d = PAPER_100_DWELLS
    got = defuzzify(d)
    return _case("TC12", "Medium", "Dwell estimate (25)", "Asymmetric 100-sample set from the paper",
                 "100 dwells, 30-120 s", "paper: mean 39.1, median 38.0, defuzzified 37.7 s",
                 f"mean {statistics.mean(d):.1f}, median {statistics.median(d):.1f}, defuzzified {got:.1f}",
                 "OPEN ISSUE", "Mean matches; our reading of eq. 26 gives 42.1 s, not 37.7 s. Ask authors / re-check formula")


def tc13():
    sc = metro_city()
    tt = solve_timetable(sc)
    slack, _, _ = transfer_slack(sc, tt["deps"])
    bad = [d for d, x in tt["connect"].items() if x != int(slack[d] >= -1e-6)]
    return _case("TC13", "Medium", "Constraints (3)-(9)", "Solver's connect flags vs independent recalculation",
                 "Metro City, 24 directions", "0 mismatches", f"{len(bad)} mismatches", not bad,
                 "Model logic equals the business rule")


def tc14():
    sc = metro_city()
    cur = run_algorithm1(sc, optimise_timetable=False)
    opt = run_algorithm1(sc)
    kc = kpis(sc, cur["timetable"]["deps"], None)
    ko = kpis(sc, opt["timetable"]["deps"], None)
    inside = all(sc.trains[t].earliest_dep <= v <= sc.trains[t].latest_dep for t, v in opt["timetable"]["deps"].items())
    return _case("TC14", "Medium", "Constraint (5), objective", "Optimised vs current timetable",
                 "Metro City", "connected passengers >= current; all departures inside windows",
                 f"{ko['Connected by last train']:.0f} vs {kc['Connected by last train']:.0f}; inside windows: {inside}",
                 ko["Connected by last train"] >= kc["Connected by last train"] and inside, "Never worse than today")


def tc15():
    sc = metro_city()
    tt = solve_timetable(sc)
    served = []
    for n in range(0, 9):
        b = solve_bus(sc, tt["deps"], tt["connect"], fleet=n)
        served.append(sum(g["pax"] for g in b["groups"] if g["gid"] in b["served"]))
    mono = all(a <= b + 1e-6 for a, b in zip(served, served[1:]))
    return _case("TC15", "Medium", "Sensitivity (paper 4.3)", "Passengers bridged as fleet grows 0..8",
                 "Metro City", "non-decreasing", " -> ".join(f"{s:.0f}" for s in served), mono,
                 "More buses never hurt")


def tc16():
    sc = two_line_crossing()
    deps = solve_timetable(sc)["deps"]
    mc = monte_carlo(sc, deps, runs=50, seed=1, run_noise=0.0)
    slack, _, _ = transfer_slack(sc, deps)
    ok = all(mc["prob"][d] == (1.0 if slack[d] >= -1e-6 else 0.0) for d in slack)
    return _case("TC16", "Small", "Simulation verify", "No randomness -> simulation = deterministic model",
                 "toy, constant dwell 30 s, run noise 0", "probabilities exactly 0 or 1, matching the model",
                 "match" if ok else "mismatch", ok, "Extreme test of the stress-test simulator")


def tc17():
    sc = grid_city()
    t0 = time.perf_counter()
    r = run_algorithm1(sc)
    secs = time.perf_counter() - t0
    k = kpis(sc, r["timetable"]["deps"], r["bus"])
    return _case("TC17", "Large", "Performance", "Vienna-sized network",
                 f"{len(sc.trains)} trains, {len(sc.stations)} stations, {len(sc.transfer_directions())} directions, N = 15",
                 "solves in < 30 s", f"{secs:.1f} s; rate {k['Transfer rate - train + bus (%)']:.0f}%",
                 secs < 30, "Fast enough for planners to try what-ifs")


ALL = [tc01, tc02, tc03, tc04, tc05, tc06, tc07, tc08, tc09, tc10, tc11, tc12, tc13, tc14, tc15, tc16, tc17]


def run_all():
    return [f() for f in ALL]
