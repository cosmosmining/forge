#!/usr/bin/env python3
"""Merge targets/baseline_<block>.json into targets/targets.json and targets/calibration.json.
Refuses to write unless every block has T0, T1 and references, and the original RTL
fails post-route at T1 (otherwise T1 would not need any RTL change)."""
import datetime
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLOCKS = ["gcd", "aes_cipher_top", "riscv", "dct_mac", "dctub", "jpeg_qnr"]


def tool_versions():
    oss = os.environ.get("OSS_CAD_BIN", "/opt/eda/oss-cad-suite/bin")
    ore = os.environ.get("OPENROAD_EXE", "/opt/eda/openroad/bin/openroad")
    orfs = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
    v = lambda cmd: subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout.strip()
    return {"yosys": v([os.path.join(oss, "yosys"), "-V"]),
            "iverilog": v([os.path.join(oss, "iverilog"), "-V"]).splitlines()[0],
            "verilator": v([os.path.join(oss, "verilator"), "--version"]),
            "openroad": v([ore, "-version"]).splitlines()[-1].strip(),
            "orfs_commit": v(["git", "-C", orfs, "rev-parse", "HEAD"])}


def main():
    out = {"created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "rule": {"T1_over_T0": 0.9, "area_power_limit_pct": 5.0,
                    "postroute_pass": "setup WNS >= 0, hold WNS >= 0, 0 DRC errors at T1",
                    "area_reference": "original RTL, post-route at T0",
                    "power_reference": "original RTL post-route layout at T0, power re-computed at the T1 frequency"},
           "tools": tool_versions(), "blocks": {}}
    cal = {}
    problems = []
    for b in BLOCKS:
        p = os.path.join(HERE, "baseline_%s.json" % b)
        if not os.path.exists(p):
            problems.append("%s: no baseline" % b)
            continue
        d = json.load(open(p))
        if "references" not in d:
            problems.append("%s: baseline incomplete" % b)
            continue
        if not d.get("original_fails_postroute_at_T1"):
            problems.append("%s: original RTL already closes at T1" % b)
        out["blocks"][b] = {k: d[k] for k in ("T0_ns", "T1_ns", "clock_latency_ns", "prelayout_min_period_ns",
                                                "references", "original_fails_postroute_at_T1")}
        cal[b] = d["clock_latency_ns"]
    if problems:
        raise SystemExit("not writing targets: " + "; ".join(problems))
    json.dump(out, open(os.path.join(HERE, "targets.json"), "w"), indent=1)
    json.dump({"clock_latency_ns": cal}, open(os.path.join(HERE, "calibration.json"), "w"), indent=1)
    print(json.dumps({b: (v["T0_ns"], v["T1_ns"]) for b, v in out["blocks"].items()}))


if __name__ == "__main__":
    main()
