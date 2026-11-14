"""Netlist generation and design bookkeeping (no simulator needed)."""
import pytest

from circuits.design_params import DesignError, DeviceSize, LDODesign, OperatingPoint, check_bin, PMOS_MODEL
from circuits.feedback_network import resistor_ratio
from circuits.ldo_topology import build_ldo, component_table
from spice import netlist_generator as ng


def test_unique_refs_and_blocks():
    comps = build_ldo(LDODesign())
    refs = [c.ref for c in comps]
    assert len(refs) == len(set(refs))
    assert {"MPASS", "MP1", "MP2", "MN6", "MP9", "R1", "R2", "COUT", "RC", "VREF", "IREF"} <= set(refs)
    assert sum(c.is_mos for c in comps) == 13  # 3 bias + 9 error amplifier + 1 pass device


def test_feedback_ratio_gives_1v2():
    d = LDODesign()
    assert resistor_ratio(1.2, 0.6) == pytest.approx(1.0)
    assert d.vout_ideal == pytest.approx(1.2)


def test_bin_validation_rejects_unknown_geometry():
    check_bin(PMOS_MODEL, DeviceSize(20, 0.5, 10))
    with pytest.raises(DesignError):
        check_bin(PMOS_MODEL, DeviceSize(13, 0.5, 1))
    with pytest.raises(DesignError):
        LDODesign(pass_dev=DeviceSize(13, 0.5, 100)).validate()


def test_operating_point_validation():
    with pytest.raises(DesignError):
        OperatingPoint(corner="xx").validate()
    with pytest.raises(DesignError):
        OperatingPoint(vin=6.0).validate()


def test_netlists_contain_expected_elements():
    d, op = LDODesign(), OperatingPoint(2.5, 10e-3, 85, "ss")
    n = ng.op_netlist(d, op)
    assert '.lib "pdk/sky130_hv/sky130_hv.lib" ss' in n and ".temp 85" in n
    assert "XMPASS vout gate vin vin sky130_fd_pr__pfet_g5v0d10v5 w=20 l=0.5 m=170" in n
    loop = ng.ac_loop_netlist(d, op)
    assert "LBRK fb fbin 1G" in loop and "XMP2 d2 fbin tail tail" in loop
    assert "PWL" in ng.tran_load_netlist(d, op)
    with pytest.raises(ValueError):
        ng.dc_sweep_netlist(d, op, "temp", 0, 1, 0.1)


def test_mismatch_offset_inserts_source():
    d = LDODesign(mismatch_vos={"MP1": 1e-3})
    n = ng.op_netlist(d, OperatingPoint())
    assert "VOS_MP1 vref_mp1 vref DC 1.000000e-03" in n
    assert "XMP1 d1 vref_mp1 tail tail" in n


def test_design_roundtrip():
    d = LDODesign(name="x", rc=0.3, pass_dev=DeviceSize(20, 0.5, 222))
    d2 = LDODesign.from_dict(d.to_dict())
    assert d2 == d
    assert len(component_table(d)) == len(build_ldo(d))
