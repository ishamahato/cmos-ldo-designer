"""Loop stability across load current, compensation resistance and output capacitance."""
from __future__ import annotations

import numpy as np
import pandas as pd

from circuits.compensation import analytic_poles_zeros
from circuits.design_params import LDODesign, OperatingPoint
from spice import ac_analysis, dc_analysis
from spice.ngspice_runner import SimulationError


def _lg_row(d: LDODesign, op: OperatingPoint, **tags) -> dict:
    try:
        lg = ac_analysis.loop_gain(d, op)
        return {**tags, "vin": op.vin, "iload": op.iload, "pm_deg": lg["phase_margin_deg"],
                "gm_db": lg["gain_margin_db"], "ugf_hz": lg["ugf_hz"], "dc_gain_db": lg["dc_gain_db"],
                "dominant_pole_hz": lg["dominant_pole_hz"], "stable": lg["stable"]}
    except SimulationError as exc:
        return {**tags, "vin": op.vin, "iload": op.iload, "error": str(exc)[:200]}


def pm_vs_load(d: LDODesign, vins=(1.8, 2.5, 3.3), loads=None) -> pd.DataFrame:
    loads = loads if loads is not None else np.logspace(np.log10(0.1e-3), np.log10(60e-3), 14)
    return pd.DataFrame([_lg_row(d, OperatingPoint(v, float(i))) for v in vins for i in loads])


def pm_vs_rc(d: LDODesign, rcs=None, loads=(1e-3, 50e-3), vin: float = 3.3) -> pd.DataFrame:
    rcs = rcs if rcs is not None else np.array([0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0])
    return pd.DataFrame([_lg_row(d.copy(rc=float(r)), OperatingPoint(vin, i), rc=float(r)) for r in rcs for i in loads])


def pm_vs_cout(d: LDODesign, couts=(0.47e-6, 1e-6, 2.2e-6, 4.7e-6), loads=(1e-3, 50e-3), vin: float = 3.3) -> pd.DataFrame:
    return pd.DataFrame([_lg_row(d.copy(cout=c), OperatingPoint(vin, i), cout_uf=c * 1e6) for c in couts for i in loads])


def pole_zero_estimates(d: LDODesign, op: OperatingPoint) -> dict:
    """Hand-analysis poles/zeros from simulated small-signal parameters at ``op``."""
    r = dc_analysis.operating_point(d, op, load="resistor")
    dev = r["devices"].set_index("ref")
    ro_pass = 1.0 / dev.loc["MPASS", "gds_s"]
    ro_ea = 1.0 / (dev.loc["MN6", "gds_s"] + dev.loc["MP9", "gds_s"])
    # gate-node capacitance approximated by the pass device Cgg (dominant contributor;
    # the Miller multiplication of Cgd is not included, so p_gate is an upper estimate)
    c_gate = dev.loc["MPASS", "cgg_f"]
    r_load = d.vout_ideal / op.iload if op.iload > 0 else 1e12
    est = analytic_poles_zeros(d, ro_pass, r_load, ro_ea, c_gate)
    est.update({"ro_pass_ohm": ro_pass, "ro_ea_ohm": ro_ea, "c_gate_f": c_gate,
                "gm_pass_s": float(dev.loc["MPASS", "gm_s"]), "vin": op.vin, "iload": op.iload})
    return est
