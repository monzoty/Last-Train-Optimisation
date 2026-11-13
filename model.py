"""Last-train timetabling + bus bridging (Kang et al., Omega 2019) - prototype engine.

Naming follows the TDD convention from class: parameters start with `p`, decision
variables with `var`. Times are minutes after midnight (negative = before midnight).

Pipeline (paper's Algorithm 1, decomposition):
    1. MILP-1  choose last-train departures to maximise successful transfers
    2. MILP-2  for the transfers that still fail, choose bridging buses (no fleet cap)
    3. if step 2 used more than pFleetSize buses, re-solve MILP-2 with the fleet cap
"""
from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

EPS = 1e-6


# --------------------------------------------------------------------------- time
def fmt_time(t: float, seconds: bool = False) -> str:
    total = round(t * 60) if seconds else round(t)
    if seconds:
        total %= 24 * 3600
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_time(s: str) -> float:
    """'00:25' -> 25, '23:50' -> -10 (hours >= 12 are treated as the previous evening)."""
    hh, mm = str(s).strip().split(":")[:2]
    t = int(hh) * 60 + int(mm)
    return t - 1440 if int(hh) >= 12 else t


# ------------------------------------------------------------------ dwell times
def defuzzify(samples_sec: list[float]) -> float:
    """Expected value of a discrete fuzzy dwell time (paper eqs. 23-26).

    Possibility of each observed value = frequency / max frequency (eq. 24).
    Weight w_h = 1/2 (max mu[1..h] - max mu[1..h-1] + max mu[h..m] - max mu[h+1..m]).
    """
    counts = Counter(samples_sec)
    vals = sorted(counts)
    top = max(counts.values())
    mu = [counts[v] / top for v in vals]
    m = len(vals)

    def mx(a: int, b: int) -> float:
        return max(mu[a:b]) if b > a else 0.0

    return sum(0.5 * (mx(0, h + 1) - mx(0, h) + mx(h, m) - mx(h + 1, m)) * vals[h] for h in range(m))


def dwell_estimate(samples_sec: list[float], method: str) -> float:
    s = sorted(samples_sec)
    if method == "mean":
        return sum(s) / len(s)
    if method == "median":
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return defuzzify(s)


# --------------------------------------------------------------------- scenario
@dataclass
class Train:
    id: str
    line: str
    stations: list[str]
    run_times: list[float]          # pRunTime between consecutive stations (min)
    earliest_dep: float             # pEarliestDep (paper T_min)
    latest_dep: float               # pLatestDep   (paper T_max)
    current_dep: float              # today's published last-train departure


@dataclass
class Scenario:
    name: str
    trains: dict[str, Train]
    stations: dict[str, dict]       # x, y, walk_transfer, walk_bus, dwell_samples (sec)
    od: list[dict]                  # origin, from_train, transfer, dest, to_train, pax
    line_colors: dict[str, str]
    params: dict = field(default_factory=dict)

    # derived ---------------------------------------------------------------
    def dwell(self, station: str) -> float:
        method = self.params.get("dwell_method", "defuzzified")
        return dwell_estimate(self.stations[station]["dwell_samples"], method) / 60.0

    def arrival_offsets(self, train: Train, dwell_override: dict | None = None,
                        run_scale: list[float] | None = None) -> dict[str, float]:
        """Minutes from origin departure to arrival at each station (eq. 3, minus t^R)."""
        off, t = {train.stations[0]: 0.0}, 0.0
        for idx in range(1, len(train.stations)):
            prev, st = train.stations[idx - 1], train.stations[idx]
            if idx > 1:  # dwell at intermediate stations only; departure from origin = t^R
                t += dwell_override[prev] if dwell_override else self.dwell(prev)
            t += train.run_times[idx - 1] * (run_scale[idx - 1] if run_scale else 1.0)
            off[st] = t
        return off

    def transfer_directions(self) -> list[tuple[str, str, str]]:
        """All (feeder train, connecting train, station) where a last-train transfer can happen."""
        out = []
        for f in self.trains.values():
            for c in self.trains.values():
                if f.line == c.line:
                    continue
                for k in set(f.stations[1:]) & set(c.stations[:-1]):
                    if self.stations[k].get("walk_transfer") is not None:
                        out.append((f.id, c.id, k))
        return sorted(out)

    def direction_pax(self) -> dict[tuple[str, str, str], float]:
        pax = {d: 0.0 for d in self.transfer_directions()}
        for g in self.od:
            key = (g["from_train"], g["to_train"], g["transfer"])
            if key in pax:
                pax[key] += g["pax"]
        return pax


