"""pnr_agent command line.

  python -m pnr_agent run  designs/a.toml [designs/b.toml ...] --out runs --work /tmp/pnr-work
  python -m pnr_agent diagnose designs/a.toml --work /tmp/pnr-work
  python -m pnr_agent try  designs/a.toml --work /tmp/pnr-work --changes '{"rt_setup_margin": 0.05}'

`diagnose` and `try` expose the same structured actions and validation the
autonomous loop uses, so a Claude Code session (or a person) can drive the
loop step by step instead of the rule-based policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import guardrails
from .actions import propose_all, rtl_proposals
from .agent import Agent
from .config import Design
from .diagnose import diagnose, library_cells
from .recipe import apply_changes, default_recipe
from .runner import Runner


def _summary_table(results: list[tuple[str, dict]], path: Path) -> None:
    lines = ["# PnR tuning agent: batch summary", "",
             "| Block | Stand-in? | Target (ns) | WNS before -> after (ns) | TNS before -> after (ns) | "
             "Hold WNS after (ns) | DRC after | Accepted edits | Equivalence | Reproduced | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, rec in results:
        b, f = rec["baseline"]["summary"], rec["final"]["summary"]
        eq = rec["final"]["equivalence"]
        rp = rec["final"]["reproduction"]
        lines.append(
            f"| [{name}]({name}/LEDGER.md) | {'yes' if rec['design']['is_standin'] else 'no'} | "
            f"{rec['design']['target_period_ns']} | {b['wns_ns']:+.4f} -> {f['wns_ns']:+.4f} | "
            f"{b['tns_ns']:+.4f} -> {f['tns_ns']:+.4f} | {f['hold_wns_ns']:+.4f} | {f['drc']} | "
            f"{', '.join(a['action'] for a in rec['accepted']) or 'none'} | "
            f"{'PASS' if eq['ok'] else 'FAIL'} | {('yes' if rp and rp['match'] else ('n/a' if rp is None else 'NO'))} | "
            f"{'CLOSED' if rec['final']['closed'] else 'NOT CLOSED'} |")
    path.write_text("\n".join(lines) + "\n")


def cmd_run(args) -> int:
    results = []
    out = Path(args.out)
    for cfg in args.designs:
        design = Design.load(cfg)
        agent = Agent(design, Path(args.work) / design.name, out / design.name, workers=args.workers,
                      threads_per_run=args.threads, max_rounds=args.max_rounds, max_evals=args.max_evals,
                      reproduce=not args.no_reproduce)
        results.append((design.name, agent.run()))
    if len(results) > 1 or args.summary:
        _summary_table(results, out / "SUMMARY.md")
    return 0 if all(r["final"]["closed"] for _, r in results) else 2


def _baseline(args):
    design = Design.load(args.design)
    runner = Runner(design, Path(args.work) / design.name / "flow", threads=args.threads)
    recipe = default_recipe(design.knobs)
    return design, runner, recipe


def cmd_diagnose(args) -> int:
    design, runner, recipe = _baseline(args)
    if args.changes:
        recipe = apply_changes(recipe, json.loads(args.changes))
    ev = runner.evaluate(recipe)
    libcells = library_cells(design.platform.liberty.read_text(errors="replace"))
    diag = diagnose(ev, design.target_period_ns, libcells, design.platform.dont_use)
    menu = [vars(p) for p in propose_all(diag, recipe, design)]
    print(json.dumps({"summary": ev.summary(), "diagnosis": diag.brief(), "actions": menu,
                      "rtl_proposals": [vars(p) for p in rtl_proposals(diag, design)]},
                     indent=1, default=list))
    return 0


def cmd_try(args) -> int:
    design, runner, recipe = _baseline(args)
    base = runner.evaluate(recipe)
    cand = runner.evaluate(apply_changes(recipe, json.loads(args.changes)))
    checks = guardrails.validate(cand, base, design, design.golden_fingerprint())
    print(json.dumps({"baseline": base.summary(), "candidate": cand.summary(), "checks": checks,
                      "closed": guardrails.is_closed(cand.summary()) and all(c["ok"] for c in checks)},
                     indent=1, default=list))
    return 0


def cmd_summary(args) -> int:
    results = []
    for path in args.ledgers:
        rec = json.loads(Path(path).read_text())
        results.append((rec["design"]["name"], rec))
    _summary_table(results, Path(args.out))
    print(Path(args.out).read_text())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pnr_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="cross-block table from existing ledger.json files")
    s.add_argument("ledgers", nargs="+")
    s.add_argument("--out", default="runs/SUMMARY.md")
    s.set_defaults(func=cmd_summary)
    r = sub.add_parser("run", help="autonomous closure loop on one or more blocks")
    r.add_argument("designs", nargs="+")
    r.add_argument("--out", default="runs")
    r.add_argument("--work", default="work")
    r.add_argument("--workers", type=int, default=4, help="candidates evaluated in parallel per round")
    r.add_argument("--threads", type=int, default=1, help="OpenROAD threads per candidate")
    r.add_argument("--max-rounds", type=int, default=8)
    r.add_argument("--max-evals", type=int, default=40)
    r.add_argument("--no-reproduce", action="store_true")
    r.add_argument("--summary", action="store_true", help="write SUMMARY.md even for one block")
    r.set_defaults(func=cmd_run)
    for name, fn in (("diagnose", cmd_diagnose), ("try", cmd_try)):
        p = sub.add_parser(name)
        p.add_argument("design")
        p.add_argument("--work", default="work")
        p.add_argument("--threads", type=int, default=4)
        p.add_argument("--changes", default=None if name == "diagnose" else "{}",
                       help="JSON dict of recipe knob changes")
        p.set_defaults(func=fn)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
