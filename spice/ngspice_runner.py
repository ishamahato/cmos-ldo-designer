"""Locate and execute ngspice in batch mode.

``run_netlist`` writes the netlist into a fresh temporary folder, links the PDK
next to it, runs ``ngspice -b`` and returns stdout plus every ``*.dat`` file
written by ``wrdata``.  Failures raise :class:`SimulationError` with the
relevant part of the log - results are never silently fabricated.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from circuits.design_params import PDK_DIR
from .result_parser import parse_prints, read_wrdata

log = logging.getLogger(__name__)

INSTALL_HELP = (
    "ngspice was not found. Install it:\n"
    "  macOS:  brew install ngspice\n"
    "  Ubuntu/Debian:  sudo apt-get install ngspice\n"
    "  Windows: download from https://ngspice.sourceforge.io and add it to PATH\n"
    "or set the NGSPICE environment variable to the executable path."
)
FATAL_PATTERNS = re.compile(
    r"(timestep too small|singular matrix|simulation\(s\) aborted|no such vector|"
    r"could not find a valid modelname|unknown subckt|error on line|fatal error|cannot open)",
    re.IGNORECASE,
)


class NgspiceNotFound(RuntimeError):
    pass


class SimulationError(RuntimeError):
    def __init__(self, msg: str, log_text: str = "", netlist: str = ""):
        super().__init__(msg)
        self.log_text = log_text
        self.netlist = netlist


def find_ngspice() -> str | None:
    env = os.environ.get("NGSPICE")
    if env and Path(env).exists():
        return env
    return shutil.which("ngspice")


def ngspice_version() -> str | None:
    exe = find_ngspice()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"ngspice-(\S+)", out)
    return m.group(1) if m else out.strip()[:60]


@dataclass
class SimResult:
    stdout: str
    values: dict[str, float] = field(default_factory=dict)
    data: dict[str, pd.DataFrame] = field(default_factory=dict)
    netlist: str = ""


def run_netlist(netlist: str, timeout: float = 300.0, keep_dir: Path | None = None) -> SimResult:
    exe = find_ngspice()
    if exe is None:
        raise NgspiceNotFound(INSTALL_HELP)
    tmp = Path(tempfile.mkdtemp(prefix="ldo_sim_"))
    try:
        try:
            (tmp / "pdk").symlink_to(PDK_DIR.parent, target_is_directory=True)
        except OSError:  # e.g. Windows without symlink privilege
            shutil.copytree(PDK_DIR.parent, tmp / "pdk")
        (tmp / "circuit.cir").write_text(netlist)
        try:
            # one OpenMP thread per ngspice: parallelism comes from running several
            # simulations at once (oversubscription made PVT/optimisation ~3x slower)
            env = {**os.environ, "OMP_NUM_THREADS": os.environ.get("LDO_OMP_THREADS", "1")}
            proc = subprocess.run([exe, "-b", "circuit.cir"], cwd=tmp, capture_output=True,
                                  text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise SimulationError(f"ngspice timed out after {timeout}s", netlist=netlist) from exc
        text = proc.stdout + "\n" + proc.stderr
        bad = FATAL_PATTERNS.search(text)
        if proc.returncode != 0 or bad:
            snippet = "\n".join(l for l in text.splitlines() if re.search("error|abort|singular|too small|cannot", l, re.I))[:2000]
            raise SimulationError(f"ngspice failed (rc={proc.returncode}): {snippet or text[-800:]}",
                                  log_text=text, netlist=netlist)
        data = {p.stem: read_wrdata(p) for p in tmp.glob("*.dat")}
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            (keep_dir / "circuit.cir").write_text(netlist)
            (keep_dir / "ngspice.log").write_text(text)
        return SimResult(stdout=text, values=parse_prints(text), data=data, netlist=netlist)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
