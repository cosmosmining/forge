# PnR timing-closure ledger: standin_aes_250mhz

> **STAND-IN, NOT BUILD 6.** OpenROAD aes_nangate45 netlist at 250 MHz, slow corner (stand-in for a Build 6 block)

- Target clock: **4.0 ns** (250.0 MHz), fixed. Golden SDC sha256 `bad911cfc8111346...`, netlist sha256 `5a933454a2bbce8a...`
- Tools: 2.0-unstable-2025-03-01_e794373d44ac5421f0633d8dda7e5c59e8fe79bf / 2.6.0 / Yosys 0.55 (git sha1 60f126cd00c94892782470192d6c9f7abebe7c05, g++ 14.3.0 -fPIC -O3)
- Started 2026-11-28T00:24:51, finished 2026-11-28T00:45:33; 5 flow evaluations, 1 round(s)

## Verdict: **CLOSED**

Setup and hold met at 4.0 ns with the golden SDC: WNS -0.1299 -> +0.0412 ns, TNS -1.3371 -> +0.0000 ns, 1 accepted edit(s), routed with 0 DRC, logic proven equivalent.

| Metric (independent OpenSTA sign-off, golden SDC, RCX parasitics) | Before | After |
|---|---|---|
| Setup WNS (ns) | -0.1299 | +0.0412 |
| Setup TNS (ns) | -1.3371 | +0.0000 |
| Violating setup endpoints | 20 | 0 |
| Hold WNS (ns) | +0.1439 | +0.1444 |
| Violating hold endpoints | 0 | 0 |
| Routing DRC violations | 0 | 0 |
| Antenna nets | 0 | 0 |
| Slew/cap/fanout violations | 0 | 0 |
| Cell area (um^2) | 31431.4 | 31573.9 |
| Total power (W, default activity) | 4.7100e-02 | 4.7300e-02 |
| Global-route wirelength, before any ECO re-route (um) | 769698 | 769698 |

- Logic equivalence, golden netlist vs routed netlist (Yosys): **PASS**, equivalent: 694 points proven (565 state bits matched by name)
- Reproduced from an empty cache with the final recipe: **yes** (WNS +0.0412 ns, TNS +0.0000 ns, hold +0.1444 ns)
- Guardrails on the final result: golden inputs unchanged: ok, clock period unchanged at sign-off: ok, optimization overlay whitelisted: ok, fully routed, zero DRC: ok, placement legal: ok, antenna not worse: ok, no new hold violations: ok, no new slew/cap/fanout violations: ok, area growth within limit: ok

## What the agent changed (accepted edits, in order)

1. **routing_aware_eco_repair** (optimization), round 1: `grt_repair_timing`: False -> True, `grt_rt_setup_margin`: 0.0 -> 0.13
   - Why: Incremental ECO after global routing: repair_timing on global-route parasitics (closer to routed RC than placement estimates), then incremental re-route.
   - Evidence: POST_ROUTE_DEGRADATION: optimizer saw WNS +0.0003 ns on placement parasitics; routed sign-off is -0.1299 ns
   - Effect: WNS -0.1299 -> +0.0412 ns, TNS -1.3371 -> +0.0000 ns, hold +0.1439 -> +0.1444 ns, area 31431.4 -> 31573.9 um^2

## Baseline diagnosis

- Worst path: `_33202_/Q` -> `_33128_/D` (check), slack -0.1299 ns, 14 stages, cell 3.8563 ns + wire 0.0810 ns (wire 2%), max fanout 24, max slew 0.3727 ns, launch/capture clock latency 0.6377/0.5837 ns
- `DEEP_LOGIC`: 14 cell stages, cell delay 3.8563 ns
- `HIGH_FANOUT`: max fanout 24 on the worst path
- `SLOW_SLEWS`: max slew 0.3727 ns on the worst path
- `SKEW_PENALTY`: launch latency 0.6377 ns exceeds capture latency 0.5837 ns by 0.0540 ns
- `POST_ROUTE_DEGRADATION`: optimizer saw WNS +0.0003 ns on placement parasitics; routed sign-off is -0.1299 ns
- `MANY_ENDPOINTS`: 20 violating endpoints
- `WEAK_DRIVERS`: 25 X1/X2 drivers on the worst paths drive >=4 fF or >=3 loads

## Every candidate evaluated

| Round | Action | Category | Change | WNS (ns) | TNS (ns) | Hold WNS (ns) | DRC | Area (um^2) | Guardrails | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | guardband_setup_repair | optimization | `rt_setup_margin=0.13` | -0.0613 | -0.1017 | +0.1452 | 0 | 31490.7 | ok | valid, not best this round |
| 1 | resynthesize_for_delay | synthesis | `resynth_delay_ps=2400` | -0.0803 | -0.2788 | +0.0499 | 0 | 30739.2 | ok | valid, not best this round |
| 1 | routing_aware_eco_repair | optimization | `grt_repair_timing=True; grt_rt_setup_margin=0.13` | +0.0412 | +0.0000 | +0.1444 | 0 | 31573.9 | ok | ACCEPTED |
| 1 | eco_upsize_worst_paths | eco | `eco_resize=[['_27798_', 'NOR2_X4'], ['_28892_', 'OAI21_X2'], ['_28895_', 'OAI221_X2'], ...` | -0.1071 | -1.0971 | +0.1466 | 0 | 31439.9 | no new slew/cap/fanout violations | rejected: guardrail |

## Generated-script diff, baseline -> final

```diff
--- baseline/grt.tcl
+++ final/grt.tcl
@@ -54,2 +54,8 @@
 estimate_parasitics -global_routing
+global_route -start_incremental
+repair_timing -setup_margin 0.1300 -skip_gate_cloning
+set_placement_padding -global -left 1 -right 1
+detailed_placement
+global_route -end_incremental -congestion_report_file {<run>/grt/congestion_eco.rpt}
+estimate_parasitics -global_routing
 pa_timing_metrics grt
```

## Final recipe changes vs baseline

```json
{
 "grt_repair_timing": [
  false,
  true
 ],
 "grt_rt_setup_margin": [
  0.0,
  0.13
 ]
}
```
