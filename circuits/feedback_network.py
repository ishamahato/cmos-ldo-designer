"""Resistive feedback divider:  Vout = Vref * (1 + R1/R2).

For Vout = 1.2 V and Vref = 0.6 V the ratio is R1/R2 = 1.  The absolute value
sets the divider current Vout/(R1+R2); 120 k + 120 k gives 5 uA, small compared
with the 1 mA minimum load; 120 kohm is practical in SKY130 high-sheet poly.
R_SCALE factors implement Monte Carlo mismatch.
"""
from __future__ import annotations

from .components import Component
from .design_params import LDODesign


def resistor_ratio(vout: float, vref: float) -> float:
    if vout <= vref:
        raise ValueError("Vout must exceed Vref for a resistive divider")
    return vout / vref - 1.0


def build(d: LDODesign) -> list[Component]:
    blk = "Feedback network"
    return [
        Component("R1", "R", ("vout", "fb"), f"{d.r1 * d.r_scale[0]:.6e}", blk,
                  "Upper feedback resistor"),
        Component("R2", "R", ("fb", "0"), f"{d.r2 * d.r_scale[1]:.6e}", blk,
                  "Lower feedback resistor"),
    ]
