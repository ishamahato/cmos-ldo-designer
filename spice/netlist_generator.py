"""SPICE netlist generation for every analysis.

All test benches share one regulator description (``circuits.ldo_topology``)
and differ only in the stimulus/load elements and the ``.control`` block.
Netlists reference the PDK through the relative path ``pdk/sky130_hv.lib``;
``ngspice_runner`` links the real PDK directory into the run folder, which
keeps netlists portable and avoids problems with spaces in paths.
"""
from __future__ import annotations

from circuits.components import Component
from circuits.design_params import LDODesign, OperatingPoint
from circuits.ldo_topology import build_ldo

PDK_REL = "pdk/sky130_hv/sky130_hv.lib"
OP_PARAMS = ("id", "gm", "gds", "vgs", "vds", "vth", "vdsat", "cgg")


def _header(d: LDODesign, op: OperatingPoint, title: str) -> list[str]:
    op.validate()
    return [
        f"* {title} | design={d.name} corner={op.corner} T={op.temp}C",
        f'.lib "{PDK_REL}" {op.corner}',
        f".temp {op.temp:g}",
        ".options savecurrents=0 reltol=1e-4",
    ]


def _core(d: LDODesign, loop_break: bool = False) -> list[str]:
    lines: list[str] = ["* ---- LDO regulator ----"]
    for c in build_ldo(d, loop_break=loop_break):
        lines += c.to_spice(gate_offset=d.mismatch_vos.get(c.ref))
    return lines


def _load(op: OperatingPoint, d: LDODesign, kind: str, spec: str | None = None) -> list[str]:
    """kind='resistor' -> RL = Vout_nom/Iload ; kind='current' -> ILOAD source."""
    if kind == "resistor":
        rl = d.vout_ideal / op.iload if op.iload > 0 else 1e12
        return [f"RL vout 0 {rl:.6e}"]
    return [f"ILOAD vout 0 {spec or f'DC {op.iload:.6e}'}"]


def device_param_vectors(comps: list[Component]) -> list[str]:
    vecs = []
    for c in comps:
        if c.is_mos:
            inner = f"m.{c.spice_name.lower()}.m{c.model}"
            vecs += [f"@{inner}[{p}]" for p in OP_PARAMS]
    return vecs


def op_netlist(d: LDODesign, op: OperatingPoint, load: str = "resistor") -> str:
    comps = build_ldo(d)
    nodes = ["vin", "vout", "vref", "fb", "gate", "tail", "d1", "d2", "x", "nb", "pb"]
    dev = device_param_vectors(comps)
    lines = _header(d, op, "DC operating point") + [f"VIN vin 0 DC {op.vin:g}"] + _core(d) + _load(op, d, load)
    lines += [".control", "op"]
    lines += [f"print v({n})" for n in nodes]
    lines += ["print i(vin)", "print i(vref)"]
    lines += [f"print {v}" for v in dev]
    lines += [".endc", ".end"]
    return "\n".join(lines) + "\n"


