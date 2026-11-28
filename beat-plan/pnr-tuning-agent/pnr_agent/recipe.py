"""The recipe: every value the agent is allowed to change, grouped by flow stage.

Defaults reproduce OpenROAD's reference flow (OpenROAD test/flow.tcl, the
script behind its gcd/aes/tinyRocket regression metrics).  A design config can
override defaults in its [knobs] table so that the *baseline* recipe matches
the flow that produced the design's known result.

Nothing in here can change the clock period, the golden SDC, or the netlist
logic: those are not knobs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

STAGES = ["floorplan", "place", "cts", "grt", "drt"]


@dataclass(frozen=True)
class Knob:
    name: str
    stage: str
    default: object
    category: str
    help: str


KNOBS: list[Knob] = [
    # ---- floorplan (die is never changed when the design says floorplan_fixed)
    Knob("fp_core_margin", "floorplan", None, "floorplan",
         "Core-to-die margin in um on every side (None = design core_area). Die stays fixed."),
    Knob("fp_core_util", "floorplan", None, "floorplan",
         "Target core utilization; only allowed when the design's floorplan is not fixed."),
    Knob("fp_aspect_ratio", "floorplan", 1.0, "floorplan", "Core aspect ratio with fp_core_util."),
    Knob("fp_remove_synth_buffers", "floorplan", True, "floorplan",
         "Remove synthesis buffers before placement (reference flow does)."),
    # ---- re-synthesis of combinational logic to a delay target (registers untouched)
    Knob("resynth_delay_ps", "floorplan", None, "synthesis",
         "Re-map the golden netlist's combinational logic with Yosys/ABC to this delay target (ps)."),
    # ---- logic restructuring of critical cones (netlist level, registers untouched)
    Knob("rs_timing", "floorplan", False, "synthesis",
         "OpenROAD restructure -target timing: ABC re-maps deep critical cones for delay."),
    Knob("rs_depth_threshold", "floorplan", 16, "synthesis", "Only cones at least this deep (OpenROAD default 16)."),
    Knob("rs_slack_threshold", "floorplan", 0.0, "synthesis",
         "Restructure endpoints whose pre-placement slack is below this (ns)."),
    # ---- placement + electrical repair
    Knob("gp_density", "place", 0.3, "placement", "Global placement target density."),
    Knob("gp_routability_driven", "place", True, "placement", "Routability-driven global placement."),
    Knob("gp_timing_driven", "place", False, "placement", "Timing-driven global placement (net re-weighting)."),
    Knob("gp_td_net_weight_max", "place", None, "placement", "Max net weight in timing-driven placement."),
    Knob("gp_td_nets_percentage", "place", None, "placement", "Percent of worst nets re-weighted."),
    Knob("gp_pad", "place", 2, "placement", "Global placement cell padding (sites)."),
    Knob("dp_pad", "place", 1, "placement", "Detailed placement cell padding (sites)."),
    Knob("io_annealing", "place", False, "floorplan", "Simulated-annealing IO pin placement."),
    Knob("rd_slew_margin", "place", 0, "optimization", "repair_design slew margin (%)."),
    Knob("rd_cap_margin", "place", 0, "optimization", "repair_design capacitance margin (%)."),
    Knob("rd_max_wire_length", "place", None, "optimization", "repair_design max wire length (um)."),
    Knob("opt_max_fanout", "place", None, "constraint",
         "Optimization-only set_max_fanout (tightening). Sign-off uses the golden SDC."),
    Knob("opt_max_transition", "place", None, "constraint",
         "Optimization-only set_max_transition in ns (tightening). Sign-off uses the golden SDC."),
    Knob("wire_rc_layer", "place", "metal3", "optimization", "Layer RC used for placement parasitics."),
    Knob("wire_rc_layer_clk", "place", "metal6", "optimization", "Layer RC used for clock parasitics."),
    # ---- clock tree + post-CTS timing repair
    Knob("cts_buffer", "cts", "BUF_X4", "cts", "CTS buffer master."),
    Knob("cts_cluster_diameter", "cts", 100, "cts", "Sink clustering max diameter (um)."),
    Knob("cts_cluster_size", "cts", None, "cts", "Sink clustering max size."),
    Knob("cts_balance_levels", "cts", False, "cts", "Balance clock tree levels."),
    Knob("rt_setup_margin", "cts", 0.0, "optimization",
         "repair_timing setup guard-band in ns (optimize past zero to absorb post-route degradation)."),
    Knob("rt_skip_gate_cloning", "cts", True, "optimization", "Skip gate cloning in repair_timing."),
    Knob("rt_skip_pin_swap", "cts", False, "optimization", "Skip pin swapping in repair_timing."),
    Knob("rt_skip_last_gasp", "cts", False, "optimization", "Skip last-gasp sizing in repair_timing."),
    Knob("rt_repair_tns", "cts", None, "optimization", "repair_timing -repair_tns percent."),
    Knob("rt_max_passes", "cts", None, "optimization", "repair_timing -max_passes."),
    Knob("rt_use_grt_parasitics", "cts", False, "optimization",
         "Post-CTS repair_timing on global-route parasitics instead of placement estimates."),
    # ---- global route (+ ECO)
    Knob("grt_layer_adjustment", "grt", 0.5, "routing", "Routing resource reduction on metal2-metal10."),
    Knob("grt_critical_nets_pct", "grt", None, "routing",
         "Timing-driven global routing: percent of most critical nets routed with priority."),
    Knob("grt_congestion_iters", "grt", 100, "routing", "Global route congestion iterations."),
    Knob("grt_repair_timing", "grt", False, "optimization",
         "Incremental ECO: repair_timing on global-route parasitics, then incremental re-route."),
    Knob("grt_rt_setup_margin", "grt", 0.0, "optimization", "Setup guard-band for the GRT-stage ECO (ns)."),
    Knob("eco_resize", "grt", (), "eco",
         "Targeted ECO: tuple of (instance, new_master) applied before global routing."),
    # ---- detailed route
    Knob("drt_end_iter", "drt", None, "routing", "Detailed route end iteration (None = tool default)."),
]

KNOB_BY_NAME = {k.name: k for k in KNOBS}


def default_recipe(overrides: dict | None = None) -> dict:
    recipe = {k.name: k.default for k in KNOBS}
    for key, value in (overrides or {}).items():
        if key not in KNOB_BY_NAME:
            raise KeyError(f"unknown knob in design [knobs]: {key}")
        recipe[key] = _normalize(value)
    return recipe


def _normalize(value):
    if isinstance(value, list):
        return tuple(_normalize(v) for v in value)
    return value


def apply_changes(recipe: dict, changes: dict) -> dict:
    new = dict(recipe)
    for key, value in changes.items():
        if key not in KNOB_BY_NAME:
            raise KeyError(f"unknown knob: {key}")
        new[key] = _normalize(value)
    return new


def stage_knobs(recipe: dict, stage: str) -> dict:
    return {k.name: recipe[k.name] for k in KNOBS if k.stage == stage}


def prefix_hashes(recipe: dict, design_fingerprint: dict) -> dict:
    """Hash of (inputs + knobs of this stage and every earlier stage).

    Two recipes that agree up to stage S share the cached result of stage S.
    """
    hashes = {}
    h = hashlib.sha256(json.dumps(design_fingerprint, sort_keys=True).encode())
    for stage in STAGES:
        h.update(json.dumps(stage_knobs(recipe, stage), sort_keys=True, default=str).encode())
        hashes[stage] = h.copy().hexdigest()[:16]
    return hashes


def recipe_hash(recipe: dict) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, default=str).encode()).hexdigest()[:16]


def diff(a: dict, b: dict) -> dict:
    """Knobs whose value differs, as {knob: [old, new]}."""
    return {k: [a.get(k), b.get(k)] for k in b if a.get(k) != b.get(k)}


def earliest_stage(changes: dict) -> str:
    stages = [KNOB_BY_NAME[k].stage for k in changes]
    return min(stages, key=STAGES.index) if stages else "drt"
