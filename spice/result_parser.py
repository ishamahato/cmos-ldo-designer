"""Parsers for ngspice batch output and ``wrdata`` files, plus sanity checks."""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

_PRINT_RE = re.compile(r"^\s*([@A-Za-z][\w\.\[\]\(\)#:@-]*)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*$")


class ResultValidationError(ValueError):
    pass


def parse_prints(text: str) -> dict[str, float]:
    """Collect ``name = value`` lines printed by ``print``/``meas``."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _PRINT_RE.match(line)
        if m:
            out[m.group(1).lower()] = float(m.group(2))
    return out


def read_wrdata(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", engine="python")
    cols = list(df.columns)
    cols[0] = "x"
    df.columns = [c.lower() for c in cols]
    return df


def device_op(values: dict[str, float], spice_name: str, model: str) -> dict[str, float]:
    prefix = f"@m.{spice_name.lower()}.m{model}"
    res = {}
    for k, v in values.items():
        if k.startswith(prefix + "["):
            res[k[len(prefix) + 1:-1]] = v
    return res


def operating_region(p: dict[str, float]) -> str:
    """Classify a MOSFET from |Vgs|, |Vds|, |Vth|, |Vdsat| (BSIM4 op values)."""
    vgs, vds = abs(p.get("vgs", 0.0)), abs(p.get("vds", 0.0))
    vth, vdsat = abs(p.get("vth", 0.0)), abs(p.get("vdsat", 0.0))
    if vgs < vth - 0.05:
        return "subthreshold"
    if vds >= vdsat:
        return "saturation"
    return "triode"


def require_finite(name: str, *vals: float) -> None:
    for v in vals:
        if v is None or not math.isfinite(v):
            raise ResultValidationError(f"{name}: non-finite simulation result")


def validate_frame(name: str, df: pd.DataFrame, min_rows: int = 3) -> None:
    if df is None or len(df) < min_rows:
        raise ResultValidationError(f"{name}: simulation returned too few points")
    if not np.isfinite(df.to_numpy(dtype=float)).all():
        raise ResultValidationError(f"{name}: NaN/Inf in simulation data")
