"""
Interactive teaching platform for steady-state analysis of the IEEE 14-bus system.

Run:
    pip install -r requirements.txt
    streamlit run app.py

All calculations live in core.py; this file only builds the user interface.
"""

import copy
import json
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core

st.set_page_config(page_title="IEEE 14-bus teaching platform", layout="wide")

_NEW = tuple(int(x) for x in st.__version__.split(".")[:2]) >= (1, 50)
WIDE = {"width": "stretch"} if _NEW else {"use_container_width": True}

COLOR = {"ok": "#2E8B57", "warn": "#D9A400", "high": "#E8710A", "critical": "#C62828",
         "off": "#8A8F98", "bus": "#1F3A5F"}

# Fixed one-line diagram coordinates of the IEEE 14-bus system (bus index -> x, y).
POS14 = {0: (0.0, 3.6), 1: (2.5, 5.0), 2: (6.0, 5.0), 3: (5.0, 3.4), 4: (2.4, 3.0),
         5: (2.0, 1.7), 6: (7.0, 2.4), 7: (9.0, 2.4), 8: (5.6, 1.6), 9: (5.0, 0.3),
         10: (3.2, 0.4), 11: (0.2, 0.5), 12: (1.6, -0.7), 13: (4.4, -0.8)}
VOLT_DECIMALS = 3


# ======================================================================================
# Cached calculations (keyed by the JSON of the parameters)
# ======================================================================================
@st.cache_resource
def network_info(pj):
    p = json.loads(pj)
    net = core.cached_base(p)
    short, long = core.branch_names(net)
    idx = net.bus.index
    fr = np.concatenate([idx.get_indexer(net.line.from_bus), idx.get_indexer(net.trafo.hv_bus)])
    to = np.concatenate([idx.get_indexer(net.line.to_bus), idx.get_indexer(net.trafo.lv_bus)])
    gens0 = []
    for b, r in zip(idx.get_indexer(net.gen.bus), net.gen.itertuples()):
        pmax = getattr(r, "max_p_mw", np.nan)
        estimated = pmax is None or not np.isfinite(pmax) or pmax <= 0
        if estimated:
            pmax = max(2.0 * float(r.p_mw), 50.0)
        pmin = getattr(r, "min_p_mw", 0.0)
        pmin = 0.0 if pmin is None or not np.isfinite(pmin) else float(pmin)
        gens0.append({"bus": f"B{b + 1}", "p_mw": float(r.p_mw), "vm_pu": float(r.vm_pu),
                      "pmin": pmin, "pmax": float(pmax), "estimated": bool(estimated)})
    return {"fr": fr, "to": to, "short": short, "long": long, "n_lines": len(net.line),
            "is_trafo": [k >= len(net.line) for k in range(len(short))],
            "bus_names": [f"B{i + 1}" for i in range(len(net.bus))],
            "gen_buses": set(idx.get_indexer(net.gen.bus)) | set(idx.get_indexer(net.ext_grid.bus)),
            "gen_names": ["Slack (B1)"] + [f"G{i + 1} ({g['bus']})" for i, g in enumerate(gens0)],
            "gens0": gens0, "n_shunts": len(net.shunt),
            "shunt_names": [f"Shunt B{b + 1}" for b in idx.get_indexer(net.shunt.bus)],
            "load_buses": core.load_buses(net), "name": net.name or "IEEE 14-bus (case14)",
            "counts": (len(net.bus), len(net.line), len(net.trafo), len(net.gen) + len(net.ext_grid))}


def default_ui_params():
    p = core.default_params()
    info = network_info(json.dumps(p, sort_keys=True))
    p["gens"] = [{"in_service": True, "p_mw": g["p_mw"], "vm_pu": g["vm_pu"]} for g in info["gens0"]]
    p["shunts"] = [True] * info["n_shunts"]
    p.update(n1_active=True, n1_branch=0, n1_hour=-2, n1_ranking=True)
    return p


