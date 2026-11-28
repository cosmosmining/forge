"""Safe formula evaluator and analytical transformer model.

Expected values are written out by hand from the architecture constants,
independently of claimcheck.transformer.
"""

import unittest

from claimcheck import formula as F
from claimcheck import registry as R
from claimcheck import transformer as T


class FormulaTests(unittest.TestCase):
    def test_arithmetic(self):
        self.assertAlmostEqual(F.evaluate("cycles * period_ns * 1e-6", {"cycles": 580000, "period_ns": 2.0}), 1.16)
        self.assertEqual(F.evaluate("min(a, b) + max(a, b) - abs(-a)", {"a": 2, "b": 5}), 5.0)
        self.assertEqual(F.evaluate("-(2 ** 10) / 4", {}), -256.0)

    def test_names(self):
        self.assertEqual(F.names_in("a * b + min(a, c)"), ["a", "b", "c"])

    def test_rejects_anything_but_arithmetic(self):
        for bad in ("__import__('os').system('echo hi')", "a.__class__", "[x for x in a]", "lambda: 1",
                    "a[0]", "open('x')", "a if b else c", "'s'", "True + 1", "2 ** 1000", "", "a ="):
            with self.subTest(bad=bad):
                with self.assertRaises(F.FormulaError):
                    F.evaluate(bad, {"a": 1, "b": 2, "c": 3})

    def test_unknown_input_and_division_by_zero(self):
        with self.assertRaises(F.FormulaError):
            F.evaluate("x + 1", {})
        with self.assertRaises(F.FormulaError):
            F.evaluate("1 / z", {"z": 0})


class TransformerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llama, cls.llama_rec = T.load_arch(R.MODELS_DIR, "llama-3-70b")
        cls.qwen, cls.qwen_rec = T.load_arch(R.MODELS_DIR, "qwen2.5-0.5b")

    def test_llama_params_hand_derived(self):
        embed = 128256 * 8192
        per_layer = 8192 * 8192 + 2 * 8192 * 1024 + 8192 * 8192 + 3 * 8192 * 28672 + 2 * 8192
        expected = embed + 80 * per_layer + 8192 + embed  # untied LM head
        self.assertEqual(T.param_breakdown(self.llama)["total"], expected)
        self.assertEqual(expected, 70553706496)

    def test_qwen_params_hand_derived(self):
        embed = 151936 * 896
        per_layer = (896 * 896 + 896) + 2 * (896 * 128 + 128) + 896 * 896 + 3 * 896 * 4864 + 2 * 896
        expected = embed + 24 * per_layer + 896  # tied LM head, q/k/v bias
        self.assertEqual(T.param_breakdown(self.qwen)["total"], expected)
        self.assertEqual(expected, 494032768)
        self.assertEqual(T.param_breakdown(self.qwen)["non_embedding"], 24 * per_layer + 896)

    def test_totals_match_the_nominal_sizes_in_the_names(self):
        self.assertLess(abs(T.param_breakdown(self.llama)["total"] / 70e9 - 1), 0.02)
        self.assertLess(abs(T.param_breakdown(self.qwen)["total"] / 0.5e9 - 1), 0.02)

    def test_request_flops_hand_derived(self):
        rf = T.request_flops(self.llama, 2048, 128)
        self.assertEqual(rf["positions"], 2175)
        linear = 2 * 80 * (2 * 8192 * 8192 + 2 * 8192 * 1024 + 3 * 8192 * 28672) * 2175
        head = 2 * 128256 * 8192 * 128
        attention = 4 * 80 * 8192 * (2175 * 2176 // 2)
        self.assertEqual(rf["total"], linear + head + attention)
        self.assertEqual(rf["total"], 304234377510912)
        self.assertLess(rf["attention"] / rf["total"], 0.03)

    def test_lm_head_on_prefill_option(self):
        a = T.request_flops(self.llama, 2048, 128)
        b = T.request_flops(self.llama, 2048, 128, lm_head_on_prefill=True)
        self.assertEqual(b["lm_head"] - a["lm_head"], 2 * 128256 * 8192 * 2047)

    def test_kv_and_streamed_bytes(self):
        self.assertEqual(T.kv_bytes_per_token(self.llama, 1), 2 * 80 * 8 * 128)
        self.assertEqual(T.streamed_weight_bytes(self.llama, 1),
                         80 * (2 * 8192 * 8192 + 2 * 8192 * 1024 + 3 * 8192 * 28672) + 128256 * 8192)

    def test_transcriptions_never_disagree(self):
        for rec in (self.llama_rec, self.qwen_rec):
            for field, vals, status in T.cross_check(rec):
                self.assertNotIn("DISAGREE", status, (rec["name"], field, vals))

    def test_bad_lengths(self):
        with self.assertRaises(ValueError):
            T.request_flops(self.llama, 0, 1)


if __name__ == "__main__":
    unittest.main()
