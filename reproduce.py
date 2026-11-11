"""
Regenerates every table, figure and number reported in the manuscript.

Usage:
    python reproduce.py            # writes results/*.csv, results/macros.tex, figures/*

All numbers in the manuscript are read from results/macros.tex, so text and data
cannot drift apart. Run time: about three minutes on a laptop.
"""

import json
import platform
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import pandapower as pp  # noqa: E402

import core  # noqa: E402

ROOT = Path(__file__).parent
RES = ROOT / "results"
FIG = ROOT / "figures"
RES.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8,
    "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 150, "savefig.bbox": "tight",
    "pdf.fonttype": 42,
})
COL = 3.5  # IEEE single-column width (in)

macros = {}


def mac(name, value):
    macros[name] = value


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=600)
    plt.close(fig)


def fmt(x, nd):
    return f"{x:.{nd}f}"


P = core.default_params()
base = core.cached_base(P)
short, long = core.branch_names(base)
lb = core.load_buses(base)

# ------------------------------------------------------------------ environment
env = {"python": platform.python_version(), "pandapower": pp.__version__,
       "numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__,
       "os": platform.platform()}
(RES / "environment.json").write_text(json.dumps(env, indent=2))
mac("envPython", env["python"])
mac("envPandapower", env["pandapower"])
mac("envNumpy", env["numpy"])
mac("envPandas", env["pandas"])

# ------------------------------------------------------------------ validation
val = core.validate_base_case()
val["dv_pct"] = 100 * (val.vm_pandapower - val.vm_cdf).abs() / val.vm_cdf
val["dva_deg"] = (val.va_pandapower - val.va_cdf).abs()
val.to_csv(RES / "validation_base_case.csv", index=False)
mac("valMaxDvPct", fmt(val.dv_pct.max(), 3))
mac("valMaxDvBus", str(int(val.bus[val.dv_pct.idxmax()])))
mac("valMaxDaDeg", fmt(val.dva_deg.max(), 3))
mac("valMaxDaBus", str(int(val.bus[val.dva_deg.idxmax()])))

# ------------------------------------------------------------------ 24 h, intact
h24 = core.run_24h(P)
h24.to_csv(RES / "hourly_intact.csv", index=False)
pk = int(h24.factor.idxmax())
lo = int(h24.factor.idxmin())
mac("peakHour", f"{pk:02d}:00")
mac("valleyHour", f"{lo:02d}:00")
mac("peakFactor", fmt(h24.factor.max(), 3))
mac("valleyFactor", fmt(h24.factor.min(), 3))
mac("hConverged", str(int(h24.converged.sum())))
mac("lossMin", fmt(h24.losses_mw.min(), 2))
mac("lossMax", fmt(h24.losses_mw.max(), 2))
mac("lossBase", fmt(h24.losses_mw[3], 2))
mac("lossDayMWh", fmt(h24.losses_mw.sum(), 1))
mac("vminLoadBus", fmt(h24.vmin_load_bus.min(), 3))
mac("vminLoadBusBus", str(int(h24.vmin_bus[h24.vmin_load_bus.idxmin()])))
mac("vmaxLoadBus", fmt(h24.vmax_load_bus.max(), 3))
mac("vmaxLoadBusBus", str(int(h24.vmax_bus[h24.vmax_load_bus.idxmax()])))
mac("maxLoadingIntact", fmt(h24.max_loading_pct.max(), 1))
mac("hoursQlim", str(int((h24.gens_at_qlim > 0).sum())))
mac("hoursViolation", str(int(h24.violation.sum())))

# bus 7 values (to explain its exclusion)
v7 = []
for h in range(24):
    net = core.build(P, h)
    core.run_pf(net)
    v7.append(net.res_bus.vm_pu.iat[6])
mac("vSevenMin", fmt(min(v7), 3))
mac("vSevenMax", fmt(max(v7), 3))

# ------------------------------------------------------------------ N-1, all hours
sweeps = []
for h in range(24):
    s = core.n1_sweep(P, h)
    s.insert(0, "hour", h)
    sweeps.append(s)
n1 = pd.concat(sweeps, ignore_index=True)
n1.to_csv(RES / "n1_all_hours.csv", index=False)
n1_peak = n1[n1.hour == pk].drop(columns="hour")
n1_peak.to_csv(RES / "n1_peak_hour.csv", index=False)

