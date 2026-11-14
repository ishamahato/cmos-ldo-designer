"""Monte Carlo mismatch analysis (EDUCATIONAL statistics).

The SKY130 g5v0d10v5 model cards expose mismatch only through global
``*_slope_spectre`` switches (their per-device vth0 slope is 0), which ngspice
cannot vary per instance.  We therefore apply *assumed* statistics:

* Threshold mismatch: Pelgrom  sigma(Vth) = A_VT / sqrt(W_total * L),
  A_VT = 8 mV*um (typical for ~12 nm gate oxide; NOT foundry data),
  applied as an independent gate-offset source on every transistor.
* Feedback resistors: sigma(R)/R = 0.25 % each (matched poly, assumed).
* Reference voltage: sigma = 0.5 % (untrimmed reference, assumed).
* Reference current: sigma = 5 % (assumed).

Global process spread is covered separately by the PDK corners (PVT step).
These numbers are NOT foundry-qualified statistics.
"""
from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from analysis.experiment_store import log_experiment
from circuits.design_params import LIMITS, SPEC, LDODesign, OperatingPoint
from circuits.ldo_topology import build_ldo
from spice import ac_analysis, dc_analysis
from spice.ngspice_runner import SimulationError

ASSUMPTIONS = {"A_VT_mV_um": 8.0, "sigma_R_pct": 0.25, "sigma_vref_pct": 0.5, "sigma_iref_pct": 5.0}


def sample_design(d: LDODesign, rng: np.random.Generator, a=ASSUMPTIONS) -> LDODesign:
    vos = {}
    for c in build_ldo(d):
        if c.is_mos:
            s = c.value
            sigma = a["A_VT_mV_um"] * 1e-3 / math.sqrt(s.w_total * s.l)
            vos[c.ref] = float(rng.normal(0.0, sigma))
    return d.copy(
        name=f"{d.name}_mc", mismatch_vos=vos,
        r_scale=(1 + rng.normal(0, a["sigma_R_pct"] / 100), 1 + rng.normal(0, a["sigma_R_pct"] / 100)),
        vref=d.vref * (1 + rng.normal(0, a["sigma_vref_pct"] / 100)),
        iref=d.iref * (1 + rng.normal(0, a["sigma_iref_pct"] / 100)),
    )


def _run_one(args) -> dict:
    i, d, d_nom_vref = args
    row = {"sample": i, "vref": d.vref, "iref_ua": d.iref * 1e6, "r1_scale": d.r_scale[0],
           "r2_scale": d.r_scale[1], **{f"vos_{k}": v * 1e3 for k, v in d.mismatch_vos.items()}}
    try:
        r = dc_analysis.operating_point(d, OperatingPoint(2.5, 10e-3), load="current")
        s = r["summary"]
        dev = r["devices"].set_index("ref")
        lg_light = ac_analysis.loop_gain(d, OperatingPoint(3.3, SPEC["iload_min"]))
        lg_heavy = ac_analysis.loop_gain(d, OperatingPoint(1.8, SPEC["iload_max"]))
        row.update(vout=s["vout"], vout_err_pct=s["vout_error_pct"], ignd_ua=s["ignd"] * 1e6,
                   i_tail_ua=float(dev.loc["MP5", "id_a"]) * 1e6,
                   ea_offset_mv=(s["vfb"] - d.vref) * 1e3,   # input-referred EA error in closed loop
                   pm_light_deg=lg_light["phase_margin_deg"], pm_heavy_deg=lg_heavy["phase_margin_deg"],
                   status="ok")
    except SimulationError as exc:
        row["status"] = f"failed: {exc}"[:200]
    return row


def run_monte_carlo(d: LDODesign, n: int = 200, seed: int = 2026, workers: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    samples = [(i, sample_design(d, rng), d.vref) for i in range(n)]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            df = pd.DataFrame(list(ex.map(_run_one, samples)))
    else:
        df = pd.DataFrame([_run_one(s) for s in samples])
    ok = df[df.status == "ok"].copy()
    ok["pm_min_deg"] = ok[["pm_light_deg", "pm_heavy_deg"]].min(axis=1)
    ok["pass"] = (ok.vout_err_pct.abs() <= LIMITS["vout_accuracy_pct"]) & (ok.pm_min_deg >= LIMITS["phase_margin_min_deg"])
    yld = float(ok["pass"].mean()) if len(ok) else float("nan")
    # 95 % Wilson interval for the yield estimate
    k, m = int(ok["pass"].sum()), len(ok)
    z = 1.96
    centre = (k + z * z / 2) / (m + z * z) if m else float("nan")
    half = z * math.sqrt(k * (m - k) / m + z * z / 4) / (m + z * z) if m else float("nan")
    summary = {
        "n_samples": n, "n_ok": m, "seed": seed, "assumptions": ASSUMPTIONS,
        "vout_mean": float(ok.vout.mean()), "vout_sigma_mv": float(ok.vout.std() * 1e3),
        "vout_min": float(ok.vout.min()), "vout_max": float(ok.vout.max()),
        "ea_offset_sigma_mv": float(ok.ea_offset_mv.std()), "ea_offset_mean_mv": float(ok.ea_offset_mv.mean()),
        "i_tail_mean_ua": float(ok.i_tail_ua.mean()), "i_tail_sigma_ua": float(ok.i_tail_ua.std()),
        "ignd_mean_ua": float(ok.ignd_ua.mean()), "ignd_sigma_ua": float(ok.ignd_ua.std()),
        "pm_min_deg": float(ok.pm_min_deg.min()), "pm_mean_deg": float(ok.pm_min_deg.mean()),
        "yield_pct": yld * 100, "yield_ci95_pct": [max(0, (centre - half) * 100), min(100, (centre + half) * 100)],
        "yield_criteria": f"|Vout err| <= {LIMITS['vout_accuracy_pct']} % at 2.5 V/10 mA and PM >= {LIMITS['phase_margin_min_deg']} deg",
    }
    log_experiment("montecarlo", d.to_dict(), summary, {"n": n, "seed": seed}, tag=d.name)
    return {"samples": df, "summary": summary}
