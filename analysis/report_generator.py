"""Design report (Markdown + self-contained HTML) built from saved simulation results."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import pandas as pd

from circuits.design_params import LIMITS, PROJECT_ROOT, SPEC, LDODesign
from circuits.ldo_topology import BLOCK_DESCRIPTIONS, component_table
from spice.ngspice_runner import ngspice_version

RESULTS = PROJECT_ROOT / "results"
REPORTS = PROJECT_ROOT / "reports"


def _f(x, fmt=".3g"):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return format(x, fmt)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def _load(name: str) -> dict | None:
    p = RESULTS / name / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_markdown(names=("baseline", "optimized"), img_prefix: str = "../results") -> str:
    final = "optimized" if (RESULTS / "optimized" / "metrics.json").exists() else "baseline"
    m = _load(final)
    d = LDODesign.from_dict(json.loads((RESULTS / final / "design.json").read_text()))
    md: list[str] = []
    md.append("# CMOS LDO Designer - Design Report\n")
    md.append(f"*Generated from ngspice {ngspice_version() or '?'} simulations with the open-source "
              f"SkyWater SKY130 5 V device models (`nfet/pfet_g5v0d10v5`). Final design: **{final}**.*\n")
    md.append("## 1. Circuit architecture\n")
    md.append(f"![schematic]({img_prefix}/schematic.png)\n")
    for b, t in BLOCK_DESCRIPTIONS.items():
        md.append(f"- **{b}** - {t}")
    md.append("\n## 2. Design specifications (targets)\n")
    md.append(_md_table(pd.DataFrame([
        ["Input voltage", "1.8 - 3.3 V"], ["Output voltage", "1.2 V"], ["Load current", "1 - 50 mA"],
        ["Reference", "0.6 V"], ["Output capacitor", "1 uF"],
        ["Acceptance limits", ", ".join(f"{k}={v}" for k, v in LIMITS.items())]], columns=["Parameter", "Target"])))
    md.append("\n## 3. Transistor sizing (final design)\n")
    ct = component_table(d)[["ref", "block", "type", "value", "nodes", "function"]]
    md.append(_md_table(ct))
    md.append(f"\nFeedback: R1 = {d.r1 / 1e3:g} k, R2 = {d.r2 / 1e3:g} k -> Vout = 0.6 x (1 + R1/R2) = {d.vout_ideal:.3f} V; "
              f"Cff = {d.cff * 1e12:.3g} pF, Rc = {d.rc:.3g} ohm, Cout = {d.cout * 1e6:g} uF, Iref = {d.iref * 1e6:.3g} uA.\n")
    sz = RESULTS / "sizing_pass_device.csv"
    if sz.exists():
        md.append("Pass-device fingers needed for 1.2 x 50 mA at Vin = 1.8 V, Vsd = 0.5 V, gate at 0.15 V (simulated per corner):\n")
        md.append(_md_table(pd.read_csv(sz).round(3)))
    md.append("\n## 4. Simulation results\n")
    for name in names:
        mm = _load(name)
        if not mm:
            continue
        lt = mm["load_transient"]
        md.append(f"### {name}\n")
        md.append(_md_table(pd.DataFrame([
            ["Vout (2.5 V, 10 mA)", f"{mm['op_nominal']['vout']:.4f} V"],
            ["Quiescent current (3.3 V, no load)", f"{mm['iq_ua']['3.3V']:.1f} uA"],
            ["Line regulation (1 mA / 50 mA)", f"{_f(mm['line_reg_mv_per_v']['1mA'])} / {_f(mm['line_reg_mv_per_v']['50mA'])} mV/V"],
            ["Load regulation (1.8/2.5/3.3 V)", " / ".join(_f(v) for v in mm["load_reg_mv_per_ma"].values()) + " mV/mA"],
            ["Dropout (1/10/50 mA)", " / ".join(_f(v) for v in mm["dropout_v"].values()) + " V"],
            ["Max load at 1.8 V (Vout >= 98 %)", f"{_f(mm['max_load_ma_at_1v8'])} mA"],
            ["Min phase margin / gain margin", f"{_f(mm['pm_min_deg'], '.1f')} deg / {_f(mm['gm_min_db'], '.1f')} dB"],
            ["EA DC gain / GBW (5 pF)", f"{_f(mm['error_amp']['dc_gain_db'], '.1f')} dB / {_f(mm['error_amp']['gbw_hz'] / 1e6)} MHz"],
            ["EA systematic offset", f"{_f(mm['error_amp']['systematic_offset_mv'])} mV"],
            ["PSRR @ DC / 1 kHz / 100 kHz", f"{_f(mm['closed_loop']['psrr_dc_db'], '.1f')} / {_f(mm['closed_loop']['psrr_1khz_db'], '.1f')} / {_f(mm['closed_loop']['psrr_100khz_db'], '.1f')} dB"],
            ["Load step 1->50->1 mA (2.5 V)", f"-{lt['undershoot_mv']:.1f} / +{lt['overshoot_mv']:.1f} mV, settling {_f(lt['settling_up_us'])} / {_f(lt['settling_down_us'])} us"],
            ["Efficiency 1.8 V @ 1 / 50 mA", f"{mm['efficiency_pct']['1.8V_1mA']:.1f} / {mm['efficiency_pct']['1.8V_50mA']:.1f} %"],
        ], columns=["Metric", "Value"])))
        md.append("")
    md.append("### Waveforms (final design)\n")
    for p in ("vin_vout", "line_regulation", "load_regulation", "dropout", "efficiency", "quiescent_current",
              "bode_loop", "closed_loop_psrr", "pm_vs_load", "pm_vs_rc", "tran_load_2v5", "tran_load_1v8", "tran_line"):
        md.append(f"![{p}]({img_prefix}/{final}/plots/{p}.png)")
    md.append("\n## 5. Performance analysis and stability\n")
    pz = m.get("poles_zeros", {})
    if pz:
        md.append(_md_table(pd.DataFrame([{"load": k, **{kk: _f(vv) for kk, vv in v.items()}} for k, v in pz.items()])))
    spec = RESULTS / "spec_compliance.csv"
    md.append("\n## 6. Validation against targets\n")
    if spec.exists():
        md.append(_md_table(pd.read_csv(spec).fillna("")))
    md.append("\n## 7. Optimization results\n")
    if (RESULTS / "baseline_vs_optimized.png").exists():
        md.append(f"![comparison]({img_prefix}/baseline_vs_optimized.png)\n")
    cmp_ = RESULTS / "comparison.csv"
    if cmp_.exists():
        md.append(_md_table(pd.read_csv(cmp_).round(4)))
    md.append("\n## 8. PVT and Monte Carlo\n")
    for f in ("pvt_vout", "pvt_pm", "mc_histograms", "mc_bias"):
        if (RESULTS / final / "plots" / f"{f}.png").exists():
            md.append(f"![{f}]({img_prefix}/{final}/plots/{f}.png)")
    for f in ("pvt_summary.json", "mc_summary.json"):
        p = RESULTS / final / f
        if p.exists():
            md.append(f"\n`{f}`:\n\n```json\n{p.read_text()}\n```")
    md.append("\n## 9. Known limitations\n")
    md.append(LIMITATIONS)
    return "\n".join(md) + "\n"


LIMITATIONS = """\
- **Reference and bias current are ideal sources.** A transistor-level bandgap needs SKY130 parasitic PNP
  models that are not in the bundled minimal model set; their spread is modelled statistically instead.