l1 = n1[n1.short == "L1"].set_index("hour")
mac("lOneUnsolvedHours", str(int((~l1.solved).sum())))
mac("lOneSolvedHours", ", ".join(f"{h:02d}:00" for h in l1.index[l1.solved]))
lv = l1.loc[lo]
mac("lOneValleyLoss", fmt(lv.losses_mw, 2))
mac("lOneValleyVmin", fmt(lv.vmin_load_bus, 3))
mac("lOneValleyMaxLoading", fmt(lv.max_loading_pct, 1))
mac("lOneValleyMaxLoadingBranch", lv.max_loading_branch)
mac("lOneValleyQlim", str(int(lv.gens_at_qlim)))
unsolved_by_branch = n1.groupby("short").solved.apply(lambda x: int((~x).sum()))
mac("branchesEverUnsolved", str(int((unsolved_by_branch > 0).sum())))
over_by_hour = n1.groupby("hour").apply(lambda d: int((d.overloads.fillna(0) > 0).sum()))
mac("ctgOverloadPeak", str(int(over_by_hour[pk])))
mac("ctgOverloadValley", str(int(over_by_hour[lo])))
t4 = n1_peak[n1_peak.short == "T4"].iloc[0]
mac("tFourRank", str(int(t4["rank"])))
mac("tFourIsolated", str(t4.isolated_buses))
second = n1_peak.iloc[1]
mac("secondBranch", second.branch.replace("-", "--"))
mac("secondMaxLoading", fmt(second.max_loading_pct, 1))
mac("secondMaxLoadingBranch", second.max_loading_branch)
mac("secondVmin", fmt(second.vmin_load_bus, 3))
third = n1_peak.iloc[2]
mac("thirdBranch", third.branch.replace("-", "--"))
mac("thirdOverloads", str(int(third.overloads)))
mac("thirdVmin", fmt(third.vmin_load_bus, 3))

# ------------------------------------------------------------------ L1 with limits ignored
net = core.build(P, 3)
core.run_pf(net, enforce_q_limits=True)
loss_intact = core.losses_mw(net)
net.line.at[0, "in_service"] = False
core.run_pf(net, enforce_q_limits=False)
q = net.res_gen.q_mvar.to_numpy()
qmax = net.gen.max_q_mvar.to_numpy()
viol = np.where(q > qmax + 1e-6)[0]
mac("noQlimLossBefore", fmt(loss_intact, 2))
mac("noQlimLossAfter", fmt(core.losses_mw(net), 2))
mac("noQlimGenTwoQ", fmt(q[0], 1))
mac("noQlimGenTwoQmax", fmt(qmax[0], 0))
mac("noQlimNviol", str(len(viol)))
mac("noQlimVmin", fmt(net.res_bus.vm_pu.to_numpy()[lb].min(), 3))

# ------------------------------------------------------------------ loadability (PV curves)
curves = {}
for name, out, ql in (("intact_qlim", None, True), ("intact_noqlim", None, False),
                      ("L1out_qlim", 0, True), ("L1out_noqlim", 0, False)):
    c, last = core.loadability_curve(P, outage=out, enforce_q_limits=ql, lam_start=0.3, step=0.002)
    c.to_csv(RES / f"pv_{name}.csv", index=False)
    curves[name] = (c, last)
mac("lamIntactQ", fmt(curves["intact_qlim"][1], 3))
mac("lamIntactNoQ", fmt(curves["intact_noqlim"][1], 3) if curves["intact_noqlim"][1] < 2.999 else "3.0")
mac("lamLOneQ", fmt(curves["L1out_qlim"][1], 3))
mac("lamLOneNoQ", fmt(curves["L1out_noqlim"][1], 3))
c = curves["L1out_qlim"][0]
first_viol = c[c.vmin_load_bus < P["vmin"]]
mac("lamLOneVviol", fmt(first_viol.factor.iloc[0], 3) if len(first_viol) else "none")

# ------------------------------------------------------------------ rating sensitivity (peak)
rows = []
for tgt in (0.45, 0.55, 0.65, 0.75):
    Ps = dict(P, rating_target=tgt)
    s = core.n1_sweep(Ps, pk)
    rows.append({"rating_target_pct": int(round(100 * tgt)),
                 "unsolved": int((~s.solved).sum()),
                 "ctg_with_overload": int((s.overloads.fillna(0) > 0).sum()),
                 "total_overloads": int(s.overloads.fillna(0).sum()),
                 "ranks_2_3": ", ".join(s.short.iloc[1:3])})
sens = pd.DataFrame(rows)
sens.to_csv(RES / "rating_sensitivity.csv", index=False)
mac("sensOverMin", str(int(sens.total_overloads.min())))
mac("sensOverMax", str(int(sens.total_overloads.max())))

# ------------------------------------------------------------------ NR vs GS
nrgs = core.nr_vs_gs()
nrgs.to_csv(RES / "nr_vs_gs.csv", index=False)
nr, gs = nrgs.iloc[0], nrgs.iloc[1]
mac("nrIter", str(int(nr.iterations)))
mac("gsIter", str(int(gs.iterations)))
mac("nrMs", fmt(nr.median_ms, 1))
mac("gsMs", fmt(gs.median_ms, 1))
mac("nrSd", fmt(nr.std_ms, 1))
mac("gsSd", fmt(gs.std_ms, 1))
mac("nrgsReps", str(int(nr.repetitions)))
mac("nrgsDv", f"{nrgs.attrs['max_dv_pu']:.1e}".replace("e-", r"\times10^{-") + "}")

