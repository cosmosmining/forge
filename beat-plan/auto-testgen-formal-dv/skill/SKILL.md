---
name: forge-testgen
description: Generate directed + constrained-random tests and formal proofs for one Forge RTL block from its spec and golden (integer) model, run them, close coverage, and measure test strength by bug injection. Use when a block needs verification evidence beyond the gate's own tests, when asked to "generate tests", "prove the block", "check coverage", or "inject bugs" for a Forge block.
---

# forge-testgen (Forge feature 8)

Tool: `beat-plan/auto-testgen-formal-dv/forge_testgen` (Python 3.9+, stdlib only;
TOML specs need 3.11+ or `pip install tomli`, else use JSON specs).
Needs the open-source OSS CAD Suite on PATH: `yosys`, `sby`, `yosys-smtbmc`,
`yosys-abc`, `iverilog`/`vvp` (or `verilator`), and `bitwuzla` (yices/z3 optional).

Run every command from `beat-plan/auto-testgen-formal-dv/`.

## Procedure for one block

1. **Find the inputs.** The block's RTL file(s) and top module; the integer-model
   function this block implements (the golden); its interface (combinational, or
   valid/ready stream with clk/rst/in_valid/in_ready/out_valid/out_ready).
   If any of these is missing, stop and say which file is missing. Never invent RTL.

2. **Write the spec** `specs/<block>.toml` (format: README.md, examples in
   `fixtures/specs/`). Port widths and signedness must match the RTL exactly; legal
   input ranges come from the model configuration, never from what makes a test pass.
   For streams also give `capacity` (max transactions in flight) and `max_latency`
   (cycles with `out_ready` high and something in flight before an output must appear).

3. **Write the golden** `golden/<block>.py` in the restricted-Python DSL (README.md,
   "Golden DSL"): the same integer arithmetic as the integer model, written from the
   model, not from the RTL. Use `sat`, `wrap`, `clamp`, `rshift_round` where the model
   saturates, wraps or rounds. Add `cover("name", cond)` for behaviours that matter
   (saturation, ties, overflow).

4. **Check:** `python3 -m forge_testgen check specs/<block>.toml`. Fix every
   spec-vs-RTL issue it lists. A translation error means the golden uses an
   unsupported construct: rewrite that construct, do not drop it.

5. **Run:** `python3 -m forge_testgen run specs/<block>.toml`. Read
   `runs/<block>/report.json`:
   - `SPEC-ERROR` / `TOOL-ERROR`: fix the spec or report the tool problem.
   - `FAIL`: the RTL disagrees with the golden. Report the first mismatch and the
     replayed formal counterexample (`formal.cex`). A formal FAIL whose replay is not
     confirmed is a tool problem, not an RTL bug; say so.
   - `INCOMPLETE`: formal ended UNKNOWN; report it as such.
   - `PASS`: report formal as PROVEN or BOUNDED(n) exactly as printed. BOUNDED is
     not a proof.

6. **Measure test strength:** `python3 -m forge_testgen mutate specs/<block>.toml`.
   For each survivor, improve the generator *generally* (a missing coverage bin, a
   missing protocol scenario, a missing directed pattern), never with a test aimed
   at one mutant. Re-run and report before and after.

7. **Report** with Forge's evidence kinds: every number is `measured` (name the
   JSON file it came from) or `derived` (give the formula). Use
   `python3 -m forge_testgen results specs/*.toml` to produce RESULTS.md.

## Rules

- Never relax a test, weaken a property, widen `max_latency`, narrow a legal input
  range or edit the golden to get a PASS. Any spec change must come from the model.
- Never change the RTL under test from this skill; report the bug.
- Fixture blocks under `fixtures/` are tool self-tests, not Forge RTL; never quote
  their numbers as Forge results.
- BOUNDED(n) means "no counterexample in n cycles from reset", nothing more.
