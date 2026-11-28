"""What the agent may never do, and what every accepted result must satisfy.

Forge's rule: "Only PASS counts, and a test is never relaxed to get one."
For timing closure that means the clock, the I/O budgets and the timing
exceptions in the golden SDC are fixed.  The agent closes timing by changing
the implementation, never the question.
"""
from __future__ import annotations

import re
from pathlib import Path

# The only commands allowed in the optimization-only overlay.  They tighten
# electrical targets for the optimizer; sign-off never reads the overlay.
OVERLAY_WHITELIST = {"set_max_fanout", "set_max_transition", "set_max_capacitance"}

# Never allowed anywhere the agent writes: these would change what "timing
# closed" means rather than the implementation.
FORBIDDEN_SDC = {
    "create_clock", "create_generated_clock", "set_clock_uncertainty", "set_clock_latency",
    "set_input_delay", "set_output_delay", "set_false_path", "set_multicycle_path",
    "set_max_delay", "set_min_delay", "set_disable_timing", "set_case_analysis",
    "set_clock_groups", "set_timing_derate", "set_load", "set_driving_cell",
    "set_input_transition", "remove_clock", "set_ideal_network", "set_propagated_clock",
}

PERIOD_TOL_NS = 1e-6
SLACK_EPS_NS = 1e-6


def check_overlay(text: str) -> list[str]:
    """Return violations in an optimization overlay (empty list = clean)."""
    problems = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        cmd = re.split(r"\s+", line, maxsplit=1)[0]
        if cmd in FORBIDDEN_SDC:
            problems.append(f"forbidden command in overlay: {cmd}")
        elif cmd not in OVERLAY_WHITELIST:
            problems.append(f"command not whitelisted for overlay: {cmd}")
    return problems


def validate(ev, baseline, design, fingerprint: dict) -> list[dict]:
    """Checks every candidate must pass before it can be accepted.

    Returns a list of {name, ok, detail}.  ev/baseline are runner.Evaluation.
    """
    s, b = ev.summary(), baseline.summary()
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    now = design.golden_fingerprint()
    add("golden inputs unchanged", now == fingerprint,
        "netlist/SDC/liberty hashes and target period match baseline" if now == fingerprint
        else f"golden inputs changed: {now} vs {fingerprint}")
    periods = s["clock_periods_ns"]
    add("clock period unchanged at sign-off",
        bool(periods) and all(abs(p - design.target_period_ns) <= PERIOD_TOL_NS for p in periods.values()),
        f"sign-off clocks {periods}, target {design.target_period_ns} ns")
    overlay_problems = []
    for sdir in ev.stage_dirs.values():
        ov = Path(sdir) / "opt_constraints.sdc"
        if ov.exists():
            overlay_problems += check_overlay(ov.read_text())
    add("optimization overlay whitelisted", not overlay_problems,
        "; ".join(overlay_problems) or "only set_max_fanout/transition/capacitance (or none)")
    add("fully routed, zero DRC", s["routed"] and s["drc"] == 0,
        f"routed={s['routed']} drc={s['drc']}")
    add("placement legal", ev.route.get("placement_ok", False), "check_placement")
    ant, ant0 = s["antenna_nets"] or 0, b["antenna_nets"] or 0
    add("antenna not worse", ant <= ant0, f"{ant} vs baseline {ant0}")
    hold, hold0 = s["hold_wns_ns"], b["hold_wns_ns"]
    add("no new hold violations",
        hold is not None and hold >= min(0.0, hold0) - SLACK_EPS_NS and s["hold_violators"] <= b["hold_violators"],
        f"hold WNS {hold:+.4f} ns ({s['hold_violators']} viol) vs baseline {hold0:+.4f} ns "
        f"({b['hold_violators']} viol)")
    add("no new slew/cap/fanout violations", s["drv_violations"] <= b["drv_violations"],
        f"{s['drv_violations']} vs baseline {b['drv_violations']}")
    area, area0 = s["area_um2"], b["area_um2"]
    limit = area0 * (1 + design.max_area_growth)
    add("area growth within limit", area <= limit,
        f"{area:.1f} um2 vs baseline {area0:.1f} um2 (limit +{design.max_area_growth:.0%})")
    return checks


def is_closed(summary: dict) -> bool:
    return (summary["wns_ns"] >= -SLACK_EPS_NS and summary["tns_ns"] >= -SLACK_EPS_NS
            and summary["hold_wns_ns"] >= -SLACK_EPS_NS and summary["drc"] == 0
            and summary["routed"])
