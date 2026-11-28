"""Turn a sign-off result into a diagnosis: why is the worst path late?

Every tag carries the evidence (numbers) that triggered it, so the ledger can
show *why* an edit was chosen, not just which edit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .reports import analyze_path

DRIVE_RE = re.compile(r"^(.*_X)(\d+)$")


@dataclass
class Diagnosis:
    period_ns: float
    wns_ns: float
    tns_ns: float
    hold_wns_ns: float
    setup_violators: int
    gap_ps: float
    gap_fraction: float
    worst: dict | None
    paths: list = field(default_factory=list)
    tags: dict = field(default_factory=dict)          # tag -> evidence
    weak_drivers: list = field(default_factory=list)  # [{instance, cell, ...}]
    degradation_ns: float = 0.0
    endpoint_mix: dict = field(default_factory=dict)

    def brief(self) -> dict:
        w = self.worst or {}
        return {
            "wns_ns": round(self.wns_ns, 5), "tns_ns": round(self.tns_ns, 5),
            "hold_wns_ns": round(self.hold_wns_ns, 5), "setup_violators": self.setup_violators,
            "gap_ps": round(self.gap_ps, 1), "gap_pct_of_period": round(100 * self.gap_fraction, 2),
            "worst_path": {
                "startpoint": w.get("startpoint"), "endpoint": w.get("endpoint"), "type": w.get("type"),
                "slack_ns": round(w.get("slack_ns", 0), 5), "stages": w.get("n_stages"),
                "cell_delay_ns": round(w.get("cell_delay_ns", 0), 5),
                "wire_delay_ns": round(w.get("net_delay_ns", 0), 5),
                "wire_fraction": round(w.get("wire_fraction", 0), 3),
                "launch_latency_ns": round(w.get("launch_latency_ns", 0), 5),
                "capture_latency_ns": round(w.get("capture_latency_ns", 0), 5),
                "max_fanout": w.get("max_fanout"), "max_slew_ns": round(w.get("max_slew_ns", 0), 5),
            } if w else None,
            "tags": self.tags,
            "weak_drivers": self.weak_drivers[:8],
            "post_route_degradation_ns": round(self.degradation_ns, 5),
            "endpoint_mix_top_paths": self.endpoint_mix,
        }


def upsize(cell: str, library_cells: set[str], dont_use: list[str]) -> str | None:
    """Next stronger drive of the same function, e.g. NAND2_X1 -> NAND2_X2."""
    m = DRIVE_RE.match(cell)
    if not m:
        return None
    base, drive = m.group(1), int(m.group(2))
    stronger = sorted(int(DRIVE_RE.match(c).group(2)) for c in library_cells
                      if DRIVE_RE.match(c) and DRIVE_RE.match(c).group(1) == base
                      and int(DRIVE_RE.match(c).group(2)) > drive)
    for d in stronger:
        cand = f"{base}{d}"
        if not any(re.fullmatch(p.replace("*", ".*"), cand) for p in dont_use):
            return cand
    return None


def diagnose(ev, period_ns: float, library_cells: set[str] | None = None,
             dont_use: list[str] | None = None) -> Diagnosis:
    s = ev.summary()
    paths = [analyze_path(c) for c in ev.signoff["paths_max"]]
    fanouts = ev.signoff.get("fanouts") or {}
    for p in paths:   # OpenSTA's JSON omits fanout; take it from the text report
        for st in p["stages"]:
            if st.get("fanout") is None:
                st["fanout"] = fanouts.get(st["out_pin"])
        p["max_fanout"] = max([st["fanout"] or 0 for st in p["stages"]], default=0)
    worst = paths[0] if paths else None
    wns = s["wns_ns"]
    gap = max(0.0, -wns)
    d = Diagnosis(period_ns=period_ns, wns_ns=wns, tns_ns=s["tns_ns"], hold_wns_ns=s["hold_wns_ns"],
                  setup_violators=s["setup_violators"], gap_ps=gap * 1000,
                  gap_fraction=gap / period_ns, worst=worst, paths=paths)
    tags = d.tags
    if wns >= 0 and s["tns_ns"] >= 0 and s["hold_wns_ns"] >= 0:
        tags["CLOSED"] = "setup and hold met at sign-off"
    if s["hold_wns_ns"] < 0:
        tags["HOLD_VIOLATION"] = f"hold WNS {s['hold_wns_ns']:+.4f} ns"
    elif s["hold_wns_ns"] < 0.02:
        tags["HOLD_TIGHT"] = f"hold WNS only {s['hold_wns_ns']:+.4f} ns"
    if worst is None or wns >= 0:
        return d

    neg = [p for p in paths if p["slack_ns"] < 0]
    d.endpoint_mix = {
        "output_port": sum(p["end_is_port"] for p in neg),
        "input_port_start": sum(p["start_is_port"] for p in neg),
        "register_to_register": sum((not p["end_is_port"]) and (not p["start_is_port"]) for p in neg),
    }
    if d.endpoint_mix["output_port"] or d.endpoint_mix["input_port_start"]:
        tags["IO_BOUND"] = (f"{d.endpoint_mix['output_port']} of {len(neg)} top violating paths end at "
                            f"an output port, {d.endpoint_mix['input_port_start']} start at an input port")
    out_paths = [p for p in neg if p["end_is_port"]]
    if out_paths:
        lat = max(p["launch_latency_ns"] for p in out_paths)
        if lat >= 0.3 * gap:
            tags["IO_LAUNCH_LATENCY"] = (f"output-port paths pay the launch flop's clock insertion delay "
                                         f"({lat:.4f} ns) against an ideal-clock output budget; the miss is "
                                         f"{gap:.4f} ns")
    if worst["wire_fraction"] >= 0.25:
        tags["WIRE_DOMINATED"] = (f"wire delay {worst['net_delay_ns']:.4f} ns = "
                                  f"{100 * worst['wire_fraction']:.0f}% of the worst data path")
    if worst["n_stages"] >= 12 and worst["wire_fraction"] < 0.25:
        tags["DEEP_LOGIC"] = f"{worst['n_stages']} cell stages, cell delay {worst['cell_delay_ns']:.4f} ns"
    if worst["max_fanout"] and worst["max_fanout"] >= 12:
        tags["HIGH_FANOUT"] = f"max fanout {worst['max_fanout']} on the worst path"
    if worst["max_slew_ns"] >= 0.06:
        tags["SLOW_SLEWS"] = f"max slew {worst['max_slew_ns']:.4f} ns on the worst path"
    skew = worst["skew_penalty_ns"]
    if skew >= 0.005 and skew >= 0.1 * gap:
        tags["SKEW_PENALTY"] = (f"launch latency {worst['launch_latency_ns']:.4f} ns exceeds capture "
                                f"latency {worst['capture_latency_ns']:.4f} ns by {skew:.4f} ns")
    cong = ev.congestion
    if (cong.get("total_overflow") or 0) > 0 or (cong.get("max_layer_usage_pct") or 0) >= 70:
        tags["CONGESTED"] = (f"GRT overflow {cong.get('total_overflow')}, max layer usage "
                             f"{cong.get('max_layer_usage_pct')}%")
    grt_wns = ev.stage_metrics.get("grt", {}).get("grt_wns")
    cts_wns = ev.stage_metrics.get("cts", {}).get("cts_wns")
    est = cts_wns if cts_wns is not None else grt_wns
    if est is not None:
        d.degradation_ns = est - wns
        if d.degradation_ns >= 0.005:
            tags["POST_ROUTE_DEGRADATION"] = (f"optimizer saw WNS {est:+.4f} ns on placement parasitics; "
                                              f"routed sign-off is {wns:+.4f} ns")
    if s["setup_violators"] >= 20:
        tags["MANY_ENDPOINTS"] = f"{s['setup_violators']} violating endpoints"
    if library_cells:
        seen = set()
        for p in neg[:5]:
            for st in p["stages"]:
                if st["instance"] in seen or not st["cell"]:
                    continue
                m = DRIVE_RE.match(st["cell"])
                if not m or int(m.group(2)) > 2 or st["cell"].startswith(("DFF", "SDFF", "DL")):
                    continue
                if st["out_cap_ff"] >= 4.0 or (st["fanout"] or 0) >= 3 or st["out_slew_ns"] >= 0.025:
                    new = upsize(st["cell"], library_cells, dont_use or [])
                    if new:
                        seen.add(st["instance"])
                        d.weak_drivers.append({"instance": st["instance"], "cell": st["cell"], "to": new,
                                               "out_cap_ff": st["out_cap_ff"], "fanout": st["fanout"],
                                               "delay_ns": st["delay_ns"], "path_endpoint": p["endpoint"]})
        if d.weak_drivers:
            tags["WEAK_DRIVERS"] = (f"{len(d.weak_drivers)} X1/X2 drivers on the worst paths drive "
                                    f">=4 fF or >=3 loads")
    if gap > 0 and gap <= 0.1:
        tags["NEAR_MISS"] = f"miss is {gap * 1000:.1f} ps ({100 * d.gap_fraction:.1f}% of the period)"
    return d


def library_cells(liberty_text: str) -> set[str]:
    return set(re.findall(r"^\s*cell\s*\(\s*\"?([A-Za-z0-9_]+)\"?\s*\)", liberty_text, re.M))