@st.cache_data(show_spinner="Solving 24 hourly power flows...")
def run_day(pj):
    p = json.loads(pj)
    nb, nbr = 14, 20
    res = {"conv": np.zeros(24, bool), "vm": np.full((24, nb), np.nan), "loading": np.full((24, nbr), np.nan),
           "p_from": np.full((24, nbr), np.nan), "load": np.zeros(24), "gen": np.full(24, np.nan),
           "losses": np.full(24, np.nan), "gen_units": np.full((24, 5), np.nan), "viol": np.zeros(24, bool),
           "qlim": np.zeros(24, int), "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    lb = None
    for h in range(24):
        net = core.build(p, h)
        lb = core.load_buses(net)
        res["load"][h] = float((net.load.p_mw * net.load.scaling).sum())
        ok = core.run_pf(net, p["enforce_q_limits"])
        res["conv"][h] = ok
        if not ok:
            res["viol"][h] = True
            continue
        d = core.extract(net, True)
        res["vm"][h], res["loading"][h], res["p_from"][h] = d["vm"], d["loading"], d["p_from"]
        units = [float(net.res_ext_grid.p_mw.sum())] + list(np.nan_to_num(net.res_gen.p_mw.to_numpy(float)))
        res["gen_units"][h, :len(units)] = units
        res["gen"][h] = float(np.sum(units))
        res["losses"][h] = d["losses"]
        res["qlim"][h] = len(d["gens_at_qlim"])
        vm = np.round(d["vm"][lb], VOLT_DECIMALS)
        res["viol"][h] = bool((vm < p["vmin"]).any() or (vm > p["vmax"]).any()
                              or (d["loading"] > p["normal_limit"]).any())
    res["load_buses"] = lb
    return res


@st.cache_data(show_spinner="Solving N-1 contingency...")
def run_ctg(pj, branch, hour):
    return core.run_contingency(json.loads(pj), branch, hour)


@st.cache_data(show_spinner="Sweeping all branches (N-1)...")
def run_sweep(pj, hour):
    return core.n1_sweep(json.loads(pj), hour)


# ======================================================================================
# Visual helpers
# ======================================================================================
def hour_txt(h):
    return f"{int(h):02d}:00"


def fmt(v, nd=1, unit=""):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}{unit}"


def loading_color(c, lim):
    if c is None or np.isnan(c):
        return COLOR["off"]
    r = c / lim
    return COLOR["critical"] if r >= 1 else COLOR["high"] if r >= 0.9 else COLOR["warn"] if r >= 0.7 else COLOR["ok"]


def pill(text, level):
    c = COLOR[level]
    return (f"<span style='background:{c}22;color:{c};border:1px solid {c};padding:2px 10px;"
            f"border-radius:12px;font-size:0.8rem;font-weight:600'>{text}</span>")


def banner(level, title, detail):
    c = COLOR[level]
    st.markdown(f"<div style='border-left:8px solid {c};background:{c}1A;padding:10px 16px;border-radius:4px'>"
                f"<b style='color:{c};font-size:1.1rem'>{title}</b>&nbsp;&nbsp;{detail}</div>",
                unsafe_allow_html=True)


