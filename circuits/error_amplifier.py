"""Error amplifier: PMOS-input symmetrical (current-mirror) OTA.

Why this topology
-----------------
The 0.6 V reference is below the ~0.75 V threshold of the SKY130 5 V NMOS, so
the input pair must be PMOS.  A plain 5-transistor PMOS OTA was simulated first
and *failed*: its output cannot rise above roughly Vref + |Vgs| ~ 1.65 V, so at
Vin = 3.3 V it cannot turn the pass device off and Vout rose to 1.6-2.5 V.  The
symmetrical OTA mirrors the pair currents to an output branch (MN6/MP9) that
swings from ~0.1 V to Vin - 0.15 V, which is what a PMOS pass gate needs.

Devices
-------
MP5      tail current source (mirrors MPB1)
MP1/MP2  PMOS input pair; bulks tied to the tail node to remove body effect.
         MP1 gate = VREF (inverting input), MP2 gate = FB (non-inverting input)
MN3/MN4  diode-connected NMOS loads
MN6      mirrors MN4 current, pulls the output (pass gate) down
MN7      mirrors MN3 current into the PMOS mirror MP8
MP8/MP9  PMOS mirror; MP9 pushes the output up
Small-signal gain  A = B * gm1 * (ro6 || ro9), B = mirror ratio.
"""
from __future__ import annotations

from .components import Component
from .design_params import LDODesign


def build(d: LDODesign, fb_node: str = "fb") -> list[Component]:
    blk = "Error amplifier"
    return [
        Component("MP5", "pmos", ("tail", "pb", "vin", "vin"), d.tail, blk,
                  "Tail current source of the differential pair"),
        Component("MP1", "pmos", ("d1", "vref", "tail", "tail"), d.pair, blk,
                  "Input transistor, inverting input (VREF)"),
        Component("MP2", "pmos", ("d2", fb_node, "tail", "tail"), d.pair, blk,
                  "Input transistor, non-inverting input (feedback FB)"),
        Component("MN3", "nmos", ("d1", "d1", "0", "0"), d.nload, blk,
                  "Diode load of MP1"),
        Component("MN4", "nmos", ("d2", "d2", "0", "0"), d.nload, blk,
                  "Diode load of MP2"),
        Component("MN6", "nmos", ("gate", "d2", "0", "0"), d.nmirror, blk,
                  "Output pull-down: mirrors MP2 current (xB)"),
        Component("MN7", "nmos", ("x", "d1", "0", "0"), d.nmirror, blk,
                  "Mirrors MP1 current (xB) into PMOS mirror"),
        Component("MP8", "pmos", ("x", "x", "vin", "vin"), d.pmirror, blk,
                  "PMOS mirror diode"),
        Component("MP9", "pmos", ("gate", "x", "vin", "vin"), d.pmirror, blk,
                  "Output pull-up: mirrors MP8 current; drives pass gate"),
    ]
