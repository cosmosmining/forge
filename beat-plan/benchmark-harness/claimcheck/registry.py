"""Load and validate the claims registry (data/claims.json).

The validator enforces the labelling rules. A broken rule is an ERROR, and the CLI
exits non-zero on any ERROR. Honest gaps (missing evidence, a derivation not in
this checkout, wording known only from a search summary) are WARNings.
"""

from __future__ import annotations

import hashlib
import json
import os

from . import formula as F
from . import labels as L

HARNESS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(HARNESS_ROOT))
DEFAULT_REGISTRY = os.path.join(HARNESS_ROOT, "data", "claims.json")
MODELS_DIR = os.path.join(HARNESS_ROOT, "data", "models")
RUNS_DIR = os.path.join(HARNESS_ROOT, "runs")

REQUIRED_COMMON = ("id", "what", "unit", "label", "source", "method")


def finding(level: str, code: str, ident: str, message: str) -> dict:
    return {"level": level, "code": code, "id": ident, "message": message}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class Registry:
    def __init__(self, data: dict, path: str):
        self.path = path
        self.data = data
        self.sources = {}
        self.numbers = {}
        self.order = []
        self.duplicates = []
        for s in data.get("sources", []):
            if s.get("id") in self.sources:
                self.duplicates.append(s.get("id"))
            self.sources[s.get("id")] = s
        for n in data.get("numbers", []):
            if n.get("id") in self.numbers:
                self.duplicates.append(n.get("id"))
            else:
                self.order.append(n.get("id"))
            self.numbers[n.get("id")] = n
        self.consistency_checks = data.get("consistency_checks", [])
        self.comparisons = data.get("comparisons", [])
        self.vendor_analyses = data.get("vendor_analyses", [])

    def sha256(self) -> str:
        return sha256_file(self.path) if self.path and os.path.exists(self.path) else ""

    def label_of(self, nid: str) -> str:
        n = self.numbers.get(nid)
        return n.get("label") if n else None


def load(path: str = DEFAULT_REGISTRY) -> Registry:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema") != "forge-claimcheck/1":
        raise ValueError("%s: unsupported schema %r" % (path, data.get("schema")))
    return Registry(data, path)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(reg: Registry, repo_root: str = REPO_ROOT) -> list:
    out = []
    for d in reg.duplicates:
        out.append(finding("ERROR", "DUPLICATE-ID", d, "id used more than once"))
    for sid, s in reg.sources.items():
        if not s.get("kind") or not s.get("quality"):
            out.append(finding("ERROR", "SOURCE-INCOMPLETE", sid, "source needs 'kind' and 'quality'"))
        if s.get("reachable_from_session") is False:
            out.append(finding("WARN", "SOURCE-UNREAD", sid,
                               "primary source could not be read from this session: " + s.get("access_attempt", "")))
        if s.get("kind") == "repo-file" and s.get("path"):
            p = os.path.join(repo_root, s["path"])
            if not os.path.exists(p):
                out.append(finding("ERROR", "SOURCE-FILE-MISSING", sid, "file not found: " + s["path"]))
            elif s.get("sha256") and sha256_file(p) != s["sha256"]:
                out.append(finding("WARN", "SOURCE-FILE-CHANGED", sid,
                                   "%s changed since it was registered (sha256 differs); re-read it and update the numbers" % s["path"]))

    for nid in reg.order:
        n = reg.numbers[nid]
        out.extend(_validate_number(reg, nid, n, repo_root))

    for chk in reg.consistency_checks:
        refs = list(chk.get("inputs", {}).values()) + [chk.get("target")]
        for ref in refs:
            if ref not in reg.numbers:
                out.append(finding("ERROR", "UNKNOWN-REF", chk.get("id"), "unknown number id %r" % ref))
    for cmp in reg.comparisons:
        for ref in (cmp.get("a"), cmp.get("b")):
            if ref not in reg.numbers:
                out.append(finding("ERROR", "UNKNOWN-REF", cmp.get("id"), "unknown number id %r" % ref))
    for va in reg.vendor_analyses:
        base = va.get("baseline", {})
        refs = [va.get("claim"), base.get("claim"), base.get("peak_per_chip_tflops"), base.get("sparse_peak_per_chip_tflops")]
        for ref in refs:
            if ref is not None and ref not in reg.numbers:
                out.append(finding("ERROR", "UNKNOWN-REF", va.get("id"), "unknown number id %r" % ref))
    return out