def dc_sweep_netlist(d: LDODesign, op: OperatingPoint, sweep: str,
                     start: float, stop: float, step: float) -> str:
    """sweep='vin' (line) or 'iload' (load).  Load is a current source."""
    if sweep not in ("vin", "iload"):
        raise ValueError("sweep must be 'vin' or 'iload'")
    src = "VIN" if sweep == "vin" else "ILOAD"
    lines = _header(d, op, f"DC sweep {sweep}") + [f"VIN vin 0 DC {op.vin:g}"] + _core(d) + _load(op, d, "current")
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"dc {src} {start:g} {stop:g} {step:g}",
              "let iin = -i(vin)",
              "wrdata dc.dat v(vout) v(gate) v(fb) iin",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def ac_loop_netlist(d: LDODesign, op: OperatingPoint, fstart: float = 1.0, fstop: float = 1e9,
                    ppd: int = 40) -> str:
    """Open-loop gain by breaking the loop at the EA input.

    A 1 GH inductor closes the loop at DC (correct bias point); a 1 GF capacitor
    injects the AC test signal into the EA input.  T(s) = -V(fb)/V(fbin).
    """
    lines = _header(d, op, "AC loop gain") + [f"VIN vin 0 DC {op.vin:g}"] + _core(d, loop_break=True)
    lines += _load(op, d, "resistor")
    lines += ["LBRK fb fbin 1G", "CBRK fbin vac 1G", "VAC vac 0 DC 0 AC 1"]
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"ac dec {ppd} {fstart:g} {fstop:g}",
              "let tl = -v(fb)/v(fbin)",
              "let mag = db(tl)",
              "let ph = 180/pi*cph(tl)",
              "wrdata loop.dat mag ph",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def ac_closed_netlist(d: LDODesign, op: OperatingPoint, fstart: float = 1.0, fstop: float = 1e8,
                      ppd: int = 20) -> str:
    """Closed-loop gain Vout/Vref, PSRR (Vout/Vin) and output impedance."""
    lines = _header(d, op, "AC closed loop") + [f"VIN vin 0 DC {op.vin:g} AC 0"] + _core(d)
    lines = [ln.replace("VREF vref 0 DC", "VREF vref 0 AC 1 DC") if ln.startswith("VREF ") else ln
             for ln in lines]
    lines += _load(op, d, "resistor") + ["IZ 0 vout DC 0 AC 0"]
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"ac dec {ppd} {fstart:g} {fstop:g}",
              "let acl = db(v(vout))", "wrdata clgain.dat acl",
              "alter @vref[acmag] = 0", "alter @vin[acmag] = 1",
              f"ac dec {ppd} {fstart:g} {fstop:g}",
              "let psrr = db(v(vout))", "wrdata psrr.dat psrr",
              "alter @vin[acmag] = 0", "alter @iz[acmag] = 1",
              f"ac dec {ppd} {fstart:g} {fstop:g}",
              "let zout = mag(v(vout))", "wrdata zout.dat zout",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def tran_load_netlist(d: LDODesign, op: OperatingPoint, i_low: float = 1e-3, i_high: float = 50e-3,
                      t_edge: float = 1e-6, t_on: float = 50e-6, t_off: float = 250e-6,
                      t_stop: float = 450e-6, t_step: float = 20e-9) -> str:
    pwl = (f"PWL(0 {i_low:g} {t_on:g} {i_low:g} {t_on + t_edge:g} {i_high:g} "
           f"{t_off:g} {i_high:g} {t_off + t_edge:g} {i_low:g})")
    lines = _header(d, op, "Load transient") + [f"VIN vin 0 DC {op.vin:g}"] + _core(d)
    lines += _load(op, d, "current", pwl)
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"tran {t_step:g} {t_stop:g} 0 {t_step * 5:g}",
              "let iin = -i(vin)",
              "wrdata tran.dat v(vout) v(gate) iin",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def tran_line_netlist(d: LDODesign, op: OperatingPoint, v_low: float = 2.5, v_high: float = 3.3,
                      t_edge: float = 1e-6, t_on: float = 50e-6, t_off: float = 250e-6,
                      t_stop: float = 450e-6, t_step: float = 20e-9) -> str:
    pwl = (f"PWL(0 {v_low:g} {t_on:g} {v_low:g} {t_on + t_edge:g} {v_high:g} "
           f"{t_off:g} {v_high:g} {t_off + t_edge:g} {v_low:g})")
    lines = _header(d, op, "Line transient") + [f"VIN vin 0 {pwl}"] + _core(d) + _load(op, d, "current")
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"tran {t_step:g} {t_stop:g} 0 {t_step * 5:g}",
              "let iin = -i(vin)",
              "wrdata tran.dat v(vout) v(vin) v(gate) iin",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def full_netlist_for_display(d: LDODesign, op: OperatingPoint | None = None) -> str:
    """Human-readable netlist of the regulator with an example test bench."""
    op = op or OperatingPoint()
    return op_netlist(d, op).split(".control")[0] + ".end\n"


def _ea_core(d: LDODesign) -> list[str]:
    """Bias network + error amplifier only (VREF removed: inputs are driven by the bench).
    Inverting input = node ``vref`` (MP1 gate), non-inverting = ``inp`` (MP2 gate)."""
    from circuits import biasing, error_amplifier
    comps = [c for c in biasing.build(d) if c.ref != "VREF"] + error_amplifier.build(d, fb_node="inp")
    lines = ["* ---- bias + error amplifier ----"]
    for c in comps:
        lines += c.to_spice(gate_offset=d.mismatch_vos.get(c.ref))
    return lines


def ea_dc_netlist(d: LDODesign, op: OperatingPoint, vcm: float = 0.6, c_load: float = 5e-12) -> str:
    """Differential DC transfer (Vinp swept around Vcm) and unity-gain follower CM sweep."""
    lines = _header(d, op, "Error amplifier DC") + [f"VIN vin 0 DC {op.vin:g}"] + _ea_core(d)
    lines += [f"VN vref 0 DC {vcm:g}", f"VP inp 0 DC {vcm:g}", f"CL gate 0 {c_load:g}"]
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"dc VP {vcm - 0.05:g} {vcm + 0.05:g} 0.0001",
              "wrdata ea_diff.dat v(gate)",
              "op", "print i(vin)",
              ".endc", ".end"]
    return "\n".join(lines) + "\n"


def ea_follower_netlist(d: LDODesign, op: OperatingPoint) -> str:
    """Unity-gain follower: output fed back to the inverting input; sweep the
    non-inverting input to find the input common-mode range."""
    lines = _header(d, op, "Error amplifier ICMR") + [f"VIN vin 0 DC {op.vin:g}"] + _ea_core(d)
    lines = [ln for ln in lines]
    lines += ["VP inp 0 DC 0.6", "RFB gate vref 1", "CL gate 0 5p"]
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              f"dc VP 0 {op.vin:g} 0.005", "wrdata ea_cm.dat v(gate)", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def ea_ac_netlist(d: LDODesign, op: OperatingPoint, vcm: float = 0.6, c_load: float = 5e-12) -> str:
    """Open-loop differential gain with the output biased by a slow DC servo
    (1 GH inductor from output to the inverting input keeps it in the linear region)."""
    lines = _header(d, op, "Error amplifier AC") + [f"VIN vin 0 DC {op.vin:g}"] + _ea_core(d)
    lines += [f"VP inp 0 DC {vcm:g} AC 1", "LSRV gate vref 1G", "CSRV vref 0 1G", f"CL gate 0 {c_load:g}"]
    lines += [".control", "set wr_vecnames", "set wr_singlescale",
              "ac dec 20 1 1e9", "let g = db(v(gate))", "let p = 180/pi*cph(v(gate))",
              "wrdata ea_ac.dat g p", ".endc", ".end"]
    return "\n".join(lines) + "\n"
