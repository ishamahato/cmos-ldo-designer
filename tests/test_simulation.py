"""Integration tests: real ngspice runs on the SKY130 models (skipped without ngspice)."""
import pytest

from circuits.design_params import LDODesign, OperatingPoint
from spice import ac_analysis, dc_analysis, transient_analysis
from spice.ngspice_runner import SimulationError, run_netlist
from tests.conftest import requires_ngspice


@requires_ngspice
def test_operating_point_regulates():
    r = dc_analysis.operating_point(LDODesign(), OperatingPoint(2.5, 10e-3))
    s = r["summary"]
    assert abs(s["vout"] - 1.2) < 0.024           # within 2 %
    assert 0 < s["ignd"] < 100e-6
    assert s["iin"] > s["iload"]
    regions = dict(zip(r["devices"].ref, r["devices"].region))
    assert regions["MP1"] in ("saturation", "subthreshold")


@requires_ngspice
def test_loop_is_stable_at_nominal():
    lg = ac_analysis.loop_gain(LDODesign(), OperatingPoint(2.5, 10e-3))
    assert lg["stable"] and lg["phase_margin_deg"] > 45


@requires_ngspice
def test_low_esr_reduces_phase_margin():
    hi = ac_analysis.loop_gain(LDODesign(rc=0.5), OperatingPoint(3.3, 1e-3))["phase_margin_deg"]
    lo = ac_analysis.loop_gain(LDODesign(rc=0.01), OperatingPoint(3.3, 1e-3))["phase_margin_deg"]
    assert lo < hi


@requires_ngspice
def test_load_step_runs():
    r = transient_analysis.load_step(LDODesign(), OperatingPoint(2.5, 1e-3))
    assert 0 < r["undershoot_mv"] < 200


@requires_ngspice
def test_bad_netlist_raises():
    with pytest.raises(SimulationError):
        run_netlist("* broken\nXQ a b c d nosuchsubckt\n.control\nop\n.endc\n.end\n")
