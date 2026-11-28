"""Checks: reproduce arithmetic, test consistency, compare claims, analyse vendor claims.

Every value a check computes is MODELLED. A check never upgrades a label.
"""

from __future__ import annotations

from . import formula as F
from . import labels as L
from . import transformer as T
from .registry import MODELS_DIR

COMPARE_KEYS = ("model", "chips", "precision", "metric_kind", "token_counting", "s_in", "s_out", "batch")


class Resolver:
    """Gives every registry number a numeric value. Formulas are evaluated
    recursively, with cycle detection. For a number with both a stated value and a
    formula, the RECOMPUTED value is what flows downstream."""

    def __init__(self, reg):
        self.reg = reg
        self.cache = {}

    def value(self, nid: str, _stack: tuple = ()) -> float:
        if nid in self.cache:
            return self.cache[nid]
        if nid in _stack:
            raise F.FormulaError("cycle: " + " -> ".join(_stack + (nid,)))
        n = self.reg.numbers.get(nid)
        if n is None:
            raise F.FormulaError("unknown number id %r" % nid)
        if n.get("formula"):
            env = {name: self.value(ref, _stack + (nid,)) for name, ref in (n.get("inputs") or {}).items()}
            v = F.evaluate(n["formula"], env)
        else:
            v = n.get("value")
            if v is None:
                raise F.FormulaError("%s has no value (label %s)" % (nid, n.get("label")))
        self.cache[nid] = v
        return v

    def leaf_labels(self, nid: str, _seen=None) -> set:
        """Labels of the non-computed numbers a value ultimately rests on."""
        _seen = set() if _seen is None else _seen
        if nid in _seen:
            return set()
        _seen.add(nid)
        n = self.reg.numbers[nid]
        if not n.get("formula"):
            return {n.get("label")}
        out = set()
        for ref in (n.get("inputs") or {}).values():
            out |= self.leaf_labels(ref, _seen)
        return out


def reproduce(reg, res: Resolver) -> list:
    rows = []
    for nid in reg.order:
        n = reg.numbers[nid]
        if n.get("label") != L.MODELLED:
            continue
        row = {"id": nid, "unit": n.get("unit"), "formula": n.get("formula"), "stated": n.get("value"),
               "inputs": [], "label": L.MODELLED}
        if not n.get("formula"):
            row.update(status="NOT REPRODUCIBLE", detail="derivation (formula and inputs) not registered; see method")
            rows.append(row)
            continue
        try:
            for name, ref in (n.get("inputs") or {}).items():
                row["inputs"].append({"name": name, "ref": ref, "value": res.value(ref), "label": reg.label_of(ref)})
            got = res.value(nid)
        except F.FormulaError as exc:
            row.update(status="ERROR", detail=str(exc))
            rows.append(row)
            continue
        row["recomputed"] = got
        row["rests_on"] = sorted(res.leaf_labels(nid))
        stated = n.get("value")
        if stated is None:
            row.update(status="COMPUTED", detail="value computed by the harness")
        else:
            tol = n.get("tolerance_rel", 0.005)
            rel = abs(got - stated) / abs(stated) if stated else abs(got)
            row["rel_err"] = rel
            row.update(status="REPRODUCED" if rel <= tol else "MISMATCH",
                       detail="relative difference %.3g (tolerance %.3g)" % (rel, tol))
        rows.append(row)
    return rows


def consistency(reg, res: Resolver) -> list:
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
           "==": lambda a, b: abs(a - b) <= 0.005 * abs(b)}
    rows = []
    for chk in reg.consistency_checks:
        row = {"id": chk["id"], "question": chk.get("question"), "formula": chk["formula"],
               "relation": chk["relation"], "target": chk["target"], "unit": chk.get("unit"),
               "note": chk.get("note"), "label": L.MODELLED}
        try:
            env = {name: res.value(ref) for name, ref in chk["inputs"].items()}
            implied = F.evaluate(chk["formula"], env)
            target = res.value(chk["target"])
        except F.FormulaError as exc:
            row.update(status="ERROR", detail=str(exc))
            rows.append(row)
            continue
        holds = ops[chk["relation"]](implied, target)
        row.update(implied=implied, target_value=target, target_label=reg.label_of(chk["target"]),
                   inputs=[{"name": k, "ref": v, "value": env[k], "label": reg.label_of(v)} for k, v in chk["inputs"].items()],
                   status="CONSISTENT" if holds else "INCONSISTENT")
        rows.append(row)
    return rows


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def compare(reg, res: Resolver) -> list:
    rows = []
    for cmp in reg.comparisons:
        a, b = reg.numbers[cmp["a"]], reg.numbers[cmp["b"]]
        la, lb = a.get("label"), b.get("label")
        row = {"id": cmp["id"], "question": cmp.get("question"), "a": cmp["a"], "b": cmp["b"],
               "label_a": la, "label_b": lb, "fields": []}
        if L.NOT_YET in (la, lb):
            row.update(verdict="NO DATA", measured="no number on at least one side")
            rows.append(row)
            continue
        ca, cb = a.get("conditions") or {}, b.get("conditions") or {}
        diffs, unknown = [], []
        for k in COMPARE_KEYS:
            va, vb = ca.get(k), cb.get(k)
            if va is None or vb is None:
                state = "unknown"
                unknown.append(k)
            elif _norm(va) == _norm(vb):
                state = "same"
            else:
                state = "different"
                diffs.append(k)
            row["fields"].append({"field": k, "a": va, "b": vb, "state": state})
        if diffs:
            verdict = "NOT COMPARABLE"
        elif unknown:
            verdict = "COMPARABILITY UNVERIFIED"
        else:
            verdict = "SAME STATED CONDITIONS"
        measured = ("both sides measured" if la == lb == L.MEASURED
                    else "NOT A MEASURED COMPARISON (%s vs %s)" % (la, lb))
        try:
            ratio = res.value(cmp["a"]) / res.value(cmp["b"])
        except (F.FormulaError, ZeroDivisionError):
            ratio = None
        row.update(verdict=verdict, measured=measured, differs=diffs, unknown=unknown,
                   ratio=ratio, ratio_label=L.MODELLED,
                   value_a=_safe(res, cmp["a"]), value_b=_safe(res, cmp["b"]))
        rows.append(row)
    return rows


