"""Static (Matplotlib) plots of simulation results, written next to the CSV data."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# fixed-order categorical palette (validated reference palette, light mode)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dd"

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 140, "font.size": 9.5, "axes.titlesize": 11,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7, "axes.spines.top": False,
    "axes.spines.right": False, "lines.linewidth": 2.0, "legend.frameon": False,
    "axes.prop_cycle": matplotlib.cycler(color=SERIES),
})


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_design(res_dir: Path) -> list[Path]:
    """Generate every standard plot for one characterised design."""
    out = res_dir / "plots"
    out.mkdir(exist_ok=True)
    m = json.loads((res_dir / "metrics.json").read_text())
    name = m["design"]
    made: list[Path] = []

    # line regulation / Vin-Vout
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, f in enumerate(sorted(res_dir.glob("line_sweep_*mA.csv"))):
        df = pd.read_csv(f)
        ax.plot(df.vin, df.vout, color=SERIES[i], label=f"Iload = {f.stem.split('_')[-1]}")
    ax.plot([1, 3.6], [1, 3.6], color=MUTED, lw=1, ls=":", label="Vout = Vin")
    ax.axvspan(1.8, 3.3, color=SERIES[0], alpha=0.06, lw=0)
    ax.set(xlabel="Input voltage Vin (V)", ylabel="Output voltage Vout (V)", ylim=(0, 1.4),
           title=f"Input vs output voltage ({name})")
    ax.legend(loc="lower right")
    made.append(_save(fig, out / "vin_vout.png"))

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, f in enumerate(sorted(res_dir.glob("line_sweep_*mA.csv"))):
        df = pd.read_csv(f)
        s = df[(df.vin >= 1.8) & (df.vin <= 3.3)]
        ax.plot(s.vin, s.vout * 1e3, color=SERIES[i], label=f"Iload = {f.stem.split('_')[-1]}")
    ax.set(xlabel="Vin (V)", ylabel="Vout (mV)", title="Line regulation, Vin = 1.8-3.3 V")
    ax.legend()
    made.append(_save(fig, out / "line_regulation.png"))

    # load regulation
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, v in enumerate((1.8, 2.5, 3.3)):
        df = pd.read_csv(res_dir / f"load_sweep_{v:g}V.csv")
        ax.plot(df.iload * 1e3, df.vout * 1e3, color=SERIES[i], label=f"Vin = {v:g} V")
    ax.axvline(50, color=MUTED, lw=1, ls=":")
    ax.set(xlabel="Load current (mA)", ylabel="Vout (mV)", title="Load regulation")
    ax.legend()
    made.append(_save(fig, out / "load_regulation.png"))

    # efficiency
    eff = pd.read_csv(res_dir / "efficiency_vs_load.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, v in enumerate((1.8, 2.5, 3.3)):
        s = eff[(eff.vin_set == v) & (eff.iload > 0)]
        ax.plot(s.iload * 1e3, s.efficiency_pct, color=SERIES[i], label=f"Vin = {v:g} V")
        ax.axhline(1.2 / v * 100, color=SERIES[i], lw=1, ls=":")
    ax.set(xscale="log", xlabel="Load current (mA)", ylabel="Efficiency (%)",
           title="Efficiency vs load (dotted: Vout/Vin limit)", ylim=(0, 75))
    ax.legend(loc="lower right")
    made.append(_save(fig, out / "efficiency.png"))

    # quiescent current
    iq = pd.read_csv(res_dir / "iq_vs_vin.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.5))
    ax.plot(iq.vin, iq.iin * 1e6, color=SERIES[0])
    ax.set(xlabel="Vin (V)", ylabel="Quiescent current (uA)", title="Quiescent current (no load)")
    made.append(_save(fig, out / "quiescent_current.png"))

    # dropout
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, f in enumerate(sorted(res_dir.glob("dropout_sweep_*mA.csv"), key=lambda p: float(p.stem.split('_')[-1][:-2]))):
        df = pd.read_csv(f)
        ax.plot(df.vin, df.vout, color=SERIES[i], label=f"Iload = {f.stem.split('_')[-1]}")
    ax.axhline(0.98 * 1.2, color=MUTED, lw=1, ls=":", label="98 % of 1.2 V")
    ax.set(xlabel="Vin (V)", ylabel="Vout (V)", xlim=(1.0, 2.2), ylim=(0.8, 1.25), title="Dropout region")
    ax.legend(loc="lower right")
    made.append(_save(fig, out / "dropout.png"))

    # Bode
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.6, 5.6), sharex=True)
    for i, key in enumerate(("1.8V_1mA", "1.8V_50mA", "3.3V_1mA", "3.3V_50mA")):
        df = pd.read_csv(res_dir / f"loop_{key}.csv")
        lab = key.replace("_", ", ")
        pm = m["loop"][key]["phase_margin_deg"]
        a1.semilogx(df.freq, df.mag, color=SERIES[i], label=f"{lab} (PM {pm:.0f} deg)")
        a2.semilogx(df.freq, df.ph - 360 * np.round(df.ph.iloc[0] / 360), color=SERIES[i])
    a1.axhline(0, color=MUTED, lw=1)
    a2.axhline(-180, color=MUTED, lw=1, ls=":")
    a1.set(ylabel="Loop gain (dB)", title="Open-loop gain T(s) (loop broken at EA input)", ylim=(-60, 80))
    a2.set(ylabel="Phase (deg)", xlabel="Frequency (Hz)", ylim=(-270, 30))
    a1.legend(fontsize=8)
    made.append(_save(fig, out / "bode_loop.png"))

    # closed loop & PSRR
    cl = pd.read_csv(res_dir / "closed_loop.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.semilogx(cl.freq, cl.acl, color=SERIES[0], label="Closed-loop gain Vout/Vref")
    ax.semilogx(cl.freq, cl.psrr, color=SERIES[1], label="Supply gain Vout/Vin (PSRR)")
    ax.set(xlabel="Frequency (Hz)", ylabel="dB", title="Closed-loop response, Vin = 2.5 V, 10 mA")
    ax.legend()
    made.append(_save(fig, out / "closed_loop_psrr.png"))

    # transients
    for fname, title in (("tran_load_2v5", "Load step 1 -> 50 -> 1 mA, Vin = 2.5 V"),
                         ("tran_load_1v8", "Load step 1 -> 50 -> 1 mA, Vin = 1.8 V")):
        df = pd.read_csv(res_dir / f"{fname}.csv")
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.6, 4.8), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
        a1.plot(df.time * 1e6, df.vout * 1e3, color=SERIES[0])
        a1.set(ylabel="Vout (mV)", title=title)
        t = df.time * 1e6
        il = np.where((t >= 51) & (t < 250), 50, np.where((t > 50) & (t < 51), 1 + 49 * (t - 50), 1))
        il = np.where((t >= 250) & (t < 251), 50 - 49 * (t - 250), il)
        a2.plot(t, il, color=SERIES[1])
        a2.set(xlabel="Time (us)", ylabel="Iload (mA)")
        made.append(_save(fig, out / f"{fname}.png"))
    df = pd.read_csv(res_dir / "tran_line.csv")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.6, 4.8), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    a1.plot(df.time * 1e6, df.vout * 1e3, color=SERIES[0])
    a1.set(ylabel="Vout (mV)", title="Line step 1.8 -> 3.3 -> 1.8 V (1 us edges), 10 mA")
    a2.plot(df.time * 1e6, df.vin, color=SERIES[1])
    a2.set(xlabel="Time (us)", ylabel="Vin (V)")
    made.append(_save(fig, out / "tran_line.png"))

    # stability maps
    pl = pd.read_csv(res_dir / "pm_vs_load.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, v in enumerate((1.8, 2.5, 3.3)):
        s = pl[pl.vin == v]
        ax.semilogx(s.iload * 1e3, s.pm_deg, marker="o", ms=4, color=SERIES[i], label=f"Vin = {v:g} V")
    ax.axhline(45, color=MUTED, lw=1, ls=":")
    ax.set(xlabel="Load current (mA)", ylabel="Phase margin (deg)", title="Phase margin vs load")
    ax.legend()
    made.append(_save(fig, out / "pm_vs_load.png"))
    pr = pd.read_csv(res_dir / "pm_vs_rc.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, il in enumerate(sorted(pr.iload.unique())):
        s = pr[pr.iload == il]
        ax.semilogx(s.rc, s.pm_deg, marker="o", ms=4, color=SERIES[i], label=f"Iload = {il * 1e3:g} mA")
    ax.axhline(45, color=MUTED, lw=1, ls=":")
    ax.set(xlabel="Series compensation resistance Rc / ESR (ohm)", ylabel="Phase margin (deg)",
           title="Phase margin vs Rc (Vin = 3.3 V)")
    ax.legend()
    made.append(_save(fig, out / "pm_vs_rc.png"))
    return made


def plot_pvt(grid: pd.DataFrame, out: Path, name: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    ok = grid[grid.status == "ok"]
    made = []
    corners = list(dict.fromkeys(ok.corner))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8), sharey=False)
    for ax, il in zip(axes, (1e-3, 50e-3)):
        for i, c in enumerate(corners):
            s = ok[(ok.corner == c) & (ok.iload == il) & (ok.vin == 1.8)].sort_values("temp")
            ax.plot(s.temp, s.vout * 1e3, marker="o", ms=4, color=SERIES[i], label=c)
        ax.set(xlabel="Temperature (C)", ylabel="Vout (mV)", title=f"Vin = 1.8 V, {il * 1e3:g} mA")
    axes[0].legend(title="corner")
    fig.suptitle(f"Output voltage across process corners and temperature ({name})", fontsize=11)
    made.append(_save(fig, out / "pvt_vout.png"))
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for i, c in enumerate(corners):
        s = ok[ok.corner == c]
        ax.scatter(s.temp + (i - 2) * 3, s.pm_deg, s=14, color=SERIES[i], label=c)
    ax.axhline(45, color=MUTED, lw=1, ls=":")
    ax.set(xlabel="Temperature (C)", ylabel="Phase margin (deg)", title="Phase margin over PVT (all Vin, loads)")
    ax.legend(title="corner", ncol=5, fontsize=8)
    made.append(_save(fig, out / "pvt_pm.png"))
    return made


def plot_mc(samples: pd.DataFrame, out: Path, name: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    ok = samples[samples.status == "ok"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4))
    axes[0].hist(ok.vout * 1e3, bins=30, color=SERIES[0], edgecolor="white", linewidth=1)
    axes[0].axvline(1200, color=MUTED, ls=":")
    axes[0].set(xlabel="Vout (mV)", ylabel="count", title="Output voltage")
    axes[1].hist(ok.ea_offset_mv, bins=30, color=SERIES[1], edgecolor="white", linewidth=1)
    axes[1].set(xlabel="FB - VREF (mV)", title="EA input-referred error")
    axes[2].hist(ok[["pm_light_deg", "pm_heavy_deg"]].min(axis=1), bins=30, color=SERIES[2], edgecolor="white", linewidth=1)
    axes[2].axvline(45, color=MUTED, ls=":")
    axes[2].set(xlabel="worst-case PM (deg)", title="Phase margin")
    fig.suptitle(f"Monte Carlo ({len(ok)} samples, educational mismatch model) - {name}", fontsize=11)
    made = [_save(fig, out / "mc_histograms.png")]
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.hist(ok.i_tail_ua, bins=30, color=SERIES[3], edgecolor="white", linewidth=1)
    ax.set(xlabel="EA tail current (uA)", ylabel="count", title="Bias current variation")
    made.append(_save(fig, out / "mc_bias.png"))
    return made


def plot_comparison(base: dict, opt: dict, out: Path) -> Path:
    rows = comparison_rows(base, opt)
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    labels = [r[0] for r in rows]
    y = np.arange(len(rows))
    # normalise each metric to the baseline value (baseline = 1)
    rel = [r[2] / r[1] if r[1] else np.nan for r in rows]
    ax.barh(y, rel, color=SERIES[0], height=0.55)
    ax.axvline(1.0, color=MUTED, lw=1)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    for yi, (r, v) in enumerate(zip(rows, rel)):
        ax.text(v + 0.02, yi, f"{r[1]:.3g} -> {r[2]:.3g}", va="center", fontsize=8, color=INK)
    ax.set(xlabel="Optimized / baseline", title="Baseline vs optimized (tt, 27 C)")
    ax.set_xlim(0, max(1.6, np.nanmax(rel) + 0.5))
    return _save(fig, out / "baseline_vs_optimized.png")


def comparison_rows(base: dict, opt: dict) -> list[tuple[str, float, float]]:
    g = lambda m, *k: _dig(m, k)
    keys = [("Worst phase margin (deg)", ("pm_min_deg",)),
            ("Dropout @50 mA (V)", ("dropout_v", "50mA")),
            ("|Load reg| @2.5 V (mV/mA)", ("load_reg_mv_per_ma", "2.5V")),
            ("Quiescent current @3.3 V (uA)", ("iq_ua", "3.3V")),
            ("Load-step undershoot (mV)", ("load_transient", "undershoot_mv")),
            ("Load-release overshoot (mV)", ("load_transient", "overshoot_mv")),
            ("Line reg @1 mA (mV/V)", ("line_reg_mv_per_v", "1mA")),
            ("Efficiency 1.8 V, 1 mA (%)", ("efficiency_pct", "1.8V_1mA"))]
    return [(lab, abs(g(base, *k)), abs(g(opt, *k))) for lab, k in keys]


def _dig(m: dict, keys) -> float:
    for k in keys:
        m = m[k]
    return float(m)


def plot_sweeps(df: pd.DataFrame, out: Path) -> Path:
    """Small multiples: each swept parameter (rows) vs four key metrics (columns)."""
    params = list(dict.fromkeys(df.param))
    metrics = [("pm_min", "min PM (deg)"), ("dropout_v", "dropout @50 mA (V)"),
               ("load_reg_mv_per_ma", "load reg (mV/mA)"), ("iq_ua", "Iq (uA)")]
    fig, axes = plt.subplots(len(params), len(metrics), figsize=(11, 2.0 * len(params)), squeeze=False)
    for i, p in enumerate(params):
        s = df[(df.param == p) & (df.status == "ok")].sort_values("value")
        for j, (k, lab) in enumerate(metrics):
            ax = axes[i][j]
            ax.plot(s.value, s[k], marker="o", ms=3.5, color=SERIES[0])
            if i == 0:
                ax.set_title(lab)
            if j == 0:
                ax.set_ylabel(p)
            if p in ("rc", "cout_uf"):
                ax.set_xscale("log")
    fig.suptitle("One-at-a-time parameter sensitivity (tt, 27 C)", fontsize=11)
    return _save(fig, out / "sensitivity_sweeps.png")
