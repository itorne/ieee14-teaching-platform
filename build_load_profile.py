"""
Rebuilds data/load_profile_north_ons_2026.csv from the raw ONS file.

Raw data: ONS open data, dataset "Curva de Carga Horaria" (CC-BY),
https://dados.ons.org.br/dataset/curva-carga, yearly file CURVA_CARGA_2026.csv (separator ';').
Expected columns: id_subsistema, nom_subsistema, din_instante, val_cargaenergiahomwmed.

Usage:
    python build_load_profile.py CURVA_CARGA_2026.csv [--start 2026-01-01] [--end 2026-09-29]

Procedure: keep the North subsystem (id_subsistema == "N"), keep complete days in the
interval, average the hourly load for each hour of the day, and divide by the mean of the
10:00 and 11:00 averages. The script prints the 24 factors and checks them against
core.LOAD_PROFILE.
"""

import argparse
from pathlib import Path

import pandas as pd

import core


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_csv")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-09-29")
    a = ap.parse_args()
    raw = pd.read_csv(a.raw_csv, sep=";")
    raw = raw[raw.id_subsistema.astype(str).str.upper() == "N"].copy()
    raw["t"] = pd.to_datetime(raw.din_instante)
    raw = raw[(raw.t >= a.start) & (raw.t < pd.Timestamp(a.end) + pd.Timedelta(days=1))]
    raw["day"] = raw.t.dt.date
    full = raw.groupby("day").t.count()
    raw = raw[raw.day.isin(full[full == 24].index)]
    g = raw.groupby(raw.t.dt.hour).val_cargaenergiahomwmed
    out = pd.DataFrame({"hour": range(24), "mean_mw": g.mean().round(2).values,
                        "std_mw": g.std().round(2).values, "n_days": g.count().values})
    ref = (out.mean_mw[10] + out.mean_mw[11]) / 2
    out["factor"] = (out.mean_mw / ref).round(3)
    path = Path(__file__).parent / "data" / "load_profile_north_ons_2026.csv"
    out.to_csv(path, index=False)
    print(out.to_string(index=False))
    print("Days used:", out.n_days.max(), "| identical to core.LOAD_PROFILE:", list(out.factor) == core.LOAD_PROFILE)


if __name__ == "__main__":
    main()
