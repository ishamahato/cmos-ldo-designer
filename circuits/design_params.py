"""Design parameters, operating conditions and PDK bookkeeping for the CMOS LDO.

Everything that defines a circuit instance lives here, so an experiment can be
reproduced from a single JSON dictionary (see ``LDODesign.to_dict``).

Units: transistor W/L in micrometres (the SKY130 model files use
``.option scale=1.0u``), resistances in ohms, capacitances in farads,
currents in amperes, voltages in volts, temperatures in degrees Celsius.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDK_DIR = PROJECT_ROOT / "pdk" / "sky130_hv"
PDK_LIB = PDK_DIR / "sky130_hv.lib"

NMOS_MODEL = "sky130_fd_pr__nfet_g5v0d10v5"
PMOS_MODEL = "sky130_fd_pr__pfet_g5v0d10v5"
CORNERS: tuple[str, ...] = ("tt", "ff", "ss", "fs", "sf")

# Design targets from the project specification (targets, not results).
SPEC = {
    "vin_min": 1.8,
    "vin_max": 3.3,
    "vout_nom": 1.2,
    "iload_max": 50e-3,
    "iload_min": 1e-3,
    "vref": 0.6,
    "cout": 1e-6,
}

# Acceptance limits used by the validation step.  They are engineering
# choices for this educational design and are documented in the README.
LIMITS = {
    "vout_accuracy_pct": 2.0,        # |Vout - 1.2| / 1.2 over the whole PVT space
    "phase_margin_min_deg": 45.0,
    "gain_margin_min_db": 10.0,
    "line_reg_max_mv_per_v": 10.0,
    "load_reg_max_mv_per_ma": 0.5,
    "dropout_max_v": 0.6,            # must be <= 0.6 V to regulate at Vin = 1.8 V
    "iq_max_ua": 100.0,
    "load_step_dev_max_mv": 60.0,    # 5 % of Vout for a 1 -> 50 mA step
}


class DesignError(ValueError):
    """Raised when a design or operating point is physically invalid."""


@dataclass(frozen=True)
class DeviceSize:
    """Per-finger width ``w`` and length ``l`` in um, ``m`` parallel fingers."""

    w: float
    l: float
    m: int = 1

    @property
    def w_total(self) -> float:
        return self.w * self.m

    @property
    def aspect(self) -> float:
        return self.w * self.m / self.l


@lru_cache(maxsize=None)
def model_bins(model: str) -> frozenset[tuple[float, float]]:
    """(W, L) bin centres provided by the PDK for ``model``."""
    path = PDK_DIR / model.replace("sky130_fd_pr__", "") / f"{model}.bins.csv"
    with path.open() as fh:
        return frozenset((float(r["W"]), float(r["L"])) for r in csv.DictReader(fh))


def check_bin(model: str, size: DeviceSize) -> None:
    """The SKY130 BSIM4 cards are binned; only characterised (W, L) pairs are valid."""
    if (round(size.w, 3), round(size.l, 3)) not in model_bins(model):
        raise DesignError(
            f"{model}: W={size.w} um, L={size.l} um is not a characterised PDK bin. "
            f"Valid pairs: {sorted(model_bins(model))}"
        )
    if size.m < 1:
        raise DesignError(f"multiplicity must be >= 1, got {size.m}")


@dataclass
class LDODesign:
    """Every sizing and component value of the regulator."""

    name: str = "baseline"
    vref: float = 0.6
    iref: float = 5e-6                      # reference current into MNB1
    mnb: DeviceSize = DeviceSize(5.0, 1.0, 1)       # MNB1/MNB2 NMOS bias mirror
    mpb: DeviceSize = DeviceSize(20.0, 1.0, 1)      # MPB1 PMOS bias diode
    tail: DeviceSize = DeviceSize(20.0, 1.0, 2)     # MP5 tail current source
    pair: DeviceSize = DeviceSize(20.0, 1.0, 2)     # MP1/MP2 input pair
    nload: DeviceSize = DeviceSize(5.0, 1.0, 1)     # MN3/MN4 diode loads
    nmirror: DeviceSize = DeviceSize(5.0, 1.0, 1)   # MN6/MN7 output mirrors (B factor)
    pmirror: DeviceSize = DeviceSize(20.0, 1.0, 1)  # MP8/MP9 output PMOS mirror
    pass_dev: DeviceSize = DeviceSize(20.0, 0.5, 170)  # MPASS
    r1: float = 120e3                       # Vout -> FB
    r2: float = 120e3                       # FB -> GND
    cff: float = 10e-12                     # feed-forward cap across R1
    cout: float = 1e-6
    rc: float = 0.5                         # series compensation resistance (ESR) of Cout
    mismatch_vos: dict[str, float] = field(default_factory=dict)  # Monte Carlo gate offsets
    r_scale: tuple[float, float] = (1.0, 1.0)  # Monte Carlo resistor errors (R1, R2)

    # ----------------------------------------------------------------- derived
    @property
    def vout_ideal(self) -> float:
        return self.vref * (1.0 + self.r1 / self.r2)

    @property
    def mirror_ratio(self) -> float:
        """Current gain B of the symmetrical OTA output mirrors."""
        return (self.nmirror.aspect / self.nload.aspect)

    @property
    def tail_current(self) -> float:
        """Ideal (lambda = 0) tail current from the mirror ratios."""
        # MNB1 -> MNB2 is 1:1 (same DeviceSize), MPB1 -> MP5 is tail/mpb.
        return self.iref * (self.tail.aspect / self.mpb.aspect)

    def validate(self) -> None:
        for attr, model in (("mnb", NMOS_MODEL), ("nload", NMOS_MODEL), ("nmirror", NMOS_MODEL),
                            ("mpb", PMOS_MODEL), ("tail", PMOS_MODEL), ("pair", PMOS_MODEL),
                            ("pmirror", PMOS_MODEL), ("pass_dev", PMOS_MODEL)):
            check_bin(model, getattr(self, attr))
        for attr in ("r1", "r2", "cout", "iref"):
            if getattr(self, attr) <= 0:
                raise DesignError(f"{attr} must be positive")
        if self.rc < 0 or self.cff < 0:
            raise DesignError("rc and cff must be non-negative")

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["r_scale"] = list(self.r_scale)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LDODesign":
        kw: dict[str, Any] = {}
        names = {f.name for f in fields(cls)}
        for k, v in d.items():
            if k not in names:
                continue
            if isinstance(v, dict) and {"w", "l", "m"} <= set(v):
                v = DeviceSize(float(v["w"]), float(v["l"]), int(v["m"]))
            if k == "r_scale":
                v = tuple(v)
            kw[k] = v
        return cls(**kw)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def copy(self, **changes: Any) -> "LDODesign":
        return replace(self, **changes)


@dataclass(frozen=True)
class OperatingPoint:
    vin: float = 2.5
    iload: float = 10e-3
    temp: float = 27.0
    corner: str = "tt"

    def validate(self) -> None:
        if self.corner not in CORNERS:
            raise DesignError(f"unknown corner {self.corner!r}; available: {CORNERS}")
        if not 0.0 < self.vin <= 5.0:
            raise DesignError("vin must be in (0, 5] V for the 5 V SKY130 devices")
        if self.iload < 0:
            raise DesignError("iload must be >= 0")
        if not -55 <= self.temp <= 150:
            raise DesignError("temperature outside model validity range")
