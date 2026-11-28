"""Command line for the Forge DV agent.

  dv doctor                              tool versions
  dv introspect RTL... --top T           ports + a draft manifest
  dv tbgen MANIFEST [--out D]            write the testbench and vectors only
  dv verify MANIFEST [--seeds 1,2,3]     lint + structure + sims + bit-exact compare -> verdict
  dv mutants MANIFEST                    list the bugs the mutation engine would inject
  dv campaign MANIFEST [--formal]        mutation campaign (kill rate, survivors classified)
  dv bugs MANIFEST BUGS.toml             hand-written bugs must FAIL, benign rewrites must PASS
  dv equiv MANIFEST --gate RTL...        is a changed RTL equivalent to the manifest's RTL?
  dv selftest [--quick]                  the agent's own success test on its fixtures

Exit status: 0 = everything PASS / as expected, 1 = FAIL, 2 = INCOMPLETE or usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__, manifest, tools

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seeds(s: str) -> list:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def cmd_doctor(a):
    v = tools.versions()
    for k, x in v.items():
        print(f"{k:12s} {x or 'MISSING'}")
    need = ["yosys", "iverilog", "verilator"]
    missing = [n for n in need if not v.get(n)]
    if missing:
        print(f"\nMissing required tools: {missing}. Install the OSS CAD Suite "
              "(https://github.com/YosysHQ/oss-cad-suite-build) or your package manager's yosys/iverilog/verilator, "
              "or point DVAGENT_TOOL_PATH at their bin directory.")
        return 2
    return 0


def cmd_introspect(a):
    from . import introspect
    ports, _ = introspect.yosys_ports(a.rtl, a.top, a.include or [], {}, {})
    for p in ports:
        print(f"{p.direction:6s} {'signed' if p.signed else '      '} [{p.width:4d}] {p.name}")
    if a.draft:
        text = introspect.draft_manifest(a.rtl, a.top, a.include or [], golden=a.golden,
                                         base_dir=os.path.dirname(os.path.abspath(a.draft)))
        with open(a.draft, "w") as f:
            f.write(text)
        print(f"\ndraft manifest written to {a.draft} - check every line")
    return 0


def cmd_tbgen(a):
    from . import verify as V
    m = manifest.load(a.manifest)
    out = a.out or os.path.join(os.getcwd(), f"dv_tb_{m.name}")
    prep = V.prepare(m, a.seed, out)
    print(f"testbench: {prep.meta['tb']}")
    print(f"{prep.meta['n_in']} input beats, {prep.meta['n_out']} expected output beats, sources {prep.meta['sources']}")
    print(f"run: cd {out} && iverilog -g2012 -s dvagent_tb -o sim.vvp tb.sv {' '.join(m.rtl_paths)} && vvp sim.vvp")
    return 0


def cmd_verify(a):
    from . import verify as V
    m = manifest.load(a.manifest)
    base = a.out or os.path.join(os.getcwd(), "dv_runs", m.name)
    sims = a.sims.split(",") if a.sims else None
    worst = 0
    rows = []
    tv = tools.versions()
    for seed in _seeds(a.seeds):
        out = os.path.join(base, f"seed{seed}")
        t0 = time.time()
        r = V.verify(m, V.Options(seed=seed, simulators=sims, coverage=None if not a.no_coverage else False,
                                  jobs=a.jobs, tool_versions=tv), out)
        rows.append((seed, r["verdict"], time.time() - t0, out, r.get("reasons", [])))
        worst = max(worst, {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[r["verdict"]])
    for seed, v, secs, out, reasons in rows:
        print(f"{m.name} seed {seed}: {v} ({secs:.1f} s)  report: {os.path.join(out, 'report.md')}")
        for x in reasons[:8]:
            print(f"    - {x}")
    return worst


def cmd_mutants(a):
    from . import mutate
    m = manifest.load(a.manifest)
    ms = mutate.generate_for(m.rtl_paths)
    for x in ms:
        print(f"{x.id:44s} {os.path.basename(x.file)}:{x.line}:{x.col} {x.op:5s} {x.old!r} -> {x.new!r}")
    print(f"{len(ms)} mutants")
    return 0


def cmd_campaign(a):
    from . import campaign
    m = manifest.load(a.manifest)
    out = a.out or os.path.join(os.getcwd(), "dv_campaigns", m.name)
    s = campaign.campaign(m, out, seed=a.seed, max_mutants=a.max, jobs=a.jobs,
                          sims=a.sims.split(",") if a.sims else None, formal=a.formal)
    keys = ("baseline_verdict", "generated", "run", "stillborn", "compiled", "killed", "killed_functional",
            "killed_lint_only", "survived", "survivor_classes", "escapes", "unexplained", "score", "secs")
    print(json.dumps({k: s.get(k) for k in keys}, indent=2))
    print(f"details: {os.path.join(out, 'campaign.json')}")
    if s.get("error"):
        print(s["error"])
        return 2
    if s.get("unexplained"):
        print(f"{s['unexplained']} survivors are unexplained; run with --formal to classify them")
    return 0 if not s.get("escapes") and not s.get("unexplained") else 1


def cmd_bugs(a):
    from . import campaign
    m = manifest.load(a.manifest)
    out = a.out or os.path.join(os.getcwd(), "dv_bugs", m.name)
    r = campaign.bugs(m, a.bugs, out, seed=a.seed, sims=a.sims.split(",") if a.sims else None, jobs=a.jobs)
    for e in r["entries"]:
        mark = "ok " if e.get("ok") else "BAD"
        print(f"[{mark}] {e['kind']:6s} {e['id']:28s} expected {e.get('expected')}, got {e.get('verdict')}  "
              f"{e.get('caught_by') or ''} {e.get('first_mismatch') or ''}")
    good = r["bugs_caught"] == r["bugs_total"] and r["benign_passed"] == r["benign_total"]
    return 0 if good else 1


def cmd_equiv(a):
    from . import formal, introspect
    m = manifest.load(a.manifest)
    out = a.out or os.path.join(os.getcwd(), "dv_equiv", m.name)
    ye = formal.yosys_equiv(m, m.rtl_paths, a.gate, os.path.join(out, "equiv"))
    print(f"yosys equiv: {ye['status']}")
    if ye["status"] == "proven":
        return 0
    ports = introspect.ports_for_manifest(m)
    eq = formal.equivalence(m, ports, m.rtl_paths, a.gate, os.path.join(out, "sby"), depth=a.depth, mode="bmc")
    print(f"sby {eq.get('mode')} depth {eq.get('depth')}: {eq['status']} {eq.get('trace') or eq.get('detail') or ''}")
    return {"proven": 0, "bounded": 0, "cex": 1}.get(eq["status"], 2)


def cmd_selftest(a):
    from . import selftest
    if a.learning_demo:
        return selftest.learning_demo(out=a.out, jobs=a.jobs)
    return selftest.run(quick=a.quick, out=a.out, jobs=a.jobs, seeds=_seeds(a.seeds), formal=not a.no_formal)


def main(argv=None):
    p = argparse.ArgumentParser(prog="dv", description="Forge DV agent " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("doctor")
    s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("introspect")
    s.add_argument("rtl", nargs="+")
    s.add_argument("--top", required=True)
    s.add_argument("--include", action="append")
    s.add_argument("--draft", help="write a draft manifest here")
    s.add_argument("--golden", default="golden.py:model")
    s.set_defaults(fn=cmd_introspect)
    s = sub.add_parser("tbgen")
    s.add_argument("manifest")
    s.add_argument("--out")
    s.add_argument("--seed", type=int, default=1)
    s.set_defaults(fn=cmd_tbgen)
    s = sub.add_parser("verify")
    s.add_argument("manifest")
    s.add_argument("--out")
    s.add_argument("--seeds", default="1")
    s.add_argument("--sims", help="comma list, default from manifest (iverilog,verilator)")
    s.add_argument("--no-coverage", action="store_true")
    s.add_argument("--jobs", type=int, default=4)
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("mutants")
    s.add_argument("manifest")
    s.set_defaults(fn=cmd_mutants)
    s = sub.add_parser("campaign")
    s.add_argument("manifest")
    s.add_argument("--out")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--max", type=int, default=None, help="sample at most this many mutants")
    s.add_argument("--jobs", type=int, default=4)
    s.add_argument("--sims", help="default iverilog")
    s.add_argument("--formal", action="store_true", help="classify survivors with yosys equiv + sby")
    s.set_defaults(fn=cmd_campaign)
    s = sub.add_parser("bugs")
    s.add_argument("manifest")
    s.add_argument("bugs")
    s.add_argument("--out")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--sims", help="default iverilog,verilator")
    s.add_argument("--jobs", type=int, default=4)
    s.set_defaults(fn=cmd_bugs)
    s = sub.add_parser("equiv")
    s.add_argument("manifest")
    s.add_argument("--gate", nargs="+", required=True, help="changed RTL files (same names as the manifest's)")
    s.add_argument("--out")
    s.add_argument("--depth", type=int, default=20)
    s.set_defaults(fn=cmd_equiv)
    s = sub.add_parser("selftest")
    s.add_argument("--quick", action="store_true", help="one seed, iverilog only, no formal")
    s.add_argument("--out")
    s.add_argument("--jobs", type=int, default=4)
    s.add_argument("--seeds", default="1,2,3")
    s.add_argument("--no-formal", action="store_true")
    s.add_argument("--learning-demo", action="store_true",
                   help="weak testbenches: formal must find escapes and the learned input must kill them")
    s.set_defaults(fn=cmd_selftest)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except manifest.ManifestError as e:
        print(f"manifest error: {e}", file=sys.stderr)
        return 2
