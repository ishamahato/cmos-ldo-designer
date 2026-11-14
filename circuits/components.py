"""Netlist element abstraction shared by every circuit block.

Each element carries a unique reference designator, the block it belongs to and
a one-line description of its function, so the SPICE netlist, the component
table in the dashboard and the report are all generated from the same data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .design_params import NMOS_MODEL, PMOS_MODEL, DeviceSize


@dataclass
class Component:
    ref: str                       # unique identifier, e.g. "MPASS", "R1"
    kind: str                      # nmos | pmos | R | C | I | V | L
    nodes: tuple[str, ...]         # MOS: (d, g, s, b); two-terminal: (p, n)
    value: Any = None              # passive value / source spec, or DeviceSize for MOS
    block: str = ""
    function: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mos(self) -> bool:
        return self.kind in ("nmos", "pmos")

    @property
    def model(self) -> str:
        return {"nmos": NMOS_MODEL, "pmos": PMOS_MODEL}.get(self.kind, "")

    @property
    def spice_name(self) -> str:
        """Instance name as it appears in the netlist (MOS are subcircuits -> X prefix)."""
        return f"X{self.ref}" if self.is_mos else self.ref

    def to_spice(self, gate_offset: float | None = None) -> list[str]:
        if self.is_mos:
            size: DeviceSize = self.value
            d, g, s, b = self.nodes
            lines: list[str] = []
            if gate_offset:  # Monte Carlo threshold mismatch modelled as a gate offset source
                gi = f"{g}_{self.ref.lower()}"
                lines.append(f"VOS_{self.ref} {gi} {g} DC {gate_offset:.6e}")
                g = gi
            lines.append(
                f"{self.spice_name} {d} {g} {s} {b} {self.model} "
                f"w={size.w:g} l={size.l:g} m={size.m:d}"
            )
            return lines
        p, n = self.nodes
        return [f"{self.ref} {p} {n} {self.value}"]

    def describe(self) -> dict[str, Any]:
        row: dict[str, Any] = {"ref": self.ref, "type": self.kind, "block": self.block,
                               "nodes": " ".join(self.nodes), "function": self.function}
        if self.is_mos:
            s: DeviceSize = self.value
            row.update(model=self.model, w_um=s.w, l_um=s.l, m=s.m, w_total_um=s.w_total,
                       value=f"{s.w:g}/{s.l:g} x{s.m}")
        else:
            row.update(model="", value=str(self.value))
        return row
