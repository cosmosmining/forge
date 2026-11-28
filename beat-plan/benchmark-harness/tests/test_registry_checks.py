"""Registry rules (labels, locks, evidence) and the checks built on them."""

import copy
import hashlib
import os
import tempfile
import unittest

from claimcheck import checks as C
from claimcheck import formula as F
from claimcheck import labels as L
from claimcheck import registry as R

LOCKED = "forge.beatplan.tokps_474713"


def mutated(fn):
    reg = R.load()
    data = copy.deepcopy(reg.data)
    fn(data)
    return R.Registry(data, reg.path)


def number(data, nid):
    return next(n for n in data["numbers"] if n["id"] == nid)


def codes(reg, repo_root=R.REPO_ROOT):
    return {f["code"] for f in R.errors(R.validate(reg, repo_root))}


class RegistryRuleTests(unittest.TestCase):
    def test_shipped_registry_has_no_errors(self):
        findings = R.validate(R.load())
        self.assertEqual(R.errors(findings), [], findings)

    def test_every_number_has_label_source_method(self):
        reg = R.load()
        for nid in reg.order:
            n = reg.numbers[nid]
            self.assertIn(n["label"], L.ALL_LABELS, nid)
            self.assertTrue(n["source"], nid)
            self.assertTrue(n["method"], nid)

    def test_474713_is_modelled_and_locked(self):
        n = R.load().numbers[LOCKED]
        self.assertEqual(n["value"], 474713)
        self.assertEqual(n["label"], L.MODELLED)
        self.assertEqual(n["basis"], "arithmetic")
        self.assertEqual(n["label_lock"]["label"], L.MODELLED)

    def test_relabelling_474713_as_measured_is_refused(self):
        reg = mutated(lambda d: number(d, LOCKED).update(label="MEASURED"))
        self.assertTrue({"LABEL-LOCK", "MEASURED-WITHOUT-RUN", "MEASURED-WITHOUT-EVIDENCE"} <= codes(reg))

    def test_lock_holds_even_with_plausible_evidence_fields(self):
        def f(d):
            number(d, LOCKED).update(label="MEASURED", measured_on="FPGA",
                                     evidence={"status": "run-record", "run_id": "x"})
        self.assertIn("LABEL-LOCK", codes(mutated(f)))

    def test_vendor_claim_cannot_be_relabelled_measured_quietly(self):
        reg = mutated(lambda d: number(d, "etched.sohu.server_tokps").update(label="MEASURED"))
        self.assertTrue({"MEASURED-WITHOUT-RUN", "MEASURED-WITHOUT-EVIDENCE"} <= codes(reg))

    def test_computed_number_cannot_be_measured(self):
        def f(d):
            number(d, "forge.harness.tokps_qwen05b_1engine_b1").update(
                label="MEASURED", measured_on="x", evidence={"status": "not-in-checkout"})
        self.assertIn("COMPUTED-AS-MEASURED", codes(mutated(f)))

    def test_vendor_claim_needs_vendor_and_quote(self):
        def f(d):
            n = number(d, "etched.sohu.server_tokps")
            del n["quote"], n["stated_by"]
        self.assertTrue({"CLAIM-WITHOUT-QUOTE", "CLAIM-WITHOUT-VENDOR"} <= codes(mutated(f)))

    def test_not_yet_must_stay_empty(self):
        reg = mutated(lambda d: number(d, "forge.site.fpga_tokps").update(value=1000))
        self.assertIn("NOT-YET-HAS-VALUE", codes(reg))

    def test_unlabelled_or_unsourced_number_refused(self):
        def f(d):
            d["numbers"].append({"id": "x.unlabelled", "what": "w", "value": 1, "unit": "tok/s",
                                 "source": ["SRC-SITE"], "method": "m"})
            d["numbers"].append({"id": "x.unsourced", "what": "w", "value": 1, "unit": "tok/s",
                                 "label": "MODELLED", "basis": "arithmetic", "source": [], "method": "m"})
        got = codes(mutated(f))
        self.assertIn("BAD-LABEL", got)
        self.assertIn("NO-SOURCE", got)

    def test_formula_inputs_must_resolve(self):
        def f(d):
            number(d, "forge.harness.tokps_qwen05b_1engine_b1")["inputs"] = {"t_ms": "no.such.number"}
        self.assertIn("UNKNOWN-REF", codes(mutated(f)))

    def test_evidence_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "log.txt"), "w") as fh:
                fh.write("tool output\n")
            good = hashlib.sha256(b"tool output\n").hexdigest()

            def with_hash(h):
                def f(d):
                    d["numbers"].append({"id": "x.measured", "what": "w", "value": 1, "unit": "cycles",
                                         "label": "MEASURED", "measured_on": "RTL simulation", "source": ["SRC-SITE"],
                                         "method": "m", "evidence": {"status": "present", "path": "log.txt", "sha256": h}})
                return mutated(f)
            self.assertIn("EVIDENCE-MISMATCH", codes(with_hash("0" * 64), root))
            self.assertNotIn("EVIDENCE-MISMATCH", codes(with_hash(good), root))

    def test_site_source_unchanged(self):
        got = {f["code"] for f in R.validate(R.load())}
        self.assertNotIn("SOURCE-FILE-CHANGED", got)
        self.assertNotIn("SOURCE-FILE-MISSING", got)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = R.load()
        cls.out = C.run_all(cls.reg)

    def row(self, key, rid):
        return next(r for r in self.out[key] if r["id"] == rid)

    def test_site_arithmetic_reproduces(self):
        r = self.row("reproduce", "forge.site.time_per_token_qwen05b_ms")
        self.assertEqual(r["status"], "REPRODUCED")
        self.assertAlmostEqual(r["recomputed"], 1.16)
        self.assertEqual(r["label"], L.MODELLED)

    def test_474713_cannot_be_reproduced_here(self):
        self.assertEqual(self.row("reproduce", LOCKED)["status"], "NOT REPRODUCIBLE")

    def test_computed_values(self):
        self.assertAlmostEqual(self.row("reproduce", "forge.harness.tokps_qwen05b_1engine_b1")["recomputed"], 1000 / 1.16)
        self.assertEqual(self.row("reproduce", "nvidia.h100sxm.fp8_dense_tflops")["recomputed"], 1979.0)
        self.assertEqual(self.row("reproduce", "nvidia.h100sxm.fp8_dense_tflops")["rests_on"], [L.VENDOR_CLAIM])

    def test_mismatch_is_detected(self):
        reg = mutated(lambda d: number(d, "forge.site.time_per_token_qwen05b_ms").update(value=1.30))
        r = next(x for x in C.reproduce(reg, C.Resolver(reg)) if x["id"] == "forge.site.time_per_token_qwen05b_ms")
        self.assertEqual(r["status"], "MISMATCH")

    def test_474713_vs_etched_is_not_a_measured_comparison(self):
        r = self.row("compare", "CMP-474713-VS-ETCHED")
        self.assertEqual(r["verdict"], "COMPARABILITY UNVERIFIED")
        self.assertTrue(r["measured"].startswith("NOT A MEASURED COMPARISON"))
        self.assertEqual(r["ratio_label"], L.MODELLED)
        self.assertAlmostEqual(r["ratio"], 474713 / 500000)

    def test_qwen_engine_vs_etched_is_not_comparable(self):
        r = self.row("compare", "CMP-QWEN-ENGINE-VS-ETCHED")
        self.assertEqual(r["verdict"], "NOT COMPARABLE")
        self.assertTrue({"model", "chips", "precision", "metric_kind"} <= set(r["differs"]))

    def test_matching_measured_numbers_compare(self):
        def f(d):
            cond = {"model": "m", "chips": 1, "precision": "int8", "metric_kind": "aggregate-throughput",
                    "token_counting": "output-only", "s_in": 8, "s_out": 8, "batch": 1}
            for i in ("x.a", "x.b"):
                d["numbers"].append({"id": i, "what": "w", "value": 10, "unit": "tok/s", "label": "MEASURED",
                                     "measured_on": "FPGA", "source": ["SRC-SITE"], "method": "m",
                                     "evidence": {"status": "run-record", "run_id": "r"}, "conditions": dict(cond)})
            d["comparisons"] = [{"id": "CMP-X", "a": "x.a", "b": "x.b"}]
        reg = mutated(f)
        r = C.compare(reg, C.Resolver(reg))[0]
        self.assertEqual(r["verdict"], "SAME STATED CONDITIONS")
        self.assertEqual(r["measured"], "both sides measured")

    def test_etched_internal_consistency(self):
        r = self.row("consistency", "CHK-ETCHED-160-H100")
        self.assertEqual(r["status"], "CONSISTENT")
        self.assertAlmostEqual(r["implied"], 500000 / 23000 * 8)

    def test_vendor_analysis_numbers(self):
        va = self.out["vendor"][0]
        total = 304234377510912
        io = next(c for c in va["conventions"] if c["convention"] == "input+output")
        oo = next(c for c in va["conventions"] if c["convention"] == "output-only")
        self.assertAlmostEqual(io["chip_flops"] / (500000 / 2176 * total / 8), 1.0)
        self.assertAlmostEqual(oo["chip_flops"] / (500000 / 128 * total / 8), 1.0)
        rows = {r["convention"]: r for r in va["baseline"]["rows"]}
        self.assertAlmostEqual(rows["input+output"]["fraction_of_peak"], 23000 / 2176 * total / 8 / 1979e12)
        self.assertAlmostEqual(rows["output-only"]["fraction_of_peak"], 23000 / 128 * total / 8 / 1979e12)
        self.assertTrue(rows["input+output"]["feasible"])
        self.assertFalse(rows["output-only"]["feasible"])
        self.assertEqual(va["inferred_convention"], "input+output")
        self.assertAlmostEqual(va["chip_flops_vs_peak"], (500000 / 2176 * total / 8) / 1979e12)
        k1 = va["weight_passes"][0]
        self.assertEqual(k1["tokens_per_pass"], 1)
        stream = 80 * (2 * 8192 * 8192 + 2 * 8192 * 1024 + 3 * 8192 * 28672) + 128256 * 8192
        self.assertAlmostEqual(k1["bytes_per_s_per_chip"] / (500000 / 2176 * 2175 * stream / 8), 1.0)
        self.assertEqual(va["label"], L.MODELLED)

    def test_cycles_are_detected(self):
        def f(d):
            d["numbers"].append({"id": "x.a", "what": "w", "value": None, "unit": "u", "label": "MODELLED",
                                 "basis": "arithmetic", "source": ["SRC-HARNESS"], "method": "m",
                                 "formula": "b + 1", "inputs": {"b": "x.b"}})
            d["numbers"].append({"id": "x.b", "what": "w", "value": None, "unit": "u", "label": "MODELLED",
                                 "basis": "arithmetic", "source": ["SRC-HARNESS"], "method": "m",
                                 "formula": "a + 1", "inputs": {"a": "x.a"}})
        with self.assertRaises(F.FormulaError):
            C.Resolver(mutated(f)).value("x.a")


if __name__ == "__main__":
    unittest.main()
