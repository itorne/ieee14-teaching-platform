# Interactive Teaching Platform for Power Flow and N-1 Analysis (IEEE 14-bus)

Open-source platform for teaching steady-state security analysis on the IEEE 14-bus system:
24 hourly scenarios built from open data of the Brazilian system operator (ONS), N-1 analysis of
every branch, and modelling choices that the student can change (generator reactive limits,
provisional branch ratings, island treatment, contingency ranking). It is a teaching **digital
model**; it exchanges no data with a physical system.

Repository: https://github.com/itorne/ieee14-teaching-platform

## Quick start

**Students (Portuguese):** see [INSTALACAO.md](INSTALACAO.md). On Windows, double-click `iniciar.bat`;
on macOS/Linux run `./iniciar.sh`. The first run creates a virtual environment and installs everything.

Manual installation:

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py              # opens http://localhost:8501
```

## Files

| File | Purpose |
|---|---|
| `core.py` | All calculations (no interface code): network, hourly scenarios, reactive limits, provisional ratings, N-1 and ranking, loadability curve, validation, Newton-Raphson vs Gauss-Seidel. |
| `app.py` | Streamlit interface used by students. |
| `reproduce.py` | Regenerates every table, figure and number of the manuscript (`results/`, `figures/`). |
| `build_load_profile.py` | Rebuilds `data/load_profile_north_ons_2026.csv` from the raw ONS file. |
| `data/load_profile_north_ons_2026.csv` | Hourly means, standard deviations, number of days and normalized factors. |
| `evaluation/` | Classroom-evaluation analysis script and response template. |
| `results/`, `figures/` | Outputs of `reproduce.py`. |

## Modelling choices (all visible on screen)

- **Network**: `pandapower.networks.case14()` without manual changes; bus 1 slack, buses 2, 3, 6, 8 PV.
- **Power flow**: Newton-Raphson, generator reactive-power limits enforced by default (switch on the
  *Network parameters* screen). The slack generator has no reactive limit.
- **Hourly scenarios**: loads and PV-generator active power multiplied by `f_h = f_global * c_h`, with `c_h`
  the ONS North-subsystem profile (2026-01-01 to 2026-09-29) normalized to the mean of 10:00 and 11:00.
  Only the shape of the profile is used.
- **Provisional ratings**: `S_rating = max(S_peak / target, 25 MVA)` from the intact network at the peak hour
  (default target 55 %). By construction, the intact network never exceeds the target at the peak; ratings are a
  teaching device, not equipment data.
- **Voltage indicators**: load (PQ) buses only; bus 7 (star point of a three-winding transformer) excluded.
- **N-1 ranking**: lexicographic: (1) no power-flow solution, (2) load lost by islanding (topological check),
  (3) index `J = sum(max(L - L_em, 0))/100 + 10 * sum(voltage excursion of load buses)`.

## Reproducing the manuscript

```bash
python reproduce.py                         # about 3 minutes; writes results/ and figures/
python evaluation/analyze_evaluation.py     # reads evaluation/responses.csv if present
```

`results/macros.tex` holds every number quoted in the manuscript. `results/environment.json` records the
software versions of the run.

## Data

ONS, *Curva de Carga Horária*, open data, license CC-BY: https://dados.ons.org.br/dataset/curva-carga

## License and citation

MIT License (see `LICENSE`). Citation metadata are in `CITATION.cff`; the archived version has a DOI on Zenodo
(badge to be added after the first release). Please also cite the accompanying article (reference to be added after publication).
