"""
Computation core of the IEEE 14-bus interactive teaching platform.

This module has no user-interface code. It is imported by the Streamlit app (app.py)
and by the reproduction script (reproduce.py), so that every number in the paper
and on screen comes from the same functions.

Main modelling choices (all configurable through the `params` dictionary):
  * Network: pandapower.networks.case14(), loaded without manual changes.
  * Power flow: Newton-Raphson (pandapower.runpp) with generator reactive-power
    limits enforced by default (PV buses switch to PQ when a limit is reached).
  * Hourly scenarios: loads and PV-generator active power are multiplied by
    f_h = f_global * c_h, where c_h is the normalised ONS North-subsystem profile.
  * Branch ratings: case14() carries no realistic ratings, so provisional ratings
    are derived as S_rating = max(S_peak / target, floor) from the intact network
    at the peak hour. This makes the intact peak loading equal to the target by
    construction; the ratings are a teaching device, not equipment data.
  * Voltage indicators exclude bus 7 (the fictitious star point of the
    three-winding transformer of the original IEEE 14-bus case).
  * N-1 ranking is lexicographic: (1) no power-flow solution, (2) load lost by
    islanding, (3) continuous index J of overload and voltage violations.
"""

from __future__ import annotations

import copy
import time

import networkx as nx
import numpy as np
import pandapower as pp
import pandapower.networks as pn
import pandapower.topology as top
import pandas as pd

# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
# Normalised hourly load profile of the Brazilian North subsystem, built from the ONS
# open dataset "Curva de Carga Horaria" (CC-BY), 2026-01-01 to 2026-09-29 (272 days,
# 6,528 hourly records). Hourly means normalised so that the mean of 10:00 and 11:00
# equals 1.00. Source table: data/load_profile_north_ons_2026.csv.
LOAD_PROFILE = [1.071, 1.047, 1.023, 1.000, 0.983, 0.971, 0.941, 0.937, 0.963, 0.981, 0.996,
                1.004, 1.003, 1.030, 1.055, 1.058, 1.045, 1.024, 1.028, 1.057, 1.070, 1.086,
                1.097, 1.091]

# Bus 7 (index 6) of the IEEE 14-bus case is the star point of a three-winding
# transformer and carries no load; it is excluded from load-bus voltage indicators.
FICTITIOUS_BUSES_CASE14 = {6}

DEFAULT_RATING_TARGET = 0.55   # intact peak loading used to derive provisional ratings
DEFAULT_RATING_FLOOR = 25.0    # MVA, lower bound of the provisional ratings
MAX_ITER = 30


def default_params() -> dict:
    """Default operating parameters (same defaults as the user interface)."""
    return {
        "global_factor": 1.0,
        "profile": list(LOAD_PROFILE),
        "vmin": 0.95,
        "vmax": 1.10,
        "normal_limit": 100.0,        # % of provisional rating, intact network
        "emergency_limit": 110.0,     # % of provisional rating, N-1
        "enforce_q_limits": True,
        "rating_target": DEFAULT_RATING_TARGET,
        "rating_floor": DEFAULT_RATING_FLOOR,
        "gens": None,                 # None = original dispatch of case14()
        "shunts": None,               # None = all shunts in service
    }


# --------------------------------------------------------------------------------------
# Network construction
# --------------------------------------------------------------------------------------
def _branch_s(net) -> np.ndarray:
    """Apparent power (MVA) of every branch, lines first, then transformers;
    the larger of the two terminal values."""
    rl, rt = net.res_line, net.res_trafo
    s_l = np.maximum(np.hypot(rl.p_from_mw, rl.q_from_mvar), np.hypot(rl.p_to_mw, rl.q_to_mvar))
    s_t = np.maximum(np.hypot(rt.p_hv_mw, rt.q_hv_mvar), np.hypot(rt.p_lv_mw, rt.q_lv_mvar))
    return np.concatenate([np.asarray(s_l, float), np.asarray(s_t, float)])


def run_pf(net, enforce_q_limits: bool = True, **kw) -> bool:
    """Newton-Raphson power flow. Returns False when no solution is found."""
    try:
        pp.runpp(net, algorithm="nr", enforce_q_lims=enforce_q_limits,
                 max_iteration=kw.pop("max_iteration", MAX_ITER), **kw)
        return True
    except Exception:  # LoadflowNotConverged or no slack in an island
        return False


