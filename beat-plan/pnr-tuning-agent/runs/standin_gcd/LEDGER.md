# PnR timing-closure ledger: standin_gcd

> **STAND-IN, NOT BUILD 6.** OpenROAD gcd_nangate45 reference config (stand-in for a Build 6 block)

- Target clock: **0.485 ns** (2061.9 MHz), fixed. Golden SDC sha256 `5b2d072132dc4055...`, netlist sha256 `a7ac54960562b5bc...`
- Tools: 2.0-unstable-2025-03-01_e794373d44ac5421f0633d8dda7e5c59e8fe79bf / 2.6.0 / Yosys 0.55 (git sha1 60f126cd00c94892782470192d6c9f7abebe7c05, g++ 14.3.0 -fPIC -O3)
- Started 2026-11-28T00:26:10, finished 2026-11-28T00:30:45; 32 flow evaluations, 8 rounds

## Verdict: **NOT CLOSED**

Not closed: sign-off still fails (WNS -0.0345 ns, TNS -0.2959 ns, hold +0.0567 ns). Stop reason: round budget (8) used.

| Metric (independent OpenSTA sign-off, golden SDC, RCX parasitics) | Before | After |
|---|---|---|
| Setup WNS (ns) | -0.0463 | -0.0345 |
| Setup TNS (ns) | -0.4096 | -0.2959 |
| Violating setup endpoints | 22 | 19 |
| Hold WNS (ns) | +0.0503 | +0.0567 |
| Violating hold endpoints | 0 | 0 |
| Routing DRC violations | 0 | 0 |
| Antenna nets | 0 | 0 |
| Slew/cap/fanout violations | 0 | 0 |
| Cell area (um^2) | 550.1 | 599.6 |
| Total power (W, default activity) | 2.2300e-03 | 2.6300e-03 |
| Routed wirelength, GRT (um) | 7828 | 8307 |

- Logic equivalence, golden netlist vs routed netlist (Yosys): **PASS**, equivalent: 54 points proven (36 state bits matched by name)
- Reproduced from an empty cache with the final recipe: **yes** (WNS -0.0345 ns, TNS -0.2959 ns, hold +0.0567 ns)
- Guardrails on the final result: golden inputs unchanged: ok, clock period unchanged at sign-off: ok, optimization overlay whitelisted: ok, fully routed, zero DRC: ok, placement legal: ok, antenna not worse: ok, no new hold violations: ok, no new slew/cap/fanout violations: ok, area growth within limit: ok

## What the agent changed (accepted edits, in order)

1. **routing_aware_eco_repair** (optimization), round 1: `grt_repair_timing`: False -> True, `grt_rt_setup_margin`: 0.0 -> 0.047
   - Why: Incremental ECO after global routing: repair_timing on global-route parasitics (closer to routed RC than placement estimates), then incremental re-route.
   - Evidence: POST_ROUTE_DEGRADATION: optimizer saw WNS -0.0406 ns on placement parasitics; routed sign-off is -0.0463 ns
   - Effect: WNS -0.0463 -> -0.0427 ns, TNS -0.4096 -> -0.3820 ns, hold +0.0503 -> +0.0505 ns, area 550.1 -> 583.3 um^2
2. **faster_clock_tree** (cts), round 2: `cts_buffer`: 'BUF_X4' -> 'BUF_X8'
   - Why: Output paths start at a flop whose clock arrives late (insertion delay) while the output budget assumes an ideal clock; build the tree from stronger buffers to cut real latency.
   - Evidence: IO_LAUNCH_LATENCY: output-port paths pay the launch flop's clock insertion delay (0.0534 ns) against an ideal-clock output budget; the miss is 0.0427 ns
   - Effect: WNS -0.0427 -> -0.0379 ns, TNS -0.3820 -> -0.4468 ns, hold +0.0505 -> +0.0564 ns, area 583.3 -> 595.0 um^2
