"""Frequency compensation: output-pole dominant with a series-R zero.

Loop poles/zeros (see README for derivation):
  p_out  = 1 / (2 pi (Rout) Cout),   Rout = ro_pass || R_L || (R1+R2)   (dominant)
  p_gate = 1 / (2 pi Ro_EA C_gate)   (EA output / pass-gate node)
  z_rc   = 1 / (2 pi Rc Cout)        (series resistance / ESR zero)
  z_ff   = 1 / (2 pi R1 Cff), p_ff = 1 / (2 pi (R1||R2) Cff)  (feed-forward pair)
z_rc is placed below the unity-gain frequency so it cancels p_gate's phase lag.

Elements: COUT (1 uF), RC (series resistor/ESR), CFF (across R1).
"""
from __future__ import annotations

import math

from .components import Component
from .design_params import LDODesign


def build(d: LDODesign) -> list[Component]:
    blk = "Compensation"
    comps = [
        Component("COUT", "C", ("vout", "co"), f"{d.cout:.6e}", blk, "Output capacitor"),
        Component("RC", "R", ("co", "0"), f"{max(d.rc, 1e-6):.6e}", blk,
                  "Series compensation resistance / ESR (creates LHP zero)"),
    ]
    if d.cff > 0:
        comps.append(Component("CFF", "C", ("vout", "fb"), f"{d.cff:.6e}", blk,
                               "Feed-forward capacitor across R1 (zero/pole pair)"))
    return comps


def analytic_poles_zeros(d: LDODesign, ro_pass: float, r_load: float,
                         ro_ea: float, c_gate: float) -> dict[str, float]:
    """Hand-analysis estimates (Hz) using simulated small-signal parameters."""
    rout = 1.0 / (1.0 / ro_pass + 1.0 / r_load + 1.0 / (d.r1 + d.r2))
    out = {
        "p_out_hz": 1.0 / (2 * math.pi * rout * d.cout),
        "p_gate_hz": 1.0 / (2 * math.pi * ro_ea * c_gate),
        "z_rc_hz": 1.0 / (2 * math.pi * d.rc * d.cout) if d.rc > 0 else math.inf,
    }
    if d.cff > 0:
        out["z_ff_hz"] = 1.0 / (2 * math.pi * d.r1 * d.cff)
        out["p_ff_hz"] = 1.0 / (2 * math.pi * (d.r1 * d.r2 / (d.r1 + d.r2)) * d.cff)
    return out