def _validate_number(reg: Registry, nid: str, n: dict, repo_root: str) -> list:
    out = []
    for field in REQUIRED_COMMON:
        if field not in n:
            out.append(finding("ERROR", "MISSING-FIELD", nid, "missing required field %r" % field))
    label = n.get("label")
    if label not in L.ALL_LABELS:
        out.append(finding("ERROR", "BAD-LABEL", nid,
                           "label %r is not one of %s" % (label, ", ".join(L.ALL_LABELS))))
        return out
    if not n.get("method"):
        out.append(finding("ERROR", "NO-METHOD", nid, "every number needs a method"))
    srcs = n.get("source") or []
    if not isinstance(srcs, list) or not srcs:
        out.append(finding("ERROR", "NO-SOURCE", nid, "every number needs at least one source id"))
    for sid in srcs if isinstance(srcs, list) else []:
        if sid not in reg.sources:
            out.append(finding("ERROR", "UNKNOWN-SOURCE", nid, "unknown source id %r" % sid))

    value = n.get("value")
    has_formula = bool(n.get("formula"))
    if label == L.NOT_YET:
        if value is not None:
            out.append(finding("ERROR", "NOT-YET-HAS-VALUE", nid, "a NOT-YET entry must have value null"))
    else:
        if value is None and not has_formula:
            out.append(finding("ERROR", "NO-VALUE", nid, "a labelled number needs a value or a formula"))
        if value is not None and not _is_number(value):
            out.append(finding("ERROR", "VALUE-NOT-NUMBER", nid, "value must be a number"))
        if n.get("unit") in (None, ""):
            out.append(finding("ERROR", "NO-UNIT", nid, "a labelled number needs a unit"))

    lock = n.get("label_lock")
    if lock and lock.get("label") != label:
        out.append(finding("ERROR", "LABEL-LOCK", nid,
                           "label is %s but is locked to %s: %s" % (label, lock.get("label"), lock.get("reason", ""))))

    if label == L.MEASURED:
        if has_formula:
            out.append(finding("ERROR", "COMPUTED-AS-MEASURED", nid,
                               "a number computed by a formula is MODELLED, never MEASURED"))
        if not n.get("measured_on"):
            out.append(finding("ERROR", "MEASURED-WITHOUT-RUN", nid,
                               "MEASURED needs 'measured_on' (what ran: simulation, FPGA, silicon, ...)"))
        ev = n.get("evidence")
        if not isinstance(ev, dict) or ev.get("status") not in L.EVIDENCE_STATUSES:
            out.append(finding("ERROR", "MEASURED-WITHOUT-EVIDENCE", nid,
                               "MEASURED needs evidence.status in %s" % (L.EVIDENCE_STATUSES,)))
        elif ev["status"] == "present":
            p = os.path.join(repo_root, ev.get("path", ""))
            if not ev.get("path") or not os.path.isfile(p):
                out.append(finding("ERROR", "EVIDENCE-MISSING", nid, "evidence file not found: %r" % ev.get("path")))
            elif not ev.get("sha256") or sha256_file(p) != ev["sha256"]:
                out.append(finding("ERROR", "EVIDENCE-MISMATCH", nid, "evidence sha256 missing or does not match"))
        elif ev["status"] == "not-in-checkout":
            out.append(finding("WARN", "EVIDENCE-NOT-HERE", nid,
                               "reported measurement; its evidence (%s) is not in this checkout, so it is not re-verified" % ev.get("expected", "?")))
        elif ev["status"] == "run-record" and not ev.get("run_id"):
            out.append(finding("ERROR", "EVIDENCE-MISSING", nid, "evidence.status run-record needs run_id"))

    if label == L.MODELLED:
        if n.get("basis") not in L.MODELLED_BASES:
            out.append(finding("ERROR", "MODELLED-WITHOUT-BASIS", nid,
                               "MODELLED needs basis in %s" % (L.MODELLED_BASES,)))
        if has_formula:
            try:
                names = F.names_in(n["formula"])
            except F.FormulaError as exc:
                out.append(finding("ERROR", "BAD-FORMULA", nid, str(exc)))
                names = []
            inputs = n.get("inputs") or {}
            for name in names:
                if name not in inputs:
                    out.append(finding("ERROR", "FORMULA-INPUT-UNBOUND", nid, "formula input %r has no mapping" % name))
                elif inputs[name] not in reg.numbers:
                    out.append(finding("ERROR", "UNKNOWN-REF", nid, "input %r -> unknown number id %r" % (name, inputs[name])))
        elif n.get("basis") == "arithmetic":
            out.append(finding("WARN", "DERIVATION-MISSING", nid,
                               "arithmetic number without a formula: cannot be reproduced until its formula and inputs are registered"))

    if label == L.VENDOR_CLAIM:
        if not n.get("stated_by"):
            out.append(finding("ERROR", "CLAIM-WITHOUT-VENDOR", nid, "VENDOR-CLAIM needs 'stated_by'"))
        if n.get("claim_type") not in L.CLAIM_TYPES:
            out.append(finding("ERROR", "CLAIM-WITHOUT-TYPE", nid, "claim_type must be one of %s" % (L.CLAIM_TYPES,)))
        if not n.get("quote"):
            out.append(finding("ERROR", "CLAIM-WITHOUT-QUOTE", nid, "VENDOR-CLAIM needs the vendor's wording in 'quote'"))
        if n.get("quote_status") not in L.QUOTE_STATUSES:
            out.append(finding("ERROR", "CLAIM-QUOTE-STATUS", nid, "quote_status must be one of %s" % (L.QUOTE_STATUSES,)))
        elif n.get("quote_status") == "search-summary":
            out.append(finding("WARN", "UNVERIFIED-WORDING", nid,
                               "wording from a search summary, not checked against the primary page"))
    return out


def errors(findings: list) -> list:
    return [f for f in findings if f["level"] == "ERROR"]
