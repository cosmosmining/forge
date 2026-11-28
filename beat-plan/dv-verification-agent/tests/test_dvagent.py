"""Unit tests for the DV agent. Run from beat-plan/dv-verification-agent:

    python3 -m unittest discover -s tests -v

The end-to-end tests need yosys, iverilog and verilator and are skipped without them.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from dvagent import compare, gm, manifest, mutate, stimulus, tools, vlex  # noqa: E402
from dvagent.introspect import Port  # noqa: E402

FIX = os.path.join(HERE, "selftest", "fixtures")


class TestGoldenHelpers(unittest.TestCase):
    def test_signed_unsigned(self):
        self.assertEqual(gm.to_signed(0xFF, 8), -1)
        self.assertEqual(gm.to_signed(0x7F, 8), 127)
        self.assertEqual(gm.to_unsigned(-1, 8), 0xFF)
        self.assertEqual(gm.wrap(2 ** 31, 32), -(2 ** 31))
        self.assertEqual(gm.wrap(-1, 4, signed=False), 15)

    def test_lanes_roundtrip(self):
        vals = [-128, 127, 0, -1]
        packed = gm.pack(vals, 8)
        self.assertEqual(packed, 0xFF007F80)
        self.assertEqual(gm.lanes(packed, 4, 8, signed=True), vals)
        self.assertEqual(gm.lanes(gm.to_signed(packed, 32), 4, 8, signed=True), vals)

    def test_rounding_and_saturation(self):
        self.assertEqual(gm.shift_round_half_up(5, 1), 3)
        self.assertEqual(gm.shift_round_half_up(-5, 1), -2)   # (-5 + 1) >> 1
        self.assertEqual(gm.shift_round_half_up(7, 0), 7)
        self.assertEqual(gm.sra(-7, 1), -4)
        self.assertEqual(gm.sat_signed(300, 8), 127)
        self.assertEqual(gm.sat_signed(-300, 8), -128)


class TestLexer(unittest.TestCase):
    SRC = ("module m(input signed [7:0] a); // comment with + and -\n"
           "  assign y = a >>> 2'd1 + 8'shF0 - '0; /* a+b\n */ `define F(x) \\\n x+1\n"
           "  wire z = W'(a) ? \"s+t\" : $signed(b);\nendmodule\n")

    def test_roundtrip_and_positions(self):
        toks = vlex.tokenize(self.SRC)
        self.assertEqual("".join(t.text for t in toks), self.SRC)
        sig = vlex.significant(toks)
        self.assertEqual(sig[0].text, "module")
        self.assertEqual((sig[0].line, sig[0].col), (1, 1))
        assign = next(t for t in sig if t.text == "assign")
        self.assertEqual((assign.line, assign.col), (2, 3))

    def test_comments_strings_directives_are_opaque(self):
        kinds = {t.text: t.kind for t in vlex.tokenize(self.SRC)}
        self.assertIn("// comment with + and -", kinds)
        self.assertEqual(kinds['"s+t"'], "string")
        self.assertTrue(any(k == "directive" and t.startswith("`define") for t, k in kinds.items()))

    def test_numbers(self):
        self.assertEqual(vlex.parse_number("8'shF0"), (8, True, "h", 0xF0))
        self.assertEqual(vlex.parse_number("127"), (None, True, None, 127))
        self.assertIsNone(vlex.parse_number("4'bx01"))
        self.assertEqual(vlex.format_number(5, False, "d", 2), "5'd2")


class TestMutation(unittest.TestCase):
    RTL = """module t (input logic clk, input logic rst_n, input logic signed [7:0] a, b,
               output logic signed [7:0] y);
  // a + b in a comment must not be mutated
  logic signed [8:0] s;
  assign s = a + b;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) y <= '0;
    else if (s > 9'sd127) y <= 8'sd127;
    else y <= (s < -9'sd128) ? -8'sd128 : s[7:0];
  end
endmodule
"""

    def gen(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.sv")
        with open(p, "w") as f:
            f.write(self.RTL)
        ms = mutate.generate(p)
        return p, ms, d

    def test_operators_present(self):
        p, ms, d = self.gen()
        try:
            ops = {m.op for m in ms}
            for op in ("AOR", "ROR", "CR", "IFN", "STMT", "EDGE", "SGN", "TERN", "UOD", "SLICE"):
                self.assertIn(op, ops)
        finally:
            shutil.rmtree(d)

    def test_single_point_and_outside_comments(self):
        p, ms, d = self.gen()
        try:
            for m in ms:
                new = m.apply(self.RTL)
                self.assertNotEqual(new, self.RTL, m.id)
                self.assertIn("// a + b in a comment must not be mutated", new, m.id)
            ids = [m.id for m in ms]
            self.assertEqual(len(ids), len(set(ids)))
        finally:
            shutil.rmtree(d)

    def test_nba_is_not_a_relational_operator(self):
        p, ms, d = self.gen()
        try:
            for m in ms:
                if m.op == "ROR":
                    self.assertNotEqual(m.old, "<=", f"NBA mutated as relational: {m.id}")
        finally:
            shutil.rmtree(d)

    def test_ternary_swap(self):
        p, ms, d = self.gen()
        try:
            t = [m for m in ms if m.op == "TERN"]
            self.assertEqual(len(t), 1)
            self.assertIn("? s[7:0] : -8'sd128", t[0].apply(self.RTL))
        finally:
            shutil.rmtree(d)

    def test_sample_is_deterministic(self):
        p, ms, d = self.gen()
        try:
            a = [m.id for m in mutate.sample(ms, 5, seed=3)]
            b = [m.id for m in mutate.sample(ms, 5, seed=3)]
            self.assertEqual(a, b)
            self.assertEqual(len(a), 5)
        finally:
            shutil.rmtree(d)


class TestCompare(unittest.TestCase):
    def test_bit_exact_and_hints(self):
        ports = [Port("y", "output", 8, True)]
        exp = [{"y": -128}, {"y": 5}, {"y": 3}, {"y": 0}]
        rows = [(0, ["80"]), (1, ["04"]), (2, ["xx"]), (3, ["00"]), (4, ["00"])]
        r = compare.compare(exp, rows, ports)
        self.assertEqual(r.mismatch_beats, 2)
        self.assertEqual(r.x_beats, 1)
        self.assertEqual(r.extra, 1)
        self.assertFalse(r.ok)
        self.assertIn("off by one", r.mismatches[0].hint)
        self.assertIn("X/Z", r.mismatches[1].hint)

    def test_missing(self):
        ports = [Port("y", "output", 4, False)]
        r = compare.compare([{"y": 1}, {"y": 2}], [(0, ["1"])], ports)
        self.assertEqual(r.missing, 1)


class TestStimulusAndManifest(unittest.TestCase):
    def test_corners_in_range(self):
        c = stimulus.scalar_corners(-128, 127, 8, True)
        self.assertIn(-128, c)
        self.assertIn(127, c)
        self.assertIn(0, c)
        self.assertTrue(all(-128 <= v <= 127 for v in c))
        c2 = stimulus.scalar_corners(0, 31, 5, False)
        self.assertTrue(all(0 <= v <= 31 for v in c2))

    def test_deterministic_and_ranges(self):
        m = manifest.load(os.path.join(FIX, "fx_requant", "manifest.toml"))
        ports = [Port("acc", "input", 32, True), Port("mult", "input", 16, False),
                 Port("shift", "input", 5, False), Port("zp", "input", 8, True), Port("y", "output", 8, True)]
        a = stimulus.build(m, ports, 7)
        b = stimulus.build(m, ports, 7)
        self.assertEqual(a.beats, b.beats)
        for bt in a.beats:
            self.assertTrue(-(2 ** 31) <= bt["acc"] < 2 ** 31)
            self.assertTrue(0 <= bt["shift"] <= 31)

    def test_manifest_rejects_waiver_without_reason(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(FIX, "fx_requant")
            for f in ("golden.py",):
                shutil.copy(os.path.join(src, f), d)
            os.makedirs(os.path.join(d, "rtl"))
            shutil.copy(os.path.join(src, "rtl", "fx_requant.sv"), os.path.join(d, "rtl"))
            with open(os.path.join(src, "manifest.toml")) as f:
                text = f.read()
            text += '\n[checks]\nwaivers = [ { code = "WIDTH", reason = "" } ]\n'
            with open(os.path.join(d, "manifest.toml"), "w") as f:
                f.write(text)
            with self.assertRaises(manifest.ManifestError):
                manifest.load(os.path.join(d, "manifest.toml"))
        finally:
            shutil.rmtree(d)


HAVE_TOOLS = not tools.require(["yosys", "iverilog", "vvp", "verilator"])


@unittest.skipUnless(HAVE_TOOLS, "needs yosys, iverilog and verilator")
class TestEndToEnd(unittest.TestCase):
    def test_clean_pass_and_injected_bug_fail(self):
        from dvagent import verify as V
        m = manifest.load(os.path.join(FIX, "fx_requant", "manifest.toml"))
        d = tempfile.mkdtemp()
        try:
            r = V.verify(m, V.Options(seed=11, simulators=["iverilog"], coverage=False), os.path.join(d, "clean"))
            self.assertEqual(r["verdict"], "PASS", r.get("reasons"))
            with open(m.rtl_paths[0]) as f:
                src = f.read().replace("assign zp_x   = {{42{zp[7]}}, zp};", "assign zp_x   = {42'd0, zp};")
            os.makedirs(os.path.join(d, "bug"))
            bug = os.path.join(d, "bug", "fx_requant.sv")
            with open(bug, "w") as f:
                f.write(src)
            r2 = V.verify(m, V.Options(seed=11, simulators=["iverilog"], coverage=False, rtl_override=[bug]),
                          os.path.join(d, "bugrun"))
            self.assertEqual(r2["verdict"], "FAIL")
            self.assertTrue(any("differ from the golden model" in x for x in r2["reasons"]))
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
