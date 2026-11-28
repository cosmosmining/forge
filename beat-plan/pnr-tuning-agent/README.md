# PnR tuning agent (Forge feature 2 of 8)

An agent that reads post-route timing (worst path, WNS/TNS, congestion), edits
the floorplan, optimization constraints and synthesis/physical recipe, re-runs
OpenROAD, and keeps only edits that make an **independent sign-off** better
without relaxing anything. Every run leaves a ledger of what changed, why, and
the before/after timing.

> **Status, 28 Nov 2026.** Build 6 netlists, SDCs and reports were **not** in this
> cloud workspace (the repo only held the website; the laptop folder was not
> attached; attaching other repos was refused). So the success test, "closes the
> Build 6 blocks that are 0.050 ns short of 250 MHz", has **not been run**. The
> agent was built and verified on two labeled stand-ins instead
> ([RESULTS.md](RESULTS.md), [runs/SUMMARY.md](runs/SUMMARY.md)):
>
> - **aes at 250 MHz, slow corner** (misses by 0.130 ns, 2.6x Build 6's gap): **closed**.
>   WNS -0.1299 -> +0.0412 ns and TNS -1.337 -> 0 with one routing-aware ECO,
>   +0.45% area. Proven equivalent and reproduced from an empty cache.
> - **gcd at OpenROAD's 0.485 ns reference** (misses by 0.046 ns, 9.5% of its
>   period): **improved, not closed**, -0.0463 -> -0.0345 ns. Deep-logic path;
>   the ledger leaves an RTL proposal.
>
> To run it on Build 6, see "Running it on Build 6" below.

## The loop

```
 golden inputs (netlist, SDC, liberty, period)  -- hashed, never edited
            |
   recipe --+--> OpenROAD flow, 5 cached stages ------------------------------+
     ^           floorplan -> place -> cts(+repair) -> global route(+ECO)     |
     |           -> detailed route -> RCX extraction                          |
     |                                                                        v
     |      independent sign-off: fresh OpenSTA process, routed netlist + SPEF +
     |      GOLDEN SDC only  ->  WNS/TNS/hold, top paths (JSON), DRVs, power
     |                                                                        |
     |      diagnosis: worst-path anatomy (cell vs wire delay, stages, fanout,
     |      slews, launch/capture latency), GRT congestion, optimizer-vs-route
     |      degradation  ->  tags with evidence                               |
     |                                                                        v
     +-- accept best candidate  <--  guardrails + "is it better?"  <--  try the
         (greedy, accumulates)       on each candidate                 top-ranked
                                                                     actions in parallel
   end: Yosys equivalence proof (golden netlist vs routed netlist),
        re-run final recipe from an empty cache, write LEDGER.md + ledger.json
```

Code: `pnr_agent/` (`agent.py` loop, `actions.py` catalog, `diagnose.py`,
`guardrails.py`, `runner.py` staged OpenROAD runs with checkpoint reuse,
`tcl.py` script generation, `reports.py` parsers, `equiv.py`, `synth.py`,
`ledger.py`).

## What the agent may and may not change

Forge's rule is "a test is never relaxed to get a PASS". Here that means:

| Never (enforced) | How |
|---|---|
| Clock period, waveform, uncertainty, latency | Not knobs. Sign-off re-reads the golden SDC and checks every clock period equals the target. |
| I/O delays, false/multicycle paths, max/min delay, case analysis, derates, loads | Not knobs. Generated scripts are tested never to contain these commands (`tests/test_guardrails.py`). |
| The netlist's logic | Every final result is proven equivalent to the golden netlist (Yosys, registers matched by name, mutation-tested). |
| The die size, when the block's floorplan is fixed | `floorplan_fixed = true` blocks area-changing floorplan edits. |

The only SDC the agent writes is an **optimization-only overlay**
(`set_max_fanout`, `set_max_transition`, `set_max_capacitance`, i.e. tightening),
whitelisted and never read by sign-off. Each candidate must also pass:
routed with 0 DRC, legal placement, no new hold violations, no new
slew/cap/fanout violations, antennas not worse, area growth within the
design's limit.

## Action catalog

Ordered fine-grained first. This follows the PACT paper (below): local,
validated edits beat a sweep of tool settings.

