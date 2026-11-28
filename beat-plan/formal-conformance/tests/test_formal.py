"""forge_formal: the gate must be able to say FAIL and INCOMPLETE, not only PASS."""
from pathlib import Path

import pytest
from conftest import FC, TOOLS, needs_eda, spec_variant

import forge_formal as ff
from fc_common import Sanitizer, load_json, sha256_file

SPECS = sorted((FC / "formal" / "specs").glob("*.json"))


# ------------------------------------------------------------------ no tools needed
def test_parse_bmc_failure_without_step_in_summary():
    log = "\n".join([
        "SBY 0:00:00 [bmc] engine_0: ##   0:00:00  Checking assertions in step 0..",
        "SBY 0:00:00 [bmc] engine_0: ##   0:00:00  Checking assertions in step 1..",
        "SBY 0:00:00 [bmc] engine_0: ##   0:00:00  Assert failed in forge_harness: p_x",
        "SBY 0:00:00 [bmc] summary: counterexample trace: bmc/engine_0/trace.vcd",
        "SBY 0:00:00 [bmc] summary:   failed assertion forge_harness.p_x at h.sv:3.1-3.9",
        "SBY 0:00:00 [bmc] DONE (FAIL, rc=2)"])
    r = ff.parse_sby(log, Path("/nonexistent"), 2)
    assert r["status"] == "FAIL"
    assert r["failed"] == [{"property": "p_x", "at": "h.sv:3.1-3.9", "step": 1}]
    assert r["induction_failed"] == []


def test_parse_prove_basecase_and_induction_are_kept_apart():
    log = "\n".join([
        "SBY [p] summary: counterexample trace: p/engine_0/trace.vcd",
        "SBY [p] summary:   failed assertion forge_harness.p_a at h.sv:1.1-1.2 step 11",
        "SBY [p] summary: counterexample trace [induction]: p/engine_0/trace_induct.vcd",
        "SBY [p] summary:   failed assertion forge_harness.p_b at h.sv:2.1-2.2",
        "SBY [p] DONE (FAIL, rc=2)"])
    r = ff.parse_sby(log, Path("/nonexistent"), 2)
    assert [f["property"] for f in r["failed"]] == ["p_a"] and r["failed"][0]["step"] == 11
    assert [f["property"] for f in r["induction_failed"]] == ["p_b"]


def test_parse_covers_with_and_without_step():
    log = "\n".join([
        "SBY [c] engine_0: ##   0:00:00  Reached cover statement in step 0 at forge_harness: c_zero",
        "SBY [c] summary:   reached cover statement forge_harness.c_zero at h.sv:1.1-1.2",
        "SBY [c] summary:   reached cover statement forge_harness.c_five at h.sv:2.1-2.2 step 5",
        "SBY [c] summary: unreached cover statements:",
        "SBY [c] summary:   forge_harness.c_never at h.sv:3.1-3.2",
        "SBY [c] DONE (FAIL, rc=2)"])
    r = ff.parse_sby(log, Path("/nonexistent"), 2)
    assert r["reached"] == [{"cover": "c_zero", "step": 0}, {"cover": "c_five", "step": 5}]
    assert r["unreached"] == ["c_never"]


def test_harness_rejects_unknown_port():
    spec = {"block": "b", "instances": [{"name": "dut", "module": "m", "connect": {}, "expose": [],
                                         "expose_prep": []}],
            "clock": None, "reset": None, "free_inputs": {}, "anyconst": {}, "helper_sv": [],
            "properties": [], "covers": [], "_sha256": "0" * 64}
    h = ff.Harness(spec, {"m": [{"name": "a", "dir": "input", "width": 1, "signed": False}]})
    assert h.rw("dut.a") == "a"
    with pytest.raises(ff.SpecError):
        h.rw("dut.nope")


def test_spec_rejects_bad_property_type(tmp_path):
    bad = tmp_path / "bad.json"
    rtl = FC / "standins" / "rtl" / "gray_encoder_w8.v"
    bad.write_text('{"schema": "forge.formal.spec/v1", "block": "b", "rtl": ["%s"], '
                   '"instances": [{"name": "dut", "module": "gray_encoder_w8"}], '
                   '"properties": [{"id": "p", "type": "assert_eventually", "expr": "1"}]}' % rtl)
    with pytest.raises(ff.SpecError):
        ff.load_spec(bad)


