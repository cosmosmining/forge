"""forge_conformance: records (never re-runs), refuses what it cannot trace, catches tampering."""
import json
import os
import shutil
import subprocess

import pytest
from conftest import FC

import forge_conformance as fc
from fc_common import sha256_file

CLAIMS = FC / "conformance" / "claims.json"


def _write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1))
    return p


def _claims(tmp, claims):
    return _write(tmp / "claims.json", {"schema": fc.CLAIMS_SCHEMA, "pack": {"title": "t"}, "claims": claims})


# ------------------------------------------------------------------ the committed pack
def test_committed_claims_build_and_verify(tmp_path):
    pack = fc.build(CLAIMS, tmp_path / "pack")
    assert pack["leak_findings"] == 0
    assert pack["counts"]["recorded"] == 12 and pack["counts"]["bit_exact_recorded"] == 4
    assert {n["id"] for n in pack["not_recorded"]} == {
        "forge.qwen05b.engine_equals_integer_model", "forge.qwen7b.gpu_integer_engine_matches",
        "forge.rows_weights_beside_multipliers.exact", "forge.engine.gate_pass"}
    assert all("no evidence file" in n["reason"] for n in pack["not_recorded"])
    assert fc.verify(tmp_path / "pack") == []


def test_committed_pack_in_repo_verifies():
    assert fc.verify(FC / "pack") == []


def test_build_is_deterministic(tmp_path):
    a = fc.build(CLAIMS, tmp_path / "a")
    b = fc.build(CLAIMS, tmp_path / "b")
    assert a["manifest_sha256"] == b["manifest_sha256"]


def test_build_and_verify_start_no_process(tmp_path, monkeypatch):
    """The pack records; it must not re-simulate or re-prove. Any attempt to start a
    process (simulator, sby, yosys) makes this test fail."""
    def boom(*a, **k):
        raise AssertionError("conformance tried to start a process")
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, boom)
    monkeypatch.setattr(os, "system", boom)
    fc.build(CLAIMS, tmp_path / "pack")
    assert fc.verify(tmp_path / "pack") == []


# ------------------------------------------------------------------ tampering
def _fifo_verdict(pack):
    return pack / "files" / "results" / "standin_syncfifo_w8_d4" / "verdict.json"


def test_tamper_with_manifest_untouched_is_caught(tmp_path):
    fc.build(CLAIMS, tmp_path / "p")
    v = _fifo_verdict(tmp_path / "p")
    v.write_text(v.read_text().replace('"verdict": "PASS"', '"verdict": "FAIL"', 1))
    assert any("changed: files/results/standin_syncfifo_w8_d4/verdict.json" in p
               for p in fc.verify(tmp_path / "p"))


def test_tamper_with_manifest_rewritten_is_still_caught(tmp_path):
    """Even if someone edits evidence AND rewrites manifest.json to match, the recorded
    hashes in pack.json and the re-read values expose it."""
    pk = tmp_path / "p"
    fc.build(CLAIMS, pk)
    v = _fifo_verdict(pk)
    d = json.loads(v.read_text())
    d["bit_exact"]["counterexamples"] = 3
    v.write_text(json.dumps(d, indent=2) + "\n")
    man = json.loads((pk / "manifest.json").read_text())
    for e in man["files"]:
        f = pk / e["file"]
        e["sha256"], e["bytes"] = sha256_file(f), f.stat().st_size
    (pk / "manifest.json").write_text(json.dumps(man, indent=2) + "\n")
    problems = fc.verify(pk)
    assert any("evidence file changed" in p for p in problems)
    assert any("counterexamples no longer matches" in p for p in problems)


def test_tampered_log_breaks_the_chain(tmp_path):
    pk = tmp_path / "p"
    fc.build(CLAIMS, pk)
    log = pk / "files" / "results" / "standin_gray_decoder_w8" / "prove.log"
    log.write_text(log.read_text() + "\nSBY [prove] DONE (PASS, rc=0)\n")
    assert any("chain broken" in p or "evidence file changed" in p for p in fc.verify(pk))


def test_extra_file_is_caught(tmp_path):
    fc.build(CLAIMS, tmp_path / "p")
    (tmp_path / "p" / "files" / "smuggled.txt").write_text("hello\n")
    assert "not in manifest: files/smuggled.txt" in fc.verify(tmp_path / "p")