def network_figure(info, d, P, lim, removed=None, height=400):
    """One-line diagram: branch colour/width = loading, arrow = active-power direction,
    bus colour = voltage within/outside limits, square = generator bus."""
    vm, ld, pf = d["vm"], d["loading"], d["p_from"]
    fig = go.Figure()
    mx, my, mt = [], [], []
    for k in range(len(info["fr"])):
        x0, y0 = POS14[int(info["fr"][k])]
        x1, y1 = POS14[int(info["to"][k])]
        mx.append((x0 + x1) / 2)
        my.append((y0 + y1) / 2)
        if removed is not None and k == removed:
            fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip",
                                     line=dict(color=COLOR["off"], width=2, dash="dash")))
            mt.append(f"{info['long'][k]}<br><b>REMOVED (N-1)</b>")
            continue
        c, p = ld[k], pf[k]
        col = loading_color(c, lim)
        width = 2 + 4 * min(max(0.0 if np.isnan(c) else c, 0.0), 100.0) / 100.0
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip",
                                 line=dict(color=col, width=width)))
        mt.append(f"{info['long'][k]}<br>Loading: {fmt(c, 0, '%')}<br>P: {fmt(p, 1, ' MW')}")
        if not np.isnan(p) and abs(p) > 1:
            n = np.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / n * np.sign(p), (y1 - y0) / n * np.sign(p)
            fig.add_annotation(x=mx[-1] + ux * 0.18, y=my[-1] + uy * 0.18, ax=mx[-1] - ux * 0.18,
                               ay=my[-1] - uy * 0.18, xref="x", yref="y", axref="x", ayref="y", text="",
                               showarrow=True, arrowhead=3, arrowsize=1.3, arrowwidth=1.6, arrowcolor=col)
    lines = [k for k in range(len(mx)) if not info["is_trafo"][k]]
    trafos = [k for k in range(len(mx)) if info["is_trafo"][k]]
    fig.add_trace(go.Scatter(x=[mx[k] for k in lines], y=[my[k] for k in lines], mode="markers",
                             marker=dict(size=14, opacity=0), hovertext=[mt[k] for k in lines], hoverinfo="text"))
    fig.add_trace(go.Scatter(x=[mx[k] for k in trafos], y=[my[k] for k in trafos], mode="markers",
                             marker=dict(size=11, symbol="diamond", color="#7A4EAB", line=dict(width=1.5, color="white")),
                             hovertext=[mt[k] for k in trafos], hoverinfo="text"))
    isl = set(int(i) for i in np.where(np.isnan(vm))[0])
    colors, symbols, hov = [], [], []
    for i, v in enumerate(vm):
        if i in isl:
            colors.append(COLOR["off"])
        elif i in info["load_buses"] and (v < P["vmin"] or v > P["vmax"]):
            colors.append(COLOR["critical"])
        else:
            colors.append(COLOR["bus"])
        symbols.append("square" if i in info["gen_buses"] else "circle")
        hov.append(f"{info['bus_names'][i]}<br>Voltage: " + ("de-energised (island)" if i in isl else f"{v:.3f} pu"))
    fig.add_trace(go.Scatter(x=[POS14[i][0] for i in range(len(vm))], y=[POS14[i][1] for i in range(len(vm))],
                             mode="markers+text", text=info["bus_names"], textposition="middle center",
                             textfont=dict(color="white", size=10), hovertext=hov, hoverinfo="text",
                             marker=dict(size=32, color=colors, symbol=symbols, line=dict(width=2, color="white"))))
    fig.update_layout(height=height, margin=dict(l=5, r=5, t=5, b=5), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


LEGEND = ("Square = generator bus · circle = load bus · red = load-bus voltage outside limits · "
          "branch colour and width = loading (green, yellow, orange, red) · arrow = active-power "
          "direction · purple diamond = transformer.")


def chart(fig):
    st.plotly_chart(fig, **WIDE)


def table(df):
    st.dataframe(df, hide_index=True, **WIDE)


def hour_axis(fig):
    fig.update_xaxes(tickmode="array", tickvals=list(range(0, 24, 3)), ticktext=[hour_txt(h) for h in range(0, 24, 3)])
    return fig


def go_to(screen):
    st.session_state["screen"] = screen


# ======================================================================================
# Panels
# ======================================================================================
def assess_hour(res, h, P):
    n_h = int(res["viol"].sum())
    if not res["conv"][h]:
        return "critical", "No solution", f"{hour_txt(h)} · the power flow has no solution."
    lb = res["load_buses"]
    vm, ld = np.round(res["vm"][h][lb], VOLT_DECIMALS), res["loading"][h]
    n_v = int(np.sum((vm < P["vmin"]) | (vm > P["vmax"])))
    n_l = int(np.sum(ld > P["normal_limit"]))
    summary = f"{hour_txt(h)} · {n_h} of 24 hours with violations"
    if n_v + n_l > 0:
        return "critical", "Critical", f"{n_l} overloaded branch(es), {n_v} load bus(es) outside the voltage range · {summary}"
    if np.nanmax(ld) > 0.8 * P["normal_limit"] or vm.min() < P["vmin"] + 0.01 or vm.max() > P["vmax"] - 0.01:
        return "warn", "Alert", f"Small margin to a limit · {summary}"
    q = f" · {res['qlim'][h]} generator(s) at reactive limit" if res["qlim"][h] else ""
    return "ok", "Normal", f"All limits respected{q} · {summary}"


def violations_table(info, r, P):
    a, d = r["before"], r["after"]
    rows = []
    for i in r["isolated"]:
        rows.append([info["bus_names"][i], "Island", f"{a['vm'][i]:.3f} pu", "de-energised", "—"])
    for k in np.where(d["loading"] > P["emergency_limit"])[0]:
        rows.append([info["long"][k], "Overload", fmt(a["loading"][k], 0, "%"), fmt(d["loading"][k], 0, "%"),
                     f"{P['emergency_limit']:.0f}%"])
    for i in info["load_buses"]:
        v = d["vm"][i]
        if np.isnan(v):
            continue
        if v < P["vmin"]:
            rows.append([info["bus_names"][i], "Undervoltage", f"{a['vm'][i]:.3f} pu", f"{v:.3f} pu", f"{P['vmin']:.2f} pu"])
        elif v > P["vmax"]:
            rows.append([info["bus_names"][i], "Overvoltage", f"{a['vm'][i]:.3f} pu", f"{v:.3f} pu", f"{P['vmax']:.2f} pu"])
    return pd.DataFrame(rows, columns=["Element", "Type", "Before", "After", "Limit"])


def day_block(info, res, hour, P, last=23):
    complete = last >= 23
    n_h = int(res["viol"][:last + 1].sum())
    if complete:
        badge = pill("no violations in 24 h", "ok") if n_h == 0 else pill(f"{n_h} h with violations", "critical")
    else:
        badge = pill(f"simulating... {last + 1}/24 h", "warn" if n_h else "off")
    st.markdown(f"#### 24-hour power flow &nbsp; {badge}", unsafe_allow_html=True)
    hours = list(range(last + 1))
    t1, t2, t3, t4 = st.tabs(["Network", "Load × generation", "Branch loading", "Voltages"])
    with t1:
        d = {"vm": res["vm"][hour], "loading": res["loading"][hour], "p_from": res["p_from"][hour]}
        st.caption(f"Network state at {hour_txt(hour)}.")
        chart(network_figure(info, d, P, P["normal_limit"]))
        st.caption(LEGEND)
        if res["conv"][hour]:
            topb = pd.DataFrame({"Branch": info["long"], "Loading (%)": d["loading"].round(1),
                                 "Flow (MW)": d["p_from"].round(1)}).sort_values("Loading (%)", ascending=False).head(5)
            st.markdown("**Most loaded branches at this hour**")
            table(topb)
    with t2:
        fig = go.Figure()
        for j, name in enumerate(info["gen_names"]):
            fig.add_trace(go.Scatter(x=hours, y=res["gen_units"][:last + 1, j], name=name, stackgroup="g",
                                     mode="lines", line=dict(width=0.5)))
        fig.add_trace(go.Scatter(x=hours, y=res["load"][:last + 1], name="Load", mode="lines",
                                 line=dict(color=COLOR["critical"], width=3, dash="dot")))
        fig.add_vline(x=hour, line_dash="dash", line_color=COLOR["off"])
        if not complete:
            fig.update_xaxes(range=[-0.5, 23.5])
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="MW",
                          legend=dict(orientation="h", y=-0.2))
        chart(hour_axis(fig))
        c1, c2 = st.columns(2)
        seen = res["load"][:last + 1]
        c1.metric("Peak hour" if complete else "Peak hour (so far)", hour_txt(int(np.argmax(seen))),
                  f"{np.max(seen):.0f} MW", delta_color="off")
        c2.metric("Energy losses in the day" if complete else "Energy losses (so far)",
                  f"{np.nansum(res['losses'][:last + 1]):.0f} MWh")
    with t3:
        lim = P["normal_limit"]
        scale = [[0, COLOR["ok"]], [0.5, COLOR["ok"]], [0.62, COLOR["warn"]], [0.75, COLOR["high"]],
                 [0.83, COLOR["critical"]], [1, "#7B1010"]]
        fig = go.Figure(go.Heatmap(z=res["loading"][:last + 1].T, x=hours, y=info["long"], zmin=0, zmax=1.2 * lim,
                                   colorscale=scale, colorbar=dict(title="%"),
                                   hovertemplate="%{y}<br>%{x}h: %{z:.0f}%<extra></extra>"))
        fig.add_vline(x=hour, line_dash="dash", line_color="white")
        if not complete:
            fig.update_xaxes(range=[-0.5, 23.5])
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
        chart(hour_axis(fig))
        st.caption("Loading in % of the provisional rating (see Network parameters). "
                   "By construction, the intact network reaches the rating target at the peak hour.")
    with t4:
        lb = res["load_buses"]
        v = res["vm"][:last + 1][:, lb]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hours, y=np.nanmax(v, axis=1), name="Maximum (load buses)", mode="lines+markers"))
        fig.add_trace(go.Scatter(x=hours, y=np.nanmin(v, axis=1), name="Minimum (load buses)", mode="lines+markers"))
        fig.add_hline(y=P["vmax"], line_dash="dash", line_color=COLOR["critical"])
        fig.add_hline(y=P["vmin"], line_dash="dash", line_color=COLOR["critical"])
        fig.add_vline(x=hour, line_dash="dash", line_color=COLOR["off"])
        if not complete:
            fig.update_xaxes(range=[-0.5, 23.5])
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="pu",
                          legend=dict(orientation="h", y=-0.2))
        chart(hour_axis(fig))
        st.caption("Load (PQ) buses only. Generator buses hold their set-point voltage, and bus 7 is the "
                   "fictitious star point of a three-winding transformer.")
    st.button("Network parameters", key="b_net", on_click=go_to, args=("params_net",))


