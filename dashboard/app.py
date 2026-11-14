"""CMOS LDO Designer - Streamlit engineering dashboard.

Run with:  streamlit run dashboard/app.py   (or  python run.py dashboard)
Saved results come from ``python run.py all``; the Simulation Laboratory runs
ngspice live.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.experiment_store import load_experiments, log_experiment  # noqa: E402
from circuits.design_params import CORNERS, DeviceSize, LDODesign, OperatingPoint  # noqa: E402
from circuits.ldo_topology import BLOCK_DESCRIPTIONS, component_table  # noqa: E402
from spice import ac_analysis, dc_analysis, transient_analysis  # noqa: E402
from spice.netlist_generator import full_netlist_for_display  # noqa: E402
from spice.ngspice_runner import NgspiceNotFound, SimulationError, find_ngspice, ngspice_version  # noqa: E402

RESULTS = ROOT / "results"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]

st.set_page_config(page_title="CMOS LDO Designer", layout="wide")


# ---------------------------------------------------------------- helpers
def available_designs() -> list[str]:
    return [p.name for p in sorted(RESULTS.glob("*")) if (p / "metrics.json").exists()]


@st.cache_data
def metrics(name: str) -> dict:
    return json.loads((RESULTS / name / "metrics.json").read_text())


@st.cache_data
def csv(name: str, file: str) -> pd.DataFrame | None:
    p = RESULTS / name / file
    return pd.read_csv(p) if p.exists() else None


def design_of(name: str) -> LDODesign:
    p = RESULTS / name / "design.json"
    return LDODesign.from_dict(json.loads(p.read_text())) if p.exists() else LDODesign()


def fig_base(title: str, x: str, y: str, logx: bool = False) -> go.Figure:
    f = go.Figure()
    f.update_layout(title=title, xaxis_title=x, yaxis_title=y, template="plotly_white", height=380,
                    margin=dict(l=50, r=20, t=50, b=40), hovermode="x unified",
                    legend=dict(orientation="h", y=-0.2))
    if logx:
        f.update_xaxes(type="log")
    return f


def bode(df: pd.DataFrame, label: str = "", fig=None, i: int = 0):
    fig = fig or make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06)
    ph = df.ph - 360 * (df.ph.iloc[0] / 360).round()
    fig.add_trace(go.Scatter(x=df.freq, y=df.mag, name=f"|T| {label}", line=dict(color=SERIES[i % 6], width=2)), 1, 1)
    fig.add_trace(go.Scatter(x=df.freq, y=ph, name=f"phase {label}", line=dict(color=SERIES[i % 6], width=2, dash="dot"),
                             showlegend=False), 2, 1)
    fig.update_xaxes(type="log", title_text="Frequency (Hz)", row=2, col=1)
    fig.update_xaxes(type="log", row=1, col=1)
    fig.update_yaxes(title_text="Loop gain (dB)", row=1, col=1)
    fig.update_yaxes(title_text="Phase (deg)", row=2, col=1)
    fig.update_layout(template="plotly_white", height=520, hovermode="x unified", margin=dict(t=30))
    return fig


# ---------------------------------------------------------------- sidebar
st.sidebar.title("CMOS LDO Designer")
st.sidebar.caption("Low-power voltage regulation - SKY130 5 V devices, ngspice")
page = st.sidebar.radio("Section", ["Overview", "Circuit Explorer", "Simulation Laboratory", "Visualization",
                                    "PVT & Monte Carlo", "Design Report", "Experiments"])
ng = find_ngspice()
st.sidebar.markdown(f"**ngspice:** {'`' + (ngspice_version() or '?') + '`' if ng else 'not found - live simulation disabled'}")
designs = available_designs()
if not designs:
    st.warning("No saved results yet. Run `python run.py all` (or at least `python run.py baseline`).")
default = "optimized" if "optimized" in designs else (designs[0] if designs else None)

# ---------------------------------------------------------------- Overview
if page == "Overview":
    st.title("Overview")
    if default:
        name = st.selectbox("Design", designs, index=designs.index(default))
        m = metrics(name)
        op = m["op_nominal"]
        c = st.columns(5)
        c[0].metric("Input voltage", f"{op['vin']:.2f} V")
        c[1].metric("Output voltage", f"{op['vout']:.4f} V", f"{op['vout_error_pct']:+.2f} %")
        c[2].metric("Load current", f"{op['iload'] * 1e3:.2f} mA")
        c[3].metric("Efficiency", f"{op['efficiency_pct']:.1f} %")
        c[4].metric("Ground current", f"{op['ignd'] * 1e6:.1f} uA")
        c = st.columns(5)
        c[0].metric("Dropout @50 mA", f"{m['dropout_v']['50mA']:.3f} V")
        c[1].metric("Quiescent current (3.3 V)", f"{m['iq_ua']['3.3V']:.1f} uA")
        c[2].metric("Min phase margin", f"{m['pm_min_deg']:.1f} deg")
        c[3].metric("Load-step undershoot", f"{m['load_transient']['undershoot_mv']:.1f} mV")
        c[4].metric("Simulation status", "OK" if ng else "offline (saved data)")
        st.caption(f"Nominal point: {m['corner']} corner, {m['temp']} C, Vin = 2.5 V, 10 mA resistive load.")
        sp = RESULTS / "spec_compliance.csv"
        if sp.exists():
            st.subheader("Validation against targets")
            st.dataframe(pd.read_csv(sp), width="stretch", hide_index=True)
        st.subheader("Circuit configuration")
        d = design_of(name)
        st.json({k: v for k, v in d.to_dict().items() if k not in ("mismatch_vos", "r_scale")}, expanded=False)

# ---------------------------------------------------------------- Circuit Explorer
elif page == "Circuit Explorer":
    st.title("Circuit Explorer")
    name = st.selectbox("Design", designs or ["baseline"])
    d = design_of(name)
    img = RESULTS / name / "plots" / "schematic.png"
    if img.exists():
        st.image(str(img), caption="Transistor-level schematic (net labels join nets with the same name)")
    for b, t in BLOCK_DESCRIPTIONS.items():
        st.markdown(f"**{b}** - {t}")
    tbl = component_table(d)
    blk = st.multiselect("Filter blocks", list(BLOCK_DESCRIPTIONS), default=list(BLOCK_DESCRIPTIONS))
    st.dataframe(tbl[tbl.block.isin(blk)], width="stretch", hide_index=True)
    dev = csv(name, "device_operating_points.csv")
    if dev is not None:
        st.subheader("Transistor operating points (2.5 V, 10 mA, tt, 27 C)")
        st.dataframe(dev, width="stretch", hide_index=True)
    st.subheader("Feedback connections")
    st.markdown(f"VOUT -> R1 ({d.r1 / 1e3:g} k) -> **FB** -> R2 ({d.r2 / 1e3:g} k) -> GND; FB drives MP2 "
                f"(non-inverting input), VREF drives MP1. Vout = Vref (1 + R1/R2) = {d.vout_ideal:.3f} V. "
                f"Cff = {d.cff * 1e12:.3g} pF across R1.")
    st.subheader("SPICE netlist")
    st.code(full_netlist_for_display(d), language="text")

# ---------------------------------------------------------------- Simulation Lab
elif page == "Simulation Laboratory":
    st.title("Simulation Laboratory")
    if not ng:
        st.error("ngspice not found - install it to run live simulations (brew install ngspice / apt install ngspice).")
    base = design_of(st.selectbox("Start from design", designs or ["baseline"]))
    with st.form("lab"):
        c1, c2, c3 = st.columns(3)
        vin = c1.slider("Input voltage (V)", 1.6, 3.6, 2.5, 0.05)
        iload = c1.slider("Load current (mA)", 0.0, 60.0, 10.0, 0.5) * 1e-3
        corner = c1.selectbox("Process corner", CORNERS)
        temp = c1.select_slider("Temperature (C)", [-40, 0, 27, 85, 125], 27)
        cout = c2.select_slider("Output capacitor (uF)", [0.47, 1.0, 2.2, 4.7, 10.0], base.cout * 1e6) * 1e-6
        rc = c2.number_input("Series Rc / ESR (ohm)", 0.001, 5.0, float(base.rc), 0.05, format="%.3f")
        cff = c2.number_input("Cff (pF)", 0.0, 100.0, float(base.cff * 1e12), 1.0)
        iref = c2.number_input("Iref (uA)", 0.5, 20.0, float(base.iref * 1e6), 0.5)
        pass_m = c3.number_input("Pass fingers (20/0.5 um each)", 20, 600, base.pass_dev.m, 10)
        pair_m = c3.number_input("Input-pair fingers (20/1 um)", 1, 10, base.pair.m)
        tail_m = c3.number_input("Tail fingers (20/1 um)", 1, 10, base.tail.m)
        analyses = c3.multiselect("Analyses", ["DC", "AC", "Transient"], ["DC", "AC"])
        label = c3.text_input("Configuration label", "lab_run")
        go_btn = st.form_submit_button("Run simulation", disabled=not ng)
    d = base.copy(name=label, cout=cout, rc=rc, cff=cff * 1e-12, iref=iref * 1e-6,
                  pass_dev=DeviceSize(base.pass_dev.w, base.pass_dev.l, int(pass_m)),
                  pair=DeviceSize(base.pair.w, base.pair.l, int(pair_m)),
                  tail=DeviceSize(base.tail.w, base.tail.l, int(tail_m)))
    op = OperatingPoint(vin, iload, float(temp), corner)
    if go_btn:
        res: dict = {}
        try:
            with st.spinner("Running ngspice ..."):
                if "DC" in analyses:
                    r = dc_analysis.operating_point(d, op, load="current")
                    res.update({k: r["summary"][k] for k in ("vout", "iin", "ignd", "efficiency_pct", "vgate")})
                    st.subheader("DC operating point")
                    c = st.columns(5)
                    c[0].metric("Vout", f"{r['summary']['vout']:.4f} V", f"{r['summary']['vout_error_pct']:+.2f} %")
                    c[1].metric("Iin", f"{r['summary']['iin'] * 1e3:.3f} mA")
                    c[2].metric("Ground current", f"{r['summary']['ignd'] * 1e6:.1f} uA")
                    c[3].metric("Efficiency", f"{r['summary']['efficiency_pct']:.1f} %")
                    c[4].metric("Pass gate", f"{r['summary']['vgate']:.3f} V")
                    st.dataframe(r["devices"], width="stretch", hide_index=True)
                    sw = dc_analysis.sweep(d, op, "vin", 1.0, 3.6, 0.02)
                    f = fig_base("Line sweep at this load", "Vin (V)", "Vout (V)")
                    f.add_trace(go.Scatter(x=sw.vin, y=sw.vout, name="Vout", line=dict(color=SERIES[0], width=2)))
                    st.plotly_chart(f, width="stretch")
                if "AC" in analyses:
                    lg = ac_analysis.loop_gain(d, op)
                    res.update(pm_deg=lg["phase_margin_deg"], gm_db=lg["gain_margin_db"], ugf_hz=lg["ugf_hz"])
                    st.subheader("Loop gain")
                    c = st.columns(4)
                    c[0].metric("Phase margin", f"{lg['phase_margin_deg']:.1f} deg")
                    c[1].metric("Gain margin", f"{lg['gain_margin_db']:.1f} dB")
                    c[2].metric("UGF", f"{lg['ugf_hz'] / 1e3:.1f} kHz")
                    c[3].metric("DC loop gain", f"{lg['dc_gain_db']:.1f} dB")
                    st.plotly_chart(bode(lg["data"], label), width="stretch")
                if "Transient" in analyses:
                    tr = transient_analysis.load_step(d, OperatingPoint(vin, 1e-3, float(temp), corner))
                    res.update(undershoot_mv=tr["undershoot_mv"], overshoot_mv=tr["overshoot_mv"])
                    st.subheader("Load step 1 -> 50 -> 1 mA")
                    f = fig_base("Load transient", "Time (us)", "Vout (mV)")
                    f.add_trace(go.Scatter(x=tr["data"].time * 1e6, y=tr["data"].vout * 1e3, name="Vout",
                                           line=dict(color=SERIES[0], width=2)))
                    st.plotly_chart(f, width="stretch")
                    st.write({k: round(v, 3) for k, v in tr.items() if isinstance(v, float)})
            log_experiment("dashboard", d.to_dict(), res, op.__dict__, tag=label)
            st.session_state.setdefault("configs", []).append({"label": label, "vin": vin, "iload_ma": iload * 1e3,
                                                               "corner": corner, "temp": temp, "cout_uf": cout * 1e6,
                                                               "rc": rc, "cff_pf": cff, "pass_m": pass_m, **res})
        except (SimulationError, NgspiceNotFound, ValueError) as exc:
            st.error(f"Simulation failed: {exc}")
    if st.session_state.get("configs"):
        st.subheader("Compare configurations (this session)")
        st.dataframe(pd.DataFrame(st.session_state["configs"]), width="stretch", hide_index=True)

# ---------------------------------------------------------------- Visualization
elif page == "Visualization":
    st.title("Visualization (saved simulation results)")
    sel = st.multiselect("Designs", designs, default=designs)
    tabs = st.tabs(["Vin-Vout & line", "Load regulation", "Bode", "Transient", "Efficiency & Iq", "Baseline vs optimized"])
    with tabs[0]:
        f = fig_base("Input vs output voltage (1 mA)", "Vin (V)", "Vout (V)")
        g = fig_base("Line regulation (1.8-3.3 V)", "Vin (V)", "Vout (mV)")
        for i, n in enumerate(sel):
            for j, il in enumerate(("1mA", "50mA")):
                df = csv(n, f"line_sweep_{il}.csv")
                if df is None:
                    continue
                f.add_trace(go.Scatter(x=df.vin, y=df.vout, name=f"{n} {il}", line=dict(color=SERIES[(2 * i + j) % 6], width=2)))
                s = df[(df.vin >= 1.8) & (df.vin <= 3.3)]
                g.add_trace(go.Scatter(x=s.vin, y=s.vout * 1e3, name=f"{n} {il}", line=dict(color=SERIES[(2 * i + j) % 6], width=2)))
        st.plotly_chart(f, width="stretch")
        st.plotly_chart(g, width="stretch")
    with tabs[1]:
        f = fig_base("Load regulation", "Iload (mA)", "Vout (mV)")
        for i, n in enumerate(sel):
            for j, v in enumerate(("1.8", "3.3")):
                df = csv(n, f"load_sweep_{v}V.csv")
                if df is not None:
                    f.add_trace(go.Scatter(x=df.iload * 1e3, y=df.vout * 1e3, name=f"{n} Vin={v} V",
                                           line=dict(color=SERIES[(2 * i + j) % 6], width=2)))
        st.plotly_chart(f, width="stretch")
    with tabs[2]:
        cond = st.selectbox("Condition", ["1.8V_1mA", "1.8V_50mA", "2.5V_10mA", "3.3V_1mA", "3.3V_50mA"])
        fig = None
        for i, n in enumerate(sel):
            df = csv(n, f"loop_{cond}.csv")
            if df is not None:
                fig = bode(df, n, fig, i)
                m = metrics(n)["loop"][cond]
                st.write(f"**{n}**: PM = {m['phase_margin_deg']:.1f} deg, GM = {m['gain_margin_db']:.1f} dB, "
                         f"UGF = {m['ugf_hz'] / 1e3:.1f} kHz, DC gain = {m['dc_gain_db']:.1f} dB")
        if fig:
            st.plotly_chart(fig, width="stretch")
        cl = csv(sel[0], "closed_loop.csv") if sel else None
        if cl is not None:
            f = fig_base(f"Closed-loop gain and PSRR ({sel[0]})", "Frequency (Hz)", "dB", logx=True)
            f.add_trace(go.Scatter(x=cl.freq, y=cl.acl, name="Vout/Vref", line=dict(color=SERIES[0], width=2)))
            f.add_trace(go.Scatter(x=cl.freq, y=cl.psrr, name="Vout/Vin (PSRR)", line=dict(color=SERIES[1], width=2)))
            st.plotly_chart(f, width="stretch")
    with tabs[3]:
        for fname, title in (("tran_load_2v5.csv", "Load step 1->50->1 mA, Vin 2.5 V"),
                             ("tran_load_1v8.csv", "Load step 1->50->1 mA, Vin 1.8 V"),
                             ("tran_line.csv", "Line step 1.8->3.3->1.8 V, 10 mA")):
            f = fig_base(title, "Time (us)", "Vout (mV)")
            for i, n in enumerate(sel):
                df = csv(n, fname)
                if df is not None:
                    f.add_trace(go.Scatter(x=df.time * 1e6, y=df.vout * 1e3, name=n, line=dict(color=SERIES[i], width=2)))
            st.plotly_chart(f, width="stretch")
    with tabs[4]:
        f = fig_base("Efficiency vs load", "Iload (mA)", "Efficiency (%)", logx=True)
        g = fig_base("Quiescent current vs Vin (no load)", "Vin (V)", "Iq (uA)")
        for i, n in enumerate(sel):
            df = csv(n, "efficiency_vs_load.csv")
            if df is not None:
                for j, v in enumerate((1.8, 3.3)):
                    s = df[(df.vin_set == v) & (df.iload > 0)]
                    f.add_trace(go.Scatter(x=s.iload * 1e3, y=s.efficiency_pct, name=f"{n} {v} V",
                                           line=dict(color=SERIES[(2 * i + j) % 6], width=2)))
            iq = csv(n, "iq_vs_vin.csv")
            if iq is not None:
                g.add_trace(go.Scatter(x=iq.vin, y=iq.iin * 1e6, name=n, line=dict(color=SERIES[i], width=2)))
        st.plotly_chart(f, width="stretch")
        st.plotly_chart(g, width="stretch")
    with tabs[5]:
        cp = RESULTS / "comparison.csv"
        if cp.exists():
            df = pd.read_csv(cp)
            st.dataframe(df, width="stretch", hide_index=True)
            f = go.Figure()
            f.add_trace(go.Bar(y=df.metric, x=df.baseline, name="baseline", orientation="h", marker_color=SERIES[0]))
            f.add_trace(go.Bar(y=df.metric, x=df.optimized, name="optimized", orientation="h", marker_color=SERIES[1]))
            f.update_layout(barmode="group", template="plotly_white", height=480, xaxis_type="log",
                            title="Baseline vs optimized (absolute values, log axis)")
            st.plotly_chart(f, width="stretch")
        else:
            st.info("Run `python run.py report` after optimisation to create the comparison.")

# ---------------------------------------------------------------- PVT & MC
elif page == "PVT & Monte Carlo":
    st.title("PVT and Monte Carlo verification")
    name = st.selectbox("Design", designs, index=designs.index(default) if default else 0)
    grid = csv(name, "pvt_grid.csv")
    if grid is not None:
        st.json(json.loads((RESULTS / name / "pvt_summary.json").read_text()), expanded=False)
        ok = grid[grid.status == "ok"]
        piv = ok.pivot_table(index=["corner", "temp"], columns=["vin", "iload"], values="vout")
        st.markdown("**Vout (V) per corner / temperature / Vin / load**")
        st.dataframe(piv.style.format("{:.4f}"), width="stretch")
        f = fig_base("Phase margin over PVT", "Temperature (C)", "PM (deg)")
        for i, c in enumerate(CORNERS):
            s = ok[ok.corner == c]
            f.add_trace(go.Scatter(x=s.temp, y=s.pm_deg, mode="markers", name=c, marker=dict(color=SERIES[i], size=9),
                                   text=[f"Vin={a} I={b * 1e3:g}mA" for a, b in zip(s.vin, s.iload)]))
        f.update_layout(hovermode="closest")
        st.plotly_chart(f, width="stretch")
        iqd = csv(name, "pvt_iq_dropout.csv")
        if iqd is not None:
            st.dataframe(iqd, width="stretch", hide_index=True)
    else:
        st.info("Run `python run.py pvt` first.")
    mc = csv(name, "mc_samples.csv")
    if mc is not None:
        st.subheader("Monte Carlo (educational mismatch statistics)")
        st.json(json.loads((RESULTS / name / "mc_summary.json").read_text()), expanded=False)
        ok = mc[mc.status == "ok"]
        cols = st.columns(3)
        for col, (k, lab) in zip(cols, (("vout", "Vout (V)"), ("ea_offset_mv", "FB - VREF (mV)"), ("i_tail_ua", "Tail current (uA)"))):
            f = go.Figure(go.Histogram(x=ok[k], nbinsx=30, marker_color=SERIES[0]))
            f.update_layout(template="plotly_white", height=300, title=lab, margin=dict(t=40))
            col.plotly_chart(f, width="stretch")

# ---------------------------------------------------------------- Report
elif page == "Design Report":
    st.title("Design report")
    if st.button("Regenerate report from saved results"):
        from analysis.report_generator import write_report
        write_report()
        st.success("Report regenerated.")
    md = ROOT / "reports" / "design_report.md"
    html = ROOT / "reports" / "design_report.html"
    if html.exists():
        st.download_button("Download HTML report (self-contained)", html.read_bytes(), "ldo_design_report.html", "text/html")
    if md.exists():
        st.download_button("Download Markdown report", md.read_bytes(), "ldo_design_report.md", "text/markdown")
        st.markdown(md.read_text().replace("../results", str(RESULTS)), unsafe_allow_html=False)
    else:
        st.info("Run `python run.py report` first.")

# ---------------------------------------------------------------- Experiments
elif page == "Experiments":
    st.title("Experiment database (SQLite)")
    df = load_experiments()
    st.write(f"{len(df)} experiments in experiments/experiments.db")
    kinds = st.multiselect("Kinds", sorted(df.kind.unique()) if len(df) else [], default=None)
    if kinds:
        df = df[df.kind.isin(kinds)]
    st.dataframe(df.drop(columns=["design_json"]).tail(500), width="stretch", hide_index=True)
    opt = load_experiments("optimizer")
    if len(opt):
        costs = [json.loads(m).get("cost") if m else None for m in opt.metrics_json]
        f = fig_base("Optimizer: cost per evaluation", "evaluation #", "cost (lower is better)")
        f.add_trace(go.Scatter(y=costs, mode="markers", marker=dict(color=SERIES[0], size=7), name="cost"))
        f.update_layout(hovermode="closest")
        st.plotly_chart(f, width="stretch")
