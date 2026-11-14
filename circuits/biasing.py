"""Voltage reference and bias-current generation.

Block functions
---------------
* VREF  - 0.6 V reference.  Modelled as an ideal source (a SKY130 bandgap needs
          the parasitic PNP models, which are outside this minimal model set).
          Its statistical error is included in the Monte Carlo study.
* IREF  - reference current (default 5 uA) standing in for a bandgap/beta-
          multiplier output.  Everything downstream is transistor-level.
* MNB1  - NMOS diode converting IREF into the bias voltage NB.
* MNB2  - NMOS mirror (1:1) sinking IREF from the PMOS diode.
* MPB1  - PMOS diode generating PB, the gate bias of the error-amp tail source.
"""
from __future__ import annotations

from .components import Component
from .design_params import LDODesign


def build(d: LDODesign) -> list[Component]:
    blk = "Bias & reference"
    return [
        Component("VREF", "V", ("vref", "0"), f"DC {d.vref:g}", blk,
                  "0.6 V reference voltage (ideal, see limitations)"),
        Component("IREF", "I", ("vin", "nb"), f"DC {d.iref:.6e}", blk,
                  "Reference bias current (ideal, stands in for bandgap current)"),
        Component("MNB1", "nmos", ("nb", "nb", "0", "0"), d.mnb, blk,
                  "Diode-connected NMOS: converts IREF to bias voltage NB"),
        Component("MNB2", "nmos", ("pb", "nb", "0", "0"), d.mnb, blk,
                  "NMOS mirror: copies IREF into the PMOS bias diode"),
        Component("MPB1", "pmos", ("pb", "pb", "vin", "vin"), d.mpb, blk,
                  "Diode-connected PMOS: generates tail bias voltage PB"),
    ]