def n1_block(info, res, hour, peak, pj, P):
    if not P["n1_active"]:
        st.markdown(f"#### N-1 contingency &nbsp; {pill('off', 'off')}", unsafe_allow_html=True)
        st.info("The N-1 contingency is switched off. Turn it on and choose the branch in N-1 parameters.")
        st.button("N-1 parameters", key="b_n1", on_click=go_to, args=("params_n1",))
        return
    code = P["n1_hour"]
    h = hour if code == -2 else peak if code == -1 else int(code)
    k = int(P["n1_branch"])
    r = run_ctg(pj, k, h)
    d = r["after"]
    if not r["ok"]:
        level, verdict = "critical", "no power-flow solution"
        tab = None
    else:
        tab = violations_table(info, r, P)
        if len(tab) > 0:
            level, verdict = "critical", f"NOT secure · {len(tab)} violation(s)"
        elif np.nanmax(d["loading"]) > 0.9 * P["emergency_limit"]:
            level, verdict = "warn", "secure, small margin"
        else:
            level, verdict = "ok", "N-1 secure"
    st.markdown(f"#### N-1 contingency &nbsp; {pill(verdict, level)}", unsafe_allow_html=True)
    st.caption(f"Removed branch: {info['long'][k]} · analysed hour: {hour_txt(h)}")
    names = ["Network", "Violations", "Before × after"] + (["Ranking"] if P["n1_ranking"] else [])
    tabs = st.tabs(names)
    with tabs[0]:
        if not r["ok"]:
            st.error("No power-flow solution with this branch removed. With generator reactive limits "
                     "enforced, this usually means the operating point is beyond the loadability limit "
                     "of the weakened network (voltage collapse). Try reducing the load factor.")
        else:
            chart(network_figure(info, d, P, P["emergency_limit"], removed=k))
            st.caption(LEGEND + " Dashed branch = removed.")
            if r["isolated"]:
                st.warning(f"Island: {len(r['isolated'])} bus(es) de-energised, {r['lost_load_mw']:.1f} MW of load lost.")
            if d["gens_at_qlim"]:
                st.info(f"{len(d['gens_at_qlim'])} generator(s) at a reactive-power limit (PV bus switched to PQ).")
    with tabs[1]:
        if not r["ok"]:
            st.error("No solution: the case is classified as insecure.")
        elif len(tab) == 0:
            st.success("No voltage or loading violation with this branch removed.")
        else:
            table(tab)
    with tabs[2]:
        a = r["before"]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=info["short"], y=a["loading"], name="Before", marker_color=COLOR["off"], hovertext=info["long"]))
        fig.add_trace(go.Bar(x=info["short"], y=d["loading"], name="After", marker_color=COLOR["bus"], hovertext=info["long"]))
        fig.add_hline(y=P["emergency_limit"], line_dash="dash", line_color=COLOR["critical"], annotation_text="emergency limit")
        fig.update_layout(barmode="group", height=380, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="Loading (%)", legend=dict(orientation="h", y=-0.2))
        chart(fig)
        if r["ok"]:
            lb = info["load_buses"]
            c1, c2 = st.columns(2)
            c1.metric("Max. loading after", fmt(np.nanmax(d["loading"]), 0, "%"),
                      fmt(np.nanmax(d["loading"]) - np.nanmax(a["loading"]), 0, " p.p."), delta_color="inverse")
            c2.metric("Min. load-bus voltage after", fmt(np.nanmin(d["vm"][lb]), 3, " pu"),
                      fmt(np.nanmin(d["vm"][lb]) - np.nanmin(a["vm"][lb]), 3), delta_color="normal")
    if P["n1_ranking"]:
        with tabs[3]:
            rk = run_sweep(pj, h)
            score = np.where(~rk.solved, 100.0, np.where(rk.lost_load_mw > 0, 50.0, rk.J.fillna(0)))
            fig = go.Figure(go.Bar(x=score, y=rk.branch, orientation="h",
                                   marker_color=[COLOR["critical"] if not s else COLOR["high"] if j > 0 else COLOR["ok"]
                                                 for s, j in zip(rk.solved, rk.J.fillna(0))]))
            fig.update_layout(height=460, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"),
                              xaxis_title="Ranking score (100 = no solution; otherwise index J)")
            chart(fig)
            st.caption("Ranking order: (1) no power-flow solution, (2) load lost by islanding, "
                       "(3) index J = overload above the emergency limit (per 100 %) + 10 × load-bus voltage excursion (pu).")
            show = rk[["rank", "branch", "solved", "isolated_buses", "lost_load_mw", "overloads",
                       "max_loading_pct", "vmin_load_bus", "gens_at_qlim", "J"]].copy()
            show.columns = ["Rank", "Branch removed", "Solved", "Isolated buses", "Lost load (MW)", "Overloads",
                            "Max. loading (%)", "Min. load-bus V (pu)", "Gens at Q limit", "J"]
            table(show.round(3))
    st.button("N-1 parameters", key="b_n1", on_click=go_to, args=("params_n1",))


