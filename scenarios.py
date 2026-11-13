"""Example networks for the prototype. All data is illustrative (the paper's Vienna OD data is not published)."""
from __future__ import annotations

import random

from model import Scenario, Train

DEFAULT_PARAMS = {
    "fleet": 4,               # pFleetSize (N)
    "gamma": 12,              # pConnectionWeight (paper gamma, eq. 32)
    "bus_buffer": 2,          # pBusBuffer (min)
    "bus_earliest": 0,        # pBusEarliestDep (00:00)
    "bus_latest": 90,         # pBusLatestDep (01:30)
    "strand_penalty": 1000,   # pStrandPenalty (min-equivalent per stranded passenger, the paper's big M)
    "bus_min_per_km": 2.0,    # road travel time for display (30 km/h)
}


def _trains_for_line(line, stations, run_times, fwd_name, rev_name, fwd_cur, rev_cur, window):
    return {
        fwd_name: Train(fwd_name, line, stations, run_times, fwd_cur - window, fwd_cur + window, fwd_cur),
        rev_name: Train(rev_name, line, stations[::-1], run_times[::-1], rev_cur - window, rev_cur + window, rev_cur),
    }


def two_line_crossing(window: int = 15) -> Scenario:
    """Toy case (paper Appendix B): two bidirectional lines crossing at X -> 8 transfer directions."""
    trains = {}
    trains.update(_trains_for_line("A", ["A1", "A2", "X", "A4", "A5"], [2, 2, 2, 2], "A-East", "A-West", 10, 10, window))
    trains.update(_trains_for_line("B", ["B1", "B2", "X", "B4", "B5"], [2, 2, 2, 2], "B-South", "B-North", 10, 10, window))
    coords = {"A1": (0, 4), "A2": (2, 4), "X": (4, 4), "A4": (6, 4), "A5": (8, 4),
              "B1": (4, 8), "B2": (4, 6), "B4": (4, 2), "B5": (4, 0)}
    stations = {s: {"x": x, "y": y, "walk_transfer": 3.0 if s == "X" else None, "walk_bus": 2.0,
                    "dwell_samples": [30] * 10} for s, (x, y) in coords.items()}
    od = [
        dict(origin="A1", from_train="A-East", transfer="X", dest="B5", to_train="B-South", pax=50),
        dict(origin="A1", from_train="A-East", transfer="X", dest="B1", to_train="B-North", pax=20),
        dict(origin="A5", from_train="A-West", transfer="X", dest="B5", to_train="B-South", pax=30),
        dict(origin="A5", from_train="A-West", transfer="X", dest="B1", to_train="B-North", pax=40),
        dict(origin="B1", from_train="B-South", transfer="X", dest="A5", to_train="A-East", pax=10),
        dict(origin="B1", from_train="B-South", transfer="X", dest="A1", to_train="A-West", pax=60),
        dict(origin="B5", from_train="B-North", transfer="X", dest="A5", to_train="A-East", pax=25),
        dict(origin="B5", from_train="B-North", transfer="X", dest="A1", to_train="A-West", pax=15),
    ]
    return Scenario("Two-line crossing (toy)", trains, stations, od,
                    {"A": "#EF4444", "B": "#3B82F6"}, dict(DEFAULT_PARAMS, fleet=2))


