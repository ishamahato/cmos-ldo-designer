"""PMOS pass transistor.

A PMOS (rather than NMOS) pass device is used because its gate can be pulled
to ground, giving |Vgs| ~ Vin at low headroom, i.e. a low dropout without a
charge pump.  The device is built from ``m`` parallel 20 um / 0.5 um fingers;
0.5 um is the minimum length of the 5 V device (lowest Ron per area).
"""
from __future__ import annotations

from .components import Component
from .design_params import LDODesign


def build(d: LDODesign) -> list[Component]:
    return [Component("MPASS", "pmos", ("vout", "gate", "vin", "vin"), d.pass_dev,
                      "Pass device", "PMOS pass transistor delivering load current")]


def ron_estimate(kp_per_finger: float, vsg: float, vth: float, m: int) -> float:
    """Deep-triode on-resistance  Ron = 1 / (m * k' * (Vsg - |Vth|))."""
    vov = max(vsg - vth, 1e-6)
    return 1.0 / (m * kp_per_finger * vov)
