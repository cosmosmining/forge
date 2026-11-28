"""Measured run records (runs/*.json): the only route to a MEASURED tok/s.

A run record names what ran (FPGA, silicon, RTL simulation, or a CPU/GPU
reference), the workload, the raw counts a tool printed, and evidence files
with sha256. From those raw counts the harness derives:
  - MEASURED values: arithmetic inside the same run on its own measured quantities
    (output tokens / wall seconds, joules / output token, mean TTFT).
  - MODELLED values: anything that needs an outside assumption, e.g. tok/s from
    simulated cycles needs a clock period that the simulation did not measure.
Records marked "synthetic": true (test fixtures) are never used in reports.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

from . import formula as F
from . import labels as L
from .registry import RUNS_DIR, finding, sha256_file

RUN_SCHEMA = "forge-claimcheck-run/1"
RUN_KINDS = ("fpga", "silicon", "rtl-sim", "cpu-reference", "gpu-reference")
THROUGHPUT_KINDS = ("fpga", "silicon", "cpu-reference", "gpu-reference")
REQUIRED = ("schema", "run_id", "kind", "date_utc", "model", "workload", "raw", "evidence", "toolchain", "synthetic")


def _pos(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def load_runs(runs_dir: str = RUNS_DIR):
    runs, out = [], []
    if not os.path.isdir(runs_dir):
        return runs, out
    for name in sorted(os.listdir(runs_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(runs_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except ValueError as exc:
            out.append(finding("ERROR", "RUN-BAD-JSON", name, str(exc)))
            continue
        fs = validate_run(rec, runs_dir, name)
        out.extend(fs)
        rec["_file"] = name
        rec["_valid"] = not any(f["level"] == "ERROR" for f in fs)
        runs.append(rec)
    return runs, out


def validate_run(rec: dict, base_dir: str, ident: str) -> list:
    out = []
    for field in REQUIRED:
        if field not in rec:
            out.append(finding("ERROR", "RUN-MISSING-FIELD", ident, "missing %r" % field))
    if rec.get("schema") not in (None, RUN_SCHEMA):
        out.append(finding("ERROR", "RUN-SCHEMA", ident, "schema must be %s" % RUN_SCHEMA))
    kind = rec.get("kind")
    if kind not in RUN_KINDS:
        out.append(finding("ERROR", "RUN-KIND", ident, "kind must be one of %s" % (RUN_KINDS,)))
    if not isinstance(rec.get("synthetic"), bool):
        out.append(finding("ERROR", "RUN-SYNTHETIC-FLAG", ident, "'synthetic' must be true or false"))
    elif rec["synthetic"]:
        out.append(finding("WARN", "RUN-SYNTHETIC", ident, "synthetic record (test fixture): never used in reports"))
    ev = rec.get("evidence")
    if not isinstance(ev, list) or not ev:
        out.append(finding("ERROR", "RUN-NO-EVIDENCE", ident, "a run needs at least one evidence file (log, report) with sha256"))
    else:
        for item in ev:
            p = os.path.join(base_dir, item.get("path", ""))
            if not item.get("path") or not os.path.isfile(p):
                out.append(finding("ERROR", "RUN-EVIDENCE-MISSING", ident, "evidence not found: %r" % item.get("path")))
            elif item.get("sha256") != sha256_file(p):
                out.append(finding("ERROR", "RUN-EVIDENCE-MISMATCH", ident, "sha256 mismatch for %s" % item.get("path")))
    model = rec.get("model") or {}
    if not model.get("name"):
        out.append(finding("ERROR", "RUN-NO-MODEL", ident, "model.name required"))
    raw = rec.get("raw") or {}
    wl = rec.get("workload") or {}
    if kind in THROUGHPUT_KINDS:
        if not (isinstance(raw.get("output_tokens"), int) and raw["output_tokens"] > 0):
            out.append(finding("ERROR", "RUN-RAW", ident, "raw.output_tokens must be a positive integer"))
        if not _pos(raw.get("wall_s")):
            out.append(finding("ERROR", "RUN-RAW", ident, "raw.wall_s must be > 0"))
        for k in ("batch", "s_in", "s_out"):
            if not (isinstance(wl.get(k), int) and wl[k] >= 1):
                out.append(finding("ERROR", "RUN-WORKLOAD", ident, "workload.%s must be an integer >= 1" % k))
    if kind == "rtl-sim" and not _pos(raw.get("cycles_per_token")):
        out.append(finding("ERROR", "RUN-RAW", ident, "raw.cycles_per_token must be > 0"))
    if kind == "fpga":
        sysd = rec.get("system") or {}
        for k in ("board", "part", "clock_mhz", "bitstream_sha256", "rtl_commit"):
            if not sysd.get(k):
                out.append(finding("ERROR", "RUN-FPGA-FIELD", ident, "fpga runs need system.%s (see protocol)" % k))
        corr = rec.get("correctness") or {}
        if not isinstance(corr.get("mismatches"), int):
            out.append(finding("ERROR", "RUN-FPGA-CORRECTNESS", ident,
                               "fpga runs must also compare outputs with the integer model (correctness.mismatches)"))
        if raw.get("power_w") and not (rec.get("power_meter") or {}).get("instrument"):
            out.append(finding("ERROR", "RUN-POWER-METER", ident, "power samples need power_meter.instrument"))
    return out


def derive(rec: dict) -> list:
    """Quantities derived from one run. Same-run arithmetic is MEASURED, anything needing an outside assumption is MODELLED."""
    out = []
    raw, kind, rid = rec.get("raw") or {}, rec.get("kind"), rec.get("run_id")
    if kind in THROUGHPUT_KINDS and _pos(raw.get("output_tokens")) and _pos(raw.get("wall_s")):
        out.append({"name": "output_tokps", "value": raw["output_tokens"] / raw["wall_s"], "unit": "tok/s",
                    "label": L.MEASURED, "token_counting": "output-only",
                    "method": "raw.output_tokens / raw.wall_s from run %s" % rid})
        if isinstance(raw.get("input_tokens"), int):
            out.append({"name": "total_tokps", "value": (raw["input_tokens"] + raw["output_tokens"]) / raw["wall_s"],
                        "unit": "tok/s", "label": L.MEASURED, "token_counting": "input+output",
                        "method": "(raw.input_tokens + raw.output_tokens) / raw.wall_s from run %s" % rid})
        if raw.get("ttft_s"):
            out.append({"name": "ttft_mean_s", "value": sum(raw["ttft_s"]) / len(raw["ttft_s"]), "unit": "s",
                        "label": L.MEASURED, "method": "mean of raw.ttft_s (%d samples) from run %s" % (len(raw["ttft_s"]), rid)})
        if raw.get("power_w"):
            mean_w = sum(raw["power_w"]) / len(raw["power_w"])
            out.append({"name": "power_mean_w", "value": mean_w, "unit": "W", "label": L.MEASURED,
                        "method": "mean of raw.power_w (%d samples) from run %s" % (len(raw["power_w"]), rid)})
            out.append({"name": "energy_j_per_output_token", "value": mean_w * raw["wall_s"] / raw["output_tokens"],
                        "unit": "J/token", "label": L.MEASURED,
                        "method": "mean power x raw.wall_s / raw.output_tokens from run %s (wall power, idle not subtracted)" % rid})
    if kind == "rtl-sim" and _pos(raw.get("cycles_per_token")):
        out.append({"name": "cycles_per_token", "value": raw["cycles_per_token"], "unit": "cycles",
                    "label": L.MEASURED, "method": "extracted from the simulation log of run %s" % rid})
        clk = rec.get("clock_assumption") or {}
        if _pos(clk.get("period_ns")):
            out.append({"name": "tokps_at_assumed_clock",
                        "value": F.evaluate("1e9 / (c * p)", {"c": raw["cycles_per_token"], "p": clk["period_ns"]}),
                        "unit": "tok/s", "label": L.MODELLED, "token_counting": "output-only",
                        "method": "1e9 / (cycles_per_token x %s ns); clock ASSUMED (%s)" % (clk["period_ns"], clk.get("source", "source not given"))})
    return out


def compare_runs_to_claims(runs: list, reg, res) -> list:
    """For every valid, non-synthetic run, list the registry tok/s numbers whose stated conditions match."""
    rows = []
    for rec in runs:
        if not rec.get("_valid") or rec.get("synthetic"):
            continue
        wl = rec.get("workload") or {}
        run_cond = {"model": (rec.get("model") or {}).get("key"), "batch": wl.get("batch"), "s_in": wl.get("s_in"),
                    "s_out": wl.get("s_out"), "chips": (rec.get("system") or {}).get("chips")}
        for d in derive(rec):
            if d["unit"] != "tok/s":
                continue
            for nid in reg.order:
                n = reg.numbers[nid]
                if n.get("unit") != "tok/s" or n.get("label") == L.NOT_YET:
                    continue
                c = n.get("conditions") or {}
                keys = ("model", "batch", "s_in", "s_out", "chips")
                if any(c.get(k) is None or run_cond.get(k) is None for k in keys):
                    continue
                if any(c[k] != run_cond[k] for k in keys) or c.get("token_counting") != d.get("token_counting"):
                    continue
                try:
                    claim_v = res.value(nid)
                except F.FormulaError:
                    continue
                rows.append({"run_id": rec["run_id"], "metric": d["name"], "run_value": d["value"],
                             "run_label": d["label"], "claim": nid, "claim_value": claim_v,
                             "claim_label": n.get("label"), "ratio": d["value"] / claim_v, "ratio_label": L.MODELLED})
    return rows


def _first_line(cmd: list):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (p.stdout or p.stderr or "").strip().splitlines()
    return text[0].strip() if text else None


def env_versions() -> dict:
    """Toolchain versions, as printed by each tool in this environment (MEASURED: a tool printed it)."""
    probes = (
        ("python", [sys.executable, "--version"]),
        ("iverilog", ["iverilog", "-V"]),
        ("yosys", ["yosys", "-V"]),
        ("verilator", ["verilator", "--version"]),
        ("sby", ["sby", "--help"]),
        ("openroad", ["openroad", "-version"]),
    )
    tools = {}
    for name, cmd in probes:
        exe = cmd[0] if name == "python" else shutil.which(cmd[0])
        tools[name] = _first_line(cmd) if exe else None
    return {"tools": tools, "platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "collected_utc": _now()}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rerun(cmd: str, cwd: str, extracts: dict, kind: str, run_id: str, model: str,
          out_dir: str = RUNS_DIR, synthetic: bool = False, note: str = "", timeout_s: int = 3600):
    """Run a benchmark command, keep its full log as evidence, and pull metrics out with regexes.
    Each regex must have exactly one capture group holding the number; the LAST match is used.
    Writes <out_dir>/<run_id>.json and <out_dir>/logs/<run_id>.log. Returns (path, record, problems)."""
    if kind not in RUN_KINDS:
        raise ValueError("kind must be one of %s" % (RUN_KINDS,))
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,80}", run_id):
        raise ValueError("run_id must be 3-80 chars of [A-Za-z0-9._-]")
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
    started = _now()
    t0 = time.monotonic()
    proc = subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    wall = time.monotonic() - t0
    log = (proc.stdout or "") + (proc.stderr or "")
    log_rel = os.path.join("logs", run_id + ".log")
    with open(os.path.join(out_dir, log_rel), "w", encoding="utf-8") as fh:
        fh.write(log)
    raw, extraction, problems = {}, {}, []
    for name, rx in extracts.items():
        matches = re.findall(rx, log)
        extraction[name] = {"regex": rx, "matches": len(matches)}
        if not matches:
            problems.append("no match for %s (%s)" % (name, rx))
            continue
        last = matches[-1]
        raw[name] = float(last if isinstance(last, str) else last[0])
        if raw[name].is_integer():
            raw[name] = int(raw[name])
    if proc.returncode != 0:
        problems.append("command exited with %d" % proc.returncode)
    rec = {
        "schema": RUN_SCHEMA, "run_id": run_id, "kind": kind, "date_utc": started,
        "model": {"name": model}, "workload": {}, "raw": raw, "raw_extraction": extraction,
        "command": cmd, "exit_code": proc.returncode, "command_wall_s": wall,
        "evidence": [{"path": log_rel, "sha256": sha256_file(os.path.join(out_dir, log_rel))}],
        "toolchain": env_versions(), "synthetic": bool(synthetic), "note": note, "problems": problems,
    }
    path = os.path.join(out_dir, run_id + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
        fh.write("\n")
    return path, rec, problems
