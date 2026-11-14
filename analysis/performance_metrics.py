"""Metric extraction from simulated waveforms (no assumed values)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _crossings(x: np.ndarray, y: np.ndarray, level: float) -> list[float]:
    """Log-x interpolated crossings of y through ``level``."""
    out = []
    s = np.sign(y - level)
    idx = np.where(np.diff(s) != 0)[0]
    for i in idx:
        y0, y1 = y[i] - level, y[i + 1] - level
        lx0, lx1 = math.log10(x[i]), math.log10(x[i + 1])
        frac = y0 / (y0 - y1) if y0 != y1 else 0.0
        out.append(10 ** (lx0 + frac * (lx1 - lx0)))
    return out


def _interp_logx(x: np.ndarray, y: np.ndarray, xq: float) -> float:
    return float(np.interp(math.log10(xq), np.log10(x), y))


@dataclass
class LoopMetrics:
    dc_gain_db: float
    ugf_hz: float
    phase_margin_deg: float
    gain_margin_db: float
    f180_hz: float
    dominant_pole_hz: float
    n_unity_crossings: int
    stable: bool

    def as_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


def loop_metrics(f: np.ndarray, mag_db: np.ndarray, ph_deg: np.ndarray) -> LoopMetrics:
    f, mag_db, ph_deg = map(np.asarray, (f, mag_db, ph_deg))
    # cph() gives a continuous phase; normalise so the DC phase is near 0 deg.
    ph = ph_deg - 360.0 * round(ph_deg[0] / 360.0)
    a0 = float(mag_db[0])
    ugfs = _crossings(f, mag_db, 0.0)
    if a0 <= 0 or not ugfs:
        return LoopMetrics(a0, math.nan, math.nan, math.nan, math.nan, math.nan, len(ugfs), False)
    ugf = ugfs[-1]  # last crossing is the one that matters for (conditional) stability
    pm = 180.0 + _interp_logx(f, ph, ugf)
    f180s = _crossings(f, ph, -180.0)
    if f180s:
        f180 = f180s[0]
        gm = -_interp_logx(f, mag_db, f180)
    else:
        f180, gm = math.inf, math.inf
    p3 = _crossings(f, mag_db, a0 - 3.0)
    # conditionally stable loops (phase dips below -180 deg while |T| > 1) are flagged
    min_phase_before_ugf = float(np.min(ph[f <= ugf])) if np.any(f <= ugf) else 0.0
    stable = pm > 0 and (gm > 0) and min_phase_before_ugf > -180.0
    return LoopMetrics(a0, ugf, pm, gm, f180, p3[0] if p3 else math.nan, len(ugfs), bool(stable))


@dataclass
class StepMetrics:
    v_initial: float
    v_final: float
    peak_deviation_mv: float      # undershoot (load up) or overshoot (line up), sign-free
    peak_time_us: float
    settling_time_us: float       # back inside +/- band of the new final value
    recovery_time_us: float       # back inside +/- 1 % of the pre-step value
    ripple_pp_mv: float           # peak-to-peak of the last 20 % of the window

    def as_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


def step_metrics(t: np.ndarray, v: np.ndarray, t_edge: float, t_end: float,
                 band: float = 3e-3, direction: int = -1) -> StepMetrics:
    """``direction`` = -1 looks for a dip (undershoot), +1 for a peak (overshoot)."""
    t, v = np.asarray(t), np.asarray(v)
    pre = (t > t_edge - 10e-6) & (t < t_edge)
    win = (t >= t_edge) & (t < t_end)
    tail = (t >= t_end - 0.2 * (t_end - t_edge)) & (t < t_end)
    v0 = float(np.mean(v[pre]))
    vf = float(np.mean(v[tail]))
    tw, vw = t[win], v[win]
    i_pk = int(np.argmin(vw)) if direction < 0 else int(np.argmax(vw))
    dev = abs(float(vw[i_pk]) - v0) * 1e3

    def settle(target: float, tol: float) -> float:
        outside = np.where(np.abs(vw - target) > tol)[0]
        if len(outside) == 0:
            return 0.0
        last = outside[-1]
        if last >= len(tw) - 1:
            return math.nan  # never settled inside the window
        return float(tw[last + 1] - t_edge) * 1e6

    return StepMetrics(v0, vf, dev, float(tw[i_pk] - t_edge) * 1e6, settle(vf, band),
                       settle(v0, 0.01 * abs(v0)), float(np.ptp(v[tail])) * 1e3)
