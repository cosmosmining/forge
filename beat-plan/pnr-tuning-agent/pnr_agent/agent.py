"""The closed loop: run -> sign off -> diagnose -> propose -> try -> validate -> accept/revert.

Policy: rule-based ranking of a typed action catalog (actions.py).  Each
round evaluates the top-ranked untried proposals in parallel, each from the
current best recipe, and accepts the single best candidate that (a) passes
every guardrail and (b) improves sign-off timing.  Accepted edits accumulate
(greedy), the result is re-diagnosed, and the next round starts from there.

At the end the final recipe is (1) checked for logic equivalence against the
golden netlist and (2) reproduced from an empty cache to show the result is
not a caching or ordering artifact.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import equiv, guardrails, ledger
from .actions import propose_all, rtl_proposals
from .config import Design
from .diagnose import diagnose, library_cells
from .recipe import apply_changes, default_recipe, diff, recipe_hash
from .runner import FlowError, Runner, tool_versions

WNS_EPS = 0.0005   # ns: smaller WNS moves are treated as noise
TNS_EPS = 0.001    # ns


def score(s: dict) -> tuple:
    return (1 if guardrails.is_closed(s) else 0, round(min(s["wns_ns"], 0.0), 5),
            round(s["tns_ns"], 5), -(s["area_um2"] or 0.0))


def improves(new: dict, cur: dict) -> bool:
    if guardrails.is_closed(new) and not guardrails.is_closed(cur):
        return True
    if guardrails.is_closed(cur):
        return False
    if new["wns_ns"] > cur["wns_ns"] + WNS_EPS:
        return True
    return abs(new["wns_ns"] - cur["wns_ns"]) <= WNS_EPS and new["tns_ns"] > cur["tns_ns"] + TNS_EPS


class Agent:
    def __init__(self, design: Design, workdir: Path, outdir: Path, workers: int = 4,
                 threads_per_run: int = 1, max_rounds: int = 8, max_evals: int = 40,
                 reproduce: bool = True, log=print):
        self.design = design
        self.workdir = Path(workdir).resolve()
        self.outdir = Path(outdir).resolve()
        self.workers = workers
        self.max_rounds = max_rounds
        self.max_evals = max_evals
        self.reproduce = reproduce
        self.log = log
        self.runner = Runner(design, self.workdir / "flow", threads=threads_per_run)
        self.libcells = library_cells(design.platform.liberty.read_text(errors="replace"))
        self.history: dict = {}   # action -> tries / wins / dropped (simple track record)

    def _diag(self, ev):
        return diagnose(ev, self.design.target_period_ns, self.libcells, self.design.platform.dont_use)

    def _eval(self, recipe):
        try:
            return self.runner.evaluate(recipe), None
        except FlowError as exc:
            return None, str(exc)

    def run(self) -> dict:
        t_start = time.time()
        d = self.design
        self.outdir.mkdir(parents=True, exist_ok=True)
        fingerprint = d.golden_fingerprint()
        record = {
            "design": {"name": d.name, "top": d.top, "description": d.description,
                       "is_standin": d.is_standin, "target_period_ns": d.target_period_ns,
                       "config": str(d.config_path), "fingerprint": fingerprint,
                       "floorplan_fixed": d.floorplan_fixed},
            "tools": tool_versions(self.runner.openroad, self.runner.sta),
            "started": dt.datetime.now().isoformat(timespec="seconds"),
            "candidates": [], "accepted": [], "rounds": 0, "evaluations": 0,
        }
        base_recipe = default_recipe(d.knobs)
        self.log(f"[{d.name}] baseline flow ...")
        base, err = self._eval(base_recipe)
        if base is None:
            raise RuntimeError(f"baseline flow failed: {err}")
        record["evaluations"] += 1
        bs = base.summary()
        periods = bs["clock_periods_ns"]
        if not periods or any(abs(p - d.target_period_ns) > guardrails.PERIOD_TOL_NS for p in periods.values()):
            raise RuntimeError(f"golden SDC clock {periods} does not match target {d.target_period_ns} ns")
        diag = self._diag(base)
        record["baseline"] = {"summary": bs, "diagnosis": diag.brief(), "recipe": base_recipe,
                              "runtime_s": base.runtime_s}
        self.log(f"[{d.name}] baseline WNS {bs['wns_ns']:+.4f} TNS {bs['tns_ns']:+.4f} "
                 f"hold {bs['hold_wns_ns']:+.4f} drc {bs['drc']} tags {list(diag.tags)}")
        self._save(record, base, "baseline")

        current, cur_diag = base, diag
        evaluated = {recipe_hash(base_recipe)}
        rnd = 0
        stop_reason = "closed" if guardrails.is_closed(bs) else None
        while stop_reason is None:
            rnd += 1
            if rnd > self.max_rounds:
                stop_reason = f"round budget ({self.max_rounds}) used"
                break
            proposals = []
            for p in propose_all(cur_diag, current.recipe, d):
                h = recipe_hash(apply_changes(current.recipe, p.changes))
                hist = self.history.get(p.action, {"tries": 0, "wins": 0, "dropped": False})
                if h in evaluated or hist["dropped"]:
                    continue
                if hist["wins"] == 0 and hist["tries"]:
                    p.priority = round(p.priority - 0.25 * hist["tries"], 3)
                    p.evidence = p.evidence + [f"track record: {hist['tries']} earlier tries, none improved"]
                proposals.append(p)
            proposals.sort(key=lambda p: (-p.priority, p.action))
            if not proposals:
                stop_reason = "no untried action applies"
                break
            budget = self.max_evals - record["evaluations"]
            if budget <= 0:
                stop_reason = f"evaluation budget ({self.max_evals}) used"
                break
            batch = proposals[:min(self.workers, budget)]
            self.log(f"[{d.name}] round {rnd}: trying {[p.action for p in batch]}")
            recipes = [apply_changes(current.recipe, p.changes) for p in batch]
            for r in recipes:
                evaluated.add(recipe_hash(r))
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                results = list(pool.map(self._eval, recipes))
            record["evaluations"] += len(batch)
            cur_s = current.summary()
            best = None
            for p, (ev, err) in zip(batch, results):
                entry = {"round": rnd, "action": p.action, "category": p.category,
                         "changes": diff(current.recipe, apply_changes(current.recipe, p.changes)),
                         "rationale": p.rationale, "priority": p.priority, "evidence": p.evidence}
                if ev is None:
                    entry.update(valid=False, error=err, decision="rejected: flow error")
                else:
                    s = ev.summary()
                    checks = guardrails.validate(ev, base, d, fingerprint)
                    valid = all(c["ok"] for c in checks)
                    better = improves(s, cur_s)
                    entry.update(summary=s, checks=checks, valid=valid, improves=better,
                                 reused_stages=ev.reused_stages, runtime_s=ev.runtime_s,
                                 decision="candidate" if (valid and better) else
                                 ("rejected: guardrail" if not valid else "rejected: no improvement"))
                    if valid and better and (best is None or score(s) > score(best[1].summary())):
                        best = (p, ev, entry)
                    hist = self.history.setdefault(p.action, {"tries": 0, "wins": 0, "dropped": False})
                    hist["tries"] += 1
                    hist["wins"] += int(valid and better)
                    gap_now = max(0.0, -cur_s["wns_ns"])
                    if s["wns_ns"] < cur_s["wns_ns"] - max(gap_now, 0.02):
                        hist["dropped"] = True   # made the miss more than twice as bad: stop proposing it
                        entry["note"] = "action dropped for this run: WNS got far worse"
                    self.log(f"    {p.action:28s} WNS {s['wns_ns']:+.4f} TNS {s['tns_ns']:+.4f} "
                             f"hold {s['hold_wns_ns']:+.4f} drc {s['drc']} valid={valid} better={better}")
                record["candidates"].append(entry)
            record["rounds"] = rnd
            if best is not None:
                p, ev, entry = best
                entry["decision"] = "ACCEPTED"
                record["accepted"].append({
                    "round": rnd, "action": p.action, "category": p.category,
                    "changes": entry["changes"], "rationale": p.rationale, "evidence": p.evidence,
                    "before": cur_s, "after": ev.summary()})
                current, cur_diag = ev, self._diag(ev)
                for c in record["candidates"]:
                    if c["round"] == rnd and c is not entry and c["decision"] == "candidate":
                        c["decision"] = "valid, not best this round"
                self.log(f"[{d.name}] accepted {p.action}: WNS {ev.summary()['wns_ns']:+.4f}")
                if guardrails.is_closed(ev.summary()):
                    stop_reason = "closed"
            self._save(record, current, "progress")

        record["stop_reason"] = stop_reason
        record["action_track_record"] = self.history
        fs = current.summary()
        final_checks = guardrails.validate(current, base, d, fingerprint)
        self.log(f"[{d.name}] stop: {stop_reason}; equivalence check ...")
        eq = equiv.check(d.netlist, current.stage_dirs["drt"] / "final.v", d.top,
                         [d.platform.liberty, *d.extra_lib], self.workdir / "equiv")
        repro = None
        if self.reproduce and current is not base:
            self.log(f"[{d.name}] reproducing final recipe from an empty cache ...")
            rdir = self.workdir / "repro"
            if rdir.exists():
                shutil.rmtree(rdir)
            rr = Runner(d, rdir, threads=self.runner.threads)
            rev = rr.evaluate(current.recipe)
            rs = rev.summary()
            repro = {k: rs[k] for k in ("wns_ns", "tns_ns", "hold_wns_ns", "drc", "area_um2")}
            repro["match"] = all(abs((rs[k] or 0) - (fs[k] or 0)) <= 1e-4 for k in ("wns_ns", "tns_ns", "hold_wns_ns")) \
                and rs["drc"] == fs["drc"]
        closed = guardrails.is_closed(fs) and all(c["ok"] for c in final_checks) and eq.ok \
            and (repro is None or repro["match"])
        if closed:
            detail = (f"Setup and hold met at {d.target_period_ns} ns with the golden SDC: WNS "
                      f"{bs['wns_ns']:+.4f} -> {fs['wns_ns']:+.4f} ns, TNS {bs['tns_ns']:+.4f} -> "
                      f"{fs['tns_ns']:+.4f} ns, {len(record['accepted'])} accepted edit(s), routed with 0 DRC, "
                      f"logic proven equivalent.")
        else:
            why = []
            if not guardrails.is_closed(fs):
                why.append(f"sign-off still fails (WNS {fs['wns_ns']:+.4f} ns, TNS {fs['tns_ns']:+.4f} ns, "
                           f"hold {fs['hold_wns_ns']:+.4f} ns)")
            why += [f"guardrail failed: {c['name']}" for c in final_checks if not c["ok"]]
            if not eq.ok:
                why.append(f"equivalence: {eq.message}")
            if repro is not None and not repro["match"]:
                why.append("final result did not reproduce from an empty cache")
            detail = "Not closed: " + "; ".join(why) + f". Stop reason: {stop_reason}."
        record["final"] = {"summary": fs, "closed": closed, "verdict_detail": detail,
                           "checks": final_checks, "equivalence": eq.as_dict(), "reproduction": repro,
                           "recipe": current.recipe, "recipe_diff": diff(base_recipe, current.recipe),
                           "diagnosis": cur_diag.brief()}
        record["rtl_proposals"] = [vars(p) for p in rtl_proposals(cur_diag, d)] if not closed else []
        record["script_diff"] = ledger.script_diff(d, base_recipe, current.recipe)
        record["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        record["wall_time_s"] = round(time.time() - t_start, 1)
        self._save(record, current, "final")
        self._export(base, current)
        self.log(f"[{d.name}] {'CLOSED' if closed else 'NOT CLOSED'}: {detail}")
        return record

    def _save(self, record: dict, ev, tag: str) -> None:
        (self.outdir / "ledger.json").write_text(json.dumps(record, indent=1, default=_json_default))
        if "final" in record:
            ledger.write_markdown(record, self.outdir / "LEDGER.md")

    def _export(self, base, final) -> None:
        """Copy the small, reviewable artifacts next to the ledger."""
        for tag, ev in (("baseline", base), ("final", final)):
            dst = self.outdir / tag
            dst.mkdir(exist_ok=True)
            for name in ("top_paths_max.rpt", "violators_max.rpt", "violators_min.rpt", "drv.rpt",
                         "power.rpt", "signoff.tcl"):
                src = ev.signoff_dir / name
                if src.exists():
                    shutil.copy(src, dst / name)
            for stage, sdir in ev.stage_dirs.items():
                for name in (f"{stage}.tcl", "opt_constraints.sdc", "congestion.rpt"):
                    src = Path(sdir) / name
                    if src.exists():
                        shutil.copy(src, dst / (name if name.endswith(".tcl") else f"{stage}_{name}"))
            (dst / "recipe.json").write_text(json.dumps(ev.recipe, indent=1, sort_keys=True, default=list))


def _json_default(o):
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))
