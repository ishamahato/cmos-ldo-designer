"""One-at-a-time parameter sweeps (sensitivity analysis) with real simulations."""
from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd

from analysis.experiment_store import log_experiment
from circuits.design_params import DeviceSize, LDODesign
from spice.ngspice_runner import SimulationError
from .design_optimizer import cost, evaluate

SETTERS: dict[str, Callable[[LDODesign, float], LDODesign]] = {
    "pass_m": lambda d, v: d.copy(pass_dev=DeviceSize(d.pass_dev.w, d.pass_dev.l, int(v))),
    "tail_m": lambda d, v: d.copy(tail=DeviceSize(d.tail.w, d.tail.l, int(v))),
    "pair_m": lambda d, v: d.copy(pair=DeviceSize(d.pair.w, d.pair.l, int(v))),
    "iref_ua": lambda d, v: d.copy(iref=v * 1e-6),
    "rc": lambda d, v: d.copy(rc=v),
    "cff_pf": lambda d, v: d.copy(cff=v * 1e-12),
    "cout_uf": lambda d, v: d.copy(cout=v * 1e-6),
    "rtot_k": lambda d, v: d.copy(r1=v * 500.0, r2=v * 500.0),
}


def sweep(base: LDODesign, param: str, values: Iterable[float], with_transient: bool = False) -> pd.DataFrame:
    rows = []
    for v in values:
        d = SETTERS[param](base, v).copy(name=f"sweep_{param}_{v:g}")
        try:
            m = evaluate(d, with_transient=with_transient)
            m["cost"] = cost(m) if with_transient else float("nan")
            status = "ok"
        except SimulationError as exc:
            m, status = {}, f"failed: {exc}"
        log_experiment("sweep", d.to_dict(), m, {"param": param, "value": v}, status="ok" if status == "ok" else "failed",
                       message=status, tag=f"sweep_{param}")
        rows.append({"param": param, "value": v, "status": status, **m})
    return pd.DataFrame(rows)
