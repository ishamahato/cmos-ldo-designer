"""Compare simulated results against the design targets (Section 12 validation)."""
from __future__ import annotations

import math

import pandas as pd

from circuits.design_params import LIMITS


def _row(item, target, measured, ok, condition, note=""):
    return {"test": item, "target": target, "measured": measured,
            "result": ("PASS" if ok else "FAIL") if ok is not None else "INFO",
            "condition": condition, "note": note}


def spec_table(m: dict, pvt: dict | None = None, mc: dict | None = None) -> pd.DataFrame:
    L = LIMITS
    rows = []
    op = m["op_nominal"]
    rows.append(_row("1. Output voltage accuracy (nominal)", f"1.2 V +/- {L['vout_accuracy_pct']} %",
                     f"{op['vout']:.4f} V ({op['vout_error_pct']:+.2f} %)",
                     abs(op["vout_error_pct"]) <= L["vout_accuracy_pct"], "tt, 27 C, 2.5 V, 10 mA"))
    if pvt:
        s = pvt["summary"]
        rows.append(_row("1b. Output voltage accuracy (PVT)", f"+/- {L['vout_accuracy_pct']} %",
                         f"{s['vout_min']:.4f}-{s['vout_max']:.4f} V (max {s['vout_err_max_pct']:.2f} %)",
                         s["vout_err_max_pct"] <= L["vout_accuracy_pct"], "5 corners x 4 temps x 3 Vin x 2 loads",
                         f"worst: {s['worst_accuracy_condition']}"))
    lr = max(abs(v) for v in m["line_reg_mv_per_v"].values())
    rows.append(_row("2. Line regulation", f"<= {L['line_reg_max_mv_per_v']} mV/V", f"{lr:.3f} mV/V",
                     lr <= L["line_reg_max_mv_per_v"], "Vin 1.8-3.3 V, 1 & 50 mA"))
    ld = max(abs(v) for v in m["load_reg_mv_per_ma"].values())
    rows.append(_row("3. Load regulation", f"<= {L['load_reg_max_mv_per_ma']} mV/mA", f"{ld:.4f} mV/mA",
                     ld <= L["load_reg_max_mv_per_ma"], "1-50 mA, Vin = 1.8/2.5/3.3 V (worst)"))
    do = m["dropout_v"]["50mA"]
    rows.append(_row("4. Dropout voltage @ 50 mA", f"<= {L['dropout_max_v']} V", f"{do:.3f} V",
                     do <= L["dropout_max_v"], "tt, 27 C", "defined at Vout = 98 % of regulated value"))
    if pvt:
        dmax = pvt["summary"]["dropout_max_v"]
        rows.append(_row("4b. Dropout @ 50 mA (PVT worst)", f"<= {L['dropout_max_v']} V", f"{dmax:.3f} V",
                         dmax <= L["dropout_max_v"], "5 corners x 4 temps"))
    e = m["efficiency_pct"]
    rows.append(_row("5. Power efficiency", ">= 95 % of Vout/Vin limit at 50 mA",
                     f"{e['1.8V_50mA']:.1f} % @1.8 V/50 mA (limit 66.7 %), {e['3.3V_50mA']:.1f} % @3.3 V/50 mA (limit 36.4 %)",
                     e["1.8V_50mA"] >= 0.95 * 100 * 1.2 / 1.8,
                     "tt, 27 C", "LDO efficiency is bounded by Vout/Vin"))
    iq = max(m["iq_ua"].values())
    rows.append(_row("6. Quiescent current", f"<= {L['iq_max_ua']} uA", f"{iq:.1f} uA", iq <= L["iq_max_ua"],
                     "no load, Vin up to 3.3 V"))
    if pvt:
        rows.append(_row("6b. Quiescent current (PVT worst)", f"<= {L['iq_max_ua']} uA",
                         f"{pvt['summary']['iq_max_ua']:.1f} uA", pvt["summary"]["iq_max_ua"] <= L["iq_max_ua"],
                         "Vin = 3.3 V, all corners/temps"))
    rows.append(_row("7. Phase margin", f">= {L['phase_margin_min_deg']} deg", f"{m['pm_min_deg']:.1f} deg (min)",
                     m["pm_min_deg"] >= L["phase_margin_min_deg"], "tt, 9 Vin/load points"))
    if pvt:
        rows.append(_row("7b. Phase margin (PVT)", f">= {L['phase_margin_min_deg']} deg",
                         f"{pvt['summary']['pm_min_deg']:.1f} deg (min)",
                         pvt["summary"]["pm_min_deg"] >= L["phase_margin_min_deg"], "120 PVT points",
                         f"worst: {pvt['summary']['worst_pm_condition']}"))
    gm = m["gm_min_db"]
    rows.append(_row("8. Gain margin", f">= {L['gain_margin_min_db']} dB",
                     "no -180 deg crossing" if gm is None or (isinstance(gm, float) and math.isinf(gm)) else f"{gm:.1f} dB",
                     gm is None or gm >= L["gain_margin_min_db"], "tt, 9 Vin/load points"))
    t = m["load_transient"]
    dev = max(t["undershoot_mv"], t["overshoot_mv"])
    rows.append(_row("9. Load transient 1<->50 mA (1 us)", f"<= {L['load_step_dev_max_mv']} mV",
                     f"-{t['undershoot_mv']:.1f} / +{t['overshoot_mv']:.1f} mV, settle {t['settling_up_us']:.1f}/{t['settling_down_us']:.1f} us",
                     dev <= L["load_step_dev_max_mv"], "Vin = 2.5 V"))
    if pvt:
        g = pvt["grid"]
        g = g[(g.status == "ok") & (g.corner == "tt")]
        span = (g.vout.max() - g.vout.min()) * 1e3
        rows.append(_row("10. Temperature variation (tt)", "inside accuracy window",
                         f"Vout span {span:.1f} mV over -40..125 C, all Vin/loads", span / 1200 * 100 <= 2 * L["vout_accuracy_pct"],
                         "tt corner"))
    rows.append(_row("11. Parameter sensitivity", "documented", "see results/sweeps", None, "one-at-a-time sweeps"))
    if mc:
        s = mc["summary"]
        rows.append(_row("12. Monte Carlo yield", ">= 99 % (educational model)",
                         f"{s['yield_pct']:.1f} % (95 % CI {s['yield_ci95_pct'][0]:.1f}-{s['yield_ci95_pct'][1]:.1f} %), "
                         f"sigma(Vout) = {s['vout_sigma_mv']:.2f} mV",
                         s["yield_pct"] >= 99.0, f"{s['n_ok']} samples", "assumed mismatch statistics"))
    return pd.DataFrame(rows)
