"""The agent's own success test, run on the fixtures in selftest/fixtures.

  1. no false positives: every clean fixture PASSes on every seed, on Icarus and
     Verilator, and every behaviour-preserving rewrite in bugs.toml PASSes
  2. catches bugs: every hand-written bug in bugs.toml FAILs
  3. mutation campaign: every compiled mutant is killed, or proven equivalent,
     or explained (bounded-equivalent / timing-only); escapes are re-run with the
     vectors learned from formal counterexamples and must then be killed

The fixtures are stand-ins written to exercise the agent. They are not Forge
RTL and not Build 6 blocks.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import shutil
import time

from . import campaign, manifest, tools
from . import verify as V

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HERE, "selftest", "fixtures")


def fixtures() -> list:
    return sorted(glob.glob(os.path.join(FIXTURES, "*", "manifest.toml")))


def _learn_and_rerun(m, camp: dict, out: str, seed: int, tv: dict) -> dict:
    """Add formal counterexamples as directed input and re-check clean RTL and escapes."""
    escapes = [r for r in camp.get("mutants", []) if (r.get("formal") or {}).get("class") == "escape"]
    if not escapes:
        return {"escapes_before": 0}
    learned = []
    for r in escapes:
        learned += r["formal"].get("learned", [])
    prep = V.prepare(m, seed, os.path.join(out, "tb_learned"), cex=learned)
    clean = V.verify(m, V.Options(seed=seed, simulators=["iverilog", "verilator"], coverage=False, tool_versions=tv),
                     os.path.join(out, "clean_with_learned"), prep=prep)
    rerun = []
    for r in escapes:
        rtl = sorted(os.path.join(r["work"], "rtl", f) for f in os.listdir(os.path.join(r["work"], "rtl")))
        rep = V.verify(m, V.Options(seed=seed, simulators=["iverilog"], coverage=False, rtl_override=rtl,
                                    trace_golden=False, tool_versions=tv),
                       os.path.join(out, "rerun", r["id"]), prep=prep)
        rerun.append({"id": r["id"], "verdict": rep["verdict"]})
    return {"escapes_before": len(escapes), "learned_inputs": len(learned),
            "clean_with_learned": clean["verdict"],
            "escapes_killed_after_learning": sum(1 for x in rerun if x["verdict"] == V.FAIL),
            "rerun": rerun}


def learning_demo(out: str | None = None, jobs: int = 4) -> int:
    """Deliberately weak testbenches: escapes must be found by formal, turned into
    directed input, and then killed, while the clean RTL still PASSes."""
    out = out or os.path.join(HERE, "results", "learning_demo")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    with open(os.path.join(out, ".gitignore"), "w") as f:
        f.write("*\n!*/\n!.gitignore\n!summary.json\n!summary.md\n!campaign.json\n")
    tv = tools.versions()
    res, ok = {}, True
    for mpath in sorted(glob.glob(os.path.join(HERE, "selftest", "learning_demo", "*", "manifest.toml"))):
        m = manifest.load(mpath)
        c = campaign.campaign(m, os.path.join(out, m.name, "campaign"), seed=1, jobs=jobs, formal=True)
        lr = _learn_and_rerun(m, c, os.path.join(out, m.name, "learning"), 1, tv)
        res[m.name] = {"campaign": {k: c.get(k) for k in ("run", "compiled", "killed", "survived",
                                                           "survivor_classes", "escapes", "score")},
                       "learning": lr,
                       "escapes": [{k: r.get(k) for k in ("id", "op", "line", "old", "new")} |
                                   {"note": r["formal"].get("note"), "method": r["formal"].get("method")}
                                   for r in c.get("mutants", [])
                                   if (r.get("formal") or {}).get("class") == "escape"]}
        if lr.get("escapes_before"):
            ok &= lr["clean_with_learned"] == V.PASS and lr["escapes_killed_after_learning"] == lr["escapes_before"]
        print(f"[{m.name}] escapes {lr.get('escapes_before', 0)}, killed after learning "
              f"{lr.get('escapes_killed_after_learning', 0)}, clean with learned input: "
              f"{lr.get('clean_with_learned', '-')}", flush=True)
    summary = {"result": "PASS" if ok else "FAIL", "tools": tv, "blocks": res}
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    L = ["# Learning-loop demo", "", f"Result: **{summary['result']}**", "",
         "Deliberately weak testbenches on two self-test fixtures (not Forge RTL, not Build 6). Escapes are",
         "found by formal, their counterexamples become directed input, and the re-run must kill them while",
         "the clean RTL still passes. All numbers measured in this run.", ""]
    for name, r in res.items():
        c, lr = r["campaign"], r["learning"]
        L.append(f"## {name}")
        L.append(f"- mutants {c['run']}, killed by the weak test {c['killed']}, survivors {c['survivor_classes']}")
        L.append(f"- escapes found by formal: {lr.get('escapes_before', 0)}; learned inputs: {lr.get('learned_inputs', 0)}")
        L.append(f"- clean RTL with learned input: {lr.get('clean_with_learned', '-')}; escapes killed after "
                 f"learning: {lr.get('escapes_killed_after_learning', 0)}/{lr.get('escapes_before', 0)}")
        for e in r["escapes"][:12]:
            L.append(f"  - L{e['line']} {e['op']} `{e['old'].strip()[:40]}` -> `{e['new'].strip()[:40]}` "
                     f"({e['method']}): {e['note']}")
        L.append("")
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"learning demo {summary['result']}; summary: {os.path.join(out, 'summary.md')}")
    return 0 if ok else 1


def run(quick: bool = False, out: str | None = None, jobs: int = 4, seeds=(1, 2, 3), formal: bool = True) -> int:
    t0 = time.time()
    out = out or os.path.join(HERE, "results", "selftest")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    with open(os.path.join(out, ".gitignore"), "w") as f:
        f.write("# Keep the evidence (summaries and reports); drop build products, vectors and RTL copies.\n"
                "*\n!*/\n!.gitignore\n!summary.json\n!summary.md\n!report.json\n!report.md\n"
                "!bugs.json\n!campaign.json\n")
    tv = tools.versions()
    missing = [k for k in ("yosys", "iverilog", "verilator") if not tv.get(k)]
    if missing:
        print(f"INCOMPLETE: missing tools {missing}; run `dv doctor`")
        return 2
    seeds = [1] if quick else list(seeds)
    sims = ["iverilog"] if quick else ["iverilog", "verilator"]
    formal = formal and not quick
    summary = {"started": dt.datetime.now().isoformat(timespec="seconds"), "tools": tv, "seeds": seeds,
               "simulators": sims, "formal": formal, "fixtures": {},
               "note": "fixtures are stand-ins written to exercise the agent; not Forge RTL, not Build 6"}
    ok = True
    for mpath in fixtures():
        m = manifest.load(mpath)
        fx = {"clean": [], "bugs": None, "campaign": None}
        fdir = os.path.join(out, m.name)
        # 1. false positives on clean RTL
        for seed in seeds:
            r = V.verify(m, V.Options(seed=seed, simulators=sims, coverage=not quick, jobs=jobs, tool_versions=tv),
                         os.path.join(fdir, f"clean_seed{seed}"))
            cov = r["checks"].get("coverage") or {}
            fx["clean"].append({"seed": seed, "verdict": r["verdict"], "reasons": r.get("reasons", []),
                                "beats": r.get("stimulus", {}).get("output_beats"),
                                "line_cov": (cov.get("line") or {}).get("ratio"),
                                "toggle_cov": (cov.get("toggle") or {}).get("ratio"),
                                "golden_cov": (r.get("golden", {}).get("coverage") or {}).get("ratio")})
            ok &= r["verdict"] == V.PASS
            print(f"[{m.name}] clean seed {seed}: {r['verdict']}", flush=True)
        # 2. hand-written bugs and benign rewrites
        bpath = os.path.join(os.path.dirname(mpath), "bugs.toml")
        if os.path.isfile(bpath):
            b = campaign.bugs(m, bpath, os.path.join(fdir, "bugs"), seed=seeds[0], sims=sims, jobs=jobs)
            fx["bugs"] = {k: b[k] for k in ("bugs_total", "bugs_caught", "benign_total", "benign_passed")}
            fx["bugs"]["entries"] = [{k: e.get(k) for k in ("kind", "id", "why", "expected", "verdict", "ok",
                                                            "caught_by", "first_mismatch", "reasons")}
                                     for e in b["entries"]]
            ok &= b["bugs_caught"] == b["bugs_total"] and b["benign_passed"] == b["benign_total"]
        # 3. mutation campaign
        c = campaign.campaign(m, os.path.join(fdir, "campaign"), seed=seeds[0], jobs=jobs, formal=formal)
        keep = ("baseline_verdict", "generated", "run", "stillborn", "compiled", "killed", "killed_functional",
                "killed_lint_only", "survived", "survivor_classes", "escapes", "unexplained", "score", "secs",
                "by_operator")
        fx["campaign"] = {k: c.get(k) for k in keep}
        fx["campaign"]["survivors"] = [
            {k: r.get(k) for k in ("id", "op", "line", "old", "new", "desc")} |
            {"class": (r.get("formal") or {}).get("class"), "method": (r.get("formal") or {}).get("method"),
             "note": (r.get("formal") or {}).get("note")}
            for r in c.get("mutants", []) if r["status"] == "survived"]
        if formal:
            fx["learning"] = _learn_and_rerun(m, c, os.path.join(fdir, "learning"), seeds[0], tv)
            lr = fx["learning"]
            if lr.get("escapes_before"):
                ok &= lr["clean_with_learned"] == V.PASS and lr["escapes_killed_after_learning"] == lr["escapes_before"]
            ok &= not c.get("unexplained")
        ok &= c.get("baseline_verdict") == V.PASS
        summary["fixtures"][m.name] = fx
        print(f"[{m.name}] campaign: {fx['campaign']['killed']}/{fx['campaign']['compiled']} killed, "
              f"survivors {fx['campaign']['survivor_classes']}, escapes {fx['campaign']['escapes']}", flush=True)
    summary["secs"] = round(time.time() - t0, 1)
    summary["result"] = "PASS" if ok else "FAIL"
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write(render(summary))
    print(f"selftest {summary['result']} in {summary['secs']} s; summary: {os.path.join(out, 'summary.md')}")
    return 0 if ok else 1


def render(s: dict) -> str:
    L = ["# DV agent self-test", "",
         f"Result: **{s['result']}**  ({s['secs']} s, started {s['started']})", "",
         "Every number below is **measured**: printed by the tools in this run (files under this directory).",
         "The fixtures are stand-ins written to exercise the agent. They are **not Forge RTL and not Build 6**;",
         "these numbers say nothing about Forge's design.", "",
         f"Tools: {', '.join(f'{k} {v}' for k, v in s['tools'].items() if v)}", "",
         f"Seeds {s['seeds']}, simulators {s['simulators']}, formal {'on' if s['formal'] else 'off'}.", "",
         "## 1. False positives (clean RTL and behaviour-preserving rewrites must PASS)", "",
         "| fixture | clean runs PASS | output beats/run | DUT line cov | DUT toggle cov | golden cov | rewrites PASS |",
         "|---|---|---|---|---|---|---|"]
    for name, fx in s["fixtures"].items():
        cl = fx["clean"]
        npass = sum(1 for c in cl if c["verdict"] == "PASS")
        lc = cl[0].get("line_cov")
        tc = cl[0].get("toggle_cov")
        gc = cl[0].get("golden_cov")
        b = fx.get("bugs") or {}
        L.append(f"| {name} | {npass}/{len(cl)} | {cl[0].get('beats')} | "
                 f"{'-' if lc is None else f'{lc:.1%}'} | {'-' if tc is None else f'{tc:.1%}'} | "
                 f"{'-' if gc is None else f'{gc:.0%}'} | {b.get('benign_passed', '-')}/{b.get('benign_total', '-')} |")
    L += ["", "## 2. Hand-written injected bugs (each must FAIL)", "",
          "| fixture | bug | caught | caught by | first evidence |", "|---|---|---|---|---|"]
    for name, fx in s["fixtures"].items():
        for e in (fx.get("bugs") or {}).get("entries", []):
            if e["kind"] != "bug":
                continue
            ev = e.get("first_mismatch") or "; ".join(e.get("reasons") or [])[:140]
            L.append(f"| {name} | {e['id']}: {e['why']} | {'yes' if e['ok'] else '**NO**'} | "
                     f"{', '.join(e.get('caught_by') or [])} | {ev} |")
    L += ["", "## 3. Mutation campaign (automatic single-point bugs)", "",
          "| fixture | mutants | stillborn | killed (by simulation) | survived | survivor classes | escapes | unexplained | score |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, fx in s["fixtures"].items():
        c = fx["campaign"]
        L.append(f"| {name} | {c['run']} | {c['stillborn']} | {c['killed']} ({c['killed_functional']}) | "
                 f"{c['survived']} | {c['survivor_classes']} | {c['escapes']} | {c.get('unexplained', 0)} | "
                 f"{'-' if c['score'] is None else f'{c['score']:.1%}'} |")
    L += ["", "score = killed / (compiled - proven equivalent). Survivors by class:", ""]
    for name, fx in s["fixtures"].items():
        for r in fx["campaign"].get("survivors", []):
            L.append(f"- {name} L{r['line']} {r['op']} `{r['old'].strip()[:50]}` -> `{r['new'].strip()[:50]}`: "
                     f"**{r['class']}** ({r.get('method') or ''}) {r.get('note') or ''}")
    if s["formal"]:
        L += ["", "## 4. Learning loop (formal counterexample -> new test vectors)", ""]
        for name, fx in s["fixtures"].items():
            lr = fx.get("learning") or {}
            if lr.get("escapes_before"):
                L.append(f"- {name}: {lr['escapes_before']} escapes, {lr['learned_inputs']} learned inputs; clean RTL "
                         f"with learned inputs: {lr['clean_with_learned']}; escapes killed after learning: "
                         f"{lr['escapes_killed_after_learning']}/{lr['escapes_before']}")
            else:
                L.append(f"- {name}: no escapes")
    return "\n".join(L) + "\n"
