"""Document lint, measured-run records, rerun capture, report rendering and the CLI.

Run records built here are SYNTHETIC test fixtures. They live only in temporary
directories and never touch runs/.
"""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from claimcheck import checks as C
from claimcheck import cli
from claimcheck import labels as L
from claimcheck import lint as LINT
from claimcheck import registry as R
from claimcheck import report as REP
from claimcheck import runs as RUNS

BRIEF = ("Forge 474,713 tok/s is ARITHMETIC vs Etched's 500,000 vendor claim, NOT a measurement "
         "— never present it as measured.")
SITE = os.path.join(R.REPO_ROOT, "index.html")


class LintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = R.load()
        cls.known = LINT.known_tokps(reg, C.Resolver(reg))

    def one(self, text, is_html=False):
        rows = LINT.lint_text(text, "t", self.known, is_html=is_html)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_brief_wording_passes(self):
        self.assertEqual(self.one(BRIEF)["code"], "LABELLED")

    def test_474713_called_measured_is_an_error(self):
        for text in ("Forge measured 474,713 tok/s on Llama-3 70B.",
                     "~475k tok/s, measured on our FPGA.",
                     "Measured throughput: 474713 tokens per second"):
            with self.subTest(text=text):
                r = self.one(text)
                self.assertEqual((r["level"], r["code"]), ("ERROR", "MISLABELLED"))

    def test_474713_without_label_is_an_error(self):
        r = self.one("We hit 474,713 tokens per second.")
        self.assertEqual((r["level"], r["code"]), ("ERROR", "UNLABELLED"))

    def test_labelled_variants_pass(self):
        for text in ("The projected figure is 474.7k tok/s (modelled, arithmetic).",
                     "474713 tokens per second is a projection from the beat plan.",
                     "This is not measured: 474,713 tok/s, a projection.",
                     "Measured: none. Forge ~475k tok/s (arithmetic projection) is the plan figure."):
            with self.subTest(text=text):
                self.assertEqual(self.one(text)["code"], "LABELLED")

    def test_etched_claim_wording(self):
        r = self.one("Etched claims over 500,000 Llama 70B tokens per second on one 8xSohu server.")
        self.assertEqual((r["code"], r["registry"]), ("LABELLED", "etched.sohu.server_tokps"))

    def test_unbacked_measured_figure_is_an_error(self):
        r = self.one("Our FPGA measured 1,234 tok/s at batch 1.")
        self.assertEqual((r["level"], r["code"]), ("ERROR", "UNBACKED-MEASURED"))

    def test_numbers_are_not_glued_together(self):
        r = self.one("We ran 3 tests at 200 tokens per second (estimated).")
        self.assertEqual(r["value"], 200)

    def test_html_is_stripped(self):
        r = self.one("<p>Forge <b>474,713</b> tok/s, measured</p>", is_html=True)
        self.assertEqual(r["code"], "MISLABELLED")

    def test_wrapped_markdown_paragraph_keeps_its_label(self):
        text = "Etched's own 8xH100 figure (a vendor claim\nof about 23,000 tok/s) fits under the peak.\n"
        r = self.one(text)
        self.assertEqual((r["code"], r["registry"]), ("LABELLED", "etched.claim.h100_server_tokps"))

    def test_labels_do_not_bleed_between_list_items_or_table_rows(self):
        text = ("- 474,713 tok/s is locked to MODELLED.\n- Same-run arithmetic is MEASURED.\n\n"
                "| 474,713 tok/s | arithmetic |\n| measured | x |\n")
        rows = LINT.lint_text(text, "t", self.known)
        self.assertEqual([r["code"] for r in rows], ["LABELLED", "LABELLED"])

    def test_code_fences_are_skipped(self):
        self.assertEqual(LINT.lint_text("```\nmeasured 474,713 tok/s\n```\n", "t", self.known), [])

    def test_site_page_has_no_lint_errors(self):
        rows = LINT.lint_paths([SITE], self.known)
        self.assertEqual([r for r in rows if r["level"] == "ERROR"], [])

    def test_tag_check(self):
        self.assertEqual(len(LINT.check_tags("Throughput 862 tok/s here.")), 1)
        self.assertEqual(LINT.check_tags("Throughput ~862 tok/s [MODELLED]."), [])
        self.assertEqual(LINT.check_tags("Run `forge.site.x1` on 2026-11-27, sha `1276fc73ea9e`, torchtune 0.6.1"), [])
        self.assertEqual(LINT.check_tags("Llama-3-70B on H100 with FP8 and Qwen2.5-0.5B"), [])


