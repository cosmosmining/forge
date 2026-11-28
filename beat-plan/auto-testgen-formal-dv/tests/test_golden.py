"""Differential tests of the golden-model translator.

For each small golden function: Python execution == translated graph
(Python semantics, with interval-soundness assertions) == Icarus simulation
of the emitted Verilog reference module.  Run:  python3 -m unittest -v tests.test_golden
"""

import os
import random
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from forge_testgen import golden, sim, tb, tools  # noqa: E402
from forge_testgen.golden import Field, GoldenModel, GoldenError  # noqa: E402

CASES = {
    "arith": ("""
        def f(a, b):
            return {"y": a * b - (a << 2) + (b >> 1)}
        """, [Field("a", 8, True), Field("b", 6, False)], [Field("y", 16, True)]),
    "varshift": ("""
        def f(x, s):
            return {"y": (x >> s) + (x << (s & 3)), "z": rshift_round(x, s)}
        """, [Field("x", 16, True), Field("s", 4, False)], [Field("y", 20, True), Field("z", 16, True)]),
    "satwrap": ("""
        def f(x):
            return {"s8": sat(x, 8), "u4": sat(x, 4, False), "w8": wrap(x, 8), "wu5": wrap(x, 5, signed=False)}
        """, [Field("x", 12, True)],
        [Field("s8", 8, True), Field("u4", 4, False), Field("w8", 8, True), Field("wu5", 5, False)]),
    "bitwise_neg": ("""
        def f(a, b):
            return {"y": (a & b) ^ (~a | b), "m": a % 8, "d": a // 4}
        """, [Field("a", 9, True), Field("b", 7, True)],
        [Field("y", 10, True), Field("m", 4, False), Field("d", 8, True)]),
    "boolops": ("""
        def f(a, b, c):
            t = a < b <= c
            u = (a > 0) and (b > 0) or not c
            v = a and b
            w = a or c
            return {"y": t + u * 2, "v": v, "w": w}
        """, [Field("a", 4, True), Field("b", 4, True), Field("c", 3, False)],
        [Field("y", 3, False), Field("v", 4, True), Field("w", 4, True)]),
    "ifmerge_helper": ("""
        LIMIT = 40
        def helper(v, k=3):
            if v > LIMIT:
                r = v - k
            elif v < -LIMIT:
                r = -v
            else:
                r = v * 2
            return r
        def f(a, b):
            x = helper(a)
            y = helper(b, 5)
            if x > y:
                x, y = y, x
            cover("swapped_order", a > b)
            return {"lo": x, "hi": y}
        """, [Field("a", 8, True), Field("b", 8, True)], [Field("lo", 10, True), Field("hi", 10, True)]),
    "vectors": ("""
        def f(a, w):
            prods = [a[i] * w[i] for i in range(4)]
            acc = 0
            for p in prods:
                acc += p
            best = 0
            for i in range(1, 4):
                if a[i] > a[best]:
                    best = i
            return {"dot": acc, "mx": max(a), "mn": min(a[1:]), "idx": best,
                    "absd": [abs(a[i] - w[i]) for i in range(4)], "s": sum(x >> 1 for x in a)}
        """, [Field("a", 8, True, count=4), Field("w", 8, True, count=4)],
        [Field("dot", 18, True), Field("mx", 8, True), Field("mn", 8, True), Field("idx", 2, False),
         Field("absd", 9, False, count=4), Field("s", 10, True)]),
}


def _vectors(gm, n, seed):
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        vec = {}
        for f in gm.inputs:
            def one():
                lo, hi = f.type_range()
                r = rnd.random()
                if r < 0.3:
                    return rnd.choice([lo, hi, 0, 1, -1 if lo < 0 else 1, lo + 1, hi - 1])
                return rnd.randint(lo, hi)
            vec[f.name] = [one() for _ in range(f.count)] if f.is_vector else one()
        out.append(vec)
    return out


class TranslatorTest(unittest.TestCase):
    def _model(self, tmp, name, src, ins, outs):
        path = os.path.join(tmp, "%s.py" % name)
        with open(path, "w") as fh:
            fh.write(textwrap.dedent(src))
        return GoldenModel(path, "f", ins, outs)

    def test_graph_matches_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, (src, ins, outs) in CASES.items():
                gm = self._model(tmp, name, src, ins, outs)
                tr = gm.translate()
                for vec in _vectors(gm, 3000, 1):
                    py_out, py_cov = gm.evaluate(vec)
                    g_out, g_cov, _, ok, _ = tr.evaluate(vec)
                    self.assertEqual(py_out, g_out, "%s %r" % (name, vec))
                    self.assertEqual(py_cov, g_cov, "%s covers %r" % (name, vec))
                    self.assertTrue(ok)

    @unittest.skipUnless(tools.which("iverilog"), "iverilog not installed")
    def test_verilog_matches_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, (src, ins, outs) in CASES.items():
                gm = self._model(tmp, name, src, ins, outs)
                tr = gm.translate()
                work = os.path.join(tmp, "sim_" + name)
                os.makedirs(work)
                ref = os.path.join(work, "ref.v")
                with open(ref, "w") as fh:
                    fh.write(tr.verilog("ref_" + name))
                vecs = _vectors(gm, 2000, 2)
                exp = [tb.pack(gm.outputs, gm.evaluate(v)[0]) for v in vecs]
                tb.write_hex(os.path.join(work, "stim.hex"), [tb.pack(gm.inputs, v) for v in vecs],
                             tb.total_bits(gm.inputs))
                tb.write_hex(os.path.join(work, "exp.hex"), exp, tb.total_bits(gm.outputs))
                extra = ["ok", "constraints_ok"] + ["gcov_%s" % k for k in tr.golden_covers]
                with open(os.path.join(work, "tb.v"), "w") as fh:
                    fh.write(tb.comb_tb("ref_" + name, gm.inputs, gm.outputs, len(vecs),
                                        port_of=lambda f: "g_" + f.name, extra_outputs=extra))
                res = sim.run(work, "tb.v", [ref])
                self.assertTrue(res.compiled, res.log[-2000:])
                self.assertTrue(res.ok, "%s: %s" % (name, res.first_messages or res.log[-1500:]))
                got = tb.read_hex(os.path.join(work, "got.hex"))
                self.assertEqual(got, exp, name)

    def test_rejects_unsupported(self):
        bad = {
            "division": "def f(a):\n    return {'y': a // 3}\n",
            "dyn_index": "def f(a, i):\n    return {'y': a[i:i+1]}\n",
            "while": "def f(a):\n    while a:\n        a -= 1\n    return {'y': a}\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, src in bad.items():
                ins = [Field("a", 8, True, count=4 if name == "dyn_index" else 1)]
                if name == "dyn_index":
                    ins.append(Field("i", 2, False))
                gm = self._model(tmp, name, src, ins, [Field("y", 8, True)])
                with self.assertRaises(GoldenError, msg=name):
                    gm.translate()


if __name__ == "__main__":
    unittest.main()
