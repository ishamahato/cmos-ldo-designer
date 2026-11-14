"""Power, efficiency and quiescent-current calculations.

Efficiency = (Vout * Iload) / (Vin * Iin) * 100      (Iin includes ground current)
Ground current  Ignd = Iin - Iload
Dissipation     Pd   = Vin * Iin - Vout * Iload
For an LDO the efficiency is bounded by Vout/Vin (e.g. 66.7 % at 1.8 V, 36.4 % at 3.3 V).
"""
from __future__ import annotations

import numpy as np


def efficiency_pct(vin, iin, vout, iload):
    vin, iin, vout, iload = map(np.asarray, (vin, iin, vout, iload))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(vin * iin > 0, vout * iload / (vin * iin) * 100.0, np.nan)


def ground_current(iin, iload):
    return np.asarray(iin) - np.asarray(iload)


def dissipation(vin, iin, vout, iload):
    return np.asarray(vin) * np.asarray(iin) - np.asarray(vout) * np.asarray(iload)


def efficiency_bound_pct(vin, vout):
    return np.asarray(vout) / np.asarray(vin) * 100.0