# --------------------------------------------------------------- evaluation
def times_for(sc: Scenario, deps: dict[str, float], dwell_override=None, run_scales=None):
    """Arrival / departure time of every last train at every station."""
    arr, dep = {}, {}
    for tid, tr in sc.trains.items():
        off = sc.arrival_offsets(tr, dwell_override, run_scales.get(tid) if run_scales else None)
        for i, st in enumerate(tr.stations):
            arr[tid, st] = deps[tid] + off[st]
            if i == 0:
                dep[tid, st] = deps[tid]
            elif i < len(tr.stations) - 1:
                dw = dwell_override[st] if dwell_override else sc.dwell(st)
                dep[tid, st] = arr[tid, st] + dw
    return arr, dep


def transfer_slack(sc, deps, dwell_override=None, run_scales=None):
    """Last-train transfer redundant time (eq. 7): Dep(c,k) - Arr(f,k) - walk(k)."""
    arr, dep = times_for(sc, deps, dwell_override, run_scales)
    return {
        (f, c, k): dep[c, k] - arr[f, k] - sc.stations[k]["walk_transfer"]
        for (f, c, k) in sc.transfer_directions()
    }, arr, dep


# ----------------------------------------------------------------- MILP-1
def solve_timetable(sc: Scenario, fixed: dict[str, float] | None = None) -> dict:
    """MILP-1: choose departure times to maximise connected passengers (+ gamma x connections)."""
    gamma = sc.params.get("gamma", 12)
    solver = pywraplp.Solver.CreateSolver("SCIP")
    t0 = time.perf_counter()

    varLastDep = {}
    for tid, tr in sc.trains.items():
        lo, hi = (fixed[tid], fixed[tid]) if fixed else (tr.earliest_dep, tr.latest_dep)
        if lo > hi + EPS:
            return {"status": "INFEASIBLE",
                    "message": f"Departure window of {tid} is empty ({fmt_time(lo)} > {fmt_time(hi)})."}
        varLastDep[tid] = solver.IntVar(lo, hi, f"varLastDep[{tid}]")

    offs = {tid: sc.arrival_offsets(tr) for tid, tr in sc.trains.items()}
    pax = sc.direction_pax()
    varConnect, bigM = {}, {}
    for (f, c, k), p in pax.items():
        # slack = varLastDep[c] - varLastDep[f] + const   (const holds offsets, dwell, walking)
        const = offs[c][k] + sc.dwell(k) - offs[f][k] - sc.stations[k]["walk_transfer"]
        tf, tc = sc.trains[f], sc.trains[c]
        lo = (fixed[c] - fixed[f] if fixed else tc.earliest_dep - tf.latest_dep) + const
        hi = (fixed[c] - fixed[f] if fixed else tc.latest_dep - tf.earliest_dep) + const
        x = solver.BoolVar(f"varConnect[{f}>{c}@{k}]")
        slack = varLastDep[c] - varLastDep[f] + const
        # Linearised eq. 8 -> eq. 9, with the smallest valid big-M for each direction
        if lo < 0:
            solver.Add(slack >= lo * (1 - x))       # x = 1 only if slack >= 0
        if hi > 0:
            solver.Add(slack <= hi * x)             # slack > 0 forces x = 1
        elif hi < -EPS:
            solver.Add(x == 0)                      # can never connect inside the windows
        varConnect[f, c, k] = x
        bigM[f, c, k] = max(-lo, 0)

    # tiny tie-breaker: among equally good timetables prefer the smallest change (|dep - current|)
    shift = {}
    for tid, tr in sc.trains.items():
        s = solver.NumVar(0, solver.infinity(), f"varShift[{tid}]")
        solver.Add(s >= varLastDep[tid] - tr.current_dep)
        solver.Add(s >= tr.current_dep - varLastDep[tid])
        shift[tid] = s

    solver.Maximize(
        sum(p * varConnect[d] for d, p in pax.items())
        + gamma * sum(varConnect.values())
        - 0.001 * sum(shift.values())
    )
    status = solver.Solve()
    elapsed = time.perf_counter() - t0
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": "INFEASIBLE", "message": "MILP-1 has no feasible timetable."}
    deps = {tid: round(v.solution_value()) for tid, v in varLastDep.items()}
    return {
        "status": "OPTIMAL" if status == pywraplp.Solver.OPTIMAL else "FEASIBLE",
        "deps": deps,
        "connect": {d: int(round(v.solution_value())) for d, v in varConnect.items()},
        "objective": solver.Objective().Value(),
        "n_vars": solver.NumVariables(),
        "n_cons": solver.NumConstraints(),
        "seconds": elapsed,
        "bigM": bigM,
    }