3. **guardband_setup_repair** (optimization), round 3: `rt_setup_margin`: 0.0 -> 0.038
   - Why: Post-CTS repair_timing stops at zero slack on placement parasitics, then routing takes 37.9 ps back. Re-run it to a +38 ps guard-band so it over-fixes what routing costs.
   - Evidence: NEAR_MISS: miss is 37.9 ps (7.8% of the period)
   - Effect: WNS -0.0379 -> -0.0352 ns, TNS -0.4468 -> -0.3737 ns, hold +0.0564 -> +0.0564 ns, area 595.0 -> 594.8 um^2
4. **anneal_io_pins** (floorplan), round 4: `io_annealing`: False -> True
   - Why: Re-place IO pins with simulated annealing against the placed logic.
   - Evidence: IO_BOUND: 3 of 10 top violating paths end at an output port, 0 start at an input port
   - Effect: WNS -0.0352 -> -0.0345 ns, TNS -0.3737 -> -0.3603 ns, hold +0.0564 -> +0.0568 ns, area 594.8 -> 593.7 um^2
5. **enable_gate_cloning** (optimization), round 5: `rt_skip_gate_cloning`: True -> False
   - Why: Let repair_timing clone gates to split the load of drivers on critical paths (the reference flow disables it).
   - Evidence: WEAK_DRIVERS: 7 X1/X2 drivers on the worst paths drive >=4 fF or >=3 loads; track record: 1 earlier tries, none improved
   - Effect: WNS -0.0345 -> -0.0344 ns, TNS -0.3603 -> -0.2993 ns, hold +0.0568 -> +0.0567 ns, area 593.7 -> 599.3 um^2
6. **guardband_setup_repair** (optimization), round 6: `rt_setup_margin`: 0.038 -> 0.0727
   - Why: Post-CTS repair_timing stops at zero slack on placement parasitics, then routing takes 34.4 ps back. Re-run it to a +73 ps guard-band so it over-fixes what routing costs.
   - Evidence: NEAR_MISS: miss is 34.4 ps (7.1% of the period)
   - Effect: WNS -0.0344 -> -0.0345 ns, TNS -0.2993 -> -0.2959 ns, hold +0.0567 -> +0.0567 ns, area 599.3 -> 599.6 um^2

## Baseline diagnosis

- Worst path: `_679_/Q` -> `resp_msg[15]` (output_delay), slack -0.0463 ns, 15 stages, cell 0.3764 ns + wire 0.0049 ns (wire 1%), max fanout 5, max slew 0.0230 ns, launch/capture clock latency 0.0530/0.0000 ns
- `IO_BOUND`: 6 of 10 top violating paths end at an output port, 0 start at an input port
- `IO_LAUNCH_LATENCY`: output-port paths pay the launch flop's clock insertion delay (0.0535 ns) against an ideal-clock output budget; the miss is 0.0463 ns
- `DEEP_LOGIC`: 15 cell stages, cell delay 0.3764 ns
- `POST_ROUTE_DEGRADATION`: optimizer saw WNS -0.0406 ns on placement parasitics; routed sign-off is -0.0463 ns
- `MANY_ENDPOINTS`: 22 violating endpoints
- `WEAK_DRIVERS`: 16 X1/X2 drivers on the worst paths drive >=4 fF or >=3 loads
- `NEAR_MISS`: miss is 46.3 ps (9.5% of the period)

## Every candidate evaluated