def advance_hour():
    h = min(st.session_state.get("hour_max", 0) + 1, 23)
    st.session_state["hour_max"] = h
    st.session_state["hour"] = h


def restart_sim():
    st.session_state.update(hour_mode="sim", hour_max=0, hour=0)


def finish_sim():
    st.session_state["hour_mode"] = "free"


def hour_control():
    """'sim' mode reveals the hours one at a time (as if hourly data were arriving);
    after 24 h, 'free' mode allows any hour to be revisited with a slider."""
    if "hour_mode" not in st.session_state:
        st.session_state.update(hour_mode="sim", hour_max=0, hour=0)
    c_title, c_ctrl = st.columns([3, 2], gap="large")
    c_title.markdown("## IEEE 14-bus operation panel")
    if st.session_state["hour_mode"] == "sim":
        hmax = st.session_state["hour_max"]
        with c_ctrl:
            st.caption(f"Step-through mode: one hour at a time ({hmax + 1} of 24)")
            st.progress((hmax + 1) / 24)
            b1, b2 = st.columns(2)
            b1.button("↺ Restart", on_click=restart_sim, **WIDE)
            if hmax < 23:
                b2.button("▶ Next hour", on_click=advance_hour, type="primary", **WIDE)
            else:
                b2.button("✓ Explore all 24 h", on_click=finish_sim, type="primary", **WIDE)
        return st.session_state["hour"]
    with c_ctrl:
        hour = st.slider("Analysed hour", 0, 23, key="hour", format="%d h")
        st.button("↺ Restart step-through", on_click=restart_sim)
    return hour


