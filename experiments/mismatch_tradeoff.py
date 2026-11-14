"""Experiment: does enlarging the NMOS mirror devices (MN3/MN4/MN6/MN7) improve
Monte Carlo accuracy, and what does it cost in phase margin?

Run:  python experiments/mismatch_tradeoff.py   (~3 min)  -> results/mismatch_tradeoff.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from circuits.design_params import DeviceSize, LDODesign, OperatingPoint  # noqa: E402
from spice.ac_analysis import loop_gain  # noqa: E402
from verification.monte_carlo import _run_one, sample_design  # noqa: E402

base = LDODesign.from_dict(json.loads((ROOT / "results/optimized/design.json").read_text()))
variant = base.copy(name="optimized_bigmirror", nload=DeviceSize(5, 4, 4), nmirror=DeviceSize(5, 4, 4))
out = {}
for d in (base, variant):
    rng = np.random.default_rng(11)
    rows = [_run_one((i, sample_design(d, rng), d.vref)) for i in range(60)]
    worst = loop_gain(d, OperatingPoint(1.8, 1e-3, -40.0, "sf"))
    nom = loop_gain(d, OperatingPoint(2.5, 10e-3))
    out[d.name] = {
        "mirror_size": f"{d.nload.w}/{d.nload.l} x{d.nload.m}",
        "mc_samples": 60,
        "ea_offset_sigma_mv": float(np.std([r["ea_offset_mv"] for r in rows], ddof=1)),
        "vout_sigma_mv": float(np.std([r["vout"] for r in rows], ddof=1) * 1e3),
        "pm_nominal_deg": nom["phase_margin_deg"],
        "pm_worst_pvt_deg (sf,-40C,1.8V,1mA)": worst["phase_margin_deg"],
    }
    print(d.name, out[d.name])
(ROOT / "results" / "mismatch_tradeoff.json").write_text(json.dumps(out, indent=2))
