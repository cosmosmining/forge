"""The action catalog: structured edits the agent can make, and when.

Lesson taken from PACT (Lin et al., "Post-route Agentic Checkpoint Tuning for
FPGA Timing Closure", arXiv:2608.23602): a plain sweep of tool directives
gained +2.98% Fmax where structured, local edits with validation gained
+22.30%; closure is limited by "action granularity and validation discipline".
So the catalog is ordered fine-grained first (guard-banded repair, routing-
aware ECO, targeted resizing), then placement/floorplan, and every action is
a typed edit to the recipe that the harness validates, never free-form Tcl.

Categories map to the brief's "floorplan / constraints / RTL":
  floorplan   -> core margin inside a fixed die, IO pin placement
  constraint  -> optimization-only overlay (tighter fanout/transition limits)
  placement, cts, optimization, routing, eco -> physical implementation edits
  rtl         -> written proposal only (changes latency; needs Forge's proof gate)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .diagnose import Diagnosis


@dataclass
class Proposal:
    action: str
    category: str
    changes: dict
    rationale: str
    priority: float
    evidence: list = field(default_factory=list)


@dataclass
class RtlProposal:
    """Recorded, never auto-applied: an RTL change alters cycle behaviour and
    must pass Forge's verification gate (simulation vs. the integer model)."""
    title: str
    detail: str
    evidence: dict


def _round_up_ps(ns: float) -> float:
    return math.ceil(ns * 1000.0) / 1000.0


def _boost(diag: Diagnosis, tags: tuple, amount: float) -> tuple[float, list]:
    hit = [t for t in tags if t in diag.tags]
    return (amount if hit else 0.0), [f"{t}: {diag.tags[t]}" for t in hit]


