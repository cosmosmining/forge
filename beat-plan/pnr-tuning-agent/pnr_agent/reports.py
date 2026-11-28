"""Parsers for OpenROAD / OpenSTA outputs.

All times returned in ns, capacitances in fF, power in W.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

S_TO_NS = 1e9
F_TO_FF = 1e15


def last_error(log_text: str) -> str:
    errs = [l for l in log_text.splitlines() if "[ERROR" in l or l.startswith("Error")]
    return errs[-1].strip() if errs else "no error line in log"


def count_drc(drc_rpt: Path, log_text: str = "") -> int | None:
    """Count TritonRoute DRC violations from the -output_drc report."""
    m = re.findall(r"PA_DRC_COUNT (\d+)", log_text)
    if m:
        return int(m[-1])
    if drc_rpt.exists():
        return sum(1 for line in drc_rpt.read_text(errors="replace").splitlines()
                   if line.startswith("violation type"))
    return None


def parse_grt_congestion(log_text: str) -> dict:
    """Last 'Final congestion report' table + total wirelength from a GRT log."""
    out: dict = {"layers": {}}
    blocks = log_text.split("Final congestion report:")
    if len(blocks) > 1:
        block = blocks[-1]
        for line in block.splitlines()[1:]:
            m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", line)
            if m:
                name = m.group(1)
                row = {"resource": int(m.group(2)), "demand": int(m.group(3)),
                       "usage_pct": float(m.group(4)), "overflow_h": int(m.group(5)),
                       "overflow_v": int(m.group(6)), "overflow": int(m.group(7))}
                if name == "Total":
                    out["total_usage_pct"] = row["usage_pct"]
                    out["total_overflow"] = row["overflow"]
                    break
                out["layers"][name] = row
    wl = re.findall(r"Total wirelength:\s*([\d.]+)\s*um", log_text)
    if wl:
        out["wirelength_um"] = float(wl[-1])
    if out["layers"]:
        out["max_layer_usage_pct"] = max(r["usage_pct"] for r in out["layers"].values())
    return out


def _count_violated(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(errors="replace").splitlines() if "(VIOLATED)" in line)


def parse_power(path: Path) -> float | None:
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("Total"):
            nums = re.findall(r"[-+]?\d+\.\d+e[-+]\d+", line)
            if len(nums) >= 4:
                return float(nums[3])
    return None


def parse_signoff(sdir: Path) -> dict:
    log = (sdir / "signoff.log").read_text(errors="replace")

    def grab(tag):
        m = re.findall(rf"^{tag} (\S+)", log, re.M)
        if not m:
            raise ValueError(f"sign-off log has no {tag}")
        v = float(m[-1])  # sta:: Tcl accessors return user units (ns)
        return None if abs(v) > 1e29 else v

    clocks = {m.group(1): float(m.group(2))
              for m in re.finditer(r"^PA_CLOCK (\S+) (\S+)", log, re.M)}
    wns_max, wns_min = grab("PA_WNS_MAX"), grab("PA_WNS_MIN")
    out = {
        "clock_periods": clocks,
        "wns_max": wns_max,
        "wns_min": wns_min,
        "tns_max": grab("PA_TNS_MAX"),
        "tns_min": grab("PA_TNS_MIN"),
        "skew_setup": grab("PA_SKEW_SETUP"),
        "violators_max": _count_violated(sdir / "violators_max.rpt"),
        "violators_min": _count_violated(sdir / "violators_min.rpt"),
        "drv_violations": _count_violated(sdir / "drv.rpt"),
        "power_total_w": parse_power(sdir / "power.rpt"),
        "paths_max": load_paths(sdir / "paths_max.json"),
        "paths_min": load_paths(sdir / "paths_min.json"),
        "fanouts": parse_fanouts(sdir / "top_paths_max.rpt"),
    }
    return out


FANOUT_RE = re.compile(r"^\s+(\d+)\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+[\^v]\s+(\S+)\s+\(")


def parse_fanouts(path: Path) -> dict:
    """{driver pin: fanout} from an OpenSTA text path report run with -fields fanout."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        m = FANOUT_RE.match(line)
        if m:
            out[m.group(2)] = int(m.group(1))
    return out


def load_paths(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(errors="replace")
    i = text.find("{")
    if i < 0:
        return []
    return json.loads(text[i:]).get("checks", [])


def _ns(v):
    return None if v is None else v * S_TO_NS


def analyze_path(check: dict) -> dict:
    """Break one OpenSTA JSON path into launch clock, data stages and capture.

    Cell delay = arrival(output pin) - arrival(input pin) of the same instance.
    Net delay  = arrival(load pin)   - arrival(driver pin) of the previous instance.
    """
    sp = check["source_path"]
    start = check["startpoint"]
    idx = next((i for i, p in enumerate(sp) if p.get("pin") == start), None)
    if idx is None:  # input port startpoints may be listed by port name
        idx = next((i for i, p in enumerate(sp) if p.get("pin", "").split("/")[0] == start), 0)
    start_is_port = "/" not in start
    launch_latency = 0.0
    if not start_is_port and idx > 0 and sp[idx - 1].get("instance") == sp[idx].get("instance"):
        launch_latency = sp[idx - 1]["arrival"] * S_TO_NS
    data = sp[idx - 1:] if (not start_is_port and idx > 0) else sp[idx:]
    stages, cell_delay, net_delay = [], 0.0, 0.0
    for a, b in zip(data, data[1:]):
        d = (b["arrival"] - a["arrival"]) * S_TO_NS
        if a.get("instance") and a.get("instance") == b.get("instance"):
            cell_delay += d
            stages.append({
                "instance": b["instance"], "cell": b.get("cell"),
                "in_pin": a["pin"], "out_pin": b["pin"], "delay_ns": round(d, 5),
                "out_cap_ff": round((b.get("capacitance") or 0) * F_TO_FF, 3),
                "out_slew_ns": round((b.get("slew") or 0) * S_TO_NS, 5),
                "fanout": b.get("fanout"), "net": b.get("net"),
            })
        else:
            net_delay += d
            if stages:
                stages[-1]["wire_delay_ns"] = round(d, 5)
    tcp = check.get("target_clock_path") or []
    capture_latency = tcp[-1]["arrival"] * S_TO_NS if tcp else 0.0
    end = check["endpoint"]
    total = cell_delay + net_delay
    return {
        "type": check["type"],
        "startpoint": start, "endpoint": end,
        "start_is_port": start_is_port,
        "end_is_port": check["type"] == "output_delay",
        "slack_ns": check["slack"] * S_TO_NS,
        "arrival_ns": check["data_arrival_time"] * S_TO_NS,
        "required_ns": check["required_time"] * S_TO_NS,
        "margin_ns": (check.get("margin") or 0) * S_TO_NS,
        "launch_latency_ns": launch_latency,
        "capture_latency_ns": capture_latency,
        "skew_penalty_ns": (launch_latency - capture_latency) if tcp else 0.0,
        "cell_delay_ns": cell_delay,
        "net_delay_ns": net_delay,
        "wire_fraction": (net_delay / total) if total > 0 else 0.0,
        "n_stages": len(stages),
        "stages": stages,
        "max_fanout": max([s["fanout"] or 0 for s in stages], default=0),
        "max_cap_ff": max([s["out_cap_ff"] for s in stages], default=0.0),
        "max_slew_ns": max([s["out_slew_ns"] for s in stages], default=0.0),
    }
