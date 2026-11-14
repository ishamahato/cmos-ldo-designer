"""Loop-gain (stability) and closed-loop AC analyses."""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.performance_metrics import loop_metrics
from circuits.design_params import LDODesign, OperatingPoint
from .netlist_generator import ac_closed_netlist, ac_loop_netlist
from .ngspice_runner import run_netlist
from .result_parser import validate_frame


def loop_gain(d: LDODesign, op: OperatingPoint) -> dict:
    r = run_netlist(ac_loop_netlist(d, op))
    df = r.data["loop"].rename(columns={"x": "freq"})
    validate_frame("loop gain", df, 20)
    m = loop_metrics(df.freq.to_numpy(), df.mag.to_numpy(), df.ph.to_numpy())
    return {"data": df, **m.as_dict()}


def closed_loop(d: LDODesign, op: OperatingPoint) -> dict:
    r = run_netlist(ac_closed_netlist(d, op))
    cl = r.data["clgain"].rename(columns={"x": "freq"})
    ps = r.data["psrr"].rename(columns={"x": "freq"})
    zo = r.data["zout"].rename(columns={"x": "freq"})
    df = cl.merge(ps, on="freq").merge(zo, on="freq")
    validate_frame("closed loop", df, 20)
    f = df.freq.to_numpy()
    acl = df.acl.to_numpy()
    bw = f[np.where(acl < acl[0] - 3)[0][0]] if np.any(acl < acl[0] - 3) else np.nan
    pk = float(acl.max() - acl[0])
    return {"data": df, "closed_loop_dc_db": float(acl[0]), "closed_loop_bw_hz": float(bw),
            "closed_loop_peaking_db": pk, "psrr_dc_db": float(df.psrr.iloc[0]),
            "psrr_1khz_db": float(np.interp(3, np.log10(f), df.psrr)),
            "psrr_100khz_db": float(np.interp(5, np.log10(f), df.psrr)),
            "zout_dc_ohm": float(df.zout.iloc[0])}
