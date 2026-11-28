---
name: forge-dv-agent
description: Verify generated RTL for Forge. Writes a self-checking testbench from a block manifest and a Python golden model, checks every output bit-exactly against the golden model on Icarus and Verilator, runs Verilator lint and a yosys structural check, measures coverage, and grades the testbench with injected bugs (mutation campaign) whose survivors are classified with yosys/SymbiYosys. Use when a block's RTL was generated or changed, before a block may enter the gate, when a test fails and needs triage, or when asked how strong a testbench is.
---

# Forge DV agent

The tool lives in `beat-plan/dv-verification-agent/` (run `./dv ...` from there, or
`python3 -m dvagent ...` with that directory on `PYTHONPATH`). Verdicts follow the gate:
**PASS, FAIL or INCOMPLETE. Only PASS counts.**

## Rules (do not bend these)

1. **Never relax a check to get PASS.** No lowering coverage thresholds, removing ports
   from comparison, shrinking stimulus, adding lint waivers without a real reason, or
   switching off a simulator because it fails. A waiver must state *why the warning
   cannot change behaviour*; it stays visible in every report.
2. **The golden model is the reference.** It comes from the integer model / spec, never
   from the RTL. If RTL and golden disagree, fix the RTL. Change the golden model only when
   the integer model changed, and say so in the log with the integer-model reference.
3. **Never invent RTL, results or numbers.** Every number you report carries its kind
   (`measured` = a tool printed it, file named; `derived` = arithmetic on measured
   numbers, formula given; `model`; `not yet`). Results on the self-test fixtures say
   nothing about Forge blocks.
4. If a tool is missing the verdict is INCOMPLETE, not PASS. Run `./dv doctor`.

## Workflow for a new or changed block

1. **Ports**: `./dv introspect rtl/*.sv --top <top> --draft manifest.toml`
   (yosys reads the ports; the draft guesses clock/reset/valid/ready by name - check it).
2. **Manifest** (`manifest.toml`): protocol `comb` | `pipe` | `stream`; clock, reset and
   polarity; handshake names (`in_valid`, `in_ready`, `out_valid`, `out_ready`, `in_last`);
   `latency` for pipes without `out_valid`; per-port `range`, `lanes`/`lane_signed`,
   `values`, `corners`, `hold`. See `selftest/fixtures/*/manifest.toml`.
3. **Golden model** (`golden.py`): plain Python ints; use `dvagent.gm` helpers
   (`to_signed`, `wrap`, `lanes`, `pack`, `sat_signed`, `shift_round_half_up`).
   `style = "map"`: `f(beat) -> outputs`; `style = "stream"`: `f(all_beats) -> output beats`.
   Write branches explicitly (saturation, rounding, special cases) so golden-model line
   coverage shows which spec behaviour the stimulus reached.
4. **Verify**: `./dv verify manifest.toml --seeds 1-3`. Read `report.md` per seed.
5. **Grade the testbench**: `./dv campaign manifest.toml --formal`.
   - `escapes` must be 0. An escape is a real functional difference the tests missed;
     the report gives learned input beats - add them to the manifest's `directed` file.
   - `bounded-equivalent`, `timing-only` and `needs-review` survivors must be read and
     accepted by a person; they are not proofs of correctness. `needs-review` is used for
     clock/reset edge changes, which cycle-based formal tools cannot judge.
6. **Hand-written bugs** for blocks that matter: write `bugs.toml` with realistic bugs
   (must FAIL) and behaviour-preserving rewrites (must PASS); `./dv bugs manifest.toml bugs.toml`.

## Triage of a FAIL

`report.md` lists the first mismatches with a hint computed from the bit difference:

| hint | usual cause |
|---|---|
| only the sign bit differs | signedness: an unsigned operand (often a `{...}` concat) turned `>>>` into `>>`, or a missing `$signed` |
| only high bits differ | sign extension, overflow width, carry |
| only low bits / off by one | rounding constant or direction, shift amount, truncation |
| saturated / RTL saturated | clamp bound or overflow compare |
| output is zero | register not updated, cleared too early, wrong select |
| X/Z on output | missing reset, uninitialised state, undriven logic |
| N expected output beats never appeared | handshake bug or hang; check `in_ready`/`out_valid` logic |
| output protocol broken | `out_valid` dropped or data changed before `out_ready` |
| DUT accepted k of n input beats | input handshake stuck |

Lint FAILs name the Verilator code (WIDTH*, LATCH, MULTIDRIVEN, ...) and file:line.
Structural FAILs come from yosys (latches, logic loops, async reset that does not synthesise).

## What the testbench does

Inputs change 1 time unit after posedge (like clock-to-q of upstream flops) and outputs
are sampled at posedge, so a flop that wrongly uses the falling edge shows up as a latency
error instead of hiding behind a race. For handshake blocks it inserts
random idle gaps, drives random junk on data inputs while `in_valid` is low, and applies
random `out_ready` back-pressure including long stalls. Every output beat is compared with
`!==` inside the testbench **and** independently in Python from the dumped outputs; if the
two disagree the verdict is INCOMPLETE. Verilator runs with random initial values
(`+verilator+rand+reset+2`), Icarus is 4-state, so reset bugs show up in one or the other.

## Known limits

- One clock domain; no inout ports; SystemVerilog interfaces/classes are not supported
  by the port reader (yosys).
- Reset is always applied with the clock running; an asynchronous reset made synchronous
  is not caught by the testbench and shows up as a `needs-review` survivor.
- yosys `equiv` and sby treat every flop as updating once per step whatever its clock
  edge, so the agent never lets formal call a clock/reset edge change equivalent.
- Throughput (cycles) is not checked, only values and order of transactions.
- The transaction-level formal check (`[formal] txn_check = true`) is sound but slow with
  the open-source solvers; it is off by default.