| Round | Action | Category | Change | WNS (ns) | TNS (ns) | Hold WNS (ns) | DRC | Area (um^2) | Guardrails | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | guardband_setup_repair | optimization | `rt_setup_margin=0.047` | -0.0440 | -0.4202 | +0.0506 | 0 | 572.2 | ok | valid, not best this round |
| 1 | resynthesize_for_delay | synthesis | `resynth_delay_ps=291` | -0.3428 | -12.8618 | +0.0505 | 0 | 535.5 | ok | rejected: no improvement |
| 1 | routing_aware_eco_repair | optimization | `grt_repair_timing=True; grt_rt_setup_margin=0.047` | -0.0427 | -0.3820 | +0.0505 | 0 | 583.3 | ok | ACCEPTED |
| 1 | eco_upsize_worst_paths | eco | `eco_resize=(('_377_', 'INV_X2'), ('_378_', 'NAND2_X2'), ('_380_', 'OAI21_X4'), ('_384_'...` | -0.0477 | -0.3518 | +0.0505 | 0 | 556.2 | ok | rejected: no improvement |
| 2 | guardband_setup_repair | optimization | `rt_setup_margin=0.043` | -0.0426 | -0.4205 | +0.0504 | 0 | 577.5 | ok | rejected: no improvement |
| 2 | enable_gate_cloning | optimization | `rt_skip_gate_cloning=False` | -0.0428 | -0.4300 | +0.0505 | 0 | 583.3 | ok | rejected: no improvement |
| 2 | faster_clock_tree | cts | `cts_buffer='BUF_X8'` | -0.0379 | -0.4468 | +0.0564 | 0 | 595.0 | ok | ACCEPTED |
| 2 | eco_upsize_worst_paths | eco | `eco_resize=(('_354_', 'INV_X2'), ('_355_', 'NAND2_X4'), ('_356_', 'NAND2_X4'), ('_392_'...` | -0.0467 | -0.2827 | +0.0507 | 0 | 584.9 | ok | rejected: no improvement |
| 3 | guardband_setup_repair | optimization | `rt_setup_margin=0.038` | -0.0352 | -0.3737 | +0.0564 | 0 | 594.8 | ok | ACCEPTED |
| 3 | faster_clock_tree | cts | `cts_buffer='BUF_X16'` | -0.0346 | -0.3834 | +0.0590 | 0 | 631.5 | area growth within limit | rejected: guardrail |
| 3 | shrink_core_margin | floorplan | `fp_core_margin=2.0` | -0.0378 | -0.3844 | +0.0549 | 0 | 610.2 | area growth within limit | rejected: guardrail |
| 3 | repair_on_route_parasitics | optimization | `rt_use_grt_parasitics=True` | -0.0383 | -0.3918 | +0.0562 | 0 | 588.7 | ok | valid, not best this round |
| 4 | guardband_setup_repair | optimization | `rt_setup_margin=0.0727` | -0.0351 | -0.3690 | +0.0563 | 0 | 595.0 | ok | valid, not best this round |
| 4 | faster_clock_tree | cts | `cts_buffer='BUF_X16'` | -0.0350 | -0.4014 | +0.0590 | 0 | 611.8 | area growth within limit | rejected: guardrail |
| 4 | repair_on_route_parasitics | optimization | `rt_use_grt_parasitics=True` | -0.0390 | -0.4480 | +0.0563 | 0 | 601.2 | ok | rejected: no improvement |
| 4 | anneal_io_pins | floorplan | `io_annealing=True` | -0.0345 | -0.3603 | +0.0568 | 0 | 593.7 | ok | ACCEPTED |
| 5 | guardband_setup_repair | optimization | `rt_setup_margin=0.0727` | -0.0345 | -0.3587 | +0.0568 | 0 | 594.0 | ok | valid, not best this round |
| 5 | faster_clock_tree | cts | `cts_buffer='BUF_X16'` | -0.0344 | -0.3906 | +0.0596 | 0 | 611.8 | area growth within limit | rejected: guardrail |
| 5 | repair_on_route_parasitics | optimization | `rt_use_grt_parasitics=True` | -0.0376 | -0.3895 | +0.0567 | 0 | 596.9 | ok | rejected: no improvement |
| 5 | enable_gate_cloning | optimization | `rt_skip_gate_cloning=False` | -0.0344 | -0.2993 | +0.0567 | 0 | 599.3 | ok | ACCEPTED |
| 6 | guardband_setup_repair | optimization | `rt_setup_margin=0.0727` | -0.0345 | -0.2959 | +0.0567 | 0 | 599.6 | ok | ACCEPTED |
| 6 | faster_clock_tree | cts | `cts_buffer='BUF_X16'` | -0.0339 | -0.3424 | +0.0599 | 0 | 617.7 | area growth within limit | rejected: guardrail |
| 6 | repair_on_route_parasitics | optimization | `rt_use_grt_parasitics=True` | -0.0380 | -0.3749 | +0.0566 | 0 | 590.8 | ok | rejected: no improvement |
| 6 | timing_driven_placement | placement | `gp_timing_driven=True` | -0.0390 | -0.3805 | +0.0566 | 0 | 611.3 | area growth within limit | rejected: guardrail |
| 7 | faster_clock_tree | cts | `cts_buffer='BUF_X16'` | -0.0339 | -0.3424 | +0.0599 | 0 | 617.7 | area growth within limit | rejected: guardrail |
| 7 | repair_on_route_parasitics | optimization | `rt_use_grt_parasitics=True` | -0.0380 | -0.3749 | +0.0566 | 0 | 590.8 | ok | rejected: no improvement |
| 7 | route_critical_nets_first | routing | `grt_critical_nets_pct=10` | -0.0345 | -0.2959 | +0.0567 | 0 | 599.6 | ok | rejected: no improvement |
| 7 | eco_upsize_worst_paths | eco | `eco_resize=(('_371_', 'NAND2_X4'), ('_479_', 'XNOR2_X2'), ('rebuffer1', 'BUF_X2'), ('re...` | -0.0383 | -0.1669 | +0.0566 | 0 | 627.2 | area growth within limit | rejected: guardrail |
| 8 | shrink_core_margin | floorplan | `fp_core_margin=2.0` | -0.0381 | -0.3814 | +0.0552 | 0 | 613.4 | area growth within limit | rejected: guardrail |
| 8 | raise_placement_density | placement | `gp_density=0.45` | -0.0330 | -0.1620 | +0.0572 | 0 | 637.3 | area growth within limit | rejected: guardrail |
| 8 | timing_driven_placement | placement | `gp_timing_driven=True` | -0.0386 | -0.3769 | +0.0566 | 0 | 612.9 | area growth within limit | rejected: guardrail |