def base_network(rating_target: float = DEFAULT_RATING_TARGET,
                 rating_floor: float = DEFAULT_RATING_FLOOR,
                 profile=None, enforce_q_limits: bool = True):
    """case14() plus provisional branch ratings stored in column `rating_mva`."""
    net = pn.case14()
    peak = max(profile or LOAD_PROFILE)
    net.load["scaling"] = peak
    net.gen["scaling"] = peak
    if not run_pf(net, enforce_q_limits):
        raise RuntimeError("Intact network does not solve at the peak hour.")
    rating = np.maximum(_branch_s(net) / rating_target, rating_floor)
    nl = len(net.line)
    net.line["rating_mva"] = rating[:nl]
    net.trafo["rating_mva"] = rating[nl:]
    net.load["scaling"] = 1.0
    net.gen["scaling"] = 1.0
    return net


_BASE_CACHE: dict = {}


def cached_base(params: dict):
    key = (params["rating_target"], params["rating_floor"], tuple(params["profile"]),
           params["enforce_q_limits"])
    if key not in _BASE_CACHE:
        _BASE_CACHE[key] = base_network(params["rating_target"], params["rating_floor"],
                                        params["profile"], params["enforce_q_limits"])
    return _BASE_CACHE[key]


def branch_names(net) -> tuple[list, list]:
    """Short labels (L1..L15, T1..T5) and long labels with bus numbers (1-based)."""
    nl, nt = len(net.line), len(net.trafo)
    fr = list(net.line.from_bus) + list(net.trafo.hv_bus)
    to = list(net.line.to_bus) + list(net.trafo.lv_bus)
    short = [f"L{k + 1}" for k in range(nl)] + [f"T{k + 1}" for k in range(nt)]
    long = [f"{short[k]} ({fr[k] + 1}-{to[k] + 1})" for k in range(nl + nt)]
    return short, long


def load_buses(net) -> list:
    """Buses whose voltage is a free variable (PQ) and that are not fictitious."""
    controlled = set(net.gen.bus) | set(net.ext_grid.bus)
    return [b for b in net.bus.index if b not in controlled and b not in FICTITIOUS_BUSES_CASE14]


def hour_factor(params: dict, h: int) -> float:
    return float(params["global_factor"] * params["profile"][h])


def build(params: dict, hour: int):
    """Copy of the base network with dispatch, shunts and hourly scaling applied."""
    net = copy.deepcopy(cached_base(params))
    if params.get("gens"):
        for i, g in enumerate(params["gens"]):
            gi = net.gen.index[i]
            net.gen.at[gi, "in_service"] = bool(g["in_service"])
            net.gen.at[gi, "p_mw"] = float(g["p_mw"])
            net.gen.at[gi, "vm_pu"] = float(g["vm_pu"])
    if params.get("shunts"):
        for i, on in enumerate(params["shunts"]):
            if i < len(net.shunt):
                net.shunt.at[net.shunt.index[i], "in_service"] = bool(on)
    f = hour_factor(params, hour)
    net.load["scaling"] = f
    net.gen["scaling"] = f
    return net


# --------------------------------------------------------------------------------------
# Result extraction
# --------------------------------------------------------------------------------------
def losses_mw(net) -> float:
    return float(np.nansum(net.res_line.pl_mw) + np.nansum(net.res_trafo.pl_mw))


def loading_pct(net) -> np.ndarray:
    rating = np.concatenate([net.line["rating_mva"].to_numpy(float),
                             net.trafo["rating_mva"].to_numpy(float)])
    return 100.0 * _branch_s(net) / rating


def gens_at_q_limit(net, tol: float = 1e-3) -> list:
    """Indices of PV generators operating at a reactive-power limit."""
    q = net.res_gen.q_mvar.to_numpy(float)
    qmax = net.gen.max_q_mvar.to_numpy(float)
    qmin = net.gen.min_q_mvar.to_numpy(float)
    on = net.gen.in_service.to_numpy(bool)
    return [int(i) for i in np.where(on & ((q >= qmax - tol) | (q <= qmin + tol)))[0]]


def extract(net, ok: bool) -> dict:
    nb, nbr = len(net.bus), len(net.line) + len(net.trafo)
    if not ok:
        return {"ok": False, "vm": np.full(nb, np.nan), "loading": np.full(nbr, np.nan),
                "p_from": np.full(nbr, np.nan), "losses": np.nan, "q_gen": np.full(len(net.gen), np.nan),
                "gens_at_qlim": []}
    return {"ok": True,
            "vm": net.res_bus.vm_pu.to_numpy(float),
            "loading": loading_pct(net),
            "p_from": np.concatenate([net.res_line.p_from_mw.to_numpy(float),
                                      net.res_trafo.p_hv_mw.to_numpy(float)]),
            "losses": losses_mw(net),
            "q_gen": net.res_gen.q_mvar.to_numpy(float),
            "gens_at_qlim": gens_at_q_limit(net)}


