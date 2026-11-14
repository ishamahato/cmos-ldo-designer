import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spice.ngspice_runner import find_ngspice  # noqa: E402

requires_ngspice = pytest.mark.skipif(find_ngspice() is None, reason="ngspice not installed")
