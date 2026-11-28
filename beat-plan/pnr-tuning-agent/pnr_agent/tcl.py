"""OpenROAD Tcl generation, one script per flow stage, plus the OpenSTA sign-off script.

Stage structure follows OpenROAD's reference flow (test/flow.tcl in the
OpenROAD repository, BSD-3-Clause, Copyright (c) 2019 The Regents of the
University of California).  Every value the agent may change comes from the
recipe; every value it may not change (netlist, golden SDC, liberty, period)
comes from the design config.

The optimization-only constraint overlay (opt_constraints.sdc) is the only
SDC the agent writes.  It may only *tighten* electrical limits and is never
read by sign-off.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import Design

METRICS_TCL = r"""
set ::pa_metrics {}
proc pa_metric {key value} { lappend ::pa_metrics $key $value }
proc pa_num {v} {
  if {[string is double -strict $v]} {
    if {abs($v) > 1e29} { return null }
    return [format %.6g $v]
  }
  return "\"$v\""
}
proc pa_write_metrics {path} {
  set fh [open $path w]
  puts $fh "\{"
  set n [llength $::pa_metrics]
  for {set i 0} {$i < $n} {incr i 2} {
    set k [lindex $::pa_metrics $i]
    set v [pa_num [lindex $::pa_metrics [expr {$i + 1}]]]
    set sep [expr {$i + 2 < $n ? "," : ""}]
    puts $fh "  \"$k\": $v$sep"
  }
  puts $fh "\}"
  close $fh
}
proc pa_timing_metrics {prefix} {
  pa_metric ${prefix}_wns [sta::worst_slack -max]
  pa_metric ${prefix}_tns [sta::total_negative_slack -max]
  pa_metric ${prefix}_hold_wns [sta::worst_slack -min]
}
proc pa_have_macros {} {
  foreach inst [[[[::ord::get_db] getChip] getBlock] getInsts] {
    if {[string match [[$inst getMaster] getType] "BLOCK"]} { return 1 }
  }
  return 0
}
"""


def _q(path) -> str:
    """Brace-quote a path for Tcl."""
    s = str(path)
    if any(c in s for c in "{}"):
        raise ValueError(f"unsupported character in path: {s}")
    return "{" + s + "}"


def _tcl_list(items) -> str:
    return "{" + " ".join(str(i) for i in items) + "}"


def overlay_sdc(recipe: dict) -> str:
    """Optimization-only constraints. Whitelisted commands only (see guardrails)."""
    lines = []
    if recipe["opt_max_fanout"] is not None:
        lines.append(f"set_max_fanout {int(recipe['opt_max_fanout'])} [current_design]")
    if recipe["opt_max_transition"] is not None:
        lines.append(f"set_max_transition {float(recipe['opt_max_transition']):.4f} [current_design]")
    return "\n".join(lines) + ("\n" if lines else "")


def _preamble(design: Design, recipe: dict, stage: str, prev_odb: Path | None,
              overlay_path: Path | None, threads: int, netlist: Path | None = None) -> list[str]:
    p = design.platform
    out = [f"# pnr_agent generated script: stage={stage} design={design.name}", METRICS_TCL]
    if design.sdc_prelude:
        out.append(f"source {_q(design.sdc_prelude)}")
    out.append(f"set_thread_count {threads}")
    out.append("sta::set_thread_count 1")
    out.append(f"read_lef {_q(p.tech_lef)}")
    out.append(f"read_lef {_q(p.std_cell_lef)}")
    out += [f"read_lef {_q(x)}" for x in design.extra_lef]
    out.append(f"read_liberty {_q(p.liberty)}")
    out += [f"read_liberty {_q(x)}" for x in design.extra_lib]
    if prev_odb is None:
        if netlist is not None:
            out.append(f"# re-synthesized netlist (registers untouched; proven equivalent at the end)")
        out.append(f"read_verilog {_q(netlist or design.netlist)}")
        out.append(f"link_design {design.top}")
    else:
        out.append(f"read_db {_q(prev_odb)}")
    out.append(f"read_sdc {_q(design.sdc)}")
    if overlay_path is not None:
        out.append(f"source {_q(overlay_path)} ;# optimization-only overlay, never used by sign-off")
    out.append(f"source {_q(p.layer_rc)}")
    out.append(f"set_wire_rc -signal -layer {recipe['wire_rc_layer']}")
    out.append(f"set_wire_rc -clock -layer {recipe['wire_rc_layer_clk']}")
    if p.dont_use:
        out.append(f"set_dont_use {_tcl_list(p.dont_use)}")
    if prev_odb is not None:  # tracks exist only after initialize_floorplan
        out.append(f"set_routing_layers -signal {p.signal_layers} -clock {p.clock_layers}")
        out.append(f"set_global_routing_layer_adjustment {p.signal_layers} {recipe['grt_layer_adjustment']}")
    return out


def _floorplan_args(design: Design, recipe: dict) -> str:
    p = design.platform
    if recipe["fp_core_util"] is not None:
        if design.floorplan_fixed:
            raise ValueError("fp_core_util changes the die; design says floorplan_fixed")
        margin = recipe["fp_core_margin"] if recipe["fp_core_margin"] is not None else 10.0
        return (f"-site {p.site} -utilization {float(recipe['fp_core_util'])} "
                f"-aspect_ratio {float(recipe['fp_aspect_ratio'])} -core_space {float(margin)}")
    if design.die_area is None:
        raise ValueError("design has no die_area/core_area and fp_core_util is not set")
    die = design.die_area
    core = design.core_area
    if recipe["fp_core_margin"] is not None:
        m = float(recipe["fp_core_margin"])
        core = [die[0] + m, die[1] + m, die[2] - m, die[3] - m]
    return f"-site {p.site} -die_area {_tcl_list(die)} -core_area {_tcl_list(core)}"


def abc_liberty_text(liberty_text: str, dont_use: list[str]) -> str:
    """Copy of the liberty with dont-use cells marked, so ABC (restructure) never maps to them."""
    pats = [re.compile(p.replace("*", ".*") + r"$") for p in dont_use]

    def mark(m):
        return m.group(0) + "\n    dont_use : true ;" if any(pt.match(m.group(1)) for pt in pats) else m.group(0)
    return re.sub(r"^\s*cell\s*\(\s*\"?([A-Za-z0-9_]+)\"?\s*\)\s*\{", mark, liberty_text, flags=re.M)


def stage_script(design: Design, recipe: dict, stage: str, prev_odb: Path | None,
                 out_dir: Path, overlay_path: Path | None, threads: int,
                 abc_liberty: Path | None = None, netlist: Path | None = None) -> str:
    p = design.platform
    out = _preamble(design, recipe, stage, prev_odb, overlay_path, threads, netlist)
    odb = out_dir / f"{stage}.odb"
    metrics = out_dir / "metrics.json"
    r = recipe

    if stage == "floorplan":
        out.append(f"initialize_floorplan {_floorplan_args(design, recipe)}")
        out.append(f"source {_q(p.tracks)}")
        if r["fp_remove_synth_buffers"]:
            out.append("remove_buffers")
        if r["rs_timing"]:
            if abc_liberty is None:
                raise ValueError("rs_timing needs the dont-use-marked liberty for ABC")
            lo_cell, lo_pin = p.tielo_port.split("/")
            hi_cell, hi_pin = p.tiehi_port.split("/")
            out.append("pa_metric rs_cells_before [llength [get_cells *]]")
            # restructure walks worst-slack paths; force a timing update first or it sees depth 0
            out.append("pa_metric rs_wns_before [sta::worst_slack -max]")
            out.append(f"restructure -target timing -slack_threshold {float(r['rs_slack_threshold']):.4f} "
                       f"-depth_threshold {int(r['rs_depth_threshold'])} -liberty_file {_q(abc_liberty)} "
                       f"-tielo_port */{lo_cell}/{lo_pin} -tiehi_port */{hi_cell}/{hi_pin} "
                       f"-work_dir {_q(out_dir)} -abc_logfile {_q(out_dir / 'abc_restructure.log')}")
            out.append("pa_metric rs_cells_after [llength [get_cells *]]")
        out.append(f"place_pins -random -hor_layers {p.io_hor_layer} -ver_layers {p.io_ver_layer}")
        hx, hy = p.macro_halo
        out.append("if {[pa_have_macros]} {")
        out.append(f"  rtl_macro_placer -halo_width {hx} -halo_height {hy} "
                   f"-report_directory {_q(out_dir / 'rtlmp')}")
        out.append("}")
        out.append(f"tapcell {p.tapcell_args}")
        out.append(f"source {_q(p.pdn_cfg)}")
        out.append("pdngen")
        out.append("pa_metric instance_count [llength [get_cells *]]")

    elif stage == "place":
        out.append("set_macro_extension 2")
        gp = ["global_placement"]
        if r["gp_routability_driven"]:
            gp.append("-routability_driven")
        if r["gp_timing_driven"]:
            gp.append("-timing_driven")
            if r["gp_td_net_weight_max"] is not None:
                gp.append(f"-timing_driven_net_weight_max {float(r['gp_td_net_weight_max'])}")
            if r["gp_td_nets_percentage"] is not None:
                gp.append(f"-timing_driven_nets_percentage {float(r['gp_td_nets_percentage'])}")
        gp.append(f"-density {float(r['gp_density'])}")
        gp.append(f"-pad_left {int(r['gp_pad'])} -pad_right {int(r['gp_pad'])}")
        out.append(" ".join(gp))
        pins = f"place_pins -hor_layers {p.io_hor_layer} -ver_layers {p.io_ver_layer}"
        if r["io_annealing"]:
            pins += " -annealing"
        out.append(pins)
        out.append("estimate_parasitics -placement")
        rd = f"repair_design -slew_margin {r['rd_slew_margin']} -cap_margin {r['rd_cap_margin']}"
        if r["rd_max_wire_length"] is not None:
            rd += f" -max_wire_length {float(r['rd_max_wire_length'])}"
        out.append(rd)
        out.append(f"repair_tie_fanout -separation {p.tie_separation} {p.tielo_port}")
        out.append(f"repair_tie_fanout -separation {p.tie_separation} {p.tiehi_port}")
        out.append(f"set_placement_padding -global -left {int(r['dp_pad'])} -right {int(r['dp_pad'])}")
        out.append("detailed_placement")
        out.append("estimate_parasitics -placement")
        out.append("pa_timing_metrics place")
        out.append("pa_metric utilization [rsz::utilization]")
        out.append("pa_metric design_area [rsz::design_area]")

    elif stage == "cts":
        out.append("repair_clock_inverters")
        cts = [f"clock_tree_synthesis -root_buf {r['cts_buffer']} -buf_list {r['cts_buffer']}",
               "-sink_clustering_enable",
               f"-sink_clustering_max_diameter {int(r['cts_cluster_diameter'])}"]
        if r["cts_cluster_size"] is not None:
            cts.append(f"-sink_clustering_size {int(r['cts_cluster_size'])}")
        if r["cts_balance_levels"]:
            cts.append("-balance_levels")
        out.append(" ".join(cts))
        out.append("repair_clock_nets")
        out.append(f"set_placement_padding -global -left {int(r['dp_pad'])} -right {int(r['dp_pad'])}")
        out.append("detailed_placement")
        out.append("set_propagated_clock [all_clocks]")
        if r["rt_use_grt_parasitics"]:
            out.append(f"global_route -congestion_iterations {int(r['grt_congestion_iters'])}")
            out.append("estimate_parasitics -global_routing")
        else:
            out.append("estimate_parasitics -placement")
        out.append(_repair_timing_cmd(r, r["rt_setup_margin"]))
        out.append("detailed_placement")
        out.append("estimate_parasitics -placement")
        out.append("pa_timing_metrics cts")
        out.append("pa_metric clock_skew [sta::worst_clock_skew -setup]")
        out.append("pa_metric utilization [rsz::utilization]")
        out.append("pa_metric design_area [rsz::design_area]")

    elif stage == "grt":
        out.append("set_propagated_clock [all_clocks]")
        if r["eco_resize"]:
            for inst, master in r["eco_resize"]:
                out.append(f"if {{[llength [get_cells -quiet {{{inst}}}]]}} "
                           f"{{ replace_cell {{{inst}}} {master}; puts \"PA_ECO_RESIZED {inst} {master}\" }} "
                           f"else {{ puts \"PA_ECO_MISSING {inst}\" }}")
            out.append(f"set_placement_padding -global -left {int(r['dp_pad'])} -right {int(r['dp_pad'])}")
            out.append("detailed_placement")
        out.append(f"pin_access -bottom_routing_layer {p.min_routing_layer} "
                   f"-top_routing_layer {p.max_routing_layer}")
        grt = (f"global_route -congestion_iterations {int(r['grt_congestion_iters'])} -verbose "
               f"-congestion_report_file {_q(out_dir / 'congestion.rpt')}")
        if r["grt_critical_nets_pct"] is not None:
            grt += f" -critical_nets_percentage {float(r['grt_critical_nets_pct'])}"
        out.append(grt)
        if r["grt_repair_timing"]:
            out.append("estimate_parasitics -global_routing")
            out.append("global_route -start_incremental")
            out.append(_repair_timing_cmd(r, r["grt_rt_setup_margin"]))
            out.append(f"set_placement_padding -global -left {int(r['dp_pad'])} -right {int(r['dp_pad'])}")
            out.append("detailed_placement")
            out.append("global_route -end_incremental "
                       f"-congestion_report_file {_q(out_dir / 'congestion_eco.rpt')}")
        out.append("estimate_parasitics -global_routing")
        out.append("pa_timing_metrics grt")
        if p.diode_cell:
            out.append(f"repair_antennas {p.diode_cell} -iterations 5")
        else:
            out.append("repair_antennas -iterations 5")
        out.append("pa_metric grt_antenna_nets [check_antennas]")
        out.append(f"write_guides {_q(out_dir / 'route.guide')}")
        out.append("pa_metric utilization [rsz::utilization]")
        out.append("pa_metric design_area [rsz::design_area]")

    elif stage == "drt":
        out.append("set_propagated_clock [all_clocks]")
        out.append(f"read_guides {_q(prev_odb.parent / 'route.guide')}")
        out.append(f"pin_access -bottom_routing_layer {p.min_routing_layer} "
                   f"-top_routing_layer {p.max_routing_layer}")
        dr = (f"detailed_route -output_drc {_q(out_dir / 'drc.rpt')} -no_pin_access -save_guide_updates "
              f"-bottom_routing_layer {p.min_routing_layer} -top_routing_layer {p.max_routing_layer} -verbose 0")
        if r["drt_end_iter"] is not None:
            dr += f" -droute_end_iter {int(r['drt_end_iter'])}"
        out.append(dr)
        out.append("set ant_iter 0")
        out.append("while {[check_antennas] && $ant_iter < 5} {")
        out.append("  repair_antennas" + (f" {p.diode_cell}" if p.diode_cell else ""))
        out.append(f"  {dr.replace('drc.rpt', 'drc_ant.rpt').replace(' -no_pin_access', '')}")
        out.append("  incr ant_iter")
        out.append("}")
        out.append("if {![catch {detailed_route_num_drvs} pa_drc]} { puts \"PA_DRC_COUNT $pa_drc\"; "
                   "pa_metric drc_count $pa_drc }")
        out.append("pa_metric antenna_nets [check_antennas]")
        out.append("pa_metric routed [design_is_routed]")
        out.append(f"filler_placement {p.filler_cells}")
        out.append("pa_metric placement_ok [expr {[catch {check_placement -verbose}] == 0}]")
        out.append("pa_metric utilization [rsz::utilization]")
        out.append("pa_metric design_area [rsz::design_area]")
        out.append(f"write_verilog -remove_cells {_tcl_list([p.filler_cells, 'TAPCELL*'])} "
                   f"{_q(out_dir / 'final.v')}")
        out.append(f"write_def {_q(out_dir / 'final.def')}")
        if p.rcx_rules:
            out.append("define_process_corner -ext_model_index 0 X")
            out.append(f"extract_parasitics -ext_model_file {_q(p.rcx_rules)}")
            out.append(f"write_spef {_q(out_dir / 'final.spef')}")
        else:
            out.append("estimate_parasitics -global_routing")
            out.append(f"write_spef {_q(out_dir / 'final.spef')}")

    else:
        raise ValueError(stage)

    out.append(f"write_db {_q(odb)}")
    out.append(f"pa_write_metrics {_q(metrics)}")
    return "\n".join(out) + "\n"


def _repair_timing_cmd(r: dict, setup_margin: float) -> str:
    cmd = ["repair_timing"]
    if setup_margin:
        cmd.append(f"-setup_margin {float(setup_margin):.4f}")
    if r["rt_skip_gate_cloning"]:
        cmd.append("-skip_gate_cloning")
    if r["rt_skip_pin_swap"]:
        cmd.append("-skip_pin_swap")
    if r["rt_skip_last_gasp"]:
        cmd.append("-skip_last_gasp")
    if r["rt_repair_tns"] is not None:
        cmd.append(f"-repair_tns {float(r['rt_repair_tns'])}")
    if r["rt_max_passes"] is not None:
        cmd.append(f"-max_passes {int(r['rt_max_passes'])}")
    return " ".join(cmd)


def signoff_script(design: Design, netlist: Path, spef: Path, out_dir: Path) -> str:
    """Independent sign-off in a fresh OpenSTA process with the GOLDEN SDC only."""
    p = design.platform
    o = out_dir
    lines = [f"# pnr_agent sign-off (OpenSTA, golden SDC only) design={design.name}"]
    if design.sdc_prelude:
        lines.append(f"source {_q(design.sdc_prelude)}")
    lines.append(f"read_liberty {_q(p.liberty)}")
    lines += [f"read_liberty {_q(x)}" for x in design.extra_lib]
    lines.append(f"read_verilog {_q(netlist)}")
    lines.append(f"link_design {design.top}")
    lines.append(f"read_sdc {_q(design.sdc)}")
    lines.append("set_propagated_clock [all_clocks]")
    lines.append(f"read_spef {_q(spef)}")
    lines.append("foreach clk [all_clocks] { puts \"PA_CLOCK [get_name $clk] [get_property $clk period]\" }")
    lines.append("puts \"PA_WNS_MAX [sta::worst_slack -max]\"")
    lines.append("puts \"PA_WNS_MIN [sta::worst_slack -min]\"")
    lines.append("puts \"PA_TNS_MAX [sta::total_negative_slack -max]\"")
    lines.append("puts \"PA_TNS_MIN [sta::total_negative_slack -min]\"")
    lines.append("puts \"PA_SKEW_SETUP [sta::worst_clock_skew -setup]\"")
    fields = "-fields {slew capacitance fanout input_pin net}"
    lines.append(f"report_checks -path_delay max -format json -digits 5 -group_path_count 10 "
                 f"-endpoint_path_count 1 {fields} > {_q(o / 'paths_max.json')}")
    lines.append(f"report_checks -path_delay min -format json -digits 5 -group_path_count 5 "
                 f"-endpoint_path_count 1 {fields} > {_q(o / 'paths_min.json')}")
    lines.append(f"report_checks -path_delay max -format end -slack_max 0 -group_path_count 1000000 "
                 f"-digits 5 > {_q(o / 'violators_max.rpt')}")
    lines.append(f"report_checks -path_delay min -format end -slack_max 0 -group_path_count 1000000 "
                 f"-digits 5 > {_q(o / 'violators_min.rpt')}")
    # text form of the top paths: carries per-driver fanout, which the JSON form omits
    lines.append(f"report_checks -path_delay max -format full_clock_expanded -digits 4 "
                 f"-group_path_count 10 -endpoint_path_count 1 {fields} > {_q(o / 'top_paths_max.rpt')}")
    lines.append(f"report_check_types -max_slew -max_capacitance -max_fanout -violators "
                 f"> {_q(o / 'drv.rpt')}")
    lines.append(f"report_power > {_q(o / 'power.rpt')}")
    return "\n".join(lines) + "\n"