# --------------------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------------------
def run_24h(params: dict) -> pd.DataFrame:
    """Hourly power flows of the intact network."""
    net0 = build(params, 0)
    lb = load_buses(net0)
    short, _ = branch_names(net0)
    rows = []
    for h in range(24):
        net = build(params, h)
        d = extract(net, run_pf(net, params["enforce_q_limits"]))
        row = {"hour": h, "factor": hour_factor(params, h), "converged": d["ok"],
               "load_mw": float((net.load.p_mw * net.load.scaling).sum())}
        if d["ok"]:
            vm = d["vm"][lb]
            row.update(losses_mw=d["losses"],
                       vmin_load_bus=float(vm.min()), vmin_bus=int(lb[int(vm.argmin())]) + 1,
                       vmax_load_bus=float(vm.max()), vmax_bus=int(lb[int(vm.argmax())]) + 1,
                       max_loading_pct=float(np.nanmax(d["loading"])),
                       max_loading_branch=short[int(np.nanargmax(d["loading"]))],
                       gens_at_qlim=len(d["gens_at_qlim"]),
                       violation=bool((vm < params["vmin"]).any() or (vm > params["vmax"]).any()
                                      or (d["loading"] > params["normal_limit"]).any()))
        rows.append(row)
    return pd.DataFrame(rows)


def island_analysis(net) -> tuple[list, float]:
    """Buses disconnected from every slack bus (topological check before the power
    flow) and the load they carry (MW)."""
    g = top.create_nxgraph(net, respect_switches=True, include_out_of_service=False)
    slack = set(net.ext_grid.bus[net.ext_grid.in_service])
    energised = set()
    for comp in nx.connected_components(g):
        if comp & slack:
            energised |= comp
    isolated = sorted(set(net.bus.index[net.bus.in_service]) - energised)
    mask = net.load.bus.isin(isolated) & net.load.in_service
    lost = float((net.load.p_mw[mask] * net.load.scaling[mask]).sum())
    return [int(b) for b in isolated], lost


def run_contingency(params: dict, branch: int, hour: int) -> dict:
    """Removes one branch (lines first, then transformers) and re-solves."""
    net = build(params, hour)
    before = extract(net, run_pf(net, params["enforce_q_limits"]))
    nl = len(net.line)
    if branch < nl:
        net.line.at[net.line.index[branch], "in_service"] = False
    else:
        net.trafo.at[net.trafo.index[branch - nl], "in_service"] = False
    isolated, lost = island_analysis(net)
    ok = run_pf(net, params["enforce_q_limits"])
    after = extract(net, ok)
    if ok:
        after["loading"][branch] = np.nan
        after["p_from"][branch] = 0.0
    return {"before": before, "after": after, "ok": ok, "isolated": isolated, "lost_load_mw": lost}


def severity_index(after: dict, params: dict, lb: list) -> float:
    """Continuous index J for a solved contingency: overload above the emergency limit
    (in units of 100 %) plus ten times the voltage excursion (pu) of load buses."""
    ld = after["loading"]
    vm = after["vm"][lb]
    over = np.nansum(np.clip(ld - params["emergency_limit"], 0, None)) / 100.0
    volt = np.nansum(np.clip(params["vmin"] - vm, 0, None) + np.clip(vm - params["vmax"], 0, None))
    return float(over + 10.0 * volt)


def n1_sweep(params: dict, hour: int) -> pd.DataFrame:
    """N-1 sweep of all branches with lexicographic ranking."""
    net0 = build(params, hour)
    lb = load_buses(net0)
    short, long = branch_names(net0)
    rows = []
    for k in range(len(short)):
        r = run_contingency(params, k, hour)
        a = r["after"]
        rows.append({
            "branch": long[k], "short": short[k], "solved": r["ok"],
            "isolated_buses": " ".join(str(b + 1) for b in r["isolated"]),
            "lost_load_mw": r["lost_load_mw"],
            "overloads": int(np.nansum(a["loading"] > params["emergency_limit"])) if r["ok"] else np.nan,
            "max_loading_pct": float(np.nanmax(a["loading"])) if r["ok"] else np.nan,
            "max_loading_branch": short[int(np.nanargmax(a["loading"]))] if r["ok"] else "",
            "vmin_load_bus": float(np.nanmin(a["vm"][lb])) if r["ok"] else np.nan,
            "gens_at_qlim": len(a["gens_at_qlim"]) if r["ok"] else np.nan,
            "losses_mw": a["losses"],
            "J": severity_index(a, params, lb) if r["ok"] else np.nan,
        })
    df = pd.DataFrame(rows)
    df["_c1"] = (~df.solved).astype(int)
    df = df.sort_values(["_c1", "lost_load_mw", "J"], ascending=False).drop(columns="_c1")
    df.insert(0, "rank", range(1, len(df) + 1))
    return df.reset_index(drop=True)


