"""Parsers, diagnosis and action policy, on real OpenROAD/OpenSTA output (gcd baseline)."""
from pathlib import Path
from types import SimpleNamespace

from pnr_agent import reports
from pnr_agent.actions import propose_all
from pnr_agent.diagnose import diagnose, upsize
from pnr_agent.recipe import (KNOB_BY_NAME, STAGES, apply_changes, default_recipe, earliest_stage,
                              prefix_hashes)

FIX = Path(__file__).parent / "fixtures"


def test_grt_congestion_parser():
    c = reports.parse_grt_congestion((FIX / "gcd_grt_excerpt.log").read_text())
    assert c["total_overflow"] == 0
    assert c["total_usage_pct"] == 4.89
    assert c["layers"]["metal2"]["usage_pct"] == 11.46
    assert c["wirelength_um"] == 7887.0
    assert c["max_layer_usage_pct"] == 11.46


def test_violators_and_power():
    assert reports._count_violated(FIX / "gcd_violators_max.rpt") == 22
    assert reports.parse_power(FIX / "gcd_power.rpt") == 2.23e-03


def test_worst_path_breakdown_matches_signoff():
    checks = reports.load_paths(FIX / "gcd_paths_max.json")
    p = reports.analyze_path(checks[0])
    assert p["startpoint"] == "_679_/Q" and p["endpoint"] == "resp_msg[15]"
    assert p["end_is_port"] and not p["start_is_port"]
    assert abs(p["slack_ns"] - (-0.04629)) < 1e-4
    # launch latency + clk->Q + data cells + wires == data arrival
    total = p["launch_latency_ns"] + p["cell_delay_ns"] + p["net_delay_ns"]
    assert abs(total - p["arrival_ns"]) < 2e-4
    assert p["n_stages"] == 15


def _ev_from_fixtures():
    signoff = {"paths_max": reports.load_paths(FIX / "gcd_paths_max.json")}
    s = {"wns_ns": -0.0463, "tns_ns": -0.4096, "hold_wns_ns": 0.0503, "setup_violators": 22}
    return SimpleNamespace(summary=lambda: s, signoff=signoff,
                           congestion=reports.parse_grt_congestion((FIX / "gcd_grt_excerpt.log").read_text()),
                           stage_metrics={"cts": {"cts_wns": -0.0406}})


def test_diagnosis_tags_on_gcd():
    cells = {"INV_X1", "INV_X2", "NAND2_X1", "NAND2_X2", "NAND2_X4", "OAI21_X2", "OAI21_X4", "NOR2_X2",
             "NOR2_X4", "BUF_X1", "BUF_X2"}
    d = diagnose(_ev_from_fixtures(), 0.485, cells, ["CLKBUF_*"])
    for tag in ("IO_BOUND", "IO_LAUNCH_LATENCY", "DEEP_LOGIC", "POST_ROUTE_DEGRADATION", "NEAR_MISS",
                "MANY_ENDPOINTS", "WEAK_DRIVERS"):
        assert tag in d.tags, tag
    assert "CONGESTED" not in d.tags and "WIRE_DOMINATED" not in d.tags
    assert all(w["to"] in cells for w in d.weak_drivers)


def test_upsize_respects_dont_use():
    cells = {"AOI211_X1", "AOI211_X2", "AOI211_X4"}
    assert upsize("AOI211_X1", cells, ["AOI211_X2"]) == "AOI211_X4"
    assert upsize("AOI211_X4", cells, []) is None


def test_policy_ranks_fine_grained_first_and_uses_only_real_knobs():
    cells = {"INV_X1", "INV_X2", "NAND2_X1", "NAND2_X2"}
    d = diagnose(_ev_from_fixtures(), 0.485, cells, [])
    design = SimpleNamespace(die_area=[0, 0, 100.13, 100.8], core_area=[10.07, 11.2, 90.25, 91], rtl=[])
    props = propose_all(d, default_recipe(), design)
    assert props[0].category in ("optimization", "eco")
    for p in props:
        assert p.changes and all(k in KNOB_BY_NAME for k in p.changes)
        assert p.rationale
    # nothing to do once closed
    closed = SimpleNamespace(**{**vars(d), "wns_ns": 0.01})
    assert propose_all(closed, default_recipe(), design) == []


def test_cache_prefix_reuse():
    base = default_recipe()
    fp = {"x": 1}
    h0 = prefix_hashes(base, fp)
    h1 = prefix_hashes(apply_changes(base, {"grt_critical_nets_pct": 10}), fp)
    assert [h0[s] == h1[s] for s in STAGES] == [True, True, True, False, False]
    h2 = prefix_hashes(apply_changes(base, {"gp_density": 0.5}), fp)
    assert [h0[s] == h2[s] for s in STAGES] == [True, False, False, False, False]
    assert earliest_stage({"rt_setup_margin": 0.1, "eco_resize": ()}) == "cts"


def test_fanout_parser_on_text_report():
    f = reports.parse_fanouts(FIX / "gcd_final_worst_path.rpt")
    assert f["_696_/Q"] == 4 and f["_369_/ZN"] == 2 and f["clkbuf_2_3__f_clk/Z"] == 10
    assert "_369_/A" not in f   # input pins carry no fanout
