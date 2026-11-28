"""Command line: python3 -m claimcheck <check|report|lint|analyze|env|rerun> ...

Exit status is 0 when there are no ERRORs and 1 otherwise, so the commands can gate a commit or CI step.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from . import checks as C
from . import fmt
from . import labels as L
from . import lint as LINT
from . import registry as R
from . import report as REP
from . import runs as RUNS


def _load(args):
    reg = R.load(args.registry)
    findings = R.validate(reg)
    runs, run_findings = RUNS.load_runs(args.runs)
    return reg, findings, runs, run_findings


def _print_findings(findings, verbose=False):
    for f in findings:
        if f["level"] == "ERROR" or verbose:
            print("  %-5s %-24s %-40s %s" % (f["level"], f["code"], f["id"], f["message"]))


def cmd_check(args) -> int:
    reg, findings, runs, run_findings = _load(args)
    results = C.run_all(reg)
    allf = findings + run_findings
    errs = R.errors(allf)
    print("claimcheck %s: %d numbers, %d sources, %d run records" % (__version__, len(reg.order), len(reg.sources), len(runs)))
    print("validation: %d errors, %d warnings" % (len(errs), len([f for f in allf if f["level"] == "WARN"])))
    _print_findings(allf, args.verbose)
    for r in results["reproduce"]:
        print("  reproduce %-45s %-17s %s" % (r["id"], r["status"], r.get("detail", "")))
    for r in results["consistency"]:
        print("  consistency %-43s %s" % (r["id"], r["status"]))
    for r in results["compare"]:
        print("  compare %-47s %s | %s" % (r["id"], r["verdict"], r.get("measured", "")))
    bad = [r for r in results["reproduce"] if r["status"] in ("MISMATCH", "ERROR")]
    bad += [r for r in results["consistency"] if r["status"] == "ERROR"]
    return 1 if (errs or bad) else 0


def cmd_report(args) -> int:
    reg, findings, runs, run_findings = _load(args)
    results = C.run_all(reg)
    run_cmp = RUNS.compare_runs_to_claims(runs, reg, results["resolver"])
    known = LINT.known_tokps(reg, results["resolver"], runs)
    targets = args.lint or [p for p in REP.DEFAULT_LINT_TARGETS if os.path.exists(p)]
    files = list(LINT.iter_docs(targets))
    lint_rows = LINT.lint_paths(files, known, display_root=R.REPO_ROOT)
    text, data = REP.build(reg, results, runs, run_findings, run_cmp, findings, lint_rows,
                           [os.path.relpath(f, R.REPO_ROOT) for f in files])
    problems = REP.tag_problems(text)
    if problems:
        print("REFUSED: the generated report has numbers without a label tag:")
        for p in problems[:20]:
            print("  %s  %r in: %s" % (p["where"], p["number"], p["line"]))
        return 1
    md, js = REP.write(args.out, text, data)
    errs = R.errors(findings + run_findings) + [r for r in lint_rows if r["level"] == "ERROR"]
    print("wrote %s and %s (tag check: every numeric line labelled)" % (md, js))
    print("validation errors: %d; lint errors: %d" % (len(R.errors(findings + run_findings)),
                                                      len([r for r in lint_rows if r["level"] == "ERROR"])))
    return 1 if errs else 0


def cmd_lint(args) -> int:
    reg = R.load(args.registry)
    res = C.Resolver(reg)
    runs, _ = RUNS.load_runs(args.runs)
    known = LINT.known_tokps(reg, res, runs)
    rows = LINT.lint_paths(args.paths, known)
    for r in rows:
        if r["level"] != "OK" or args.verbose:
            print("%-5s %-18s %s  %r  %s" % (r["level"], r["code"], r["where"], r["text"], r["message"]))
    n_err = len([r for r in rows if r["level"] == "ERROR"])
    print("lint: %d tok/s figures, %d errors, %d warnings" % (len(rows), n_err, len([r for r in rows if r["level"] == "WARN"])))
    if args.tags:
        for p in args.paths:
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    probs = REP.tag_problems(fh.read(), p)
                for q in probs:
                    print("UNTAGGED %s %r: %s" % (q["where"], q["number"], q["line"]))
                n_err += len(probs)
    return 1 if n_err else 0


def cmd_analyze(args) -> int:
    reg = R.load(args.registry)
    results = C.run_all(reg)
    for va in results["vendor"]:
        if args.claim and va["claim"] != args.claim:
            continue
        print("%s  claim %s = %s tok/s [VENDOR-CLAIM]" % (va["id"], va["claim"], fmt.plain(va["claim_value"])))
        print("  FLOPs per request %s [MODELLED]" % fmt.si(va["request_flops"]["total"], "FLOP"))
        for cv in va["conventions"]:
            print("  %-13s per-chip %s [MODELLED]" % (cv["convention"], fmt.si(cv["chip_flops"], "FLOP/s")))
        if va.get("baseline"):
            for r in va["baseline"]["rows"]:
                print("  baseline %-13s %s%% of peak, possible=%s [MODELLED]" % (r["convention"], fmt.sig(r["fraction_of_peak"] * 100), r["feasible"]))
            print("  " + va["baseline"]["verdict"])
        for w in va["weight_passes"]:
            print("  %5d tokens/pass -> %s per chip [MODELLED]" % (w["tokens_per_pass"], fmt.si(w["bytes_per_s_per_chip"], "B/s")))
    return 0


def cmd_env(args) -> int:
    env = RUNS.env_versions()
    lines = ["# Toolchain in this environment", "",
             "Collected `%s` by `python3 -m claimcheck env`. Every version below was printed by the tool itself %s; "
             "missing means the tool is not installed here." % (env["collected_utc"], L.tag(L.MEASURED)), "",
             "| Tool | Version line | Label |", "|---|---|---|"]
    for k, v in env["tools"].items():
        lines.append("| %s | `%s` | %s |" % (k, v if v else "missing", L.tag(L.MEASURED)))
    lines += ["", "Platform `%s`, %s CPUs %s." % (env["platform"], env["cpu_count"], L.tag(L.MEASURED)), ""]
    text = "\n".join(lines)
    print(text)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "ENVIRONMENT.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(args.out, "environment.json"), "w", encoding="utf-8") as fh:
            json.dump(env, fh, indent=2)
            fh.write("\n")
    return 0


def cmd_rerun(args) -> int:
    extracts = {}
    for item in args.extract:
        if "=" not in item:
            print("--extract needs NAME=REGEX")
            return 2
        name, rx = item.split("=", 1)
        extracts[name] = rx
    path, rec, problems = RUNS.rerun(args.cmd, args.cwd, extracts, args.kind, args.run_id, args.model,
                                     out_dir=args.runs, synthetic=args.synthetic, note=args.note)
    print("wrote %s" % path)
    for k, v in rec["raw"].items():
        print("  %s = %s [MEASURED] (regex %r)" % (k, v, extracts[k]))
    for p in problems:
        print("  PROBLEM: " + p)
    fs = RUNS.validate_run(rec, args.runs, os.path.basename(path))
    for f in fs:
        print("  %-5s %s %s" % (f["level"], f["code"], f["message"]))
    print("Complete the record (workload, system, correctness) before it counts; see protocol/BENCHMARK_RERUN.md")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="claimcheck", description="Forge benchmark harness and vendor-claim checker")
    ap.add_argument("--registry", default=R.DEFAULT_REGISTRY)
    ap.add_argument("--runs", default=R.RUNS_DIR)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="validate the registry and run records, reproduce arithmetic, compare")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("report", help="write out/REPORT.md and out/report.json")
    p.add_argument("--out", default=os.path.join(R.HARNESS_ROOT, "out"))
    p.add_argument("--lint", nargs="*", help="documents to lint into the report (default: index.html, HANDOFF.md, README.md, protocol/)")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("lint", help="check that tok/s figures in documents carry labels")
    p.add_argument("paths", nargs="+")
    p.add_argument("--tags", action="store_true", help="also require label tags on every numeric line (for generated reports)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("analyze", help="print the vendor-claim requirement analysis")
    p.add_argument("--claim")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("env", help="record toolchain versions")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_env)

    p = sub.add_parser("rerun", help="run a benchmark command and write a run record from its log")
    p.add_argument("--kind", required=True, choices=RUNS.RUN_KINDS)
    p.add_argument("--run-id", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--cwd", default=".")
    p.add_argument("--cmd", required=True, help="command to run (no shell; quote it)")
    p.add_argument("--extract", action="append", default=[], help="NAME=REGEX with one capture group (repeatable)")
    p.add_argument("--synthetic", action="store_true", help="mark as a test fixture (never used in reports)")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_rerun)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