def restore_dispatch(info):
    P = st.session_state["P"]
    for i, g in enumerate(info["gens0"]):
        P["gens"][i]["p_mw"] = g["p_mw"]
        P["gens"][i]["vm_pu"] = g["vm_pu"]
    P["shunts"] = [True] * info["n_shunts"]
    st.session_state.pop("lab_before", None)


def lab_block(info, P, hour, res, level, title):
    """Corrective-action laboratory: active-power redispatch within generator limits and
    shunt-capacitor switching, with a before/after comparison at the selected hour."""
    with st.expander("🔧 Laboratory: corrective actions", expanded=level in ("warn", "critical")):
        st.caption("Try classical operating actions (generation redispatch and capacitor switching) "
                   "and compare the effect before and after at the selected hour.")
        with st.form("form_lab"):
            new_p = []
            for i, g in enumerate(info["gens0"]):
                mark = " *" if g["estimated"] else ""
                new_p.append(st.slider(f"{info['gen_names'][i + 1]}: active power (MW){mark}", float(g["pmin"]),
                                       float(g["pmax"]), float(P["gens"][i]["p_mw"]), step=1.0, key=f"lab_gen_{i}"))
            new_sh = [st.checkbox(f"{name} in service", value=bool(P["shunts"][i]), key=f"lab_sh_{i}")
                      for i, name in enumerate(info["shunt_names"])]
            if any(g["estimated"] for g in info["gens0"]):
                st.caption("* Estimated limit (2 × original dispatch, minimum 50 MW): the case has no official Pmax "
                           "for this generator.")
            apply = st.form_submit_button("▶ Apply action and compare", type="primary")
        if apply:
            st.session_state["lab_before"] = {"hour": hour, "vm": res["vm"][hour].copy(),
                                              "loading": res["loading"][hour].copy(), "losses": res["losses"][hour],
                                              "level": level, "title": title}
            for i, p in enumerate(new_p):
                P["gens"][i]["p_mw"] = p
            P["shunts"] = new_sh
            st.rerun()
        before = st.session_state.get("lab_before")
        if before and before["hour"] == hour:
            st.markdown("---")
            st.markdown(f"**Effect of the action at {hour_txt(hour)}**")
            lvl, ttl, _ = assess_hour(res, hour, P)
            c1, c2 = st.columns(2)
            c1.markdown(f"Before: {pill(before['title'], before['level'])}", unsafe_allow_html=True)
            c2.markdown(f"After: {pill(ttl, lvl)}", unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=info["short"], y=before["loading"], name="Before", marker_color=COLOR["off"]))
            fig.add_trace(go.Bar(x=info["short"], y=res["loading"][hour], name="After", marker_color=COLOR["bus"]))
            fig.add_hline(y=P["normal_limit"], line_dash="dash", line_color=COLOR["critical"], annotation_text="loading limit")
            fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="Loading (%)", legend=dict(orientation="h", y=-0.2))
            chart(fig)
            lb = info["load_buses"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Min. load-bus V", fmt(np.nanmin(res["vm"][hour][lb]), 3, " pu"),
                      fmt(np.nanmin(res["vm"][hour][lb]) - np.nanmin(before["vm"][lb]), 3), delta_color="normal")
            m2.metric("Max. loading", fmt(np.nanmax(res["loading"][hour]), 0, "%"),
                      fmt(np.nanmax(res["loading"][hour]) - np.nanmax(before["loading"]), 0, " p.p."), delta_color="inverse")
            m3.metric("Losses", fmt(res["losses"][hour], 1, " MW"), fmt(res["losses"][hour] - before["losses"], 1, " MW"),
                      delta_color="inverse")
            st.button("Clear comparison", on_click=lambda: st.session_state.pop("lab_before", None))
        st.button("↺ Restore original dispatch", on_click=restore_dispatch, args=(info,))