# ------------------------------------------------------------------ figures
# Fig. hourly: factor/losses and load-bus voltages
fig, ax = plt.subplots(2, 1, figsize=(COL, 3.0), sharex=True)
ax[0].bar(h24.hour, h24.losses_mw, color="#4C72B0", width=0.7, label="Active losses")
ax[0].set_ylabel("Losses (MW)")
ax0b = ax[0].twinx()
ax0b.plot(h24.hour, h24.factor, color="#C44E52", marker="o", ms=2.5, lw=1, label="Load factor")
ax0b.set_ylabel("Load factor (pu)")
ax0b.grid(False)
h1, l1_ = ax[0].get_legend_handles_labels()
h2, l2_ = ax0b.get_legend_handles_labels()
ax[0].legend(h1 + h2, l1_ + l2_, loc="upper left", ncol=2, frameon=False)
ax[0].set_ylim(0, h24.losses_mw.max() * 1.25)
ax[1].plot(h24.hour, h24.vmax_load_bus, marker="^", ms=2.5, lw=1, label="Max. load-bus voltage")
ax[1].plot(h24.hour, h24.vmin_load_bus, marker="v", ms=2.5, lw=1, label="Min. load-bus voltage")
ax[1].plot(range(24), v7, ls=":", lw=1, color="gray", label="Bus 7 (fictitious, excluded)")
ax[1].set_ylabel("Voltage (pu)")
ax[1].set_xlabel("Hour of day")
ax[1].set_xticks(range(0, 24, 3))
ax[1].legend(loc="center right", frameon=False)
save(fig, "fig_hourly")

# Fig. PV curves
fig, ax = plt.subplots(figsize=(COL, 2.4))
sty = {"intact_qlim": ("Intact, Q limits", "#4C72B0", "-"),
       "intact_noqlim": ("Intact, no Q limits", "#4C72B0", ":"),
       "L1out_qlim": ("Line 1-2 out, Q limits", "#C44E52", "-"),
       "L1out_noqlim": ("Line 1-2 out, no Q limits", "#C44E52", ":")}
for k, (lab, col, ls) in sty.items():
    cc, last = curves[k]
    ax.plot(cc.factor, cc.vmin_load_bus, ls=ls, color=col, lw=1.2, label=lab)
    ax.plot(cc.factor.iloc[-1], cc.vmin_load_bus.iloc[-1], marker="x", color=col, ms=5)
ax.axvspan(h24.factor.min(), h24.factor.max(), color="#DDAA33", alpha=0.25, lw=0,
           label="Daily range of hourly factor")
ax.axhline(P["vmin"], color="k", lw=0.8, ls="--")
ax.text(0.32, P["vmin"] + 0.005, "0.95 pu", fontsize=6.5)
ax.set_xlim(0.3, 2.0)
ax.set_xlabel("Uniform load and generation factor (pu)")
ax.set_ylabel("Min. load-bus voltage (pu)")
ax.legend(loc="lower left", frameon=False, fontsize=6.5)
save(fig, "fig_pv")

# Fig. N-1 map (branches x hours)
status = np.zeros((len(short), 24))
for _, r in n1.iterrows():
    k = short.index(r.short)
    if not r.solved:
        status[k, r.hour] = 3
    elif r.overloads > 0:
        status[k, r.hour] = 2
    elif r.vmin_load_bus < P["vmin"]:
        status[k, r.hour] = 1.5
    elif r.isolated_buses:
        status[k, r.hour] = 1
from matplotlib.colors import ListedColormap, BoundaryNorm  # noqa: E402
cmap = ListedColormap(["#E8F1E4", "#B8C7D9", "#F2C14E", "#E07B39", "#B2182B"])
norm = BoundaryNorm([-0.5, 0.5, 1.25, 1.75, 2.5, 3.5], cmap.N)
fig, ax = plt.subplots(figsize=(COL, 3.2))
ax.imshow(status, aspect="auto", cmap=cmap, norm=norm, interpolation="none")
ax.set_yticks(range(len(long)))
ax.set_yticklabels(long, fontsize=6)
ax.set_xticks(range(0, 24, 3))
ax.set_xlabel("Hour of day")
ax.grid(False)
from matplotlib.patches import Patch  # noqa: E402
ax.legend(handles=[Patch(color=cmap(i), label=t) for i, t in enumerate(
    ["Secure", "Island, no load lost", "Voltage below 0.95 pu", "Overload > 110 %", "No power-flow solution"])],
    loc="upper center", bbox_to_anchor=(0.45, -0.13), ncol=3, frameon=False, fontsize=6)
save(fig, "fig_n1map")

# ------------------------------------------------------------------ macros file
lines = ["% Generated by reproduce.py -- do not edit by hand."]
for k, v in macros.items():
    lines.append(f"\\newcommand{{\\{k}}}{{{v}}}")
(RES / "macros.tex").write_text("\n".join(lines) + "\n")
(RES / "macros.json").write_text(json.dumps(macros, indent=2))
print(json.dumps(macros, indent=2))
print("Environment:", env)
print("Python", sys.version)
