"""leak_scan: every rule fires on a sample, never echoes the secret, allowlist is exact."""
import json

import pytest

import leak_scan as ls

# Samples are assembled at runtime so this file holds no credential-shaped literal.
SAMPLES = {
    "private_key_block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "aws_access_key_id": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "github_token": "gh" + "p_" + "a1" * 18,
    "anthropic_api_key": "sk-" + "ant-" + "x" * 30,
    "slack_token": "xo" + "xb-" + "1234567890-abcdef",
    "google_api_key": "AI" + "za" + "B" * 35,
    "jwt": "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12,
    "secret_assignment": "pass" + "word = '" + "hunter22x" + "'",
    "email_address": "someone" + "@" + "example.org",
    "home_path": "/Us" + "ers/jdoe/proj",
    "tilde_user_path": "~/" + "Desktop/x",
    "session_scratch_path": "/tmp/cl" + "aude-0/x",
    "session_link": "claude.ai/code/" + "session_" + "ABC123",
    "private_ipv4": "192." + "168.1.20",
}


@pytest.mark.parametrize("rule", sorted(SAMPLES))
def test_each_rule_fires_and_redacts(rule, tmp_path):
    secret = SAMPLES[rule]
    (tmp_path / "f.txt").write_text(f"line one\nvalue: {secret} end\n")
    rep = ls.scan([tmp_path], root=tmp_path)
    hits = [i for i in rep["items"] if i["rule"] == rule]
    assert hits and hits[0]["line"] == 2 and hits[0]["file"] == "f.txt"
    assert secret not in json.dumps(rep)


def test_clean_text_has_no_findings(tmp_path):
    (tmp_path / "ok.md").write_text("Yosys 0.71, z3 4.15.4, 38 of 38 mutants killed, sha256 ab12.\n")
    assert ls.scan([tmp_path], root=tmp_path)["findings"] == 0


def test_binary_and_large_files_are_findings(tmp_path):
    (tmp_path / "w.bin").write_bytes(b"\x00\x01weights")
    (tmp_path / "big.txt").write_bytes(b"a" * (ls.MAX_BYTES + 1))
    rules = {i["rule"] for i in ls.scan([tmp_path], root=tmp_path)["items"]}
    assert rules == {"binary_file", "large_file"}


def test_allowlist_is_exact(tmp_path):
    allowed = "/home/" + "runner/work/amaranth-yosys/bin"
    other = "/home/" + "runner/work/elsewhere/bin"
    (tmp_path / "a.v").write_text(f"/* built in {allowed} */\n/* and {other} */\n")
    allow = [{"rule": "home_path", "text": "/home/" + "runner/work/amaranth-yosys/", "why": "public CI path"}]
    rep = ls.scan([tmp_path], allow=allow, root=tmp_path)
    assert rep["suppressed"] == 1 and rep["findings"] == 1 and rep["items"][0]["line"] == 2


def test_denylist_terms(tmp_path):
    (tmp_path / "n.md").write_text("pilot with ACME Fabless next month\n")
    rep = ls.scan([tmp_path], deny_terms=["acme fabless"], root=tmp_path)
    assert [i["rule"] for i in rep["items"]] == ["denylist_term"]