- **Compensation depends on a series resistance Rc (ESR) of roughly 0.3-1 ohm** in series with Cout. With a
  low-ESR ceramic capacitor (~10 mohm) the phase margin collapses (see `pm_vs_rc.png`); an explicit on-board
  series resistor or a different compensation scheme (e.g. buffered pass gate) is required in that case.
- **Monte Carlo statistics are educational assumptions** (A_VT = 8 mV.um, 0.25 % resistor, 0.5 % Vref,
  5 % Iref). The SKY130 g5v0d10v5 cards provide only global mismatch switches, so per-device foundry
  mismatch is not available in ngspice here.
- **No layout parasitics, no package/bond-wire inductance, no ESD, no current limit / thermal shutdown /
  soft start.** Resistors and capacitors are ideal (no voltage/temperature coefficients or corners).
- **Corners are device corners only** (tt/ff/ss/fs/sf from the PDK); results are pre-layout and not
  silicon-validated.
- Loop gain is measured by breaking the loop at the EA input with an L/C DC-closure; this includes the
  divider loading and is accurate at the frequencies of interest but is not a Middlebrook/Tian
  bilateral measurement.
"""


def _embed_images(html: str, base: Path) -> str:
    import re

    def repl(mo):
        src = mo.group(1)
        p = (base / src).resolve()
        if p.exists():
            return f'src="data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}"'
        return mo.group(0)

    return re.sub(r'src="([^"]+\.png)"', repl, html)


def write_report() -> dict[str, Path]:
    import markdown
    REPORTS.mkdir(exist_ok=True)
    md = build_markdown()
    p_md = REPORTS / "design_report.md"
    p_md.write_text(md)
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>CMOS LDO Design Report</title><style>"
        "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1060px;margin:2rem auto;"
        "padding:0 1rem;color:#1f1f1e;line-height:1.5}table{border-collapse:collapse;font-size:13px;margin:.6rem 0}"
        "td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}th{background:#f4f3ef}img{max-width:100%}"
        "code,pre{background:#f6f6f3;font-size:12px}pre{padding:.6rem;overflow:auto}</style></head><body>"
        + body + "</body></html>")
    p_html = REPORTS / "design_report.html"
    p_html.write_text(_embed_images(html, REPORTS))
    return {"md": p_md, "html": p_html}