## RTL proposals (recorded, not applied)

- **Pipeline or restructure the worst cone**: Worst path _696_/Q -> resp_msg[15] has 14 cell stages (0.371 ns of cell delay). If physical edits cannot recover 35 ps, split this cone with a register (adds one cycle of latency) or rebalance it in RTL. Must re-pass Forge's gate (sim vs. integer model). (This design config has no RTL, only a netlist, so this stays a proposal.)

## Generated-script diff, baseline -> final

```diff
--- baseline/place.tcl
+++ final/place.tcl
@@ -52,3 +52,3 @@
 global_placement -routability_driven -density 0.3 -pad_left 2 -pad_right 2
-place_pins -hor_layers metal3 -ver_layers metal2
+place_pins -hor_layers metal3 -ver_layers metal2 -annealing
 estimate_parasitics -placement
--- baseline/cts.tcl
+++ final/cts.tcl
@@ -51,3 +51,3 @@
 repair_clock_inverters
-clock_tree_synthesis -root_buf BUF_X4 -buf_list BUF_X4 -sink_clustering_enable -sink_clustering_max_diameter 100
+clock_tree_synthesis -root_buf BUF_X8 -buf_list BUF_X8 -sink_clustering_enable -sink_clustering_max_diameter 100
 repair_clock_nets
@@ -57,3 +57,3 @@
 estimate_parasitics -placement
-repair_timing -skip_gate_cloning
+repair_timing -setup_margin 0.0727
 detailed_placement
--- baseline/grt.tcl
+++ final/grt.tcl
@@ -54,2 +54,8 @@
 estimate_parasitics -global_routing
+global_route -start_incremental
+repair_timing -setup_margin 0.0470
+set_placement_padding -global -left 1 -right 1
+detailed_placement
+global_route -end_incremental -congestion_report_file {<run>/grt/congestion_eco.rpt}
+estimate_parasitics -global_routing
 pa_timing_metrics grt
```

## Final recipe changes vs baseline

```json
{
 "io_annealing": [
  false,
  true
 ],
 "cts_buffer": [
  "BUF_X4",
  "BUF_X8"
 ],
 "rt_setup_margin": [
  0.0,
  0.0727
 ],
 "rt_skip_gate_cloning": [
  true,
  false
 ],
 "grt_repair_timing": [
  false,
  true
 ],
 "grt_rt_setup_margin": [
  0.0,
  0.047
 ]
}
```