def _fixture_run(tmp, run_id="fixture-1", kind="fpga", **over):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    log = os.path.join(tmp, "logs", run_id + ".log")
    with open(log, "w") as fh:
        fh.write("SYNTHETIC TEST FIXTURE - not a result\n")
    rec = {
        "schema": RUNS.RUN_SCHEMA, "run_id": run_id, "kind": kind, "date_utc": "2026-11-28T00:00:00Z",
        "model": {"name": "fixture-model", "key": "fixture-model"},
        "workload": {"batch": 1, "s_in": 8, "s_out": 8},
        "system": {"board": "fixture", "part": "fixture", "clock_mhz": 1, "bitstream_sha256": "0" * 64,
                   "rtl_commit": "0" * 7, "chips": 1},
        "correctness": {"mismatches": 0},
        "raw": {"output_tokens": 1000, "input_tokens": 500, "wall_s": 10.0, "ttft_s": [0.5, 1.5],
                "power_w": [10.0, 30.0]},
        "power_meter": {"instrument": "fixture meter"},
        "evidence": [{"path": "logs/%s.log" % run_id,
                      "sha256": hashlib.sha256(b"SYNTHETIC TEST FIXTURE - not a result\n").hexdigest()}],
        "toolchain": {}, "synthetic": True,
    }
    rec.update(over)
    with open(os.path.join(tmp, run_id + ".json"), "w") as fh:
        json.dump(rec, fh)
    return rec


class RunTests(unittest.TestCase):
    def test_valid_run_and_same_run_arithmetic_is_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = _fixture_run(tmp)
            errs = [f for f in RUNS.validate_run(rec, tmp, "x") if f["level"] == "ERROR"]
            self.assertEqual(errs, [])
            d = {x["name"]: x for x in RUNS.derive(rec)}
            self.assertEqual(d["output_tokps"]["value"], 100.0)
            self.assertEqual(d["total_tokps"]["value"], 150.0)
            self.assertEqual(d["ttft_mean_s"]["value"], 1.0)
            self.assertEqual(d["energy_j_per_output_token"]["value"], 20.0 * 10.0 / 1000)
            self.assertTrue(all(x["label"] == L.MEASURED for x in d.values()))

    def test_evidence_and_protocol_fields_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = _fixture_run(tmp, evidence=[{"path": "logs/fixture-1.log", "sha256": "0" * 64}],
                               correctness={}, system={"board": "b"})
            got = {f["code"] for f in RUNS.validate_run(rec, tmp, "x") if f["level"] == "ERROR"}
            self.assertTrue({"RUN-EVIDENCE-MISMATCH", "RUN-FPGA-CORRECTNESS", "RUN-FPGA-FIELD"} <= got)

    def test_synthetic_runs_never_reach_claims_or_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fixture_run(tmp)
            runs, findings = RUNS.load_runs(tmp)
            self.assertIn("RUN-SYNTHETIC", {f["code"] for f in findings})
            reg = R.load()
            self.assertEqual(RUNS.compare_runs_to_claims(runs, reg, C.Resolver(reg)), [])
            self.assertFalse([k for k in LINT.known_tokps(None, None, runs)])

    def test_rtl_sim_tokps_needs_an_assumed_clock_so_it_is_modelled(self):
        rec = {"kind": "rtl-sim", "run_id": "s", "raw": {"cycles_per_token": 1000},
               "clock_assumption": {"period_ns": 1.0, "source": "fixture"}}
        d = {x["name"]: x for x in RUNS.derive(rec)}
        self.assertEqual(d["cycles_per_token"]["label"], L.MEASURED)
        self.assertEqual(d["tokps_at_assumed_clock"]["label"], L.MODELLED)
        self.assertAlmostEqual(d["tokps_at_assumed_clock"]["value"], 1e6)

    def test_rerun_captures_log_hash_and_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = '%s -c "print(\'CYCLES_PER_TOKEN=1000\')"' % sys.executable
            path, rec, problems = RUNS.rerun(cmd, tmp, {"cycles_per_token": r"CYCLES_PER_TOKEN=(\d+)"},
                                             "rtl-sim", "selftest-1", "selftest", out_dir=tmp, synthetic=True)
            self.assertEqual(problems, [])
            self.assertEqual(rec["raw"]["cycles_per_token"], 1000)
            self.assertTrue(rec["synthetic"])
            errs = [f for f in RUNS.validate_run(rec, tmp, "x") if f["level"] == "ERROR"]
            self.assertEqual(errs, [])
            with open(os.path.join(tmp, rec["evidence"][0]["path"]), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), rec["evidence"][0]["sha256"])

    def test_run_meets_claim_with_matching_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fixture_run(tmp, synthetic=False)
            runs, _ = RUNS.load_runs(tmp)
            reg = R.load()
            reg.data["numbers"].append({"id": "x.plan", "what": "w", "value": 125.0, "unit": "tok/s",
                                        "label": "MODELLED", "basis": "arithmetic", "source": ["SRC-HARNESS"],
                                        "method": "m", "conditions": {"model": "fixture-model", "batch": 1, "s_in": 8,
                                                                       "s_out": 8, "chips": 1,
                                                                       "token_counting": "output-only"}})
            reg = R.Registry(reg.data, reg.path)
            rows = RUNS.compare_runs_to_claims(runs, reg, C.Resolver(reg))
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["run_label"], rows[0]["claim_label"]), (L.MEASURED, L.MODELLED))
            self.assertAlmostEqual(rows[0]["ratio"], 100.0 / 125.0)


class ReportAndCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = R.load()
        results = C.run_all(reg)
        known = LINT.known_tokps(reg, results["resolver"])
        rows = LINT.lint_paths([SITE], known)
        cls.text, cls.data = REP.build(reg, results, [], [], [], R.validate(reg), rows, ["index.html"],
                                       now="2026-11-28T00:00:00Z")
        cls.known = known

    def test_every_numeric_line_is_tagged(self):
        self.assertEqual(REP.tag_problems(self.text), [])

    def test_474713_is_never_tagged_measured(self):
        lines = [ln for ln in self.text.splitlines() if "474,713" in ln]
        self.assertTrue(lines)
        for ln in lines:
            self.assertIn("[MODELLED]", ln)
            self.assertNotIn("[MEASURED]", ln)

    def test_report_passes_its_own_word_lint(self):
        bad = [r for r in LINT.lint_text(self.text, "REPORT.md", self.known) if r["level"] == "ERROR"]
        self.assertEqual(bad, [])

    def test_json_keeps_labels(self):
        by_id = {n["id"]: n for n in self.data["numbers"]}
        self.assertEqual(by_id["forge.beatplan.tokps_474713"]["label"], L.MODELLED)
        self.assertEqual(by_id["etched.sohu.server_tokps"]["label"], L.VENDOR_CLAIM)
        self.assertAlmostEqual(by_id["forge.harness.tokps_qwen05b_1engine_b1"]["resolved_value"], 1000 / 1.16)

    def test_cli_check_report_and_lint(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["check"]), 0)
            self.assertEqual(cli.main(["report", "--out", tmp, "--lint", SITE]), 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "REPORT.md")))
            bad = os.path.join(tmp, "bad.md")
            with open(bad, "w") as fh:
                fh.write("Forge measured 474,713 tok/s.\n")
            self.assertEqual(cli.main(["lint", bad]), 1)
            good = os.path.join(tmp, "good.md")
            with open(good, "w") as fh:
                fh.write(BRIEF + "\n")
            self.assertEqual(cli.main(["lint", good]), 0)


if __name__ == "__main__":
    unittest.main()