| Action | Category | What it changes | Raised by |
|---|---|---|---|
| guardband_setup_repair | optimization | post-CTS `repair_timing -setup_margin` = the post-route miss | POST_ROUTE_DEGRADATION, NEAR_MISS |
| routing_aware_eco_repair | optimization | ECO after global route: `repair_timing` on GRT parasitics + incremental re-route | POST_ROUTE_DEGRADATION, WIRE_DOMINATED |
| eco_upsize_worst_paths | eco | `replace_cell` weak X1/X2 drivers on the worst paths | WEAK_DRIVERS |
| enable_gate_cloning | optimization | let `repair_timing` clone gates | HIGH_FANOUT, WEAK_DRIVERS |
| repair_on_route_parasitics | optimization | post-CTS repair on GRT parasitics | POST_ROUTE_DEGRADATION |
| resynthesize_for_delay | synthesis | Yosys/ABC re-map of combinational logic to a delay target, registers untouched | DEEP_LOGIC |
| timing_driven_placement | placement | `global_placement -timing_driven` | WIRE_DOMINATED |
| raise/lower_placement_density | placement | `-density` +/-; lower only when congested | WIRE_DOMINATED / CONGESTED |
| shrink_core_margin | floorplan | core edge closer to the (fixed) die edge | IO_BOUND |
| anneal_io_pins | floorplan | annealing IO pin placement | IO_BOUND |
| route_critical_nets_first | routing | `global_route -critical_nets_percentage 10` | WIRE_DOMINATED, POST_ROUTE_DEGRADATION |
| tighten_max_fanout / _transition | constraint | optimization-only overlay | HIGH_FANOUT / SLOW_SLEWS |
| faster_clock_tree | cts | stronger CTS buffers (less insertion delay) | IO_LAUNCH_LATENCY |
| tighter_cts_clusters, balance_clock_levels | cts | CTS clustering / level balancing | SKEW_PENALTY |
| (RTL) pipeline/restructure proposal | rtl | **written proposal only**: changes latency, so it must re-pass Forge's gate (sim vs. integer model) | DEEP_LOGIC or gap > 5% of period |

OpenROAD's own `restructure -target timing` is wired up (knob `rs_timing`) but
not proposed: in the pinned OpenROAD build, every ABC result reports delay
FLT_MAX and is discarded, so it never changes the netlist.

## What we took from PACT

PACT: "Post-route Agentic Checkpoint Tuning for FPGA Timing Closure",
H. Lin, K. Li, L. Wang, Z. Wang, FPT 2026, [arXiv:2608.23602](https://arxiv.org/abs/2608.23602);
artifact at [github.com/FudanLLMEDA/PACT](https://github.com/FudanLLMEDA/PACT).
arxiv.org was not reachable from this session, so the following comes only from
the abstract as returned by web search, not the full paper:

- On 35 post-route UltraScale+ checkpoints, validation-clean Fmax gain was
  +22.30% geomean, vs +15.14% for DATuner and +9.78% for a Codex-agent baseline.
- A plain `phys_opt_design` directive sweep reached only +2.98%: the backend's
  global knobs alone could not make the local edits PACT made.
- The authors state post-route closure is limited not only by search time but
  by "action granularity and validation discipline".

How that shaped this agent: a typed action catalog (no free-form Tcl),
fine-grained edits ranked first, every candidate checked by an independent
sign-off process plus guardrails, keep-best/revert, a final equivalence proof
and a clean re-run. PACT targets FPGAs (Vivado + RapidWright); nothing here
claims its numbers transfer to ASIC.

## Running it

```bash
bash scripts/setup_tools.sh          # Nix: openroad, yosys, iverilog, verilator (pinned)
```

The setup script was run on x86_64 Linux. On a Mac, OpenROAD from nixpkgs may
not have a prebuilt binary; use a Linux machine or VM, OpenROAD-flow-scripts'
Docker image (then set `OPENROAD_TEST_DIR`/`PNR_PLATFORM_DIR` by hand), or a
cloud session with the Build 6 files attached.

```bash
source scripts/env.sh                 # PATH + OPENROAD_TEST_DIR + PNR_PLATFORM_DIR
```

```bash
python3 -m pytest -q tests            # 39 tests, ~2 s
```

```bash
python3 -m pnr_agent run designs/standin_gcd.toml --out runs --work /tmp/pnr-work
```

Step-by-step mode, so a Claude Code session can act as the policy (PACT-style
structured actions, same validation):

```bash
python3 -m pnr_agent diagnose designs/standin_gcd.toml --work /tmp/pnr-work
```

```bash
python3 -m pnr_agent try designs/standin_gcd.toml --work /tmp/pnr-work --changes '{"cts_buffer": "BUF_X8"}'
```

## Running it on Build 6

1. On the laptop, copy `designs/build6_TEMPLATE.toml` to one file per failing
   block and fill in the netlist, SDC, die/core and platform.
2. Check the baseline: `python3 -m pnr_agent diagnose designs/build6_<block>.toml`.
   Its WNS should match Build 6's own (about -0.050 ns). If not, set `[knobs]`
   to Build 6's flow settings first. A closure claimed against a different
   baseline would not be about Build 6.
3. Run every block in one go; it writes `runs/build6/SUMMARY.md`:

```bash
python3 -m pnr_agent run designs/build6_*.toml --out runs/build6 --work /tmp/pnr-build6 --workers 4
```

## Limitations (known)

- Rule-based policy. An LLM can drive it through `diagnose`/`try`, but no
  model is called by the loop itself (no API key or spend in this project).
- One timing corner per run (the platform's liberty). Multi-corner sign-off is
  not implemented.
- The equivalence proof matches registers by instance name. That holds for
  everything this agent does, but it would refuse a retimed netlist.
- Designs with macros (SRAMs) were not exercised in the verified runs.
- The flow is OpenROAD's reference flow, not OpenROAD-flow-scripts (ORFS). If
  Build 6 ran ORFS, match its settings in `[knobs]` (see step 2 above).