def _safe(res, nid):
    try:
        return res.value(nid)
    except F.FormulaError:
        return None


def vendor_analysis(reg, res: Resolver, va: dict, models_dir: str = MODELS_DIR) -> dict:
    """Requirements implied by a vendor throughput claim, under each token-counting
    convention, plus a check of which convention the vendor's own baseline allows."""
    claim = reg.numbers[va["claim"]]
    cond = claim.get("conditions") or {}
    arch, rec = T.load_arch(models_dir, va["arch"])
    s_in, s_out, chips = cond["s_in"], cond["s_out"], cond["chips"]
    tokps = res.value(va["claim"])
    rf = T.request_flops(arch, s_in, s_out, va.get("lm_head_on_prefill", False))
    params = T.param_breakdown(arch)
    w_stream = T.streamed_weight_bytes(arch, va["bytes_per_weight"])
    kv_tok = T.kv_bytes_per_token(arch, va["bytes_per_kv"])

    conventions = []
    for name, counted in (("input+output", s_in + s_out), ("output-only", s_out)):
        req_s = tokps / counted
        server = req_s * rf["total"]
        conventions.append({"convention": name, "counted_tokens_per_request": counted,
                            "requests_per_s": req_s, "positions_per_s": req_s * rf["positions"],
                            "server_flops": server, "chip_flops": server / chips})

    out = {"id": va["id"], "claim": va["claim"], "claim_value": tokps, "arch": rec, "arch_obj": arch,
           "params": params, "request_flops": rf, "s_in": s_in, "s_out": s_out, "chips": chips,
           "streamed_weight_bytes": w_stream, "kv_bytes_per_token": kv_tok,
           "kv_bytes_per_sequence": kv_tok * rf["positions"], "byte_assumptions": va.get("byte_assumptions"),
           "conventions": conventions, "label": L.MODELLED}

    base = va.get("baseline")
    inferred = None
    if base:
        b_tokps = res.value(base["claim"])
        peak = res.value(base["peak_per_chip_tflops"]) * 1e12
        brows = []
        for name, counted in (("input+output", s_in + s_out), ("output-only", s_out)):
            per_chip = b_tokps / counted * rf["total"] / base["chips"]
            brows.append({"convention": name, "chip_flops": per_chip, "fraction_of_peak": per_chip / peak,
                          "feasible": per_chip <= peak})
        feasible = [r["convention"] for r in brows if r["feasible"]]
        if len(feasible) == 1:
            inferred = feasible[0]
            verdict = ("Only '%s' keeps the vendor's own baseline at or under its peak, so the vendor's tok/s "
                       "most likely counts %s tokens (assuming one convention for the whole chart)." % (inferred, inferred))
        elif len(feasible) == 2:
            verdict = "Both conventions are physically possible for the baseline; the counting convention stays undetermined."
        else:
            verdict = "The baseline exceeds its peak under both conventions: the vendor figures are inconsistent with the FLOP model."
        out["baseline"] = {"claim": base["claim"], "claim_value": b_tokps, "chips": base["chips"],
                           "peak_flops": peak, "peak_name": base.get("peak_name"),
                           "peak_ref": base["peak_per_chip_tflops"], "rows": brows, "verdict": verdict}
        if base.get("sparse_peak_per_chip_tflops"):
            out["baseline"]["sparse_peak_flops"] = res.value(base["sparse_peak_per_chip_tflops"]) * 1e12
    out["inferred_convention"] = inferred

    use = next(c for c in conventions if c["convention"] == (inferred or "input+output"))
    out["used_convention"] = use["convention"]
    if base:
        out["chip_flops_vs_peak"] = use["chip_flops"] / out["baseline"]["peak_flops"]
    passes = []
    for k in va.get("tokens_per_weight_pass", []):
        per_s = use["positions_per_s"] / k
        passes.append({"tokens_per_pass": k, "weight_passes_per_s": per_s,
                       "bytes_per_s_per_chip": per_s * w_stream / chips})
    out["weight_passes"] = passes
    return out


def run_all(reg, models_dir: str = MODELS_DIR) -> dict:
    res = Resolver(reg)
    return {
        "resolver": res,
        "reproduce": reproduce(reg, res),
        "consistency": consistency(reg, res),
        "compare": compare(reg, res),
        "vendor": [vendor_analysis(reg, res, va, models_dir) for va in reg.vendor_analyses],
    }
