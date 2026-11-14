"""Top-level CMOS LDO assembly.

    VIN --+------------+-----------------+
          |            |                 |
        [bias]   [error amp (sym OTA)]  MPASS (PMOS)
          |      -: VREF   +: FB         |
          |            |  gate ---------+ g
          |            |                 |
          |            |               VOUT --+-- R1 --+-- FB --R2-- GND
          |            |                 |    +-CFF----+
          |            |               COUT
          |            |                 |
          |            |                RC
GND ------+------------+-----------------+

Negative feedback: Vout up -> FB up -> MP2 current down -> MN6 pulls less ->
gate rises -> MPASS conducts less -> Vout down.
"""
from __future__ import annotations

import pandas as pd

from . import biasing, compensation, error_amplifier, feedback_network, pass_transistor
from .components import Component
from .design_params import LDODesign

BLOCK_DESCRIPTIONS = {
    "Bias & reference": "0.6 V reference and bias-current generation with NMOS/PMOS current mirrors.",
    "Error amplifier": "PMOS-input symmetrical OTA comparing FB with VREF and driving the pass gate rail-to-rail.",
    "Pass device": "Large PMOS transistor that sources the load current from VIN to VOUT.",
    "Feedback network": "Resistor divider returning Vout/2 to the error amplifier.",
    "Compensation": "Output capacitor with series resistance (zero) and feed-forward capacitor.",
}


def build_ldo(d: LDODesign, loop_break: bool = False) -> list[Component]:
    """Return all regulator components.  With ``loop_break`` the EA input is node
    ``fbin`` instead of ``fb`` so a test bench can open the loop for AC."""
    d.validate()
    fb_in = "fbin" if loop_break else "fb"
    comps: list[Component] = []
    comps += biasing.build(d)
    comps += error_amplifier.build(d, fb_node=fb_in)
    comps += pass_transistor.build(d)
    comps += feedback_network.build(d)
    comps += compensation.build(d)
    refs = [c.ref for c in comps]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate component reference designators")
    return comps


def component_table(d: LDODesign) -> pd.DataFrame:
    return pd.DataFrame([c.describe() for c in build_ldo(d)])


def mos_refs(d: LDODesign) -> list[Component]:
    return [c for c in build_ldo(d) if c.is_mos]
