"""Process-voltage-temperature verification using the real SKY130 corners.

Corners tt/ff/ss/fs/sf come from the PDK model files (first letter = NMOS,
second = PMOS).  Resistor/capacitor corners are not included (ideal R/C).
"""
from __future__ import annotations

import itertools
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from analysis.experiment_store import log_experiment
from circuits.design_params import CORNERS, SPEC, LDODesign, OperatingPoint
from spice import ac_analysis, dc_analysis
from spice.ngspice_runner import SimulationError

TEMPS = (-40.0, 27.0, 85.0, 125.0)
VINS = (1.8, 2.5, 3.3)
LOADS = (1e-3, 50e-3)


def _one(args) -> dict:
    d, corner, temp, vin, il = args
    op = OperatingPoint(vin, il, temp, corner)
    row = {"corner": corner, "temp": temp, "vin": vin, "iload": il}
    try:
        s = dc_analysis.operating_point(d, op, load="current")["summary"]
        lg = ac_analysis.loop_gain(d, op)
        row.update(vout=s["vout"], vout_err_pct=s["vout_error_pct"], ignd_ua=s["ignd"] * 1e6,
                   efficiency_pct=s["efficiency_pct"], pm_deg=lg["phase_margin_deg"],
                   gm_db=lg["gain_margin_db"], ugf_hz=lg["ugf_hz"], loop_dc_gain_db=lg["dc_gain_db"],
                   stable=lg["stable"], status="ok")
    except SimulationError as exc:
        row.update(status=f"failed: {exc}"[:300])
    return row


def _iq(args) -> dict:
    d, corner, temp = args
    s = dc_analysis.operating_point(d, OperatingPoint(SPEC["vin_max"], 0.0, temp, corner), load="current")["summary"]
    do = dc_analysis.dropout(d, OperatingPoint(2.5, SPEC["iload_max"], temp, corner))
    return {"corner": corner, "temp": temp, "iq_ua": s["iin"] * 1e6, "vout_noload": s["vout"],
            "dropout_v": do["dropout_v"]}


def run_pvt(d: LDODesign, workers: int = 1, corners=CORNERS, temps=TEMPS, vins=VINS, loads=LOADS) -> dict:
    jobs = [(d, c, t, v, i) for c, t, v, i in itertools.product(corners, temps, vins, loads)]
    iq_jobs = [(d, c, t) for c, t in itertools.product(corners, temps)]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            grid = pd.DataFrame(list(ex.map(_one, jobs)))
            iq = pd.DataFrame(list(ex.map(_iq, iq_jobs)))
    else:
        grid = pd.DataFrame([_one(j) for j in jobs])
        iq = pd.DataFrame([_iq(j) for j in iq_jobs])
    ok = grid[grid.status == "ok"]
    summary = {
        "n_conditions": len(grid), "n_failed_sims": int((grid.status != "ok").sum()),
        "vout_min": float(ok.vout.min()), "vout_max": float(ok.vout.max()),
        "vout_err_max_pct": float(ok.vout_err_pct.abs().max()),
        "pm_min_deg": float(ok.pm_deg.min()), "gm_min_db": float(ok.gm_db.min()),
        "all_stable": bool(ok.stable.all()),
        "iq_max_ua": float(iq.iq_ua.max()), "dropout_max_v": float(iq.dropout_v.max()),
    }
    worst = ok.loc[ok.vout_err_pct.abs().idxmax()]
    summary["worst_accuracy_condition"] = f"{worst.corner} {worst.temp:g}C Vin={worst.vin:g} I={worst.iload * 1e3:g}mA"
    wpm = ok.loc[ok.pm_deg.idxmin()]
    summary["worst_pm_condition"] = f"{wpm.corner} {wpm.temp:g}C Vin={wpm.vin:g} I={wpm.iload * 1e3:g}mA"
    log_experiment("pvt", d.to_dict(), summary, {"corners": list(corners), "temps": list(temps)}, tag=d.name)
    return {"grid": grid, "iq_dropout": iq, "summary": summary}
