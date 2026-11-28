"""End-to-end regression: correct fixture RTL passes (no false positive) and a
hand-injected bug is caught by simulation AND by a formal counterexample that
replays in simulation.  Needs yosys, sby, iverilog, bitwuzla on PATH.
Run:  python3 -m unittest -v tests.test_e2e   (about 30 s)"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from forge_testgen import campaign, tools  # noqa: E402

HAVE_TOOLS = all(tools.which(t) for t in ("yosys", "sby", "iverilog", "bitwuzla", "yosys-abc"))


def _copy_fixture(tmp, name, rtl_edit=None, spec_edit=None):
    """Copy a fixture spec + RTL + golden into tmp, optionally editing the RTL."""
    for sub in ("rtl", "golden", "specs"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)
    src = os.path.join(ROOT, "fixtures")
    shutil.copy(os.path.join(src, "golden", name + ".py"), os.path.join(tmp, "golden"))
    with open(os.path.join(src, "specs", name + ".toml")) as fh:
        spec_text = fh.read()
    if spec_edit:
        assert spec_edit[0] in spec_text, spec_edit[0]
        spec_text = spec_text.replace(spec_edit[0], spec_edit[1], 1)
    with open(os.path.join(tmp, "specs", name + ".toml"), "w") as fh:
        fh.write(spec_text)
    with open(os.path.join(src, "rtl", name + ".v")) as fh:
        text = fh.read()
    if rtl_edit:
        old, new = rtl_edit
        assert old in text, old
        text = text.replace(old, new, 1)
    with open(os.path.join(tmp, "rtl", name + ".v"), "w") as fh:
        fh.write(text)
    return os.path.join(tmp, "specs", name + ".toml")


@unittest.skipUnless(HAVE_TOOLS, "EDA tools not on PATH")
class EndToEnd(unittest.TestCase):
    def _run(self, name, edit=None, n_random=300, spec_edit=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        spec = _copy_fixture(tmp, name, edit, spec_edit)
        report, _ = campaign.run_block(spec, os.path.join(tmp, "run"), n_random=n_random)
        return report

    def test_comb_correct_passes_and_is_proven(self):
        r = self._run("requant")
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["formal"]["verdict"], "PROVEN")
        self.assertEqual(r["coverage"]["holes"], [])

    def test_comb_bug_caught_by_sim_and_confirmed_formal(self):
        r = self._run("requant", ("(prod + half) >>> shift", "prod >>> shift"))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any(not e["ok"] for e in r["simulation"].values()))
        self.assertEqual(r["formal"]["verdict"], "FAIL")
        self.assertTrue(r["formal"]["cex"]["confirmed"])

    def test_stream_correct_passes_and_is_proven(self):
        r = self._run("sfifo")
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["formal"]["verdict"], "PROVEN")
        self.assertEqual(r["formal"]["covers_unreached"], [])

    def test_stream_deadlock_bug_caught(self):
        # in_ready inverted: the FIFO never accepts anything (a liveness bug)
        r = self._run("sfifo", ("assign in_ready  = !full;", "assign in_ready  = full;"))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any(not e["ok"] for e in r["simulation"].values()))
        self.assertEqual(r["formal"]["verdict"], "FAIL")
        self.assertTrue(set(r["formal"]["failed"]) & {"a_input_progress", "a_accepts_below_capacity"},
                        r["formal"]["failed"])
        self.assertTrue(r["formal"]["cex"]["confirmed"])

    def test_stream_deadlock_caught_by_progress_property_alone(self):
        r = self._run("sfifo", ("assign in_ready  = !full;", "assign in_ready  = full;"),
                      spec_edit=("accepts_below_capacity = true", "accepts_below_capacity = false"))
        self.assertEqual(r["formal"]["verdict"], "FAIL")
        self.assertIn("a_input_progress", r["formal"]["failed"])
        self.assertTrue(r["formal"]["cex"]["confirmed"])

    def test_stream_data_bug_caught(self):
        # write data into the wrong slot
        r = self._run("sfifo", ("mem[wptr[1:0]] <= in_data;", "mem[rptr[1:0]] <= in_data;"))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["formal"]["verdict"], "FAIL")
        self.assertTrue(r["formal"]["cex"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
