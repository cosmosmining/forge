"""Unit tests for generation, coverage, mutation-site finding and VCD reading.
Run:  python3 -m unittest -v tests.test_gen"""

import os
import re
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from forge_testgen import formal, gen, mutation  # noqa: E402
from forge_testgen.spec import Spec  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "specs")


def _tmp_spec(tmp, golden_src, extra=""):
    gpath = os.path.join(tmp, "g.py")
    with open(gpath, "w") as fh:
        fh.write(textwrap.dedent(golden_src))
    rtl = os.path.join(tmp, "dut.v")
    with open(rtl, "w") as fh:
        fh.write("module dut(input [7:0] a, input [3:0] s, output [7:0] y); assign y = a >> s; endmodule\n")
    spath = os.path.join(tmp, "s.toml")
    with open(spath, "w") as fh:
        fh.write(textwrap.dedent("""
            [block]
            name = "dut"
            top = "dut"
            kind = "comb"
            rtl = ["dut.v"]
            golden = "g.py:f"
            [[input]]
            name = "a"
            width = 8
            [[input]]
            name = "s"
            width = 4
            range = [0, 7]
            [[output]]
            name = "y"
            width = 8
            """) + textwrap.dedent(extra))
    return Spec(spath)


class GeneratorTest(unittest.TestCase):
    def test_pairwise_covers_all_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _tmp_spec(tmp, "def f(a, s):\n    return {'y': a >> s}\n")
            g = gen.Generator(spec, 3)
            params = [("p%d" % i, list(range(3))) for i in range(5)]
            rows = g._pairwise(params)
            for i in range(5):
                for j in range(i + 1, 5):
                    seen = {(r["p%d" % i], r["p%d" % j]) for r in rows}
                    self.assertEqual(len(seen), 9)
            self.assertLess(len(rows), 3 ** 5)

    def test_random_respects_ranges_and_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _tmp_spec(tmp, "def f(a, s):\n    return {'y': a >> s}\n",
                             '[constraints]\nexpr = ["a % 2 == 0 or s > 3"]\n')
            g = gen.Generator(spec, 5)
            for _, v in g.random(2000) + g.directed():
                self.assertTrue(0 <= v["s"] <= 7)
                self.assertTrue(v["a"] % 2 == 0 or v["s"] > 3, v)

    def test_directed_hits_field_corners(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _tmp_spec(tmp, "def f(a, s):\n    return {'y': a >> s}\n")
            g = gen.Generator(spec, 1)
            vecs = [v for _, v in g.directed()]
            self.assertTrue({0, 255} <= {v["a"] for v in vecs})
            self.assertTrue({0, 7} <= {v["s"] for v in vecs})

    def test_coverage_counts_golden_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _tmp_spec(tmp, """
                def f(a, s):
                    cover("shifted_out", a != 0 and (a >> s) == 0)
                    return {'y': a >> s}
                """)
            cov = gen.Coverage(spec)
            self.assertIn("golden.shifted_out", cov.all_bins)
            out, gcov = spec.model.evaluate({"a": 3, "s": 5})
            cov.add({"a": 3, "s": 5}, out, gcov, "t")
            self.assertEqual(cov.hits["golden.shifted_out"], 1)
            self.assertEqual(cov.hits["out.y.min"], 1)


class MutationTest(unittest.TestCase):
    def test_single_edit_and_no_comment_mutation(self):
        src = textwrap.dedent("""
            // a + b in a comment must not be mutated
            module m(input clk, input [3:0] a, input [3:0] b, output reg [4:0] q);
              wire [4:0] s = a + b;  /* also a - b here */
              always @(posedge clk) begin
                if (a < b) q <= s;
              end
            endmodule
            """)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "m.v")
            with open(p, "w") as fh:
                fh.write(src)
            muts = mutation.generate([p])
            self.assertTrue(muts)
            for m in muts:
                self.assertIn("// a + b in a comment must not be mutated", m.new_text)
                self.assertIn("/* also a - b here */", m.new_text)
                self.assertNotEqual(m.new_text, src)
            classes = {m.cls for m in muts}
            self.assertTrue({"arith", "relational", "condition", "dropped-update"} <= classes, classes)
            # port declarations are never mutated
            for m in muts:
                self.assertIn("input [3:0] a, input [3:0] b", m.new_text)


class VcdTest(unittest.TestCase):
    def test_read_vcd(self):
        text = textwrap.dedent("""
            $var integer 32 t smt_step $end
            $scope module top $end
            $var wire 8 n0 a $end
            $var wire 1 n1 v $end
            $upscope $end
            $enddefinitions $end
            #0
            b0 t
            b101 n0
            0n1
            #10
            b1 t
            1n1
            """)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "t.vcd")
            with open(p, "w") as fh:
                fh.write(text)
            sigs, steps = formal.read_vcd(p)
            self.assertEqual(sigs[("top", "a")], 8)
            self.assertEqual(steps[0][("top", "a")], 5)
            self.assertEqual(steps[1][("top", "a")], 5)  # carried forward
            self.assertEqual(steps[1][("top", "v")], 1)


class FixtureSpecsTest(unittest.TestCase):
    def test_fixture_specs_load(self):
        for name in ("requant", "argmax8", "sfifo", "dot4"):
            spec = Spec(os.path.join(FIX, name + ".toml"))
            self.assertTrue(spec.model.translate().stats()["output_fit_proven_by_intervals"])


if __name__ == "__main__":
    unittest.main()
