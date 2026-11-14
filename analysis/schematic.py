"""Transistor-level schematic drawn with schemdraw from the live design values.

Wires are drawn for the main signal path; nets that would cross the drawing
(VREF, FB, D1/D2 mirror gates, PB) are joined by name labels, as in a normal
hierarchical schematic.  Every label/size comes from ``LDODesign``.
"""
from __future__ import annotations

from pathlib import Path

import schemdraw
import schemdraw.elements as elm

from circuits.design_params import LDODesign

TOP, BOT = 10.0, 0.0
NET = "#2a78d6"


def _sz(s) -> str:
    return f"{s.w:g}/{s.l:g}" + (f" x{s.m}" if s.m > 1 else "")


def _mos(d, kind, x, y_src, ref, size, gate_left=True, diode=False):
    """Place a MOS with its source at (x, y_src). PMOS: source on top; NMOS: source at bottom."""
    if kind == "p":
        e = elm.PFet(bulk=True)
    else:
        e = elm.NFet(bulk=True)
    e = e.theta(0)
    if gate_left:
        e = e.reverse()
    e = d.add(e.anchor("source").at((x, y_src)))
    side = "right" if gate_left else "left"
    d.add(elm.Label().at((x + (0.35 if gate_left else -0.35), (e.source.y + e.drain.y) / 2))
          .label(f"{ref}\n{size}", loc=side, fontsize=8, halign="left" if gate_left else "right"))
    if diode:  # gate tied to drain
        d.add(elm.Line().at(e.gate).to((e.gate.x, e.drain.y)))
        d.add(elm.Line().at((e.gate.x, e.drain.y)).to(e.drain))
        d.add(elm.Dot().at(e.drain))
    # body tie to source drawn as label-free short connection
    d.add(elm.Line().at(e.bulk).to((x, e.bulk.y)))
    return e


def _tag(d, at, name, loc="left"):
    d.add(elm.Dot(radius=0.06).at(at))
    d.add(elm.Label().at(at).label(name, loc=loc, fontsize=8.5, color=NET))


