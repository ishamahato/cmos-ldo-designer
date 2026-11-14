#!/usr/bin/env python3
"""CMOS LDO Designer - command-line entry point.

    python run.py check            # environment + PDK + ngspice detection
    python run.py baseline         # full characterisation of the baseline design
    python run.py sweeps           # one-at-a-time sensitivity sweeps
    python run.py optimize         # differential-evolution optimisation (slow: ~20-40 min)
    python run.py optimized        # characterise the optimised design
    python run.py pvt [--design optimized]
    python run.py montecarlo [-n 200]
    python run.py report           # comparison, spec check, Markdown/HTML report
    python run.py all              # everything above in order
    python run.py dashboard        # launch Streamlit
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

log = logging.getLogger("ldo")
RESULTS = ROOT / "results"


def cmd_check(_a=None) -> bool:
    from circuits.design_params import PDK_LIB, model_bins, NMOS_MODEL, PMOS_MODEL
    from spice.ngspice_runner import find_ngspice, ngspice_version, INSTALL_HELP
    ok = True
    print(f"Python      : {platform.python_version()} ({'OK' if sys.version_info >= (3, 11) else 'need >= 3.11'})")
    ok &= sys.version_info >= (3, 11)
    for mod in ("numpy", "scipy", "pandas", "matplotlib", "plotly", "sklearn", "streamlit", "schemdraw", "markdown"):
        try:
            m = importlib.import_module(mod)
            print(f"{mod:12s}: {getattr(m, '__version__', 'ok')}")
        except ImportError:
            print(f"{mod:12s}: MISSING  (pip install -r requirements.txt)")
            ok = False
    exe = find_ngspice()
    print(f"ngspice     : {exe or 'NOT FOUND'} {ngspice_version() or ''}")
    if not exe:
        print(INSTALL_HELP)
        ok = False
    print(f"PDK library : {PDK_LIB} ({'found' if PDK_LIB.exists() else 'MISSING'})")
    ok &= PDK_LIB.exists()
    if PDK_LIB.exists():
        print(f"  {NMOS_MODEL}: {len(model_bins(NMOS_MODEL))} bins, {PMOS_MODEL}: {len(model_bins(PMOS_MODEL))} bins")
    print("Environment OK" if ok else "Environment INCOMPLETE")
    return ok


def _design(name: str):
    from circuits.design_params import LDODesign
    if name == "baseline":
        return LDODesign()
    p = RESULTS / name / "design.json"
    if not p.exists() and name == "optimized" and (RESULTS / "optimizer_result.json").exists():
        return LDODesign.from_dict(json.loads((RESULTS / "optimizer_result.json").read_text())["design"])
    return LDODesign.from_dict(json.loads(p.read_text()))


def cmd_sizing(_a=None):
    from optimization.transistor_sizing import pass_device_sizing, feedback_resistors
    t = pass_device_sizing()
    RESULTS.mkdir(exist_ok=True)
    t.to_csv(RESULTS / "sizing_pass_device.csv", index=False)
    (RESULTS / "sizing_feedback.json").write_text(json.dumps(feedback_resistors(), indent=2))
    print(t.to_string(index=False))
    print("worst-case fingers required:", int(t.fingers_required.max()))


def _characterise(name: str):
    from analysis.characterization import characterise
    from analysis.plotting import plot_design
    from analysis.schematic import draw
    d = _design(name)
    d.name = name
    t = time.time()
    m = characterise(d)
    plot_design(RESULTS / name)
    draw(d, RESULTS / name / "plots" / "schematic.png")
    if name == "baseline" or not (RESULTS / "schematic.png").exists():
        draw(d, RESULTS / "schematic.png")
    print(f"[{name}] characterised in {time.time() - t:.0f} s: Vout={m['op_nominal']['vout']:.4f} V, "
          f"PMmin={m['pm_min_deg']:.1f} deg, dropout@50mA={m['dropout_v']['50mA']:.3f} V, Iq={m['iq_ua']['3.3V']:.1f} uA")


def cmd_baseline(_a=None):
    _characterise("baseline")


def cmd_optimized(_a=None):
    _characterise("optimized")
    from analysis.schematic import draw
    draw(_design("optimized"), RESULTS / "schematic.png")


def cmd_sweeps(_a=None):
    import numpy as np
    import pandas as pd
    from analysis.plotting import plot_sweeps
    from circuits.design_params import LDODesign
    from optimization.parameter_sweep import sweep
    base = LDODesign()
    plan = {"pass_m": [120, 150, 170, 200, 250, 300], "tail_m": [1, 2, 3, 4, 6], "iref_ua": [1, 2.5, 5, 7.5, 10],
            "rc": [0.05, 0.1, 0.2, 0.5, 1.0, 2.0], "cff_pf": [0, 5, 10, 20, 50], "cout_uf": [0.47, 1, 2.2, 4.7]}
    out = RESULTS / "sweeps"
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for p, vals in plan.items():
        df = sweep(base, p, vals)
        df.to_csv(out / f"sweep_{p}.csv", index=False)
        frames.append(df)
        print(f"sweep {p}: done ({(df.status == 'ok').sum()}/{len(df)} ok)")
    allf = pd.concat(frames)
    allf.to_csv(out / "all_sweeps.csv", index=False)
    plot_sweeps(allf, out)


def cmd_optimize(a):
    from circuits.design_params import LDODesign
    from optimization.design_optimizer import optimise
    r = optimise(LDODesign(), maxiter=a.maxiter, popsize=a.popsize, workers=a.workers)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "optimizer_result.json").write_text(json.dumps(
        {"design": r["design"].to_dict(), "cost": r["cost"], "nfev": r["nfev"], "tag": r["tag"]}, indent=2))
    print(f"best cost {r['cost']:.3f} after {r['nfev']} evaluations")


def cmd_pvt(a):
    from analysis.plotting import plot_pvt
    from verification.pvt_analysis import run_pvt
    d = _design(a.design)
    t = time.time()
    r = run_pvt(d, workers=a.workers)
    out = RESULTS / a.design
    out.mkdir(parents=True, exist_ok=True)
    r["grid"].to_csv(out / "pvt_grid.csv", index=False)
    r["iq_dropout"].to_csv(out / "pvt_iq_dropout.csv", index=False)
    (out / "pvt_summary.json").write_text(json.dumps(r["summary"], indent=2))
    plot_pvt(r["grid"], out / "plots", a.design)
    print(f"PVT ({time.time() - t:.0f} s):", json.dumps(r["summary"], indent=1))


def cmd_montecarlo(a):
    from analysis.plotting import plot_mc
    from verification.monte_carlo import run_monte_carlo
    d = _design(a.design)
    t = time.time()
    r = run_monte_carlo(d, n=a.n, workers=a.workers)
    out = RESULTS / a.design
    r["samples"].to_csv(out / "mc_samples.csv", index=False)
    (out / "mc_summary.json").write_text(json.dumps(r["summary"], indent=2))
    plot_mc(r["samples"], out / "plots", a.design)
    print(f"Monte Carlo ({time.time() - t:.0f} s):", json.dumps(r["summary"], indent=1))


def cmd_report(_a=None):
    import pandas as pd
    from analysis.characterization import load_metrics
    from analysis.plotting import comparison_rows, plot_comparison
    from analysis.report_generator import write_report
    from verification.spec_check import spec_table
    final = "optimized" if (RESULTS / "optimized" / "metrics.json").exists() else "baseline"
    if final == "optimized":
        b, o = load_metrics("baseline"), load_metrics("optimized")
        plot_comparison(b, o, RESULTS)
        pd.DataFrame(comparison_rows(b, o), columns=["metric", "baseline", "optimized"]).to_csv(RESULTS / "comparison.csv", index=False)
    m = load_metrics(final)
    pvt = mc = None
    if (RESULTS / final / "pvt_summary.json").exists():
        pvt = {"summary": json.loads((RESULTS / final / "pvt_summary.json").read_text()),
               "grid": pd.read_csv(RESULTS / final / "pvt_grid.csv")}
    if (RESULTS / final / "mc_summary.json").exists():
        mc = {"summary": json.loads((RESULTS / final / "mc_summary.json").read_text())}
    st = spec_table(m, pvt, mc)
    st.to_csv(RESULTS / "spec_compliance.csv", index=False)
    print(st[["test", "measured", "result"]].to_string(index=False))
    paths = write_report()
    print("report:", paths)


def cmd_all(a):
    if not cmd_check():
        sys.exit(1)
    cmd_sizing()
    cmd_baseline()
    cmd_sweeps()
    if not (a.reuse and (RESULTS / "optimizer_result.json").exists()):
        cmd_optimize(a)
    cmd_optimized()
    a.design = "optimized"
    cmd_pvt(a)
    cmd_montecarlo(a)
    cmd_report()


def cmd_dashboard(_a=None):
    subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py")])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "sizing", "baseline", "sweeps", "optimize", "optimized", "pvt",
                                        "montecarlo", "report", "all", "dashboard"])
    ap.add_argument("--design", default="optimized", help="baseline | optimized (for pvt / montecarlo)")
    ap.add_argument("-n", type=int, default=200, help="Monte Carlo samples")
    ap.add_argument("--workers", type=int, default=1, help="parallel ngspice processes (use >1 only with spare physical cores)")
    ap.add_argument("--maxiter", type=int, default=8)
    ap.add_argument("--popsize", type=int, default=4)
    ap.add_argument("--reuse", action="store_true", help="reuse results/optimizer_result.json if present")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(asctime)s %(name)s %(message)s")
    {"check": cmd_check, "sizing": cmd_sizing, "baseline": cmd_baseline, "sweeps": cmd_sweeps,
     "optimize": cmd_optimize, "optimized": cmd_optimized, "pvt": cmd_pvt, "montecarlo": cmd_montecarlo,
     "report": cmd_report, "all": cmd_all, "dashboard": cmd_dashboard}[a.command](a)


if __name__ == "__main__":
    main()
