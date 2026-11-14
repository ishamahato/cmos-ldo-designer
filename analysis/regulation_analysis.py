"""Line regulation, load regulation, dropout and load capability from DC sweeps."""
from __future__ import annotations

import math

import numpy as np


def line_regulation_mv_per_v(vin, vout, v_lo: float, v_hi: float) -> float:
    vin, vout = np.asarray(vin), np.asarray(vout)
    a, b = np.interp([v_lo, v_hi], vin, vout)
    return float((b - a) / (v_hi - v_lo) * 1e3)


def load_regulation_mv_per_ma(iload, vout, i_lo: float, i_hi: float) -> float:
    iload, vout = np.asarray(iload), np.asarray(vout)
    a, b = np.interp([i_lo, i_hi], iload, vout)
    return float((b - a) / ((i_hi - i_lo) * 1e3) * 1e3)


def dropout_voltage(vin, vout, drop_frac: float = 0.02, v_reg_at: float | None = None) -> dict[str, float]:
    """Dropout = Vin - Vout at the lowest Vin where Vout is still >= (1 - drop_frac) * Vreg.

    Vreg is the regulated output at the highest swept Vin (or ``v_reg_at``).
    """
    vin, vout = np.asarray(vin), np.asarray(vout)
    order = np.argsort(vin)
    vin, vout = vin[order], vout[order]
    vreg = float(np.interp(v_reg_at, vin, vout)) if v_reg_at else float(vout[-1])
    thresh = (1 - drop_frac) * vreg
    below = np.where(vout < thresh)[0]
    if len(below) == 0:
        return {"vin_dropout": float(vin[0]), "dropout_v": float(vin[0] - vout[0]), "vreg": vreg,
                "note": "regulating over the whole sweep"}
    i = below[-1]
    if i + 1 >= len(vin):
        return {"vin_dropout": math.nan, "dropout_v": math.nan, "vreg": vreg}
    # interpolate the threshold crossing between i and i+1
    x0, x1, y0, y1 = vin[i], vin[i + 1], vout[i], vout[i + 1]
    vx = x0 + (thresh - y0) * (x1 - x0) / (y1 - y0)
    return {"vin_dropout": float(vx), "dropout_v": float(vx - thresh), "vreg": vreg}


def max_load_current(iload, vout, vout_min: float) -> float:
    iload, vout = np.asarray(iload), np.asarray(vout)
    ok = np.where(vout >= vout_min)[0]
    if len(ok) == 0:
        return 0.0
    # contiguous from the start of the sweep
    breaks = np.where(np.diff(ok) != 1)[0]
    last = ok[breaks[0]] if len(breaks) else ok[-1]
    return float(iload[last])