# ----------------------------------------------------------------- MILP-2
def bus_candidates(sc: Scenario, deps: dict[str, float], connected: dict) -> tuple[list, list]:
    """Missed OD groups and candidate bridging routes (i on feeder line -> j on connecting line).

    Two kinds of candidate per missed group (paper Fig. 1 / Fig. 7):
      * replacement bus: from the transfer station k to the destination (intuitive)
      * direct bus:      from the passenger's origin straight to the destination (non-intuitive)
    """
    arr, _ = times_for(sc, deps)
    groups = [dict(g, gid=n) for n, g in enumerate(sc.od)
              if g["pax"] > 0 and not connected.get((g["from_train"], g["to_train"], g["transfer"]), 0)]
    routes = {}
    for g in groups:
        for i in dict.fromkeys([g["transfer"], g["origin"]]):
            key = (g["from_train"], i, g["to_train"], g["dest"])
            if key not in routes:
                xi, yi = sc.stations[i]["x"], sc.stations[i]["y"]
                xj, yj = sc.stations[g["dest"]]["x"], sc.stations[g["dest"]]["y"]
                dist = ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5
                routes[key] = {
                    "key": key, "from_train": key[0], "from_stop": i, "to_train": key[2], "to_stop": key[3],
                    "kind": "replacement" if i == g["transfer"] else "direct",
                    "ready": arr[key[0], i] + sc.stations[i]["walk_bus"],
                    "ride_min": dist * sc.params.get("bus_min_per_km", 2.0),
                    "serves": [],
                }
            routes[key]["serves"].append(g["gid"])
    return groups, list(routes.values())


