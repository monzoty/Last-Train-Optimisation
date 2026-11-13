# Last Train DSS: prototype

Decision-support prototype for **Kang et al. (2019), "Last train timetabling optimization and bus bridging
service management in urban railway transit networks", Omega 84, 31-44.**

It shows the planner the inputs, runs the paper's Algorithm 1 (MILP-1 timetable → MILP-2 bus bridging) with
SCIP through Google OR-Tools, and presents the results: KPIs, a bus map, station timelines, a Gantt chart,
a fleet-size trade-off and live test cases. All network and demand data is illustrative.

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```
Run the tests with `python -m pytest -q test_model.py`.

## Deploy (share.streamlit.io)
1. Push this `prototype/` folder to a public GitHub repo.
2. On https://share.streamlit.io choose **New app**, pick the repo, and set the main file to `app.py`.
3. Under *Advanced settings*, set Python to 3.12.

## Files
| File | What it holds |
|---|---|
| `app.py` | Streamlit pages (Overview, Inputs, Results, Model, Tests) |
| `model.py` | MILP-1, MILP-2, Algorithm 1, KPIs, defuzzification |
| `scenarios.py` | Example networks: Metro City (3 lines), Two-line crossing (toy); Grid City (large) is used only by the speed test |
| `charts.py` | Network map, transfer-station board, timetable Gantt (shared "saas" Plotly template) |
| `ui.py` | Design system: CSS, page header, KPI cards, cards, bus list |
| `.streamlit/config.toml`, `assets/` | Theme (Inter font, indigo accent) and logo |
| `testcases.py`, `test_model.py` | Test plan TC01-TC17 (shown in the app and run by pytest) |

## Prototype simplifications (state these if asked)
- Each passenger group has one transfer station. Bus candidates are *replacement* (transfer station → destination)
  and *direct* (origin → destination).
- Paper constraint (6) (bounds on finishing time) and eq. (30) (headway waiting) are not modelled. The paper
  itself says eq. (30) is analysis only.
- The bus fleet counts bus routes, one bus per route, as in the paper.
- Constraint (11) is applied only to the buses that bridge that transfer. Taken literally, the paper's version
  links every (k, i, j).
- **Open issue (TC12):** our reading of eq. 26 reproduces the paper's 31 s example but gives 42.1 s instead of
  37.7 s on the 100-sample set.

## Pages
| Page | What it does |
|---|---|
| Overview | The problem, headline numbers (today → re-timed trains → + buses), plan map, how it works, the "will you make your connection?" demo |
| Inputs | Four sections: Train times (window chart + range sliders), Stations (walking sliders, dwell samples), Passengers (filter by station, ±20%, editable table), Buses (fleet and timing sliders). Headline numbers and a "compared with the example" line update as you edit; Undo all resets |
| Results | KPIs, auto-written findings, bus plan map and schedule, station timelines, timetable Gantt, every transfer, fleet-size trade-off |
| Model | Algorithm 1 flow, notation, MILP-1 and MILP-2 one rule per row with paper equation numbers |
| Tests | TC01-TC17 run live, plus a comparison with the paper's Vienna results |

## 2-minute demo script (Metro City)
1. **Overview** (30 s): the problem in one sentence. Today 39% → re-timed 63% → with 4 buses 80%. Drag the
   "connecting train leaves" slider from miss to make it: that rule is the whole model.
2. **Inputs** (30 s): on *Train times*, show the window chart (○ today, ◆ the model's choice). On *Buses*, set the fleet from 4 to 2. The headline drops to 72% and 170 stranded. Reset.
3. **Results** (30 s): the bus plan, then *Transfer stations → Central* (red ✕ turning green), then *Fleet size*.
4. **Model** (20 s): the two-step algorithm and the formulation table.
5. **Tests** (10 s): 16 pass + 1 open issue, and the same pattern as the paper's Vienna case.
