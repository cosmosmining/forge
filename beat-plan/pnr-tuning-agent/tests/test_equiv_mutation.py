"""The equivalence check must pass the golden netlist against itself and FAIL on a
one-gate logic change.  Needs yosys and the OpenROAD test tree (scripts/env.sh)."""
import os
import re
import shutil
from pathlib import Path

import pytest

from pnr_agent import equiv

TEST_DIR = os.environ.get("OPENROAD_TEST_DIR", "")
LIB = Path(os.environ.get("PNR_PLATFORM_DIR", "")) / "Nangate45_typ.lib"
GCD = Path(TEST_DIR) / "gcd_nangate45.v"

pytestmark = pytest.mark.skipif(not (shutil.which("yosys") and GCD.exists() and LIB.exists()),
                                reason="needs yosys + OpenROAD test tree (source scripts/env.sh)")


def test_identical_netlists_are_equivalent(tmp_path):
    r = equiv.check(GCD, GCD, "gcd", [LIB], tmp_path / "same")
    assert r.ok, r.message
    assert r.gold_states == r.gate_states > 0


def test_one_gate_mutation_is_caught(tmp_path):
    text = GCD.read_text()
    # swap the first NAND2_X1 for a NOR2_X1: same pin names (A1/A2/ZN), different logic
    m = re.search(r"\bNAND2_X1\b", text)
    assert m
    mutated = text[:m.start()] + "NOR2_X1" + text[m.end():]
    bad = tmp_path / "gcd_mutated.v"
    bad.write_text(mutated)
    r = equiv.check(GCD, bad, "gcd", [LIB], tmp_path / "mut")
    assert not r.ok, "a NAND->NOR change must not be reported equivalent"


def test_liberty_state_names():
    assert {"IQ", "IQN"} <= set(equiv.liberty_state_names(LIB))
