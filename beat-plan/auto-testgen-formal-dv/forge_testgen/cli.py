"""Command line:  python3 -m forge_testgen <command> ...

  check   <spec>                 spec <-> RTL port check + golden translation stats
  run     <spec> [--out DIR]     generate tests, simulate, cover, prove   -> report.json
  mutate  <spec> [--out DIR]     inject bugs, measure what catches them   -> mutation.json
  all     <spec...> [--out DIR]  run + mutate for several specs, write RESULTS.md
"""

import argparse
import json
import os
import sys
import tempfile

from . import campaign, report as rep
from .spec import Spec


def _default_out(spec_path, root):
    name = os.path.splitext(os.path.basename(spec_path))[0]
    return os.path.join(root, name)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forge_testgen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("spec")
    r = sub.add_parser("run")
    r.add_argument("spec")
    r.add_argument("--out", default=None)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--random", type=int, default=None, help="number of random vectors/transactions")
    r.add_argument("--sim", default="iverilog", choices=["iverilog", "verilator"])
    r.add_argument("--no-formal", action="store_true")
    m = sub.add_parser("mutate")
    m.add_argument("spec")
    m.add_argument("--out", default=None)
    m.add_argument("--seed", type=int, default=1)
    m.add_argument("--max", type=int, default=None, help="max mutants (sampled, seeded)")
    m.add_argument("--no-formal", action="store_true")
    m.add_argument("--sim", default="iverilog", choices=["iverilog", "verilator"])
    sd = sub.add_parser("seeds", help="re-generate + simulate with more seeds (false-positive check)")
    sd.add_argument("spec")
    sd.add_argument("--out", default=None)
    sd.add_argument("--n", type=int, default=5)
    a = sub.add_parser("all")
    a.add_argument("specs", nargs="+")
    a.add_argument("--out", default="runs")
    a.add_argument("--seed", type=int, default=1)
    a.add_argument("--max", type=int, default=None)
    a.add_argument("--seeds", type=int, default=5)
    a.add_argument("--results", default="RESULTS.md")
    rs = sub.add_parser("results", help="write RESULTS.md from existing run directories")
    rs.add_argument("specs", nargs="+")
    rs.add_argument("--out", default="runs")
    rs.add_argument("--results", default="RESULTS.md")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        spec = Spec(args.spec)
        with tempfile.TemporaryDirectory() as tmp:
            issues = spec.check_against_rtl(tmp)
        print(json.dumps({"spec": spec.summary(), "spec_vs_rtl": issues,
                          "golden_translation": spec.model.translate().stats()}, indent=1))
        return 1 if campaign._hard_issues(issues) else 0

    if args.cmd == "run":
        out = args.out or _default_out(args.spec, "runs")
        report, _ = campaign.run_block(args.spec, out, seed=args.seed, n_random=args.random,
                                       simulator=args.sim, do_formal=not args.no_formal)
        print(rep.block_summary_text(report))
        return 0 if report["verdict"] == "PASS" else 1

    if args.cmd == "mutate":
        from . import mutation
        out = args.out or _default_out(args.spec, "runs")
        res = mutation.run(args.spec, out, seed=args.seed, max_mutants=args.max,
                           do_formal=not args.no_formal, simulator=args.sim)
        print(rep.mutation_summary_text(res))
        return 0

    if args.cmd == "seeds":
        out = args.out or _default_out(args.spec, "runs")
        res = seed_sweep(args.spec, out, args.n)
        print(json.dumps(res, indent=1))
        return 0 if all(v == "PASS" for v in res["verdicts"].values()) else 1

    if args.cmd == "all":
        from . import mutation
        for sp in args.specs:
            out = _default_out(sp, args.out)
            report, _ = campaign.run_block(sp, out, seed=args.seed)
            print(rep.block_summary_text(report))
            if report["verdict"] == "PASS":
                print(rep.mutation_summary_text(
                    mutation.run(sp, out, seed=args.seed, max_mutants=args.max)))
                print(json.dumps(seed_sweep(sp, out, args.seeds)))
        args.cmd = "results"

    if args.cmd == "results":
        root = os.path.dirname(os.path.abspath(args.results))
        entries = [(os.path.splitext(os.path.basename(sp))[0], _default_out(sp, args.out))
                   for sp in args.specs]
        extra = ["", "## 3. More seeds on the correct RTL (false-positive check)", "",
                 "Fresh directed + random generation and simulation with each seed; formal is "
                 "seed-independent and reported in section 1.", "",
                 "Coverage per seed is bins hit / bins considered. Without formal (as in these "
                 "runs) no bin can be proven unreachable, so unreachable bins appear as holes here.",
                 "",
                 "| block | seeds | verdicts | coverage per seed | source |", "|---|---|---|---|---|"]
        for name, d in entries:
            p = os.path.join(d, "seeds.json")
            if os.path.exists(p):
                sres = json.load(open(p))
                seeds = sorted(sres["verdicts"], key=int)
                cov = sres.get("coverage") or {}
                for k in seeds:
                    if k not in cov:
                        rp = os.path.join(d, "seeds", "seed%s" % k, "report.json")
                        if os.path.exists(rp):
                            cov[k] = _cov_str(json.load(open(rp)))
                extra.append("| %s | %s | %s | %s | `%s` |" % (
                    name, ", ".join(seeds), ", ".join(sres["verdicts"][k] for k in seeds),
                    "; ".join("%s: %s" % (k, cov.get(k, "?")) for k in seeds),
                    os.path.relpath(p, root)))
            else:
                extra.append("| %s | not yet | | | |" % name)
        hist_dir = os.path.join(args.out, "history")
        if os.path.isdir(hist_dir):
            extra += ["", "## 4. Earlier runs kept for comparison (before generator/property fixes)", "",
                      "Bug injection exposed gaps; the fixes were general (new coverage-bin kind, new "
                      "properties), not tests aimed at one mutant. Same metrics as section 2.", "",
                      "| file | block | real bugs | killed by sim | killed by formal | spec-conformant | survived |",
                      "|---|---|---|---|---|---|---|"]
            for fn in sorted(os.listdir(hist_dir)):
                if not fn.endswith(".json") or "mutation" not in fn:
                    continue
                h = json.load(open(os.path.join(hist_dir, fn)))
                hs = h["summary"]
                extra.append("| `%s` | %s | %s | %s | %s | %s | %s |" % (
                    os.path.relpath(os.path.join(hist_dir, fn), root), h["block"], hs["denominator"],
                    hs["sim_kill_rate"], hs["formal_kill_rate"],
                    hs.get("spec_conformant_behavior_change", 0), hs["survived"]))
        text = rep.results_markdown(entries, root, extra_sections=extra)
        with open(args.results, "w") as fh:
            fh.write(text)
        print("wrote", args.results)
        return 0
    return 2


def _cov_str(report):
    c = report.get("coverage") or {}
    return "%s/%s%s" % (c.get("bins_hit"), c.get("bins_considered"),
                        (" holes: %s" % ", ".join(c["holes"])) if c.get("holes") else "")


def seed_sweep(spec_path, outdir, n):
    """Seeds 2..n+1: new directed/random/closure suites, simulation only."""
    verdicts, tests, coverage = {}, {}, {}
    for seed in range(2, n + 2):
        d = os.path.join(outdir, "seeds", "seed%d" % seed)
        report, _ = campaign.run_block(spec_path, d, seed=seed, do_formal=False)
        verdicts[str(seed)] = report["verdict"]
        tests[str(seed)] = report.get("tests")
        coverage[str(seed)] = _cov_str(report)
    res = {"verdicts": verdicts, "tests": tests, "coverage": coverage}
    with open(os.path.join(outdir, "seeds.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


if __name__ == "__main__":
    sys.exit(main())