def dashboard():
    P = st.session_state["P"]
    pj = json.dumps(P, sort_keys=True)
    info = network_info(json.dumps({k: P[k] for k in ("rating_target", "rating_floor", "profile", "enforce_q_limits")}
                                   | {"global_factor": 1.0}, sort_keys=True))
    res = run_day(pj)
    peak = int(np.argmax(res["load"]))
    hour = hour_control()
    level, title, detail = assess_hour(res, hour, P)
    banner(level, f"STATUS: {title}", detail)
    st.write("")
    m = st.columns(6)
    if res["conv"][hour]:
        lb = res["load_buses"]
        vm, ld = res["vm"][hour], res["loading"][hour]
        ib, ix, il = lb[int(np.nanargmin(vm[lb]))], lb[int(np.nanargmax(vm[lb]))], int(np.nanargmax(ld))
        m[0].metric("Load", f"{res['load'][hour]:.0f} MW")
        m[1].metric("Generation", f"{res['gen'][hour]:.0f} MW")
        m[2].metric(f"Losses ({100 * res['losses'][hour] / res['gen'][hour]:.1f}%)", f"{res['losses'][hour]:.1f} MW")
        m[3].metric(f"Min. load-bus V ({info['bus_names'][ib]})", f"{vm[ib]:.3f} pu")
        m[4].metric(f"Max. load-bus V ({info['bus_names'][ix]})", f"{vm[ix]:.3f} pu")
        m[5].metric(f"Max. loading ({info['short'][il]})", f"{np.nanmax(ld):.0f}%")
    else:
        for c, name in zip(m, ["Load", "Generation", "Losses", "Min. V", "Max. V", "Max. loading"]):
            c.metric(name, "—")
    st.write("")
    lab_block(info, P, hour, res, level, title)
    st.write("")
    last = st.session_state.get("hour_max", 23) if st.session_state.get("hour_mode") == "sim" else 23
    c_day, c_n1 = st.columns(2, gap="large")
    with c_day:
        day_block(info, res, hour, P, last=last)
    with c_n1:
        n1_block(info, res, hour, peak, pj, P)
    with st.sidebar:
        st.markdown("**Network**")
        nb, nl, nt, ng = info["counts"]
        st.caption(f"{info['name']}\n\n{nb} buses · {nl} lines · {nt} transformers · {ng} generators")
        st.caption("Generator reactive limits: " + ("enforced" if P["enforce_q_limits"] else "IGNORED"))
        st.caption(f"Last run: {res['run_at']}")
        st.button("Recompute all", on_click=st.cache_data.clear)


def restore_defaults():
    st.session_state["P"] = default_ui_params()
    for k in list(st.session_state.keys()):
        if k.startswith("f_") or k in ("ed_profile", "ed_gens", "lab_before"):
            st.session_state.pop(k, None)


