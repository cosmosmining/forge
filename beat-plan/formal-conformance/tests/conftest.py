import json
import shutil
import sys
from pathlib import Path

import pytest

FC = Path(__file__).resolve().parent.parent
for sub in ("", "formal", "conformance"):
    p = str(FC / sub) if sub else str(FC)
    if p not in sys.path:
        sys.path.insert(0, p)

from fc_common import find_tools  # noqa: E402

TOOLS = find_tools()
HAVE_EDA = bool(TOOLS["yosys"] and TOOLS["sby"] and shutil.which(TOOLS["solver"]))
needs_eda = pytest.mark.skipif(not HAVE_EDA, reason="yosys/sby/solver not installed")


@pytest.fixture
def scratch(request):
    """A scratch dir INSIDE the feature dir (evidence paths must stay relative to it).
    work/ is git-ignored."""
    d = FC / "work" / "pytest" / request.node.name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def spec_variant(scratch: Path, base: str, name: str, edit) -> Path:
    """Copy a committed spec, point its RTL at absolute paths, apply edit(spec)."""
    src = FC / "formal" / "specs" / f"{base}.json"
    spec = json.loads(src.read_text())
    spec["block"] = name
    spec["rtl"] = [str((src.parent / r).resolve()) for r in spec["rtl"]]
    edit(spec)
    out = scratch / f"{name}.json"
    out.write_text(json.dumps(spec, indent=1))
    return out
