"""One verification run of one block: the agent's main loop.

prepare()  ports -> stimulus -> golden outputs -> testbench files
verify()   lint + structural + simulation(s) + bit-exact compare + coverage
           -> verdict PASS / FAIL / INCOMPLETE with reasons and evidence files
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field

from . import compare as cmpmod
from . import coverage as covmod
from . import golden, introspect, lint, sim, stimulus, tbgen, tools

PASS, FAIL, INCOMPLETE = "PASS", "FAIL", "INCOMPLETE"


@dataclass
class Prepared:
    manifest: object
    ports: list
    data_in: list
    data_out: list
    stim: object
    expected: list
    golden_cov: object
    tbdir: str
    meta: dict


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def prepare(m, seed: int, tbdir: str, cex: list | None = None, trace_golden: bool = True) -> Prepared:
    ports = introspect.ports_for_manifest(m)
    data_in, data_out = tbgen.split_ports(m, ports)
    stim = stimulus.build(m, ports, seed, cex)
    fn, gpath = golden.load_callable(m.golden_model, m.base_dir)
    expected, gcov = golden.run(fn, gpath, m.golden_style, stim.beats, data_out, trace=trace_golden)
    if m.golden_style == "map" and len(expected) != len(stim.beats):
        raise golden.GoldenError("map-style golden model must return one output per input beat")
    meta = tbgen.write(m, ports, stim, expected, tbdir)
    return Prepared(m, ports, data_in, data_out, stim, expected, gcov, tbdir, meta)


def prepare_with_stimulus(m, stim, tbdir: str, ports=None) -> Prepared:
    """Like prepare(), but with a given stimulus (e.g. replayed from a formal trace)."""
    ports = ports or introspect.ports_for_manifest(m)
    data_in, data_out = tbgen.split_ports(m, ports)
    fn, gpath = golden.load_callable(m.golden_model, m.base_dir)
    expected, _ = golden.run(fn, gpath, m.golden_style, stim.beats, data_out, trace=False)
    meta = tbgen.write(m, ports, stim, expected, tbdir)
    return Prepared(m, ports, data_in, data_out, stim, expected, None, tbdir, meta)


def link_tb(prep: Prepared, run_dir: str) -> None:
    """Make run_dir a private copy of the testbench (symlinked data files)."""
    os.makedirs(run_dir, exist_ok=True)
    for name in os.listdir(prep.tbdir):
        src = os.path.join(prep.tbdir, name)
        if os.path.isfile(src) and (name.endswith(".hex") or name in ("tb.sv", "tb_meta.json")):
            dst = os.path.join(run_dir, name)
            if os.path.lexists(dst):
                os.remove(dst)
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy(src, dst)


@dataclass
class Options:
    seed: int = 1
    simulators: list | None = None
    lint: bool | None = None
    structural: bool | None = None
    coverage: bool | None = None
    jobs: int = 4
    rtl_override: list | None = None
    trace_golden: bool = True
    cex: list | None = None
    keep_going: bool = True       # run every check even after a failure (for attribution)
    tool_versions: dict | None = None
    sim_seed: int | None = None
    extra: dict = field(default_factory=dict)


def _sim_check(sr, prep, reasons_fail, reasons_inc):
    """Turn one simulator run into a check record."""
    rec = {"simulator": sr.simulator, "compiled": sr.compiled, "finished": sr.finished,
           "secs": round(sr.secs, 2), "tb_result": sr.result, "out_file": sr.out_file}
    if sr.error == "tool-missing":
        rec["status"] = "not-run"
        reasons_inc.append(f"{sr.simulator}: tool not installed")
        return rec
    if not sr.compiled:
        rec["status"] = "fail"
        rec["log_tail"] = sr.log[-3000:]
        reasons_fail.append(f"{sr.simulator}: testbench + RTL did not compile")
        return rec
    if not sr.finished:
        rec["status"] = "fail"
        rec["log_tail"] = sr.log[-3000:]
        why = "hung (wall-clock timeout: zero-delay loop?)" if sr.error == "wallclock-timeout" \
            else "ended without a DVAGENT_RESULT line (crash or $fatal)"
        reasons_fail.append(f"{sr.simulator}: simulation {why}")
        return rec
    rows = cmpmod.read_dump(sr.out_file, len(prep.data_out))
    cr = cmpmod.compare(prep.expected, rows, prep.data_out)
    tb = sr.result
    rec["compare"] = {
        "expected_beats": cr.n_expected, "observed_beats": cr.n_observed,
        "mismatch_beats": cr.mismatch_beats, "x_beats": cr.x_beats,
        "missing": cr.missing, "extra": cr.extra,
        "first_mismatches": [mm.as_dict() for mm in cr.mismatches],
    }
    problems = []
    if cr.mismatch_beats:
        problems.append(f"{cr.mismatch_beats} of {cr.n_expected} output beats differ from the golden model")
    if cr.x_beats:
        problems.append(f"{cr.x_beats} output beats contain X/Z")
    if cr.missing:
        problems.append(f"{cr.missing} expected output beats never appeared")
    if cr.extra:
        problems.append(f"{cr.extra} extra output beats")
    if tb.get("timeout"):
        problems.append("testbench cycle timeout")
    if tb.get("xctl"):
        problems.append(f"X on handshake outputs in {tb['xctl']} cycles")
    if tb.get("proto"):
        problems.append(f"output protocol broken in {tb['proto']} cycles "
                        "(out_valid dropped or data changed before out_ready)")
    if tb.get("consumed") is not None and tb.get("consumed") != len(prep.stim.beats):
        problems.append(f"DUT accepted {tb.get('consumed')} of {len(prep.stim.beats)} input beats")
    # the testbench's own !== check must agree with the Python compare
    agree = (tb.get("mismatches") == cr.mismatch_beats and tb.get("extra", 0) == cr.extra
             and tb.get("outputs") == cr.n_observed)
    rec["tb_python_agree"] = agree
    if not agree:
        reasons_inc.append(f"{sr.simulator}: testbench self-check {tb} disagrees with Python compare "
                           f"(mismatch_beats={cr.mismatch_beats}, extra={cr.extra}, observed={cr.n_observed})")
    rec["bit_exact"] = not problems
    rec["status"] = "pass" if not problems else "fail"
    for p in problems:
        reasons_fail.append(f"{sr.simulator}: {p}")
    return rec


def verify(m, opts: Options, out_dir: str, prep: Prepared | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    checks_cfg = m.checks
    sims = opts.simulators if opts.simulators is not None else list(checks_cfg["simulators"])
    do_lint = checks_cfg["lint"] if opts.lint is None else opts.lint
    do_struct = checks_cfg["structural"] if opts.structural is None else opts.structural
    do_cov = checks_cfg["coverage"] if opts.coverage is None else opts.coverage
    rtl = list(opts.rtl_override) if opts.rtl_override else m.rtl_paths

    report = {"block": m.name, "top": m.top, "manifest": m.path, "seed": opts.seed,
              "rtl": [{"file": f, "sha256": _sha256(f)} for f in rtl],
              "tools": opts.tool_versions if opts.tool_versions is not None else tools.versions(),
              "checks": {}, "numbers": []}
    fail, inc = [], []

    # 1. prepare stimulus, golden outputs and testbench
    if prep is None:
        try:
            prep = prepare(m, opts.seed, os.path.join(out_dir, "tb"), cex=opts.cex,
                           trace_golden=opts.trace_golden)
        except (golden.GoldenError, introspect.IntrospectError, ValueError) as e:
            report.update(verdict=INCOMPLETE, reasons=[f"could not build the testbench: {e}"])
            _write(report, out_dir)
            return report
    report["golden"] = {"model": m.golden_model, "style": m.golden_style}
    if prep.golden_cov is not None:
        gc = prep.golden_cov
        report["golden"]["coverage"] = {
            "ratio": round(gc.ratio, 4), "covered_lines": len(gc.covered),
            "uncovered_lines": gc.uncovered, "functions_never_called": gc.functions_never_called}
        report["numbers"].append({"name": "golden model line coverage", "value": round(100 * gc.ratio, 1),
                                  "unit": "%", "kind": "measured", "source": "sys.settrace over golden model"})
        if gc.ratio < float(checks_cfg.get("min_golden_coverage", 0.0)):
            inc.append(f"golden model line coverage {gc.ratio:.1%} below "
                       f"{checks_cfg['min_golden_coverage']:.0%}: stimulus misses spec behaviour")
    report["stimulus"] = {"input_beats": len(prep.stim.beats), "output_beats": len(prep.expected),
                          "sources": prep.stim.sources, "idle_cycles": sum(prep.stim.gaps),
                          "stall_cycles": sum(1 for r in prep.stim.ready if r == 0),
                          "testbench": prep.meta.get("tb")}

    # 2. lint and structure
    if do_lint:
        lr = lint.verilator_lint(m.top, rtl, m.include_paths, m.defines, m.parameters,
                                 checks_cfg.get("waivers"), checks_cfg.get("sim_timeout_s", 300))
        report["checks"]["lint"] = _lint_record(lr, checks_cfg.get("lint_strict", False))
        _lint_reasons(lr, checks_cfg.get("lint_strict", False), fail, inc)
        with open(os.path.join(out_dir, "lint_verilator.log"), "w") as f:
            f.write(lr.log)
    if do_struct:
        sr = lint.yosys_structural(m.top, rtl, m.include_paths, m.defines, m.parameters)
        report["checks"]["structural"] = _lint_record(sr, False)
        _lint_reasons(sr, False, fail, inc)
        with open(os.path.join(out_dir, "structural_yosys.log"), "w") as f:
            f.write(sr.log)

    # 3. simulation and bit-exact compare
    report["checks"]["sim"] = {}
    cov_file = None
    for s in sims:
        run_dir = os.path.join(out_dir, f"run_{s}")
        link_tb(prep, run_dir)
        if s == "iverilog":
            r = sim.run_iverilog(run_dir, rtl, m.include_paths, m.defines,
                                 timeout_s=checks_cfg.get("sim_timeout_s", 300))
        elif s == "verilator":
            r = sim.run_verilator(run_dir, rtl, m.include_paths, m.defines,
                                  seed=opts.sim_seed or opts.seed, coverage=do_cov, jobs=opts.jobs,
                                  build_timeout_s=checks_cfg.get("build_timeout_s", 600),
                                  timeout_s=checks_cfg.get("sim_timeout_s", 300))
            cov_file = r.coverage_file
        else:
            inc.append(f"unknown simulator {s!r}")
            continue
        with open(os.path.join(run_dir, "sim.log"), "w") as f:
            f.write(r.log)
        report["checks"]["sim"][s] = _sim_check(r, prep, fail, inc)
        if r.finished and report["checks"]["sim"][s].get("compare"):
            c = report["checks"]["sim"][s]["compare"]
            report["numbers"].append({"name": f"{s}: output beats bit-exact",
                                      "value": f"{c['expected_beats'] - c['mismatch_beats'] - c['missing']}"
                                               f" of {c['expected_beats']}",
                                      "kind": "measured", "source": os.path.relpath(r.out_file, out_dir)})
    if not sims:
        inc.append("no simulator selected")

    # 4. coverage
    if do_cov and "verilator" in sims:
        cov = covmod.parse(cov_file, rtl)
        report["checks"]["coverage"] = cov
        if cov.get("available"):
            for k in ("line", "branch", "toggle"):
                if cov[k]["total"]:
                    report["numbers"].append({
                        "name": f"DUT {k} coverage", "value": round(100 * cov[k]["ratio"], 1), "unit": "%",
                        "detail": f"{cov[k]['hit']}/{cov[k]['total']} points", "kind": "measured",
                        "source": "verilator coverage.dat"})
            for k, key in (("line", "min_line_coverage"), ("toggle", "min_toggle_coverage")):
                need = float(checks_cfg.get(key, 0.0))
                got = cov[k]["ratio"]
                if need > 0 and (got is None or got < need):
                    inc.append(f"DUT {k} coverage {0 if got is None else got:.1%} below {need:.0%}")
        else:
            inc.append("coverage requested but verilator wrote no coverage data")

    report["verdict"] = FAIL if fail else (INCOMPLETE if inc else PASS)
    report["reasons"] = fail + inc
    _write(report, out_dir)
    return report


def _lint_record(lr, strict):
    if not lr.ran:
        return {"status": "not-run", "note": lr.note}
    failing = lr.failing(strict)
    return {
        "status": "fail" if failing else "pass",
        "errors": sum(1 for i in lr.issues if i.severity == "error"),
        "risk_warnings": sum(1 for i in lr.issues if i.severity == "risk" and not i.waived),
        "style_warnings": sum(1 for i in lr.issues if i.severity == "style" and not i.waived),
        "waived": sum(1 for i in lr.issues if i.waived),
        "issues": [i.as_dict() for i in lr.issues][:40],
    }


def _lint_reasons(lr, strict, fail, inc):
    if not lr.ran:
        inc.append(f"{lr.tool}: {lr.note}")
        return
    for i in lr.failing(strict):
        where = f" {os.path.basename(i.file)}:{i.line}" if i.file else ""
        fail.append(f"{lr.tool} {i.severity} {i.code}{where}: {i.msg[:160]}")


def _write(report: dict, out_dir: str) -> None:
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write(render_md(report))


def render_md(r: dict) -> str:
    L = [f"# DV report: {r.get('block')} ({r.get('top')})", "",
         f"**Verdict: {r.get('verdict')}**  (seed {r.get('seed')})", ""]
    if r.get("reasons"):
        L.append("Reasons:")
        L += [f"- {x}" for x in r["reasons"][:30]]
        L.append("")
    st = r.get("stimulus")
    if st:
        L.append(f"Stimulus: {st['input_beats']} input beats -> {st['output_beats']} golden output beats; "
                 f"sources {st['sources']}; idle cycles {st['idle_cycles']}; stall cycles {st['stall_cycles']}")
        L.append("")
    L.append("| check | status | detail |")
    L.append("|---|---|---|")
    ch = r.get("checks", {})
    for k in ("lint", "structural"):
        if k in ch:
            c = ch[k]
            L.append(f"| {k} | {c.get('status')} | errors {c.get('errors', '-')}, risk {c.get('risk_warnings', '-')}, "
                     f"style {c.get('style_warnings', '-')}, waived {c.get('waived', '-')} |")
    for s, c in ch.get("sim", {}).items():
        cc = c.get("compare") or {}
        L.append(f"| sim {s} | {c.get('status')} | beats {cc.get('expected_beats', '-')}, mismatched "
                 f"{cc.get('mismatch_beats', '-')}, X {cc.get('x_beats', '-')}, missing {cc.get('missing', '-')}, "
                 f"extra {cc.get('extra', '-')}, {c.get('secs')} s |")
    L.append("")
    if r.get("numbers"):
        L.append("| number | value | kind | source |")
        L.append("|---|---|---|---|")
        for n in r["numbers"]:
            v = f"{n['value']}{n.get('unit', '')}" + (f" ({n['detail']})" if n.get("detail") else "")
            L.append(f"| {n['name']} | {v} | {n['kind']} | {n['source']} |")
        L.append("")
    for s, c in ch.get("sim", {}).items():
        mm = (c.get("compare") or {}).get("first_mismatches") or []
        if mm:
            L.append(f"First mismatches ({s}):")
            for x in mm[:5]:
                L.append(f"- beat {x['idx']} port {x['port']}: expected {x['expected']}, got 0x{x['got']}"
                         f" (xor {x['xor_hex']}) - {x['hint']}")
            L.append("")
    return "\n".join(L) + "\n"
