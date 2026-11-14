"""Simulation-in-the-loop design optimisation.

Every candidate is evaluated with real ngspice runs over the corners of the
operating range (Vin = 1.8/3.3 V, Iload = 1/50 mA).  The cost is a weighted
sum of normalised objectives plus hard-constraint penalties.  The search uses
SciPy differential evolution with integer handling for finger counts.
Every evaluation is written to the SQLite experiment store.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import differential_evolution

from analysis.experiment_store import log_experiment
from analysis.power_analysis import efficiency_pct
from circuits.design_params import SPEC, DeviceSize, LDODesign, OperatingPoint
from spice import ac_analysis, dc_analysis, transient_analysis
from spice.ngspice_runner import SimulationError

log = logging.getLogger(__name__)

# name, lower, upper, integer?
VARIABLES = [
    ("pass_m", 120, 300, True),     # pass-device fingers (20/0.5 um each)
    ("pair_m", 1, 6, True),         # input-pair fingers (20/1 um)
    ("tail_m", 1, 6, True),         # tail source fingers -> EA bias current
    ("iref_ua", 1.0, 10.0, False),  # reference current
    ("rc", 0.1, 1.0, False),        # series compensation resistance (ohm)
    ("cff_pf", 0.0, 50.0, False),   # feed-forward capacitor
    ("rtot_k", 60.0, 600.0, False), # R1 + R2 (ratio fixed at 1)
]

WEIGHTS = {"pm": 2.0, "dropout": 1.5, "loadreg": 1.0, "iq": 1.0, "undershoot": 1.0, "accuracy": 2.0,
           "area": 0.3}


def apply_vector(base: LDODesign, x: np.ndarray, name: str = "candidate") -> LDODesign:
    v = {n: (int(round(val)) if integer else float(val)) for (n, _, _, integer), val in zip(VARIABLES, x)}
    return base.copy(
        name=name,
        pass_dev=DeviceSize(base.pass_dev.w, base.pass_dev.l, v["pass_m"]),
        pair=DeviceSize(base.pair.w, base.pair.l, v["pair_m"]),
        tail=DeviceSize(base.tail.w, base.tail.l, v["tail_m"]),
        iref=v["iref_ua"] * 1e-6, rc=v["rc"], cff=v["cff_pf"] * 1e-12,
        r1=v["rtot_k"] * 500.0, r2=v["rtot_k"] * 500.0,
    )


def design_vector(d: LDODesign) -> np.ndarray:
    return np.array([d.pass_dev.m, d.pair.m, d.tail.m, d.iref * 1e6, d.rc, d.cff * 1e12,
                     (d.r1 + d.r2) / 1e3], dtype=float)


def evaluate(d: LDODesign, corner: str = "tt", temp: float = 27.0, with_transient: bool = True) -> dict:
    """All optimisation metrics for one design (real simulations)."""
    m: dict[str, float] = {}
    errs = []
    for vin in (SPEC["vin_min"], SPEC["vin_max"]):
        for il in (SPEC["iload_min"], SPEC["iload_max"]):
            op = OperatingPoint(vin, il, temp, corner)
            s = dc_analysis.operating_point(d, op, load="current")["summary"]
            errs.append(s["vout_error_pct"])
            lg = ac_analysis.loop_gain(d, op)
            key = f"{vin:g}V_{il * 1e3:g}mA"
            m[f"pm_{key}"] = lg["phase_margin_deg"]
            m[f"gm_{key}"] = lg["gain_margin_db"]
            m[f"ugf_{key}"] = lg["ugf_hz"]
            m[f"vout_{key}"] = s["vout"]
    pms = [v for k, v in m.items() if k.startswith("pm_")]
    gms = [v for k, v in m.items() if k.startswith("gm_")]
    m["pm_min"] = float(min(pms)) if all(math.isfinite(p) for p in pms) else -90.0
    m["gm_min"] = float(min(gms)) if all(math.isfinite(g) or g == math.inf for g in gms) else 0.0
    m["vout_err_max_pct"] = float(max(abs(e) for e in errs))
    mid = OperatingPoint(2.5, SPEC["iload_min"], temp, corner)
    s1 = dc_analysis.operating_point(d, mid, load="current")["summary"]
    s2 = dc_analysis.operating_point(d, OperatingPoint(2.5, SPEC["iload_max"], temp, corner), load="current")["summary"]
    m["load_reg_mv_per_ma"] = (s2["vout"] - s1["vout"]) / ((SPEC["iload_max"] - SPEC["iload_min"]) * 1e3) * 1e3
    s0 = dc_analysis.operating_point(d, OperatingPoint(SPEC["vin_max"], 0.0, temp, corner), load="current")["summary"]
    m["iq_ua"] = s0["iin"] * 1e6
    m["eff_1ma_1v8_pct"] = float(efficiency_pct(1.8, 1e-3 + s0["iin"], 1.2, 1e-3))
    do = dc_analysis.dropout(d, OperatingPoint(2.5, SPEC["iload_max"], temp, corner))
    m["dropout_v"] = do["dropout_v"]
    # worst PVT case for the pass device (slow PMOS, cold) - see transistor_sizing
    dw = dc_analysis.dropout(d, OperatingPoint(2.5, SPEC["iload_max"], -40.0, "sf"))
    m["dropout_worst_v"] = dw["dropout_v"]
    if with_transient and m["pm_min"] >= 30.0:  # oscillating candidates are rejected by cost anyway
        tr = transient_analysis.load_step(d, OperatingPoint(2.5, SPEC["iload_min"], temp, corner))
        m["undershoot_mv"] = tr["undershoot_mv"]
        m["overshoot_mv"] = tr["overshoot_mv"]
        m["settling_up_us"] = tr["settling_up_us"]
    m["pass_w_mm"] = d.pass_dev.w_total / 1e3
    return m


def cost(m: dict) -> float:
    c = 0.0
    c += WEIGHTS["pm"] * max(0.0, 60.0 - m["pm_min"]) / 10.0
    dvals = [m["dropout_v"], m.get("dropout_worst_v", m["dropout_v"])]
    dmax = math.nan if any(not math.isfinite(v) for v in dvals) else max(dvals)
    c += WEIGHTS["dropout"] * (dmax if math.isfinite(dmax) else 1.0) / 0.5
    c += WEIGHTS["loadreg"] * abs(m["load_reg_mv_per_ma"]) / 0.2
    c += WEIGHTS["iq"] * m["iq_ua"] / 40.0
    c += WEIGHTS["undershoot"] * m.get("undershoot_mv", 30.0) / 30.0
    c += WEIGHTS["accuracy"] * m["vout_err_max_pct"] / 1.0
    c += WEIGHTS["area"] * m["pass_w_mm"] / 3.4
    # hard constraints
    if m["pm_min"] < 45:
        c += 20 + (45 - m["pm_min"])
    if m["gm_min"] < 10:
        c += 20
    if not math.isfinite(dmax) or dmax > 0.6:   # must regulate at Vin = 1.8 V in the worst corner
        c += 10
    if m["vout_err_max_pct"] > 2.0:
        c += 10 * m["vout_err_max_pct"]
    return float(c)


@dataclass
class _Objective:
    base: LDODesign
    tag: str

    def __call__(self, x: np.ndarray) -> float:
        d = apply_vector(self.base, x)
        try:
            m = evaluate(d)
            c = cost(m)
            log_experiment("optimizer", d.to_dict(), {**m, "cost": c}, {"corner": "tt", "temp": 27}, tag=self.tag)
            return c
        except (SimulationError, ValueError, KeyError, IndexError) as exc:
            log_experiment("optimizer", d.to_dict(), None, status="failed", message=str(exc), tag=self.tag)
            return 1e3


def optimise(base: LDODesign, maxiter: int = 6, popsize: int = 4, seed: int = 7, workers: int = 1,
             tag: str | None = None) -> dict:
    tag = tag or time.strftime("opt_%Y%m%d_%H%M%S")
    bounds = [(lo, hi) for _, lo, hi, _ in VARIABLES]
    integrality = [integer for *_, integer in VARIABLES]
    x0 = design_vector(base)
    obj = _Objective(base, tag)
    # workers > 1 only helps on machines with real spare cores (on shared cloud vCPUs
    # parallel ngspice runs were measured ~10x slower each)
    res = differential_evolution(obj, bounds, integrality=integrality, maxiter=maxiter, popsize=popsize,
                                 seed=seed, workers=workers if workers > 1 else 1, updating="deferred", polish=False,
                                 init="sobol", x0=x0, tol=1e-3)
    best = apply_vector(base, res.x, name="optimized")
    return {"design": best, "cost": float(res.fun), "nfev": int(res.nfev), "x": res.x.tolist(), "tag": tag}