def solve_bus(sc: Scenario, deps: dict, connected: dict, fleet: int | None) -> dict:
    """MILP-2: pick bridging routes and bus departure times to minimise rail-to-bus waiting."""
    P = sc.params
    buffer, earliest, latest = P.get("bus_buffer", 2), P.get("bus_earliest", 0), P.get("bus_latest", 90)
    penalty = P.get("strand_penalty", 1000)
    groups, routes = bus_candidates(sc, deps, connected)
    t0 = time.perf_counter()
    if not groups:
        return {"status": "OPTIMAL", "buses": [], "groups": [], "served": {}, "wait": {},
                "n_vars": 0, "n_cons": 0, "seconds": 0.0, "objective": 0.0}

    solver = pywraplp.Solver.CreateSolver("SCIP")
    varBusRoute = {n: solver.BoolVar(f"varBusRoute[{n}]") for n in range(len(routes))}
    varBusDep = {n: solver.NumVar(earliest, latest, f"varBusDep[{n}]") for n in range(len(routes))}
    varAssign, varWait = {}, {g["gid"]: solver.NumVar(0, solver.infinity(), f"varWait[{g['gid']}]") for g in groups}
    waitM = latest - min(r["ready"] for r in routes)

    for n, r in enumerate(routes):
        # bus leaves only after passengers can reach the stop, plus a safety buffer (eqs. 36-37)
        solver.Add(varBusDep[n] >= (r["ready"] + buffer) * varBusRoute[n])
        for gid in r["serves"]:
            a = solver.BoolVar(f"varAssign[{gid},{n}]")
            solver.Add(a <= varBusRoute[n])
            solver.Add(varWait[gid] >= varBusDep[n] - r["ready"] - waitM * (1 - a))
            varAssign[gid, n] = a
    for g in groups:  # each passenger group rides at most one bus
        solver.Add(sum(a for (gid, _), a in varAssign.items() if gid == g["gid"]) <= 1)

    # eq. 15 / 38: one bus per origin stop, eq. 16 / 38: one bus per destination stop (per line pair)
    by_origin, by_dest = {}, {}
    for n, r in enumerate(routes):
        by_origin.setdefault((r["from_train"], r["to_train"], r["from_stop"]), []).append(n)
        by_dest.setdefault((r["from_train"], r["to_train"], r["to_stop"]), []).append(n)
    for ns in list(by_origin.values()) + list(by_dest.values()):
        if len(ns) > 1:
            solver.Add(sum(varBusRoute[n] for n in ns) <= 1)

    if fleet is not None:  # eq. 10: bus fleet size
        solver.Add(sum(varBusRoute.values()) <= fleet)

    pax = {g["gid"]: g["pax"] for g in groups}
    served_expr = {g["gid"]: sum(a for (gid, _), a in varAssign.items() if gid == g["gid"]) for g in groups}
    solver.Minimize(
        sum(pax[gid] * varWait[gid] for gid in pax)
        + penalty * sum(pax[gid] * (1 - served_expr[gid]) for gid in pax)
        + 0.01 * sum(varBusRoute.values())
    )
    status = solver.Solve()
    elapsed = time.perf_counter() - t0
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": "INFEASIBLE", "message": "MILP-2 has no feasible solution."}

    buses, served, wait = [], {}, {}
    for n, r in enumerate(routes):
        if varBusRoute[n].solution_value() > 0.5:
            d = varBusDep[n].solution_value()
            riders = [gid for gid in r["serves"] if varAssign[gid, n].solution_value() > 0.5]
            for gid in riders:
                served[gid] = n
                wait[gid] = d - r["ready"]
            buses.append(dict(r, dep=d, arr=d + r["ride_min"], riders=riders,
                              pax=sum(pax[g] for g in riders)))
    buses.sort(key=lambda b: b["dep"])
    for i, b in enumerate(buses, 1):
        b["name"] = f"Bus {i}"
    return {"status": "OPTIMAL" if status == pywraplp.Solver.OPTIMAL else "FEASIBLE",
            "buses": buses, "groups": groups, "served": served, "wait": wait,
            "n_vars": solver.NumVariables(), "n_cons": solver.NumConstraints(),
            "seconds": elapsed, "objective": solver.Objective().Value()}