def propose_all(diag: Diagnosis, recipe: dict, design) -> list[Proposal]:
    gap = max(0.0, -diag.wns_ns)
    period = diag.period_ns
    props: list[Proposal] = []

    def add(action, category, changes, rationale, base, boosts=()):
        changes = {k: v for k, v in changes.items() if recipe.get(k) != v}
        if not changes:
            return
        prio, ev = base, []
        for tags, amount in boosts:
            b, e = _boost(diag, tags, amount)
            prio += b
            ev += e
        props.append(Proposal(action, category, changes, rationale, round(prio, 3), ev))

    if gap <= 0:
        return props

    # --- fine-grained / optimization first (PACT: granularity + validation)
    cap = round(0.15 * period, 4)
    margin = min(cap, _round_up_ps(max(recipe["rt_setup_margin"], 0.0) + gap))
    if margin > recipe["rt_setup_margin"]:
        add("guardband_setup_repair", "optimization", {"rt_setup_margin": margin},
            f"Post-CTS repair_timing stops at zero slack on placement parasitics, then routing "
            f"takes {gap * 1000:.1f} ps back. Re-run it to a +{margin * 1000:.0f} ps guard-band so it "
            f"over-fixes what routing costs.", 0.90,
            [(("POST_ROUTE_DEGRADATION",), 0.10), (("NEAR_MISS",), 0.05)])
    if not recipe["grt_repair_timing"]:
        add("routing_aware_eco_repair", "optimization",
            {"grt_repair_timing": True, "grt_rt_setup_margin": _round_up_ps(min(cap, gap))},
            "Incremental ECO after global routing: repair_timing on global-route parasitics "
            "(closer to routed RC than placement estimates), then incremental re-route.", 0.85,
            [(("POST_ROUTE_DEGRADATION",), 0.10), (("WIRE_DOMINATED",), 0.05)])
    if diag.weak_drivers:
        current = dict(recipe["eco_resize"])
        new = dict(current)
        for wd in diag.weak_drivers[:8]:
            new[wd["instance"]] = wd["to"]
        if new != current:
            add("eco_upsize_worst_paths", "eco", {"eco_resize": tuple(sorted(new.items()))},
                "Targeted resize of weak drivers on the worst paths: "
                + ", ".join(f"{w['instance']} {w['cell']}->{w['to']} ({w['out_cap_ff']:.1f} fF)"
                            for w in diag.weak_drivers[:8]), 0.80,
                [(("WEAK_DRIVERS",), 0.10)])
    if recipe["rt_skip_gate_cloning"]:
        add("enable_gate_cloning", "optimization", {"rt_skip_gate_cloning": False},
            "Let repair_timing clone gates to split the load of drivers on critical paths "
            "(the reference flow disables it).", 0.60,
            [(("HIGH_FANOUT", "WEAK_DRIVERS"), 0.20)])
    if not recipe["rt_use_grt_parasitics"]:
        add("repair_on_route_parasitics", "optimization", {"rt_use_grt_parasitics": True},
            "Post-CTS repair_timing on global-route parasitics instead of placement estimates.", 0.60,
            [(("POST_ROUTE_DEGRADATION",), 0.10)])
    # --- logic restructuring (netlist-level "synthesis" edit; registers untouched,
    #     so the Yosys equivalence check still proves it)
    # (OpenROAD's own `restructure -target timing` is wired up as knob rs_timing but not
    #  proposed: in the pinned OpenROAD build every ABC result reports delay FLT_MAX and is
    #  discarded, so it never changes the netlist. Re-synthesis below does the same job.)
    w = diag.worst or {}
    if w and w.get("wire_fraction", 1) < 0.25 and w.get("n_stages", 0) >= 8:
        period_ps = period * 1000.0
        cur = recipe["resynth_delay_ps"]
        target = int(round(0.6 * period_ps)) if cur is None else int(round(0.8 * cur))
        if target >= int(0.3 * period_ps) and target != cur:
            add("resynthesize_for_delay", "synthesis", {"resynth_delay_ps": target},
                f"The worst path is {w['n_stages']} cell stages with only {100 * w['wire_fraction']:.0f}% "
                f"wire delay, so placement and routing cannot recover {gap * 1000:.0f} ps. Re-map the "
                f"combinational logic with Yosys/ABC to a {target} ps delay target; every register keeps "
                f"its instance, so the result is proven equivalent to the golden netlist.", 0.75,
                [(("DEEP_LOGIC",), 0.20)])

    # --- clock tree insertion delay on output-bound paths
    stronger = {"BUF_X1": "BUF_X4", "BUF_X2": "BUF_X4", "BUF_X4": "BUF_X8", "BUF_X8": "BUF_X16"}
    if "IO_LAUNCH_LATENCY" in diag.tags and recipe["cts_buffer"] in stronger:
        add("faster_clock_tree", "cts", {"cts_buffer": stronger[recipe["cts_buffer"]]},
            "Output paths start at a flop whose clock arrives late (insertion delay) while the output "
            "budget assumes an ideal clock; build the tree from stronger buffers to cut real latency.",
            0.55, [(("IO_LAUNCH_LATENCY",), 0.20)])

    # --- placement / floorplan
    if not recipe["gp_timing_driven"]:
        add("timing_driven_placement", "placement", {"gp_timing_driven": True},
            "Timing-driven global placement: re-weights critical nets so their cells are "
            "pulled together.", 0.55,
            [(("WIRE_DOMINATED",), 0.25)])
    if "CONGESTED" not in diag.tags and recipe["gp_density"] < 0.8:
        add("raise_placement_density", "placement",
            {"gp_density": round(min(0.8, recipe["gp_density"] + 0.15), 2)},
            "Pack cells more tightly (routing is not congested) to shorten wires.", 0.35,
            [(("WIRE_DOMINATED",), 0.20)])
    if "CONGESTED" in diag.tags and recipe["gp_density"] > 0.2:
        add("lower_placement_density", "placement",
            {"gp_density": round(max(0.2, recipe["gp_density"] - 0.1), 2)},
            "Spread cells: routing congestion is forcing detours.", 0.80)
    if "IO_BOUND" in diag.tags:
        die, core = design.die_area, design.core_area
        if die and core:
            cur = recipe["fp_core_margin"]
            if cur is None:
                cur = min(core[0] - die[0], core[1] - die[1], die[2] - core[2], die[3] - core[3])
            if cur > 3.0:
                add("shrink_core_margin", "floorplan", {"fp_core_margin": 2.0},
                    f"Worst paths end/start at ports on the die edge; the core edge sits {cur:.1f} um "
                    f"inside the (fixed) die. Move it to 2 um so boundary cells sit closer to their pins.",
                    0.45, [(("IO_BOUND",), 0.20)])
        if not recipe["io_annealing"]:
            add("anneal_io_pins", "floorplan", {"io_annealing": True},
                "Re-place IO pins with simulated annealing against the placed logic.", 0.40,
                [(("IO_BOUND",), 0.15)])
    if recipe["grt_critical_nets_pct"] is None:
        add("route_critical_nets_first", "routing", {"grt_critical_nets_pct": 10},
            "Timing-driven global routing: route the 10% most critical nets first, on their "
            "shortest paths.", 0.50,
            [(("WIRE_DOMINATED", "POST_ROUTE_DEGRADATION"), 0.15)])

    # --- optimization-only constraints (tightening; sign-off unchanged)
    if "HIGH_FANOUT" in diag.tags and recipe["opt_max_fanout"] is None:
        add("tighten_max_fanout", "constraint", {"opt_max_fanout": 8},
            "Optimization-only set_max_fanout 8 so repair_design buffers high-fanout nets.", 0.65)
    if "SLOW_SLEWS" in diag.tags and recipe["opt_max_transition"] is None:
        tgt = round(max(0.05, 0.75 * diag.worst["max_slew_ns"]), 3)
        add("tighten_max_transition", "constraint", {"opt_max_transition": tgt},
            f"Optimization-only set_max_transition {tgt} ns so slow edges on the critical path "
            f"get repaired.", 0.65)

    # --- clock tree
    if "SKEW_PENALTY" in diag.tags:
        if recipe["cts_cluster_diameter"] > 30:
            add("tighter_cts_clusters", "cts",
                {"cts_cluster_diameter": max(25, int(recipe["cts_cluster_diameter"]) // 2)},
                "Smaller sink clusters to cut the launch/capture latency mismatch.", 0.65)
        if not recipe["cts_balance_levels"]:
            add("balance_clock_levels", "cts", {"cts_balance_levels": True},
                "Balance clock-tree levels to cut skew on the critical path.", 0.60)

    props.sort(key=lambda p: (-p.priority, p.action))
    return props


def rtl_proposals(diag: Diagnosis, design) -> list[RtlProposal]:
    """RTL-level suggestions, recorded for a human/agent + the Forge gate."""
    out = []
    w = diag.worst
    if not w or diag.wns_ns >= 0:
        return out
    if "DEEP_LOGIC" in diag.tags or diag.gap_fraction > 0.05:
        out.append(RtlProposal(
            title="Pipeline or restructure the worst cone",
            detail=(f"Worst path {w['startpoint']} -> {w['endpoint']} has {w['n_stages']} cell stages "
                    f"({w['cell_delay_ns']:.3f} ns of cell delay). If physical edits cannot recover "
                    f"{-diag.wns_ns * 1000:.0f} ps, split this cone with a register (adds one cycle of "
                    f"latency) or rebalance it in RTL. Must re-pass Forge's gate (sim vs. integer model)."),
            evidence={"startpoint": w["startpoint"], "endpoint": w["endpoint"],
                      "stages": [s["instance"] + ":" + str(s["cell"]) for s in w["stages"]]}))
    if not design.rtl:
        for p in out:
            p.detail += " (This design config has no RTL, only a netlist, so this stays a proposal.)"
    return out
