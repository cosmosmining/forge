# HANDOFF

> This file in the `cosmosmining/forge` cloud checkout holds only the Feature 8 entry.
> On merge, append the section below to `~/Desktop/startup/HANDOFF.md`; do not replace
> that file with this one.

## Feature 8 of 8 — auto test-case generation + formal DV (cloud session, 2026-11-27/28)

**Branch:** `claude/confident-mendel-ucx4zs` · **Directory:** `beat-plan/auto-testgen-formal-dv/`
(no other path touched except this HANDOFF.md).

### What this session could not see
The cloud checkout of `cosmosmining/forge` contains only the landing page
(`index.html`, `CNAME`). Missing here, so not read or modified: `STRATEGY.md`,
`BEAT_PLAN.md`, the laptop `HANDOFF.md`, `beat-plan/strategy/*`, `chip-design-skills/`
(chip-verification, chip-formal, chip-rtl-design), the `forge/` Claude pack, formal tool
#4, conformance pack #5, and the Build 6 RTL. No laptop folder was shared with the
session; a request to attach another repo to look for them was declined by the session's
permission check. github.com (OSS CAD Suite download) is blocked by the session's
network policy, so the same open-source tools were installed from the Nix binary cache:
Yosys 0.71, SymbiYosys 0.70, Icarus Verilog 13.0, Verilator 5.054, Bitwuzla 0.9.1,
Yices 2.7.0, Z3.

### What was built
`forge_testgen` (stdlib-only Python): block spec (TOML/JSON) + golden model in a
restricted-Python DSL that also translates bit-exactly to a Verilog reference ->
directed / pairwise / vector-pattern / constrained-random tests and five valid/ready
protocol scenarios -> coverage (data corners, golden `cover()` events, automatic
decision-boundary bins, protocol) closed by solver witnesses, with unreachable bins
*proven* unreachable -> self-checking testbenches (Icarus or Verilator) plus a Python
re-check -> SymbiYosys: comb equivalence vs golden; for streams quiet-after-reset,
hold-under-backpressure, no-spurious-output, capacity, bounded latency, input progress,
accepts-below-capacity and per-transaction golden equivalence, plus covers -> every
formal counterexample replayed in simulation -> bug-injection campaign with formal
equivalent-mutant detection. 16 self-tests pass (`python3 -m unittest discover -s tests`).
Docs: `README.md`, `INTEGRATION.md`, `skill/SKILL.md`, `RESULTS.md` (generated).

### Results (measured; fixtures written in this session, NOT Build 6 blocks)
From `beat-plan/auto-testgen-formal-dv/RESULTS.md` and the JSON files it cites:

| fixture | formal on correct RTL | coverage | real injected bugs | caught by sim | caught by formal | extra seeds |
|---|---|---|---|---|---|---|
| requant (int32->int8, comb) | PROVEN | 33/33 | 21 (6 proven equivalent excluded) | 21/21 | 21/21 | 5/5 PASS |
| argmax8 (ties, comb) | PROVEN | 75/75 (8 proven unreachable) | 17 (5 equivalent) | 17/17 | 17/17 | 5/5 PASS |
| sfifo (valid/ready FIFO) | PROVEN, all 9 properties | 9/9 | 42 | 42/42 | 41/42 | 5/5 PASS |
| dot4 (2-stage MAC pipeline) | BOUNDED(16) — PDR timed out, not a proof | 50/50 | 57 (10 equivalent) | 57/57 | 57/57 | 5/5 PASS |

No false positives: every correct fixture passed on 6 seeds; 0 formal counterexamples
failed to replay. The one formal miss (sfifo, out-of-range memory read) is X behaviour
that two-valued formal cannot see; simulation caught it. Bug injection exposed three
gaps that were fixed generally and re-measured (history in `runs/history/`):
boundary bins (requant sim kills 20/21 -> 21/21), and the input-progress and
accepts-below-capacity properties (sfifo formal kills 37/41 -> 41/42).

### Not done / next (on the laptop)
1. **Build 6 success test: not yet run.** Follow `INTEGRATION.md`: write a spec + golden per
   Build 6 block (from the integer model, not the RTL), then
   `python3 -m forge_testgen all specs/*.toml --out runs_build6 --results RESULTS_BUILD6.md`.
2. Reconcile with formal tool #4 (overlapping protocol properties) and conformance pack #5
   (vector import/export) — neither was visible here.
3. Not supported yet: stream blocks that reduce k inputs to 1 output (packets).