def draw(ldo: LDODesign, path: Path) -> Path:
    with schemdraw.Drawing(show=False) as d:
        d.config(fontsize=9, unit=1.6, lw=1.1)
        # rails
        d.add(elm.Line().at((-1.5, TOP)).to((25.5, TOP)))
        d.add(elm.Label().at((-1.5, TOP)).label("VIN (1.8-3.3 V)", loc="left", fontsize=10))
        d.add(elm.Line().at((-1.5, BOT)).to((25.5, BOT)))
        d.add(elm.Label().at((-1.5, BOT)).label("GND", loc="left", fontsize=10))

        # ---------------- bias network
        d.add(elm.SourceI().at((0, TOP)).down().to((0, 4.0)).label(f"IREF\n{ldo.iref * 1e6:g} uA", loc="bottom", fontsize=8))
        mnb1 = _mos(d, "n", 0, BOT, "MNB1", _sz(ldo.mnb), gate_left=False, diode=True)
        d.add(elm.Line().at((0, 4.0)).to(mnb1.drain))
        d.add(elm.Line().at(mnb1.gate).to((2.2, mnb1.gate.y)))
        mnb2 = _mos(d, "n", 3.0, BOT, "MNB2", _sz(ldo.mnb), gate_left=True)
        d.add(elm.Line().at((2.2, mnb1.gate.y)).to(mnb2.gate))
        _tag(d, (1.6, mnb1.gate.y), "NB", loc="top")
        mpb1 = _mos(d, "p", 3.0, TOP, "MPB1", _sz(ldo.mpb), gate_left=False, diode=True)
        d.add(elm.Line().at(mpb1.drain).to(mnb2.drain))
        _tag(d, mpb1.gate, "PB", loc="right")

        # ---------------- error amplifier
        mp5 = _mos(d, "p", 7.5, TOP, "MP5", _sz(ldo.tail), gate_left=True)
        _tag(d, mp5.gate, "PB")
        y_tail = 7.2
        d.add(elm.Line().at(mp5.drain).to((7.5, y_tail)))
        d.add(elm.Line().at((6.0, y_tail)).to((9.0, y_tail)))
        _tag(d, (7.5, y_tail), "TAIL", loc="right")
        mp1 = _mos(d, "p", 6.0, y_tail, "MP1", _sz(ldo.pair), gate_left=True)
        mp2 = _mos(d, "p", 9.0, y_tail, "MP2", _sz(ldo.pair), gate_left=False)
        _tag(d, mp1.gate, "VREF (0.6 V)")
        _tag(d, mp2.gate, "FB", loc="right")
        mn3 = _mos(d, "n", 6.0, BOT, "MN3", _sz(ldo.nload), gate_left=False, diode=True)
        mn4 = _mos(d, "n", 9.0, BOT, "MN4", _sz(ldo.nload), gate_left=True, diode=True)
        d.add(elm.Line().at(mp1.drain).to(mn3.drain))
        d.add(elm.Line().at(mp2.drain).to(mn4.drain))
        _tag(d, mn3.drain, "D1", loc="left")
        _tag(d, mn4.drain, "D2", loc="right")

        mp8 = _mos(d, "p", 12.5, TOP, "MP8", _sz(ldo.pmirror), gate_left=False, diode=True)
        mn7 = _mos(d, "n", 12.5, BOT, "MN7", _sz(ldo.nmirror), gate_left=True)
        d.add(elm.Line().at(mp8.drain).to(mn7.drain))
        _tag(d, mn7.gate, "D1")
        d.add(elm.Line().at(mp8.gate).to((15.0, mp8.gate.y)))
        mp9 = _mos(d, "p", 16.0, TOP, "MP9", _sz(ldo.pmirror), gate_left=True)
        d.add(elm.Line().at((15.0, mp8.gate.y)).to(mp9.gate))
        _tag(d, (14.0, mp8.gate.y), "X", loc="top")
        mn6 = _mos(d, "n", 16.0, BOT, "MN6", _sz(ldo.nmirror), gate_left=True)
        _tag(d, mn6.gate, "D2")
        d.add(elm.Line().at(mp9.drain).to(mn6.drain))
        y_gate = 5.0
        d.add(elm.Line().at((16.0, y_gate)).to((18.0, y_gate)))
        _tag(d, (16.0, y_gate), "GATE", loc="top")

        # ---------------- pass device + output network
        mpass = _mos(d, "p", 19.5, TOP, "MPASS", _sz(ldo.pass_dev), gate_left=True)
        d.add(elm.Line().at((18.0, y_gate)).to((18.0, mpass.gate.y)))
        d.add(elm.Line().at((18.0, mpass.gate.y)).to(mpass.gate))
        y_out = 6.4
        d.add(elm.Line().at(mpass.drain).to((19.5, y_out)))
        d.add(elm.Line().at((19.5, y_out)).to((25.5, y_out)))
        _tag(d, (25.5, y_out), "VOUT = 1.2 V", loc="right")
        d.add(elm.Resistor().at((21.0, y_out)).down().to((21.0, 3.6)).label(f"R1\n{ldo.r1 / 1e3:g}k", loc="bottom", fontsize=8))
        d.add(elm.Resistor().at((21.0, 3.6)).down().to((21.0, BOT)).label(f"R2\n{ldo.r2 / 1e3:g}k", loc="bottom", fontsize=8))
        _tag(d, (21.0, 3.6), "FB", loc="left")
        if ldo.cff > 0:
            d.add(elm.Line().at((21.0, 5.9)).to((22.2, 5.9)))
            d.add(elm.Capacitor().at((22.2, 5.9)).down().to((22.2, 4.1)).label(f"CFF\n{ldo.cff * 1e12:.3g}p", loc="bottom", fontsize=8))
            d.add(elm.Line().at((22.2, 4.1)).to((22.2, 3.6)))
            d.add(elm.Line().at((22.2, 3.6)).to((21.0, 3.6)))
        d.add(elm.Capacitor().at((23.6, y_out)).down().to((23.6, 3.4)).label(f"COUT\n{ldo.cout * 1e6:g}u", loc="bottom", fontsize=8))
        d.add(elm.Resistor().at((23.6, 3.4)).down().to((23.6, BOT)).label(f"RC\n{ldo.rc:.3g}", loc="bottom", fontsize=8))
        d.add(elm.Resistor().at((25.5, y_out)).down().to((25.5, BOT)).label("RL /\nILOAD", loc="bottom", fontsize=8))
        d.save(str(path))
    return path
