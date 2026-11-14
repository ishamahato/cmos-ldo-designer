"""Metric extraction on synthetic data with known answers."""
import math

import numpy as np
import pytest

from analysis.performance_metrics import loop_metrics, step_metrics
from analysis.power_analysis import efficiency_pct
from analysis.regulation_analysis import dropout_voltage, line_regulation_mv_per_v, load_regulation_mv_per_ma
from spice.result_parser import operating_region, parse_prints


def test_loop_metrics_two_pole():
    # T(s) = A0 / ((1+s/p1)(1+s/p2)) with known PM
    f = np.logspace(0, 9, 4000)
    a0, p1, p2 = 1000.0, 100.0, 1e6
    t = a0 / ((1 + 1j * f / p1) * (1 + 1j * f / p2))
    m = loop_metrics(f, 20 * np.log10(abs(t)), np.unwrap(np.angle(t)) * 180 / np.pi)
    # analytic: |T| = 1 near 7.86e4 Hz -> PM = 180 - atan(ugf/p1) - atan(ugf/p2)
    ugf = m.ugf_hz
    pm_exact = 180 - math.degrees(math.atan(ugf / p1)) - math.degrees(math.atan(ugf / p2))
    assert m.phase_margin_deg == pytest.approx(pm_exact, abs=0.2)
    assert m.dc_gain_db == pytest.approx(60, abs=0.01)
    assert math.isinf(m.gain_margin_db)  # two-pole system never reaches -180
    assert m.stable


def test_step_metrics_first_order_dip():
    t = np.linspace(0, 200e-6, 20001)
    v = np.where(t < 50e-6, 1.2, 1.19 - 0.02 * np.exp(-(t - 50e-6) / 2e-6))
    s = step_metrics(t, v, 50e-6, 200e-6, band=1e-3, direction=-1)
    assert s.peak_deviation_mv == pytest.approx(30, abs=0.1)
    assert s.settling_time_us == pytest.approx(2e-6 * math.log(20) * 1e6, rel=0.02)


def test_efficiency_and_regulation():
    assert float(efficiency_pct(1.8, 0.05, 1.2, 0.05)) == pytest.approx(66.667, abs=1e-3)
    vin = np.linspace(1.0, 3.3, 231)
    vout = np.minimum(vin - 0.4, 1.2 + 0.001 * (vin - 1.8))
    assert line_regulation_mv_per_v(vin, vout, 1.8, 3.3) == pytest.approx(1.0, abs=1e-6)
    d = dropout_voltage(vin, vout, 0.02)
    assert d["dropout_v"] == pytest.approx(0.4, abs=1e-3)
    assert load_regulation_mv_per_ma([0.001, 0.05], [1.2, 1.19], 0.001, 0.05) == pytest.approx(-10 / 49, rel=1e-6)


def test_parser_and_region():
    v = parse_prints("v(vout) = 1.199000e+00\n@m.xmpass.mfoo[gm] = 8.2e-02\nnoise line\n")
    assert v == {"v(vout)": 1.199, "@m.xmpass.mfoo[gm]": 0.082}
    assert operating_region({"vgs": -1.4, "vds": -0.6, "vth": 0.95, "vdsat": 0.3}) == "saturation"
    assert operating_region({"vgs": -1.6, "vds": -0.1, "vth": 0.95, "vdsat": 0.5}) == "triode"
    assert operating_region({"vgs": 0.5, "vds": 1.0, "vth": 0.8, "vdsat": 0.1}) == "subthreshold"