# ----------------------------------------------------------- Algorithm 1
def run_algorithm1(sc: Scenario, optimise_timetable: bool = True) -> dict:
    fleet = sc.params.get("fleet", 5)
    log = []
    fixed = {tid: tr.current_dep for tid, tr in sc.trains.items()} if not optimise_timetable else None
    tt = solve_timetable(sc, fixed)
    if tt["status"] == "INFEASIBLE":
        return {"status": "INFEASIBLE", "message": tt["message"], "log": log}
    n_dir = len(tt["connect"])
    log.append(f"Step 1 - MILP-1 timetable: {tt['n_vars']} variables, {tt['n_cons']} constraints, "
               f"{tt['status'].lower()} in {tt['seconds']:.2f}s; "
               f"{sum(tt['connect'].values())}/{n_dir} transfer directions connected.")
    missed = [d for d, x in tt["connect"].items() if not x]
    log.append(f"Step 2 - extracted {len(missed)} missed directions; solving MILP-2 without fleet cap.")
    bus = solve_bus(sc, tt["deps"], tt["connect"], fleet=None)
    log.append(f"         MILP-2 uses {len(bus['buses'])} buses (fleet cap N = {fleet}).")
    if len(bus["buses"]) > fleet:
        log.append(f"Step 3 - {len(bus['buses'])} > N: re-solving MILP-2 with constraint (10).")
        bus = solve_bus(sc, tt["deps"], tt["connect"], fleet=fleet)
        log.append(f"         MILP-2 with cap uses {len(bus['buses'])} buses, "
                   f"{bus['n_vars']} variables, solved in {bus['seconds']:.2f}s.")
    else:
        log.append("Step 3 - fleet cap already satisfied: stop (one pass of Algorithm 1).")
    return {"status": "OK", "timetable": tt, "bus": bus, "log": log}


# ----------------------------------------------------------------- KPIs
def kpis(sc: Scenario, deps: dict, bus: dict | None) -> dict:
    slack, _, _ = transfer_slack(sc, deps)
    total = sum(g["pax"] for g in sc.od)
    by_train = 0.0
    for g in sc.od:
        if slack.get((g["from_train"], g["to_train"], g["transfer"]), -1) >= -EPS:
            by_train += g["pax"]
    by_bus = 0.0
    waits = []
    if bus:
        pax = {g["gid"]: g["pax"] for g in bus["groups"]}
        for gid in bus["served"]:
            by_bus += pax[gid]
            waits.append((bus["wait"][gid], pax[gid]))
    wsum = sum(p for _, p in waits)
    dirs_with_demand = [d for d, p in sc.direction_pax().items() if p > 0]
    return {
        "Transfer directions connected": sum(1 for d in slack if slack[d] >= -EPS),
        "Transfer directions (total)": len(slack),
        "Transfer passengers (total)": total,
        "Connected by last train": by_train,
        "Carried by bridging bus": by_bus,
        "Stranded": total - by_train - by_bus,
        "Transfer rate - train only (%)": 100 * by_train / total if total else 0,
        "Transfer rate - train + bus (%)": 100 * (by_train + by_bus) / total if total else 0,
        "Buses deployed": len(bus["buses"]) if bus else 0,
        "Avg bus wait (min)": sum(w * p for w, p in waits) / wsum if wsum else 0,
        "Directions with demand": len(dirs_with_demand),
    }


# ------------------------------------------------------------ simulation
def monte_carlo(sc: Scenario, deps: dict, runs: int, seed: int, run_noise: float) -> dict:
    """Stress-test a timetable: replay the night with random dwell and running times.

    Dwell times are drawn from each station's observed samples (empirical distribution);
    running times get a normal +/- run_noise share. Same seed = same nights (common random numbers).
    """
    rng = random.Random(seed)
    dirs = sc.transfer_directions()
    ok = Counter()
    pax = sc.direction_pax()
    served = []
    for _ in range(runs):
        dwell = {st: rng.choice(d["dwell_samples"]) / 60.0 for st, d in sc.stations.items()}
        scales = {tid: [max(0.5, rng.gauss(1.0, run_noise)) for _ in tr.run_times]
                  for tid, tr in sc.trains.items()}
        slack, _, _ = transfer_slack(sc, deps, dwell, scales)
        night = 0.0
        for d in dirs:
            if slack[d] >= -EPS:
                ok[d] += 1
                night += pax[d]
        served.append(night)
    served.sort()
    return {"prob": {d: ok[d] / runs for d in dirs}, "served": served,
            "p05": served[int(0.05 * (runs - 1))], "mean": sum(served) / runs}