# ------------------------------------------------------------------ rules a claim cannot relax
def test_bit_exact_rule_cannot_be_relaxed(tmp_path):
    _write(tmp_path / "ev" / "one_mismatch.json", {"compared": 100, "mismatches": 1})
    _write(tmp_path / "ev" / "nothing_compared.json", {"compared": 0, "mismatches": 0})
    _write(tmp_path / "ev" / "no_count.json", {"compared": 5})
    _write(tmp_path / "ev" / "good.json", {"compared": 19, "mismatches": 0})
    rec = {"compared": "/compared", "mismatches": "/mismatches"}
    claims = [dict(id=n, statement=n, kind="measured", bit_exact=True, evidence=f"ev/{n}.json",
                   record=rec if n != "no_count" else {"compared": "/compared"})
              for n in ("one_mismatch", "nothing_compared", "no_count", "good")]
    pack = fc.build(_claims(tmp_path, claims), tmp_path / "pack", root=tmp_path)
    why = {n["id"]: n["reason"] for n in pack["not_recorded"]}
    assert "1 mismatches" in why["one_mismatch"]
    assert "compared > 0" in why["nothing_compared"]
    assert "no mismatch" in why["no_count"]
    assert [r["id"] for r in pack["recorded"]] == ["good"]


def test_missing_evidence_and_failed_requirement_are_not_recorded(tmp_path):
    _write(tmp_path / "ev" / "v.json", {"verdict": "INCOMPLETE"})
    claims = [dict(id="absent", statement="s", kind="measured", evidence="ev/nope.json", record={"x": "/x"}),
              dict(id="unnamed", statement="s", kind="measured", evidence=None, claimed_in="a slide"),
              dict(id="req", statement="s", kind="measured", evidence="ev/v.json",
                   record={"verdict": "/verdict"}, require={"/verdict": "PASS"}),
              dict(id="escape", statement="s", kind="measured", evidence="../outside.json", record={"x": "/x"})]
    pack = fc.build(_claims(tmp_path, claims), tmp_path / "pack", root=tmp_path)
    why = {n["id"]: n["reason"] for n in pack["not_recorded"]}
    assert "not found" in why["absent"]
    assert why["unnamed"] == "no evidence file named"
    assert "requirement failed" in why["req"]
    assert "leaves the root" in why["escape"]
    assert pack["recorded"] == []


def test_derived_values_are_recomputed(tmp_path):
    _write(tmp_path / "ev" / "a.json", {"n": 6})
    _write(tmp_path / "ev" / "b.json", {"n": 4})
    base = [dict(id="a", statement="a", kind="measured", evidence="ev/a.json", record={"n": "/n"}),
            dict(id="b", statement="b", kind="measured", evidence="ev/b.json", record={"n": "/n"})]
    good = dict(id="ratio", statement="r", kind="derived", inputs={"x": "a#n", "y": "b#n"},
                formula="x / (x + y)", value=0.6)
    wrong = dict(id="ratio_wrong", statement="r", kind="derived", inputs={"x": "a#n", "y": "b#n"},
                 formula="x / (x + y)", value=0.9)
    sneaky = dict(id="code", statement="r", kind="derived", inputs={"x": "a#n"},
                  formula="__import__('os').getcwd()")
    pack = fc.build(_claims(tmp_path, base + [good, wrong, sneaky]), tmp_path / "pack", root=tmp_path)
    assert [r["id"] for r in pack["recorded"]] == ["a", "b", "ratio"]
    why = {n["id"]: n["reason"] for n in pack["not_recorded"]}
    assert "recomputed 0.6" in why["ratio_wrong"]
    assert "not allowed" in why["code"]
    assert fc.verify(tmp_path / "pack") == []


def test_not_yet_and_model_kinds(tmp_path):
    _write(tmp_path / "ev" / "m.json", {"pj": 0.2})
    claims = [dict(id="ny_ok", statement="s", kind="not-yet"),
              dict(id="ny_number", statement="s", kind="not-yet", value=3),
              dict(id="model_no_assumptions", statement="s", kind="model", evidence="ev/m.json", record={"pj": "/pj"}),
              dict(id="model_ok", statement="s", kind="model", evidence="ev/m.json", record={"pj": "/pj"},
                   assumptions=["no wires"])]
    pack = fc.build(_claims(tmp_path, claims), tmp_path / "pack", root=tmp_path)
    assert [r["id"] for r in pack["recorded"]] == ["ny_ok", "model_ok"]
    assert fc.verify(tmp_path / "pack") == []


def test_planted_secret_blocks_the_pack(tmp_path):
    fake_key = "AK" + "IA" + "Q" * 16                     # built at runtime, never stored
    _write(tmp_path / "ev" / "v.json", {"verdict": "PASS"})
    (tmp_path / "ev" / "notes.txt").write_text(f"deploy with {fake_key}\n")
    claims = [dict(id="c", statement="s", kind="measured", evidence="ev/v.json",
                   record={"verdict": "/verdict"}, supporting=["ev/notes.txt"])]
    with pytest.raises(SystemExit, match="leak scan found"):
        fc.build(_claims(tmp_path, claims), tmp_path / "pack", root=tmp_path)
    assert not (tmp_path / "pack").exists() and (tmp_path / "pack.REJECTED").exists()
    rep = json.loads((tmp_path / "pack.REJECTED" / "leak_scan.json").read_text())
    assert rep["findings"] == 1 and fake_key not in json.dumps(rep)
    shutil.rmtree(tmp_path / "pack.REJECTED")