def params_net_screen():
    P = st.session_state["P"]
    info = network_info(json.dumps({k: P[k] for k in ("rating_target", "rating_floor", "profile", "enforce_q_limits")}
                                   | {"global_factor": 1.0}, sort_keys=True))
    st.button("← Back to panel", on_click=go_to, args=("panel",))
    st.markdown("## Network parameters")
    st.caption("Changes take effect when applied; the panel is then recomputed.")
    with st.form("form_net"):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            fac = st.slider("Global load factor", 0.5, 1.5, float(P["global_factor"]), 0.05, key="f_fac")
            vmin = st.number_input("Minimum voltage (pu)", 0.80, 1.00, float(P["vmin"]), 0.01, format="%.2f", key="f_vmin")
            vmax = st.number_input("Maximum voltage (pu)", 1.00, 1.20, float(P["vmax"]), 0.01, format="%.2f", key="f_vmax")
            lim = st.slider("Branch loading limit, intact network (%)", 50, 150, int(P["normal_limit"]), 5, key="f_lim")
            tgt = st.slider("Provisional rating: intact loading at the peak hour (%)", 30, 90,
                            int(round(100 * P["rating_target"])), 5, key="f_tgt")
            qlim = st.checkbox("Enforce generator reactive-power limits", value=bool(P["enforce_q_limits"]), key="f_qlim")
        with c2:
            st.markdown("**Hourly load profile** (multiplies the global factor)")
            prof = st.data_editor(pd.DataFrame({"Hour": [hour_txt(h) for h in range(24)], "Factor": P["profile"]}),
                                  hide_index=True, disabled=["Hour"], num_rows="fixed", height=300, key="ed_profile",
                                  column_config={"Factor": st.column_config.NumberColumn(min_value=0.1, max_value=2.0,
                                                                                         step=0.01, format="%.3f")})
        st.markdown("**Generators**")
        gens = st.data_editor(pd.DataFrame({"Bus": [g["bus"] for g in info["gens0"]],
                                            "In service": [g["in_service"] for g in P["gens"]],
                                            "P (MW)": [g["p_mw"] for g in P["gens"]],
                                            "V (pu)": [g["vm_pu"] for g in P["gens"]]}),
                              hide_index=True, disabled=["Bus"], num_rows="fixed", key="ed_gens",
                              column_config={"P (MW)": st.column_config.NumberColumn(min_value=0.0, step=1.0, format="%.1f"),
                                             "V (pu)": st.column_config.NumberColumn(min_value=0.9, max_value=1.15,
                                                                                     step=0.005, format="%.3f")})
        b1, b2, _ = st.columns([1, 1, 3])
        apply = b1.form_submit_button("Apply and return", type="primary")
        b2.form_submit_button("Restore defaults", on_click=restore_defaults)
    if apply:
        P.update(global_factor=float(fac), vmin=float(vmin), vmax=float(vmax), normal_limit=float(lim),
                 rating_target=tgt / 100.0, enforce_q_limits=bool(qlim))
        P["profile"] = [float(x) for x in prof["Factor"].fillna(1.0)]
        P["gens"] = [{"in_service": bool(r["In service"]), "p_mw": float(r["P (MW)"]), "vm_pu": float(r["V (pu)"])}
                     for _, r in gens.iterrows()]
        go_to("panel")
        st.rerun()


def params_n1_screen():
    P = st.session_state["P"]
    info = network_info(json.dumps({k: P[k] for k in ("rating_target", "rating_floor", "profile", "enforce_q_limits")}
                                   | {"global_factor": 1.0}, sort_keys=True))
    st.button("← Back to panel", on_click=go_to, args=("panel",))
    st.markdown("## N-1 contingency parameters")
    st.caption("Changes take effect when applied; the panel is then recomputed.")
    hours = [-2, -1] + list(range(24))
    with st.form("form_n1"):
        active = st.checkbox("Use N-1 contingency", value=bool(P["n1_active"]), key="f_n1_active")
        branch = st.selectbox("Branch to remove (line or transformer)", list(range(len(info["long"]))),
                              index=int(P["n1_branch"]), format_func=lambda k: info["long"][k], key="f_n1_branch")
        hour = st.selectbox("Analysed hour", hours, index=hours.index(P["n1_hour"]),
                            format_func=lambda v: {-2: "Same hour as the panel", -1: "Peak hour"}.get(v, hour_txt(v)),
                            key="f_n1_hour")
        lim = st.slider("Branch emergency limit (%)", 100, 150, int(P["emergency_limit"]), 5, key="f_n1_lim")
        rank = st.checkbox("Also compute the ranking of all branches (slower)", value=bool(P["n1_ranking"]), key="f_n1_rank")
        b1, b2, _ = st.columns([1, 1, 3])
        apply = b1.form_submit_button("Apply and return", type="primary")
        b2.form_submit_button("Restore defaults", on_click=restore_defaults)
    if apply:
        P.update(n1_active=bool(active), n1_branch=int(branch), n1_hour=int(hour),
                 emergency_limit=float(lim), n1_ranking=bool(rank))
        go_to("panel")
        st.rerun()


def main():
    if "P" not in st.session_state:
        st.session_state["P"] = default_ui_params()
    if "screen" not in st.session_state:
        st.session_state["screen"] = "panel"
    screen = st.session_state["screen"]
    if screen == "params_net":
        params_net_screen()
    elif screen == "params_n1":
        params_n1_screen()
    else:
        dashboard()


main()
