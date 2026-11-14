"""DC operating point and DC sweeps (line, load, dropout)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis import power_analysis as pw
from analysis import regulation_analysis as reg
from circuits.design_params import SPEC, LDODesign, OperatingPoint
from circuits.ldo_topology import build_ldo
from .netlist_generator import dc_sweep_netlist, op_netlist
from .ngspice_runner import run_netlist
from .result_parser import device_op, operating_region, require_finite, validate_frame


def operating_point(d: LDODesign, op: OperatingPoint, load: str = "resistor") -> dict:
    r = run_netlist(op_netlist(d, op, load))
    v = r.values
    vout, iin = v["v(vout)"], -v["i(vin)"]
    require_finite("op", vout, iin)
    iload = vout / (d.vout_ideal / op.iload) if (load == "resistor" and op.iload > 0) else op.iload
    devices = []
    for c in build_ldo(d):
        if c.is_mos:
            p = device_op(v, c.spice_name, c.model)
            devices.append({"ref": c.ref, "block": c.block, "type": c.kind,
                            "id_a": abs(p.get("id", np.nan)), "gm_s": p.get("gm", np.nan),
                            "gds_s": p.get("gds", np.nan), "vgs_v": p.get("vgs", np.nan),
                            "vds_v": p.get("vds", np.nan), "vth_v": p.get("vth", np.nan),
                            "vdsat_v": p.get("vdsat", np.nan), "cgg_f": p.get("cgg", np.nan),
                            "region": operating_region(p)})
    dev = pd.DataFrame(devices)
    i_bias_ea = float(dev.loc[dev.ref == "MP5", "id_a"].iloc[0]) if len(dev) else np.nan
    summary = {
        "vin": op.vin, "vout": vout, "vref": v["v(vref)"], "vfb": v["v(fb)"], "vgate": v["v(gate)"],
        "iload": iload, "iin": iin, "ignd": iin - iload,
        "i_pass": float(dev.loc[dev.ref == "MPASS", "id_a"].iloc[0]),
        "i_tail": i_bias_ea, "iref": d.iref,
        "p_in_w": op.vin * iin, "p_out_w": vout * iload,
        "p_diss_w": float(pw.dissipation(op.vin, iin, vout, iload)),
        "efficiency_pct": float(pw.efficiency_pct(op.vin, iin, vout, iload)),
        "vout_error_pct": (vout - SPEC["vout_nom"]) / SPEC["vout_nom"] * 100,
        "corner": op.corner, "temp": op.temp,
    }
    return {"summary": summary, "devices": dev, "nodes": {k: x for k, x in v.items() if k.startswith("v(")}}


def sweep(d: LDODesign, op: OperatingPoint, what: str, start: float, stop: float, step: float) -> pd.DataFrame:
    r = run_netlist(dc_sweep_netlist(d, op, what, start, stop, step))
    df = r.data["dc"].rename(columns={"x": what, "v(vout)": "vout", "v(gate)": "vgate", "v(fb)": "vfb"})
    validate_frame(f"dc sweep {what}", df)
    if what == "vin":
        df["iload"] = op.iload
    else:
        df["vin"] = op.vin
    df["efficiency_pct"] = pw.efficiency_pct(df["vin"], df["iin"], df["vout"], df["iload"])
    df["ignd"] = pw.ground_current(df["iin"], df["iload"])
    return df


def line_regulation(d: LDODesign, op: OperatingPoint) -> dict:
    df = sweep(d, op, "vin", 1.0, 3.6, 0.01)
    return {"data": df, "line_reg_mv_per_v": reg.line_regulation_mv_per_v(df.vin, df.vout, SPEC["vin_min"], SPEC["vin_max"])}


def load_regulation(d: LDODesign, op: OperatingPoint) -> dict:
    df = sweep(d, op, "iload", 0.0, 60e-3, 0.25e-3)
    return {"data": df,
            "load_reg_mv_per_ma": reg.load_regulation_mv_per_ma(df.iload, df.vout, SPEC["iload_min"], SPEC["iload_max"]),
            "iq_a": float(df.iin.iloc[0])}


def dropout(d: LDODesign, op: OperatingPoint, iload: float = 50e-3, drop_frac: float = 0.02) -> dict:
    op2 = OperatingPoint(op.vin, iload, op.temp, op.corner)
    df = sweep(d, op2, "vin", 1.0, 3.3, 0.01)
    res = reg.dropout_voltage(df.vin, df.vout, drop_frac=drop_frac, v_reg_at=SPEC["vin_max"])
    return {"data": df, **res}


def max_load(d: LDODesign, op: OperatingPoint) -> dict:
    df = sweep(d, op, "iload", 0.0, 200e-3, 1e-3)
    return {"data": df, "imax_a": reg.max_load_current(df.iload, df.vout, 0.98 * SPEC["vout_nom"])}


def error_amp_characterisation(d: LDODesign, op: OperatingPoint | None = None) -> dict:
    """Stand-alone error amplifier: offset, DC gain, ICMR, bandwidth, power."""
    from analysis.performance_metrics import loop_metrics
    from .netlist_generator import ea_ac_netlist, ea_dc_netlist, ea_follower_netlist
    op = op or OperatingPoint(2.5, 0.0)
    r = run_netlist(ea_dc_netlist(d, op))
    tf = r.data["ea_diff"].rename(columns={"x": "vinp", "v(gate)": "vout"})
    vdiff = tf.vinp.to_numpy() - 0.6
    vo = tf.vout.to_numpy()
    slope = np.gradient(vo, vdiff)
    mid = op.vin / 2
    # systematic input offset: differential input that places the output at mid-supply
    order = np.argsort(vo)
    vos = float(np.interp(mid, vo[order], vdiff[order]))
    i_supply = abs(r.values["i(vin)"])
    cm = run_netlist(ea_follower_netlist(d, op)).data["ea_cm"].rename(columns={"x": "vcm", "v(gate)": "vout"})
    # ICMR: range where the unity-gain follower still tracks (slope >= 0.9 V/V)
    fslope = np.gradient(cm.vout.to_numpy(), cm.vcm.to_numpy())
    ok = cm.vcm[fslope >= 0.9]
    ac = run_netlist(ea_ac_netlist(d, op)).data["ea_ac"].rename(columns={"x": "freq", "g": "mag", "p": "ph"})
    lm = loop_metrics(ac.freq.to_numpy(), ac.mag.to_numpy(), ac.ph.to_numpy())
    return {"transfer": tf, "cm_sweep": cm, "ac": ac,
            "dc_gain_db": float(ac.mag.iloc[0]), "max_slope_db": float(20 * np.log10(np.max(np.abs(slope)))),
            "gbw_hz": lm.ugf_hz, "pole_hz": lm.dominant_pole_hz,
            "systematic_offset_mv": vos * 1e3, "icmr_low_v": float(ok.min()) if len(ok) else np.nan,
            "icmr_high_v": float(ok.max()) if len(ok) else np.nan,
            "out_swing_low_v": float(vo.min()), "out_swing_high_v": float(vo.max()),
            "supply_current_ua": i_supply * 1e6, "power_uw": i_supply * op.vin * 1e6}
