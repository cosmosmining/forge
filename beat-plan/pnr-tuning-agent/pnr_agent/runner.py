"""Run the OpenROAD flow for a recipe, stage by stage, with checkpoint reuse.

Each stage's output is cached under <workdir>/cache/<stage>/<prefix-hash>/,
where the hash covers the golden inputs plus the knobs of that stage and all
earlier stages.  A candidate that only changes routing knobs therefore reuses
the floorplan/placement/CTS checkpoints of its parent.

Sign-off is a separate OpenSTA process that reads only the routed netlist,
the extracted SPEF, the liberty and the GOLDEN SDC.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import reports, synth, tcl
from .config import Design
from .recipe import STAGES, prefix_hashes, recipe_hash


class FlowError(Exception):
    def __init__(self, stage: str, log: Path, message: str):
        super().__init__(f"{stage} failed: {message} (log: {log})")
        self.stage = stage
        self.log = log


@dataclass
class Evaluation:
    recipe: dict
    recipe_hash: str
    stage_dirs: dict
    signoff_dir: Path
    signoff: dict                 # parsed sign-off metrics
    stage_metrics: dict           # per-stage metrics.json
    route: dict                   # DRC/antenna/route status
    congestion: dict              # GRT congestion summary
    runtime_s: dict = field(default_factory=dict)
    reused_stages: list = field(default_factory=list)

    def summary(self) -> dict:
        s = self.signoff
        return {
            "wns_ns": s["wns_max"], "tns_ns": s["tns_max"],
            "hold_wns_ns": s["wns_min"], "hold_tns_ns": s["tns_min"],
            "setup_violators": s["violators_max"], "hold_violators": s["violators_min"],
            "drc": self.route.get("drc_count"), "antenna_nets": self.route.get("antenna_nets"),
            "routed": self.route.get("routed"),
            "drv_violations": s["drv_violations"],
            "area_um2": _m2_to_um2(self.stage_metrics.get("drt", {}).get("design_area")),
            "utilization": self.stage_metrics.get("drt", {}).get("utilization"),
            "power_w": s.get("power_total_w"),
            "wirelength_um": self.congestion.get("wirelength_um"),
            "grt_overflow": self.congestion.get("total_overflow"),
            "grt_estimate_wns_ns": self.stage_metrics.get("grt", {}).get("grt_wns"),
            "clock_periods_ns": s["clock_periods"],
        }


class Runner:
    def __init__(self, design: Design, workdir: Path, openroad: str = "openroad",
                 sta: str = "sta", threads: int = 2, timeout_s: int = 6 * 3600):
        self.design = design
        self.workdir = Path(workdir).resolve()
        self.openroad = openroad
        self.sta = sta
        self.threads = threads
        self.timeout_s = timeout_s
        self.fingerprint = design.golden_fingerprint()
        # Cache key also covers the script generator itself: changing how a stage
        # is scripted must invalidate old checkpoints.
        self.cache_key = dict(self.fingerprint, generator=hashlib.sha256(
            Path(tcl.__file__).read_bytes() + Path(synth.__file__).read_bytes()).hexdigest()[:16],
            design_cfg=hashlib.sha256(Path(design.config_path).read_bytes()).hexdigest()[:16])
        (self.workdir / "cache").mkdir(parents=True, exist_ok=True)
        self.abc_liberty = self.workdir / "abc_dont_use.lib"
        if not self.abc_liberty.exists():
            self.abc_liberty.write_text(tcl.abc_liberty_text(
                design.platform.liberty.read_text(errors="replace"), design.platform.dont_use))

    # ------------------------------------------------------------------ stages
    def _stage_dir(self, stage: str, h: str) -> Path:
        return self.workdir / "cache" / stage / h

    def _run_stage(self, recipe: dict, stage: str, h: str, prev_odb: Path | None) -> tuple[Path, bool]:
        sdir = self._stage_dir(stage, h)
        done = sdir / "DONE"
        lock_path = self.workdir / "cache" / f".{stage}.{h}.lock"
        sdir.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if done.exists():
                return sdir, True
            if sdir.exists():
                shutil.rmtree(sdir)
            sdir.mkdir(parents=True)
            overlay = None
            text = tcl.overlay_sdc(recipe)
            if text:
                overlay = sdir / "opt_constraints.sdc"
                overlay.write_text("# optimization-only overlay (pnr_agent). Never read by sign-off.\n" + text)
            netlist = None
            if stage == "floorplan" and recipe.get("resynth_delay_ps"):
                try:
                    netlist = synth.run_resynth(self.design, self.abc_liberty,
                                                int(recipe["resynth_delay_ps"]), sdir)
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    raise FlowError(stage, sdir / "resynth.log", str(exc)) from exc
            script = tcl.stage_script(self.design, recipe, stage, prev_odb, sdir, overlay, self.threads,
                                      abc_liberty=self.abc_liberty, netlist=netlist)
            (sdir / f"{stage}.tcl").write_text(script)
            (sdir / "recipe.json").write_text(json.dumps(recipe, indent=1, sort_keys=True, default=list))
            log = sdir / f"{stage}.log"
            t0 = time.time()
            with open(log, "w") as fh:
                proc = subprocess.run([self.openroad, "-no_init", "-exit", str(sdir / f"{stage}.tcl")],
                                      stdout=fh, stderr=subprocess.STDOUT, cwd=sdir,
                                      timeout=self.timeout_s)
            (sdir / "runtime_s").write_text(f"{time.time() - t0:.1f}\n")
            odb = sdir / f"{stage}.odb"
            if proc.returncode != 0 or not odb.exists():
                raise FlowError(stage, log, f"openroad exit {proc.returncode}; "
                                + reports.last_error(log.read_text(errors="replace")))
            done.write_text("ok\n")
            return sdir, False

    def evaluate(self, recipe: dict) -> Evaluation:
        hashes = prefix_hashes(recipe, self.cache_key)
        stage_dirs, reused, runtime = {}, [], {}
        prev_odb = None
        for stage in STAGES:
            sdir, was_cached = self._run_stage(recipe, stage, hashes[stage], prev_odb)
            stage_dirs[stage] = sdir
            if was_cached:
                reused.append(stage)
            rt = sdir / "runtime_s"
            runtime[stage] = float(rt.read_text()) if rt.exists() else None
            prev_odb = sdir / f"{stage}.odb"
        signoff_dir = self._signoff(stage_dirs["drt"])
        stage_metrics = {s: _load_json(d / "metrics.json") for s, d in stage_dirs.items()}
        grt_log = (stage_dirs["grt"] / "grt.log").read_text(errors="replace")
        drt_dir = stage_dirs["drt"]
        drt_log = (drt_dir / "drt.log").read_text(errors="replace")
        route = {
            "drc_count": reports.count_drc(drt_dir / "drc.rpt", drt_log),
            "antenna_nets": stage_metrics["drt"].get("antenna_nets"),
            "routed": bool(stage_metrics["drt"].get("routed")),
            "placement_ok": bool(stage_metrics["drt"].get("placement_ok")),
        }
        congestion = reports.parse_grt_congestion(grt_log)
        signoff = reports.parse_signoff(signoff_dir)
        return Evaluation(recipe=recipe, recipe_hash=recipe_hash(recipe), stage_dirs=stage_dirs,
                          signoff_dir=signoff_dir, signoff=signoff, stage_metrics=stage_metrics,
                          route=route, congestion=congestion, runtime_s=runtime, reused_stages=reused)

    def _signoff(self, drt_dir: Path) -> Path:
        out = drt_dir / "signoff"
        done = out / "DONE"
        if done.exists():
            return out
        out.mkdir(exist_ok=True)
        script = tcl.signoff_script(self.design, drt_dir / "final.v", drt_dir / "final.spef", out)
        (out / "signoff.tcl").write_text(script)
        log = out / "signoff.log"
        with open(log, "w") as fh:
            proc = subprocess.run([self.sta, "-no_init", "-exit", str(out / "signoff.tcl")],
                                  stdout=fh, stderr=subprocess.STDOUT, cwd=out, timeout=self.timeout_s)
        if proc.returncode != 0:
            raise FlowError("signoff", log, f"sta exit {proc.returncode}; "
                            + reports.last_error(log.read_text(errors="replace")))
        done.write_text("ok\n")
        return out


def _m2_to_um2(v):
    """rsz::design_area returns m^2."""
    return None if v is None else round(v * 1e12, 3)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tool_versions(openroad: str = "openroad", sta: str = "sta", yosys: str = "yosys") -> dict:
    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
        except Exception as exc:  # noqa: BLE001 - informational only
            return f"unavailable ({exc})"
    return {
        "openroad": run([openroad, "-version"]),
        "opensta": run([sta, "-version"]),
        "yosys": run([yosys, "-V"]),
        "host_cpus": os.cpu_count(),
    }
