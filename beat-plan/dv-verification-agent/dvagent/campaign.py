"""Bug-injection campaigns: grade how well the agent catches bugs in a block.

campaign()  automatic single-point mutants (mutate.py)
bugs()      hand-written injected bugs (must FAIL) and behaviour-preserving
            rewrites (must PASS) from a bugs.toml file

Accounting for automatic mutants
  stillborn  does not compile/elaborate in some tool; left out of the score
  killed     verdict FAIL; killed_by says which checks caught it
  survived   verdict PASS; then formal decides (formal.py):
               equivalent           proven: no input distinguishes it
               bounded-equivalent   no difference within the BMC depth
               timing-only          differs cycle by cycle, not in transactions
               needs-review         clock/reset edge change formal cannot judge
               escape               a real functional difference the tests missed
  score = killed / (compiled - equivalent)
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import shutil
import time

from . import mutate, tools
from . import verify as V

try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None


def _copy_rtl(m, work: str, replace: dict) -> list:
    """Copy the block's RTL into work/rtl, substituting files in `replace`."""
    dst_dir = os.path.join(work, "rtl")
    os.makedirs(dst_dir, exist_ok=True)
    out = []
    used = set()
    for i, src in enumerate(m.rtl_paths):
        base = os.path.basename(src)
        name = base if base not in used else f"{i}_{base}"
        used.add(name)
        dst = os.path.join(dst_dir, name)
        if src in replace:
            with open(dst, "w") as f:
                f.write(replace[src])
        else:
            shutil.copy(src, dst)
        out.append(dst)
    return out


def classify(report: dict) -> tuple:
    """(status, killed_by) from a verify report. status: stillborn|killed|survived|error."""
    ch = report.get("checks", {})
    compile_err = False
    # stillborn = a simulator cannot compile it, or Verilator rejects it outright.
    # yosys-only errors (e.g. an async reset that does not synthesise) are design
    # bugs the gate's synthesis check catches; they count as structural kills.
    if (ch.get("lint") or {}).get("errors"):
        compile_err = True
    for c in (ch.get("sim") or {}).values():
        if c.get("compiled") is False and c.get("status") != "not-run":
            compile_err = True
    if compile_err:
        return "stillborn", ["compile"]
    v = report.get("verdict")
    if v == V.PASS:
        return "survived", []
    if v == V.INCOMPLETE:
        return "error", report.get("reasons", [])[:3]
    by = []
    if (ch.get("lint") or {}).get("status") == "fail":
        by.append("lint")
    if (ch.get("structural") or {}).get("status") == "fail":
        by.append("structural")
    for s, c in (ch.get("sim") or {}).items():
        if c.get("status") == "fail":
            by.append(f"sim:{s}")
    return "killed", by


def _run_one(m, prep, mut: mutate.Mutant, base_dir: str, sims: list, tv: dict):
    work = os.path.join(base_dir, mut.id)
    shutil.rmtree(work, ignore_errors=True)
    with open(mut.file) as f:
        src = f.read()
    rtl = _copy_rtl(m, work, {os.path.abspath(mut.file): mut.apply(src)})
    opts = V.Options(seed=prep.stim.seed, simulators=sims, coverage=False, jobs=1,
                     rtl_override=rtl, trace_golden=False, tool_versions=tv)
    t0 = time.time()
    rep = V.verify(m, opts, work, prep=prep)
    status, by = classify(rep)
    return {**mut.as_dict(), "status": status, "killed_by": by, "secs": round(time.time() - t0, 2),
            "reasons": rep.get("reasons", [])[:4], "work": work}


def baseline(m, seed: int, out_dir: str, sims: list, tv: dict):
    """Prepare the testbench and check the unmodified RTL passes the same checks."""
    prep = V.prepare(m, seed, os.path.join(out_dir, "tb"))
    rep = V.verify(m, V.Options(seed=seed, simulators=sims, coverage=False, jobs=2, tool_versions=tv),
                   os.path.join(out_dir, "baseline"), prep=prep)
    return prep, rep


def campaign(m, out_dir: str, seed: int = 1, max_mutants: int | None = None, jobs: int = 4,
             sims: list | None = None, formal: bool = False, formal_depth: int | None = None,
             log=print) -> dict:
    sims = sims or ["iverilog"]
    os.makedirs(out_dir, exist_ok=True)
    tv = tools.versions()
    t0 = time.time()
    prep, base = baseline(m, seed, out_dir, sims, tv)
    summary = {"block": m.name, "top": m.top, "seed": seed, "simulators": sims, "tools": tv,
               "baseline_verdict": base["verdict"], "baseline_reasons": base.get("reasons", [])}
    if base["verdict"] != V.PASS:
        summary["error"] = "unmodified RTL does not PASS; a campaign needs a passing baseline"
        _dump(summary, out_dir)
        return summary
    all_m = mutate.generate_for(m.rtl_paths)
    chosen = mutate.sample(all_m, max_mutants, seed)
    log(f"[{m.name}] baseline PASS; {len(all_m)} mutants generated, running {len(chosen)} with {jobs} jobs")
    mdir = os.path.join(out_dir, "mutants")
    results = []
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = [ex.submit(_run_one, m, prep, mu, mdir, sims, tv) for mu in chosen]
        for fu in cf.as_completed(futs):
            results.append(fu.result())
    results.sort(key=lambda r: (r["file"], r["line"], r["col"], r["op"], r["new"]))

    survivors = [r for r in results if r["status"] == "survived"]
    if formal and survivors:
        from . import formal as F
        log(f"[{m.name}] {len(survivors)} survivors -> formal classification")
        for r in survivors:
            r["formal"] = F.classify_survivor(m, prep, r, os.path.join(out_dir, "formal", r["id"]),
                                              depth=formal_depth, tv=tv, sims=sims)
    for r in results:  # keep work dirs of interesting mutants only
        if r["status"] == "killed" and not r.get("keep"):
            shutil.rmtree(r["work"], ignore_errors=True)

    summary.update(_score(results))
    summary["generated"] = len(all_m)
    summary["secs"] = round(time.time() - t0, 1)
    summary["mutants"] = results
    _dump(summary, out_dir)
    return summary