def loadability_curve(params: dict, outage: int | None = None, lam_start: float = 0.5,
                      step: float = 0.01, lam_max: float = 3.0, enforce_q_limits: bool = True):
    """Steps a uniform load/generation factor until the power flow fails. Returns the
    curve (factor, minimum load-bus voltage) and the last solvable factor. A plain
    power flow cannot pass the nose of the PV curve, so the last solvable factor is
    a lower estimate of the loadability limit."""
    base = cached_base(params)
    lb = load_buses(base)
    net = copy.deepcopy(base)
    if outage is not None:
        nl = len(net.line)
        if outage < nl:
            net.line.at[net.line.index[outage], "in_service"] = False
        else:
            net.trafo.at[net.trafo.index[outage - nl], "in_service"] = False
    curve, lam, last_ok, init = [], lam_start, None, "auto"
    while lam <= lam_max + 1e-9:
        net.load["scaling"] = lam
        net.gen["scaling"] = lam
        ok = run_pf(net, enforce_q_limits, init=init)
        if not ok:
            break
        curve.append((lam, float(net.res_bus.vm_pu.to_numpy()[lb].min()),
                      len(gens_at_q_limit(net))))
        last_ok, init = lam, "results"
        lam = round(lam + step, 6)
    return pd.DataFrame(curve, columns=["factor", "vmin_load_bus", "gens_at_qlim"]), last_ok


def nr_vs_gs(repetitions: int = 50, tol_mva: float = 1e-8) -> pd.DataFrame:
    """Iterations and wall-clock time of runpp() for Newton-Raphson and Gauss-Seidel,
    flat start, after one warm-up run; both methods include the same pandapower
    preparation overhead."""
    rows, sol = [], {}
    for alg, kw in (("nr", {}), ("gs", {"max_iteration": 10000})):
        net = pn.case14()
        pp.runpp(net, algorithm=alg, tolerance_mva=tol_mva, init="flat", **kw)
        times = []
        for _ in range(repetitions):
            t0 = time.perf_counter()
            pp.runpp(net, algorithm=alg, tolerance_mva=tol_mva, init="flat", **kw)
            times.append(time.perf_counter() - t0)
        sol[alg] = (net.res_bus.vm_pu.to_numpy(), net.res_bus.va_degree.to_numpy())
        rows.append({"method": {"nr": "Newton-Raphson", "gs": "Gauss-Seidel"}[alg],
                     "iterations": int(net._ppc["iterations"]),
                     "median_ms": 1e3 * float(np.median(times)), "mean_ms": 1e3 * float(np.mean(times)),
                     "std_ms": 1e3 * float(np.std(times, ddof=1)), "repetitions": repetitions,
                     "losses_mw": losses_mw(net)})
    df = pd.DataFrame(rows)
    df.attrs["max_dv_pu"] = float(np.abs(sol["nr"][0] - sol["gs"][0]).max())
    df.attrs["max_dtheta_deg"] = float(np.abs(sol["nr"][1] - sol["gs"][1]).max())
    return df


# Published solution of the IEEE 14-bus case (IEEE Common Data Format, as distributed
# with MATPOWER case14.m): voltage magnitude (pu) and angle (degrees), buses 1-14.
CDF_VM = [1.060, 1.045, 1.010, 1.019, 1.020, 1.070, 1.062, 1.090, 1.056, 1.051, 1.057, 1.055, 1.050, 1.036]
CDF_VA = [0.00, -4.98, -12.72, -10.33, -8.78, -14.22, -13.37, -13.36, -14.94, -15.10, -14.79, -15.07, -15.16, -16.04]


def validate_base_case() -> pd.DataFrame:
    """Base case (factor 1.0, original dispatch) against the published CDF solution.
    Reactive limits are not enforced here because the published solution has the
    slack generator outside its own data limits."""
    net = pn.case14()
    pp.runpp(net, algorithm="nr", init="flat")
    return pd.DataFrame({"bus": range(1, 15), "vm_pandapower": net.res_bus.vm_pu.to_numpy(),
                         "vm_cdf": CDF_VM, "va_pandapower": net.res_bus.va_degree.to_numpy(),
                         "va_cdf": CDF_VA})