def test_sanitizer_hides_user_paths():
    s = Sanitizer({"<work>": Path("/tmp/job7")})
    home, mac, win = "/ho" + "me/alice/x", "/Us" + "ers/bob/y", "C:\\" + "Users\\carol\\z"   # built at runtime
    out = s(f"cd /tmp/job7/src; {home} {mac} {win} Clang /opt/b/clang++ 22")
    assert "/tmp/job7" not in out and "alice" not in out and "bob" not in out and "carol" not in out
    assert "<work>/src" in out and "Clang <path>" in out


# ------------------------------------------------------------------ end to end
@needs_eda
@pytest.mark.parametrize("spec", SPECS, ids=[p.stem for p in SPECS])
def test_committed_specs_pass_with_full_evidence(spec, scratch):
    v = ff.run_spec(spec, scratch / "results", scratch / "work", TOOLS)
    assert v["verdict"] == "PASS", v["reasons"]
    assert v["counts"]["asserts_proven"] == v["counts"]["asserts"] > 0
    assert v["counts"]["covers_reached"] == v["counts"]["covers"] > 0
    for e in v["evidence"]:                      # every evidence file exists and matches
        assert sha256_file(FC / e["file"]) == e["sha256"]
        text = (FC / e["file"]).read_text()
        assert "/tmp/" not in text and "/home/" not in text     # sanitized: no scratch or home paths


@needs_eda
def test_wrong_property_fails_with_counterexample(scratch):
    def edit(s):
        for p in s["properties"]:
            if p["id"] == "p_level_le_depth":
                p["expr"] = "level <= 3'd3"          # false: the FIFO can hold 4 entries
    v = ff.run_spec(spec_variant(scratch, "standin_syncfifo_w8_d4", "neg_wrong_bound", edit),
                    scratch / "results", scratch / "work", TOOLS)
    assert v["verdict"] == "FAIL"
    failed = v["tasks"]["prove"]["failed"]
    assert any(f["property"] == "p_level_le_depth" and f["step"] >= 4 for f in failed)
    assert v["tasks"]["prove"]["cex_traces"], "a counterexample trace must be kept as evidence"


@needs_eda
def test_unreachable_cover_fails_as_possibly_vacuous(scratch):
    v = ff.run_spec(spec_variant(scratch, "standin_syncfifo_w8_d4", "neg_unreachable_cover",
                                 lambda s: s["covers"].append({"id": "c_impossible", "expr": "level == 3'd5"})),
                    scratch / "results", scratch / "work", TOOLS)
    assert v["verdict"] == "FAIL"
    assert v["tasks"]["cover"]["unreached"] == ["c_impossible"]
    assert any("vacuous" in r for r in v["reasons"])


@needs_eda
def test_spec_without_covers_is_incomplete(scratch):
    v = ff.run_spec(spec_variant(scratch, "standin_gray_decoder_w8", "neg_no_covers",
                                 lambda s: s.__setitem__("covers", [])),
                    scratch / "results", scratch / "work", TOOLS)
    assert v["verdict"] == "INCOMPLETE"


@needs_eda
def test_non_inductive_property_is_incomplete_not_pass(scratch):
    def edit(s):
        s["properties"] = [p for p in s["properties"] if p.get("role") != "strengthening"]
    v = ff.run_spec(spec_variant(scratch, "standin_syncfifo_w8_d4", "neg_no_strengthening", edit),
                    scratch / "results", scratch / "work", TOOLS)
    assert v["verdict"] == "INCOMPLETE"
    assert v["tasks"]["prove"]["status"] == "UNKNOWN"
    assert any(f["property"] == "p_fifo_order" for f in v["tasks"]["prove"]["induction_failed"])


@needs_eda
def test_mutation_score_depends_on_the_properties(scratch):
    """Control for the mutation method: without the ordering property, data-path
    mutants must survive. With it (committed results) none survive."""
    def edit(s):
        s["properties"] = [p for p in s["properties"] if p["id"] != "p_fifo_order"]
    weak = ff.mutate_spec(spec_variant(scratch, "standin_syncfifo_w8_d4", "ctl_weak", edit),
                          scratch / "results", scratch / "work", TOOLS)
    assert weak["survived"] > 0
    full = load_json(FC / "results" / "standin_syncfifo_w8_d4" / "mutation.json")
    assert full["survived"] == 0 and full["mutants"] == weak["mutants"]
