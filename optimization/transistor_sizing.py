"""Hand-calculation style sizing, backed by single-device SKY130 simulations.

Rather than assuming textbook k' values, the per-finger characteristics are
extracted from the PDK models, then used in the standard equations.
"""
from __future__ import annotations

import math

import pandas as pd

from circuits.design_params import (CORNERS, PMOS_MODEL, SPEC, LDODesign)
from spice.netlist_generator import PDK_REL
from spice.ngspice_runner import run_netlist


def pass_finger_current(vsg: float, vsd: float, corner: str = "tt", temp: float = 27.0,
                        w: float = 20.0, l: float = 0.5) -> float:
    """Drain current of ONE pass-device finger at the given bias (simulated)."""
    net = "\n".join([
        "* pass finger characterisation", f'.lib "{PDK_REL}" {corner}', f".temp {temp:g}",
        f"VS s 0 {SPEC['vin_min']:g}", f"VG g 0 {SPEC['vin_min'] - vsg:g}",
        f"VD d 0 {SPEC['vin_min'] - vsd:g}",
        f"XP d g s s {PMOS_MODEL} w={w:g} l={l:g} m=1",
        ".control", "op", "print i(vs)", ".endc", ".end"])
    return abs(run_netlist(net).values["i(vs)"])


def pass_device_sizing(i_target: float = SPEC["iload_max"], vsd: float = 0.5, vgate_min: float = 0.15,
                       margin: float = 1.2) -> pd.DataFrame:
    """Fingers needed so the pass device carries ``margin * i_target`` at Vin = 1.8 V with
    Vsd = ``vsd`` (dropout budget) and gate at ``vgate_min`` (EA low-swing limit), per PVT."""
    vsg = SPEC["vin_min"] - vgate_min
    rows = []
    for c in CORNERS:
        for t in (-40.0, 27.0, 125.0):
            i1 = pass_finger_current(vsg, vsd, c, t)
            rows.append({"corner": c, "temp": t, "i_finger_ma": i1 * 1e3,
                         "fingers_required": math.ceil(margin * i_target / i1),
                         "ron_ohm_per_finger": vsd / i1})
    return pd.DataFrame(rows)


def feedback_resistors(vout: float = SPEC["vout_nom"], vref: float = SPEC["vref"],
                       i_div: float = 5e-6) -> dict[str, float]:
    """R1/R2 = Vout/Vref - 1 ; R1 + R2 = Vout / I_div."""
    ratio = vout / vref - 1.0
    rtot = vout / i_div
    r2 = rtot / (1 + ratio)
    return {"ratio_r1_r2": ratio, "r_total": rtot, "r1": rtot - r2, "r2": r2, "i_div": i_div}


def ea_hand_calc(d: LDODesign, gm1: float, gds6: float, gds9: float) -> dict[str, float]:
    """Symmetrical OTA:  A = B * gm1 / (gds6 + gds9)."""
    a = d.mirror_ratio * gm1 / (gds6 + gds9)
    return {"B": d.mirror_ratio, "gm1_s": gm1, "rout_ohm": 1 / (gds6 + gds9),
            "gain_vv": a, "gain_db": 20 * math.log10(a)}


def sizing_report(d: LDODesign) -> dict:
    return {"pass": pass_device_sizing(), "feedback": feedback_resistors(d.vout_ideal, d.vref,
                                                                           d.vout_ideal / (d.r1 + d.r2))}