def _score(results: list) -> dict:
    n = len(results)
    still = sum(1 for r in results if r["status"] == "stillborn")
    killed = [r for r in results if r["status"] == "killed"]
    surv = [r for r in results if r["status"] == "survived"]
    err = sum(1 for r in results if r["status"] == "error")
    func = sum(1 for r in killed if any(b.startswith("sim:") for b in r["killed_by"]))
    lint_only = len(killed) - func
    fcls = {}
    for r in surv:
        c = (r.get("formal") or {}).get("class", "unclassified")
        fcls[c] = fcls.get(c, 0) + 1
    equiv = fcls.get("equivalent", 0)
    compiled = n - still - err
    denom = compiled - equiv
    by_op = {}
    for r in results:
        d = by_op.setdefault(r["op"], {"total": 0, "stillborn": 0, "killed": 0, "survived": 0})
        d["total"] += 1
        d[r["status"] if r["status"] in d else "survived"] += 1
    return {
        "run": n, "stillborn": still, "errors": err, "compiled": compiled,
        "killed": len(killed), "killed_functional": func, "killed_lint_only": lint_only,
        "survived": len(surv), "survivor_classes": fcls,
        "escapes": fcls.get("escape", 0),                 # formal showed a functional difference
        "unexplained": fcls.get("unclassified", 0),      # no formal verdict (not run, or tool problem)
        "score": round(len(killed) / denom, 4) if denom else None,
        "by_operator": by_op,
    }


def _dump(summary: dict, out_dir: str) -> None:
    with open(os.path.join(out_dir, "campaign.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)


# ---- hand-written bugs and behaviour-preserving rewrites ------------------

def load_bugs(path: str) -> dict:
    if _toml is None:
        raise RuntimeError("bugs files are TOML; needs Python 3.11+ or tomli")
    with open(path, "rb") as f:
        data = _toml.load(f)
    return {"bug": data.get("bug", []), "benign": data.get("benign", [])}


def bugs(m, bugs_path: str, out_dir: str, seed: int = 1, sims: list | None = None,
         jobs: int = 4, log=print) -> dict:
    sims = sims or ["iverilog", "verilator"]
    spec = load_bugs(bugs_path)
    tv = tools.versions()
    prep = V.prepare(m, seed, os.path.join(out_dir, "tb"))
    base_dir = os.path.dirname(os.path.abspath(bugs_path))
    jobs_list = [("bug", b) for b in spec["bug"]] + [("benign", b) for b in spec["benign"]]

    def one(kind_entry):
        kind, b = kind_entry
        target = os.path.abspath(os.path.join(base_dir, b["file"]))
        with open(target) as f:
            src = f.read()
        n = src.count(b["find"])
        rec = {"kind": kind, "id": b["id"], "why": b.get("why", ""), "file": b["file"],
               "find": b["find"], "replace": b["replace"]}
        if n != 1:
            rec.update(status="error", reasons=[f"'find' text occurs {n} times in {b['file']} (need exactly 1)"])
            return rec
        work = os.path.join(out_dir, kind, b["id"])
        shutil.rmtree(work, ignore_errors=True)
        rtl = _copy_rtl(m, work, {target: src.replace(b["find"], b["replace"])})
        rep = V.verify(m, V.Options(seed=seed, simulators=sims, coverage=False, jobs=1, rtl_override=rtl,
                                    trace_golden=False, tool_versions=tv), work, prep=prep)
        status, by = classify(rep)
        expect = "FAIL" if kind == "bug" else "PASS"
        rec.update(verdict=rep["verdict"], status=status, caught_by=by, reasons=rep.get("reasons", [])[:4],
                   expected=expect, ok=(rep["verdict"] == expect),
                   first_mismatch=_first_mismatch(rep))
        return rec

    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        recs = list(ex.map(one, jobs_list))
    out = {"block": m.name, "seed": seed, "simulators": sims, "tools": tv, "entries": recs,
           "bugs_total": sum(1 for r in recs if r["kind"] == "bug"),
           "bugs_caught": sum(1 for r in recs if r["kind"] == "bug" and r.get("ok")),
           "benign_total": sum(1 for r in recs if r["kind"] == "benign"),
           "benign_passed": sum(1 for r in recs if r["kind"] == "benign" and r.get("ok"))}
    with open(os.path.join(out_dir, "bugs.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    log(f"[{m.name}] bugs caught {out['bugs_caught']}/{out['bugs_total']}, "
        f"benign rewrites passed {out['benign_passed']}/{out['benign_total']}")
    return out


def _first_mismatch(rep: dict):
    for s, c in (rep.get("checks", {}).get("sim") or {}).items():
        mm = (c.get("compare") or {}).get("first_mismatches") or []
        if mm:
            x = mm[0]
            return f"{s}: beat {x['idx']} {x['port']} expected {x['expected']} got 0x{x['got']} ({x['hint']})"
    return None
