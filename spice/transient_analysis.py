"""Load- and line-step transient simulations."""
from __future__ import annotations

from analysis.performance_metrics import step_metrics
from circuits.design_params import LDODesign, OperatingPoint
from .netlist_generator import tran_line_netlist, tran_load_netlist
from .ngspice_runner import run_netlist
from .result_parser import validate_frame

T_ON, T_OFF, T_STOP = 50e-6, 250e-6, 450e-6


def load_step(d: LDODesign, op: OperatingPoint, i_low: float = 1e-3, i_high: float = 50e-3,
              t_edge: float = 1e-6) -> dict:
    r = run_netlist(tran_load_netlist(d, op, i_low, i_high, t_edge, T_ON, T_OFF, T_STOP))
    df = r.data["tran"].rename(columns={"x": "time", "v(vout)": "vout", "v(gate)": "vgate"})
    validate_frame("load transient", df, 100)
    up = step_metrics(df.time.to_numpy(), df.vout.to_numpy(), T_ON, T_OFF, direction=-1)
    dn = step_metrics(df.time.to_numpy(), df.vout.to_numpy(), T_OFF, T_STOP, direction=+1)
    return {"data": df, "undershoot_mv": up.peak_deviation_mv, "overshoot_mv": dn.peak_deviation_mv,
            "settling_up_us": up.settling_time_us, "settling_down_us": dn.settling_time_us,
            "recovery_up_us": up.recovery_time_us, "recovery_down_us": dn.recovery_time_us,
            "ripple_mv": up.ripple_pp_mv, "vout_low_load": up.v_initial, "vout_high_load": up.v_final,
            "i_low": i_low, "i_high": i_high, "t_edge": t_edge}


def line_step(d: LDODesign, op: OperatingPoint, v_low: float = 2.5, v_high: float = 3.3,
              t_edge: float = 1e-6) -> dict:
    r = run_netlist(tran_line_netlist(d, op, v_low, v_high, t_edge, T_ON, T_OFF, T_STOP))
    df = r.data["tran"].rename(columns={"x": "time", "v(vout)": "vout", "v(vin)": "vin", "v(gate)": "vgate"})
    validate_frame("line transient", df, 100)
    up = step_metrics(df.time.to_numpy(), df.vout.to_numpy(), T_ON, T_OFF, direction=+1)
    dn = step_metrics(df.time.to_numpy(), df.vout.to_numpy(), T_OFF, T_STOP, direction=-1)
    return {"data": df, "line_overshoot_mv": up.peak_deviation_mv, "line_undershoot_mv": dn.peak_deviation_mv,
            "line_settling_us": up.settling_time_us, "v_low": v_low, "v_high": v_high}
