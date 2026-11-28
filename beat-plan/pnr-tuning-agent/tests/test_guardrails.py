"""The agent must never be able to close timing by changing the question."""
import itertools
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from pnr_agent import guardrails, tcl
from pnr_agent.recipe import KNOBS, default_recipe, apply_changes

FIX = Path(__file__).parent / "fixtures"


def test_overlay_whitelist_accepts_tightening():
    assert guardrails.check_overlay("set_max_fanout 8 [current_design]\n"
                                    "set_max_transition 0.0500 [current_design]\n") == []


@pytest.mark.parametrize("cmd", sorted(guardrails.FORBIDDEN_SDC))
def test_overlay_rejects_every_forbidden_command(cmd):
    problems = guardrails.check_overlay(f"{cmd} 1.0 [all_clocks]\n")
    assert problems and "forbidden" in problems[0]


def test_overlay_rejects_unknown_commands():
    assert guardrails.check_overlay("set_dont_touch foo\n")


def _fake_design(tmp_path):
    """Minimal Design stand-in with real files so generators can run."""
    from pnr_agent.config import Platform
    p = Platform(name="x", tech_lef=tmp_path / "t.lef", std_cell_lef=tmp_path / "s.lef",
                 liberty=tmp_path / "l.lib", site="S", pdn_cfg=tmp_path / "pdn.tcl",
                 tracks=tmp_path / "tr.tcl", layer_rc=tmp_path / "rc.tcl", rcx_rules=tmp_path / "rcx",
                 io_hor_layer="m3", io_ver_layer="m2", tapcell_args="-distance 1", tielo_port="L0/Z",
                 tiehi_port="L1/Z", dont_use=["CLKBUF_*"], filler_cells="FILL*", min_routing_layer="m2",
                 max_routing_layer="m9", signal_layers="m2-m9", clock_layers="m6-m9",
                 macro_halo=[1, 1], tie_separation=5)
    return SimpleNamespace(name="d", top="top", platform=p, netlist=tmp_path / "n.v", sdc=tmp_path / "g.sdc",
                           sdc_prelude=None, die_area=[0, 0, 100, 100], core_area=[10, 10, 90, 90],
                           floorplan_fixed=True, extra_lef=[], extra_lib=[])


def _random_recipes(n=60, seed=7):
    rng = random.Random(seed)
    choices = {
        "fp_core_margin": [None, 2.0, 5.0], "fp_remove_synth_buffers": [True, False],
        "rs_timing": [False, True], "resynth_delay_ps": [None, 300],
        "gp_density": [0.3, 0.6], "gp_timing_driven": [False, True], "io_annealing": [False, True],
        "opt_max_fanout": [None, 8], "opt_max_transition": [None, 0.05],
        "cts_buffer": ["BUF_X4", "BUF_X16"], "cts_balance_levels": [False, True],
        "rt_setup_margin": [0.0, 0.05], "rt_skip_gate_cloning": [True, False],
        "rt_use_grt_parasitics": [False, True], "grt_critical_nets_pct": [None, 10],
        "grt_repair_timing": [False, True], "eco_resize": [(), (("u1", "NAND2_X2"),)],
        "drt_end_iter": [None, 5],
    }
    for _ in range(n):
        yield apply_changes(default_recipe(), {k: rng.choice(v) for k, v in choices.items()})


def test_generated_scripts_never_touch_constraints(tmp_path):
    """No stage script, for any recipe, may contain a constraint-changing command
    (the golden SDC is only ever *read*)."""
    d = _fake_design(tmp_path)
    for recipe in _random_recipes():
        for stage in ["floorplan", "place", "cts", "grt", "drt"]:
            prev = None if stage == "floorplan" else tmp_path / "prev" / "x.odb"
            text = tcl.stage_script(d, recipe, stage, prev, tmp_path / stage, None, 1,
                                    abc_liberty=tmp_path / "abc.lib")
            for line in text.splitlines():
                cmd = line.strip().split(" ")[0]
                if cmd == "set_propagated_clock":   # standard post-CTS analysis mode, not an SDC edit
                    continue
                assert cmd not in guardrails.FORBIDDEN_SDC, (stage, line)
        assert guardrails.check_overlay(tcl.overlay_sdc(recipe)) == []


def test_signoff_reads_only_golden_sdc(tmp_path):
    d = _fake_design(tmp_path)
    text = tcl.signoff_script(d, tmp_path / "f.v", tmp_path / "f.spef", tmp_path / "so")
    sdc_lines = [l for l in text.splitlines() if "sdc" in l.lower() and not l.startswith("#")]
    assert sdc_lines == [f"read_sdc {{{d.sdc}}}"]
    assert "opt_constraints" not in text


def test_no_knob_can_change_the_clock_or_io_budget():
    banned = ("period", "clock_uncertainty", "input_delay", "output_delay", "false_path", "multicycle")
    for k in KNOBS:
        assert not any(b in k.name for b in banned), k.name


def test_fixed_die_cannot_be_resized(tmp_path):
    d = _fake_design(tmp_path)
    r = apply_changes(default_recipe(), {"fp_core_util": 0.5})
    with pytest.raises(ValueError):
        tcl.stage_script(d, r, "floorplan", None, tmp_path, None, 1)


def _ev(wns=-0.05, tns=-0.4, hold=0.05, hold_v=0, drc=0, area=100.0, drv=0, periods=None,
        routed=True, antenna=0, placement_ok=True):
    s = {"wns_ns": wns, "tns_ns": tns, "hold_wns_ns": hold, "hold_violators": hold_v,
         "setup_violators": 1, "drc": drc, "antenna_nets": antenna, "routed": routed,
         "drv_violations": drv, "area_um2": area, "clock_periods_ns": periods or {"clk": 4.0}}
    return SimpleNamespace(summary=lambda: s, stage_dirs={}, route={"placement_ok": placement_ok})


def _design_stub(fp):
    return SimpleNamespace(golden_fingerprint=lambda: fp, target_period_ns=4.0, max_area_growth=0.10)


def test_validate_catches_each_violation():
    fp = {"sdc_sha256": "a"}
    d = _design_stub(fp)
    base = _ev()
    assert all(c["ok"] for c in guardrails.validate(_ev(wns=0.01, tns=0), base, d, fp))
    cases = {
        "clock period unchanged at sign-off": _ev(periods={"clk": 4.1}),
        "fully routed, zero DRC": _ev(drc=3),
        "no new hold violations": _ev(hold=-0.01, hold_v=2),
        "area growth within limit": _ev(area=111.0),
        "no new slew/cap/fanout violations": _ev(drv=1),
        "antenna not worse": _ev(antenna=2),
        "placement legal": _ev(placement_ok=False),
    }
    for name, ev in cases.items():
        failed = [c["name"] for c in guardrails.validate(ev, base, d, fp) if not c["ok"]]
        assert failed == [name], (name, failed)
    changed = _design_stub({"sdc_sha256": "b"})
    failed = [c["name"] for c in guardrails.validate(_ev(), base, changed, fp) if not c["ok"]]
    assert failed == ["golden inputs unchanged"]


def test_is_closed_requires_setup_hold_and_drc():
    ok = _ev(wns=0.0, tns=0.0).summary()
    assert guardrails.is_closed(ok)
    for bad in (_ev(wns=-0.001, tns=-0.001), _ev(wns=0.0, tns=0.0, hold=-0.001), _ev(wns=0, tns=0, drc=1)):
        assert not guardrails.is_closed(bad.summary())