def metro_city(window: int = 10) -> Scenario:
    """Medium case: 3 bidirectional lines, 3 transfer stations, 20 stations, 24 transfer directions."""
    rng = random.Random(7)
    lines = {
        "Red": (["Westgate", "Mill Road", "Central", "Market", "Harbor", "Docks", "Eastpoint"],
                [3, 3, 2, 3, 2, 3], "Red-East", "Red-West", 20, 25),
        "Blue": (["Northfield", "Parkside", "Museum", "Central", "Stadium", "University", "Southend"],
                 [3, 2, 2, 3, 3, 3], "Blue-South", "Blue-North", 15, 30),
        "Green": (["Riverside", "University", "Tech Park", "Harbor", "Old Town", "Hillcrest"],
                  [4, 3, 3, 3, 3], "Green-NE", "Green-SW", 22, 18),
    }
    coords = {
        "Westgate": (0, 5), "Mill Road": (2, 5), "Central": (4, 5), "Market": (6, 5), "Harbor": (8, 5),
        "Docks": (10, 5), "Eastpoint": (12, 5),
        "Northfield": (4, 11), "Parkside": (4, 9), "Museum": (4, 7), "Stadium": (4, 3),
        "University": (5, 1), "Southend": (6, -1),
        "Riverside": (1, 0), "Tech Park": (7, 2.5), "Old Town": (9, 7), "Hillcrest": (10, 9),
    }
    walk = {"Central": 3.0, "Harbor": 4.0, "University": 2.5}
    trains = {}
    for line, (sts, runs, fn, rn, fc, rc) in lines.items():
        trains.update(_trains_for_line(line, sts, runs, fn, rn, fc, rc, window))

    def samples(transfer: bool):
        base = [rng.choice([30, 30, 32, 34, 35, 36, 38, 40]) for _ in range(16)]
        tail = [rng.choice([45, 55, 60, 90, 120]) for _ in range(4)] if transfer else [rng.choice([40, 45]) for _ in range(4)]
        return [b + (8 if transfer else 0) for b in base] + tail

    stations = {s: {"x": x, "y": y, "walk_transfer": walk.get(s), "walk_bus": 3.0 if s in walk else 2.0,
                    "dwell_samples": samples(s in walk)} for s, (x, y) in coords.items()}

    sc = Scenario("Metro City (3 lines)", trains, stations, [],
                  {"Red": "#EF4444", "Blue": "#3B82F6", "Green": "#10B981"}, dict(DEFAULT_PARAMS))
    od = []
    for f, c, k in sc.transfer_directions():
        ft, ct = trains[f], trains[c]
        origins = ft.stations[: ft.stations.index(k)]
        dests = ct.stations[ct.stations.index(k) + 1:]
        for _ in range(rng.choice([1, 1, 2])):
            od.append(dict(origin=rng.choice(origins), from_train=f, transfer=k,
                           dest=rng.choice(dests), to_train=c, pax=rng.choice([5, 10, 15, 20, 25, 30, 40])))
    # merge duplicate OD rows
    merged = {}
    for g in od:
        key = (g["origin"], g["from_train"], g["transfer"], g["dest"], g["to_train"])
        merged[key] = merged.get(key, 0) + g["pax"]
    sc.od = [dict(origin=o, from_train=f, transfer=k, dest=d, to_train=c, pax=p)
             for (o, f, k, d, c), p in merged.items()]
    return sc


def grid_city(window: int = 10) -> Scenario:
    """Large case (Vienna-like size): 3 east-west + 3 north-south lines, 15 stations each, 9 crossings."""
    rng = random.Random(11)
    pos = [0, 1, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18]   # crossings at 3, 9 and 15
    cross = {3: 0, 9: 1, 15: 2}
    trains, coords, colors = {}, {}, {}
    palette = ["#EF4444", "#3B82F6", "#10B981", "#8B5CF6", "#F59E0B", "#EC4899"]
    for n in range(3):
        for kind in ("H", "V"):
            line = f"{kind}{n + 1}"
            colors[line] = palette[len(colors)]
            fixed = [3, 9, 15][n]
            sts = []
            for p in pos:
                xy = (p, fixed) if kind == "H" else (fixed, p)
                if p in cross:
                    name = f"Jn H{[3, 9, 15].index(xy[1]) + 1}/V{[3, 9, 15].index(xy[0]) + 1}"
                else:
                    name = f"{line}-{pos.index(p) + 1:02d}"
                coords[name] = xy
                sts.append(name)
            runs = [2 + (b - a) // 2 for a, b in zip(pos, pos[1:])]
            fc, rc = rng.randint(15, 30), rng.randint(15, 30)
            trains.update(_trains_for_line(line, sts, runs, f"{line}-fwd", f"{line}-rev", fc, rc, window))
    stations = {s: {"x": x, "y": y, "walk_transfer": rng.choice([2.5, 3.0, 4.0]) if s.startswith("Jn") else None,
                    "walk_bus": 3.0 if s.startswith("Jn") else 2.0,
                    "dwell_samples": [rng.choice([30, 32, 35, 38, 40, 45, 60, 90]) for _ in range(20)]}
                for s, (x, y) in coords.items()}
    sc = Scenario("Grid City (large)", trains, stations, [], colors, dict(DEFAULT_PARAMS, fleet=15))
    od = []
    for f, c, k in sc.transfer_directions():
        ft, ct = trains[f], trains[c]
        od.append(dict(origin=rng.choice(ft.stations[: ft.stations.index(k)]), from_train=f, transfer=k,
                       dest=rng.choice(ct.stations[ct.stations.index(k) + 1:]), to_train=c,
                       pax=rng.choice([5, 10, 15, 20, 30])))
    sc.od = od
    return sc


SCENARIOS = {"Metro City (3 lines)": metro_city, "Two-line crossing (toy)": two_line_crossing}
