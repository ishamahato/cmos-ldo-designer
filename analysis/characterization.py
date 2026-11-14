"""Full characterisation of one design: every DC, AC and transient measurement.

Results are written to ``results/<design.name>/`` as CSV (waveforms), JSON
(metrics) and PNG (plots).  Every number comes from an ngspice run performed
here; nothing is filled in by hand.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import power_analysis as pw
from analysis.experiment_store import log_experiment
from circuits.design_params import PROJECT_ROOT, SPEC, LDODesign, OperatingPoint
from circuits.ldo_topology import component_table
from spice import ac_analysis, dc_analysis, transient_analysis
from spice.netlist_generator import full_netlist_for_display
from verification import stability_analysis

log = logging.getLogger(__name__)
RESULTS = PROJECT_ROOT / "results"


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not isinstance(v, pd.DataFrame)}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def characterise(d: LDODesign, out_dir: Path | None = None, corner: str = "tt", temp: float = 27.0) -> dict:
    out = out_dir or RESULTS / d.name
    out.mkdir(parents=True, exist_ok=True)
    m: dict = {"design": d.name, "corner": corner, "temp": temp}
    log.info("[%s] operating points", d.name)

    # ---- A. DC operating points (resistive load = spec "load resistance")
    ops = []
    for vin in (1.8, 2.5, 3.3):
        for il in (1e-3, 10e-3, 50e-3):
            r = dc_analysis.operating_point(d, OperatingPoint(vin, il, temp, corner))
            ops.append(r["summary"])
            if vin == 2.5 and il == 10e-3:
                r["devices"].to_csv(out / "device_operating_points.csv", index=False)
                m["op_nominal"] = r["summary"]
                m["op_nodes"] = r["nodes"]
    pd.DataFrame(ops).to_csv(out / "operating_points.csv", index=False)

    # ---- error amplifier stand-alone
    ea = dc_analysis.error_amp_characterisation(d, OperatingPoint(2.5, 0.0, temp, corner))
    for k in ("transfer", "cm_sweep", "ac"):
        ea[k].to_csv(out / f"ea_{k}.csv", index=False)
    m["error_amp"] = {k: v for k, v in ea.items() if not isinstance(v, pd.DataFrame)}

    # ---- B. DC sweeps
    log.info("[%s] DC sweeps", d.name)
    line = {}
    for il in (1e-3, 50e-3):
        lr = dc_analysis.line_regulation(d, OperatingPoint(2.5, il, temp, corner))
        lr["data"].to_csv(out / f"line_sweep_{il * 1e3:g}mA.csv", index=False)
        line[f"{il * 1e3:g}mA"] = lr["line_reg_mv_per_v"]
    m["line_reg_mv_per_v"] = line
    load = {}
    eff_frames = []
    for vin in (1.8, 2.5, 3.3):
        ld = dc_analysis.load_regulation(d, OperatingPoint(vin, 10e-3, temp, corner))
        ld["data"].to_csv(out / f"load_sweep_{vin:g}V.csv", index=False)
        load[f"{vin:g}V"] = ld["load_reg_mv_per_ma"]
        eff_frames.append(ld["data"].assign(vin_set=vin))
        m.setdefault("iq_ua", {})[f"{vin:g}V"] = ld["iq_a"] * 1e6
    m["load_reg_mv_per_ma"] = load
    eff = pd.concat(eff_frames)
    eff["efficiency_bound_pct"] = pw.efficiency_bound_pct(eff.vin, eff.vout)
    eff.to_csv(out / "efficiency_vs_load.csv", index=False)
    pick = lambda v, i: float(np.interp(i, eff[eff.vin_set == v].iload, eff[eff.vin_set == v].efficiency_pct))
    m["efficiency_pct"] = {f"{v:g}V_{i * 1e3:g}mA": pick(v, i) for v in (1.8, 3.3) for i in (1e-3, 50e-3)}
    iqv = dc_analysis.sweep(d, OperatingPoint(2.5, 0.0, temp, corner), "vin", 1.0, 3.6, 0.02)
    iqv.to_csv(out / "iq_vs_vin.csv", index=False)

    do = {}
    for il in (1e-3, 10e-3, 50e-3):
        r = dc_analysis.dropout(d, OperatingPoint(2.5, il, temp, corner), iload=il)
        r["data"].to_csv(out / f"dropout_sweep_{il * 1e3:g}mA.csv", index=False)
        do[f"{il * 1e3:g}mA"] = r["dropout_v"]
    m["dropout_v"] = do
    mx = dc_analysis.max_load(d, OperatingPoint(1.8, 1e-3, temp, corner))
    mx["data"].to_csv(out / "max_load_1v8.csv", index=False)
    m["max_load_ma_at_1v8"] = mx["imax_a"] * 1e3
    mx3 = dc_analysis.max_load(d, OperatingPoint(3.3, 1e-3, temp, corner))
    m["max_load_ma_at_3v3"] = mx3["imax_a"] * 1e3

    # ---- C. AC
    log.info("[%s] AC", d.name)
    loops = {}
    for vin in (1.8, 2.5, 3.3):
        for il in (1e-3, 10e-3, 50e-3):
            lg = ac_analysis.loop_gain(d, OperatingPoint(vin, il, temp, corner))
            lg["data"].to_csv(out / f"loop_{vin:g}V_{il * 1e3:g}mA.csv", index=False)
            loops[f"{vin:g}V_{il * 1e3:g}mA"] = {k: v for k, v in lg.items() if k != "data"}
    m["loop"] = loops
    m["pm_min_deg"] = min(v["phase_margin_deg"] for v in loops.values())
    m["gm_min_db"] = min(v["gain_margin_db"] for v in loops.values())
    cl = ac_analysis.closed_loop(d, OperatingPoint(2.5, 10e-3, temp, corner))
    cl["data"].to_csv(out / "closed_loop.csv", index=False)
    m["closed_loop"] = {k: v for k, v in cl.items() if k != "data"}
    m["poles_zeros"] = {f"{il * 1e3:g}mA": stability_analysis.pole_zero_estimates(d, OperatingPoint(2.5, il, temp, corner))
                        for il in (1e-3, 50e-3)}
    stability_analysis.pm_vs_load(d).to_csv(out / "pm_vs_load.csv", index=False)
    stability_analysis.pm_vs_rc(d).to_csv(out / "pm_vs_rc.csv", index=False)
    stability_analysis.pm_vs_cout(d).to_csv(out / "pm_vs_cout.csv", index=False)

    # ---- D. Transients
    log.info("[%s] transients", d.name)
    tl = transient_analysis.load_step(d, OperatingPoint(2.5, 1e-3, temp, corner))
    tl["data"].to_csv(out / "tran_load_2v5.csv", index=False)
    m["load_transient"] = {k: v for k, v in tl.items() if k != "data"}
    tl18 = transient_analysis.load_step(d, OperatingPoint(1.8, 1e-3, temp, corner))
    tl18["data"].to_csv(out / "tran_load_1v8.csv", index=False)
    m["load_transient_1v8"] = {k: v for k, v in tl18.items() if k != "data"}
    tn = transient_analysis.line_step(d, OperatingPoint(2.5, 10e-3, temp, corner), 1.8, 3.3)
    tn["data"].to_csv(out / "tran_line.csv", index=False)
    m["line_transient"] = {k: v for k, v in tn.items() if k != "data"}

    # ---- bookkeeping
    m["design_params"] = d.to_dict()
    (out / "design.json").write_text(d.to_json())
    (out / "netlist.cir").write_text(full_netlist_for_display(d))
    component_table(d).to_csv(out / "components.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(_jsonable(m), indent=2))
    log_experiment("characterization", d.to_dict(), _jsonable({k: v for k, v in m.items() if k != "design_params"}),
                   {"corner": corner, "temp": temp}, tag=d.name)
    return m


def load_metrics(name: str) -> dict:
    return json.loads((RESULTS / name / "metrics.json").read_text())
