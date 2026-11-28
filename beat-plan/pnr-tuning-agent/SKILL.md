---
name: pnr-tuning-agent
description: Close post-route setup timing on an OpenROAD block without relaxing constraints. Use when a block misses its clock after place-and-route (e.g. Build 6 blocks 0.050 ns short of 250 MHz) and you need edits plus a before/after record.
---

# PnR tuning agent: how to use it from Claude Code

Written for the Forge Claude pack; the pack's own `forge-timing-closure`,
`chip-physical-design` and `chip-routing` skills were not available when this
was written, so reconcile with them when merging.

## Hard rules (the harness enforces them; do not try to get around them)
- Never change the clock period, uncertainty, I/O delays or timing exceptions.
  Sign-off always re-reads the golden SDC in a fresh OpenSTA process.
- Never edit the golden netlist. Every final result must pass the Yosys
  equivalence proof against it.
- An RTL change that adds latency is a proposal for a human plus Forge's
  verification gate. It is never applied from here.
- Report numbers with their kind: everything in a ledger is *measured*
  (a tool printed it, file named). Stand-in results are not Build 6 results.

## Autonomous
```bash
source scripts/env.sh
python3 -m pnr_agent run designs/<block>.toml --out runs --work /tmp/pnr-work --workers 4
```
Read `runs/<block>/LEDGER.md`: verdict, before/after table, accepted edits with
evidence, every candidate, the generated-script diff.

## Step by step (you are the policy)
1. `python3 -m pnr_agent diagnose designs/<block>.toml --work /tmp/pnr-work` prints the
   sign-off summary, the diagnosis tags with evidence, and a ranked action menu.
2. Pick an action from the menu (or combine knobs from `pnr_agent/recipe.py`) and run
   `python3 -m pnr_agent try designs/<block>.toml --work /tmp/pnr-work --changes '<json>'`.
   It returns the candidate's sign-off and every guardrail check.
3. Keep a change only if `checks` are all ok and WNS (then TNS) improved.
   Re-diagnose with `--changes` set to the accumulated recipe.
4. Finish with `run` (or by hand: equivalence + clean re-run) before claiming closure.

## Reading the diagnosis
| Tag | Means | First levers |
|---|---|---|
| POST_ROUTE_DEGRADATION | optimizer closed on placement RC, routing took it back | guard-banded repair, routing-aware ECO |
| WIRE_DOMINATED | >=25% of the worst path is wire | timing-driven placement, density, critical-net routing |
| DEEP_LOGIC | >=12 stages, little wire | re-synthesis, then an RTL proposal |
| IO_BOUND / IO_LAUNCH_LATENCY | worst paths hit ports; clock insertion delay counts against an ideal-clock budget | IO pin annealing, core margin, stronger clock tree |
| SKEW_PENALTY | launch clock later than capture | CTS clustering / level balancing |
| CONGESTED | GRT overflow or >70% layer usage | lower density |
| WEAK_DRIVERS / HIGH_FANOUT / SLOW_SLEWS | electrical | targeted resize, gate cloning, optimization-only fanout/transition limits |
