# Integration with formal tool #4, conformance pack #5 and the Build 6 blocks

## What this session could and could not see

This cloud session's checkout of `cosmosmining/forge` contained only the public
landing page (`index.html`, `CNAME`). These files named in the brief were **not
present**, so nothing here reads, copies or modifies them:

- `STRATEGY.md`, `BEAT_PLAN.md`, `HANDOFF.md`, `beat-plan/strategy/` (`PPA_LOOP_PLAN.md`,
  `PROBLEMS_AND_IMPROVEMENTS.md`, `CLOCK_3GHZ_PLAN.md`)
- `chip-design-skills/` (`chip-verification`, `chip-formal`, `chip-rtl-design` SKILL.md files)
  and the `forge/` Claude pack
- formal tool #4 (19 tests passing) and conformance pack #5 (64 files)
- the Build 6 block RTL and its integer-model functions

No laptop folder was shared with the session, and a request to attach another repository
to look for them was declined by the session's permission check. Feature 8 was therefore
built as a self-contained package with explicit seams, and verified on fixture blocks.
**Everything below is a merge plan, not a description of #4 or #5.** Read #4 and #5
before following it and adjust where they differ.

## Merge steps on the laptop (`~/Desktop/startup`)

1. **Copy** `beat-plan/auto-testgen-formal-dv/` into `~/Desktop/startup/beat-plan/`. It
   touches no other path. Append the Feature 8 section of this branch's `HANDOFF.md`
   to the laptop's `HANDOFF.md`.
2. **Tools:** put the OSS CAD Suite `bin/` on `PATH` (the tool also looks in
   `~/oss-cad-suite/bin` and `/opt/oss-cad-suite/bin`). Run
   `python3 -m unittest discover -s tests` — all tests must pass before anything else.
3. **Reconcile with the chip-design skills.** Compare `skill/SKILL.md` with
   `chip-verification`, `chip-formal` and `chip-rtl-design`. Where those skills set rules
   (naming, gate verdicts, evidence kinds), the skill text here should defer to them;
   then add `skill/SKILL.md` to the `forge/` Claude pack as `forge-testgen`.

## Formal tool #4 (extend, do not duplicate)

`forge_testgen/formal.py` writes ordinary SymbiYosys jobs (`*.sby`) plus SystemVerilog
wrappers, so it can sit next to #4 rather than replace it.

- **Overlap to check first:** the stream protocol assertions (`a_hold_valid`,
  `a_hold_data`, `a_no_spurious_output`, `a_capacity`, `a_bounded_latency`,
  `a_quiet_after_reset`) are generic valid/ready properties. If #4's property library
  already has them, keep #4's versions as the source of truth: replace the body of
  `formal.stream_wrapper()` with a call into #4's library and keep only what is new here.
- **New capability to register with #4:** (a) equivalence against the golden through
  the golden-to-Verilog translator (`golden.Translation.verilog()`), for combinational
  blocks and per-transaction for streams; (b) coverage witnesses / unreachability proofs
  (`formal.witnesses()`); (c) mutant-vs-original miters (`formal.miter()`); (d)
  counterexample replay in simulation (`campaign.replay_*`).
- **Runner:** if #4 has its own sby runner (timeouts, solver choice, result parsing),
  point `formal.run_sby()` at it so both report the same way. Keep the verdict
  vocabulary PROVEN / BOUNDED(n) / FAIL / UNKNOWN unless #4 already defines one.
- **Tests:** add #4's 19 tests and `tests/` here to one test command and confirm both
  still pass.

## Conformance pack #5

Its 64 files presumably hold reference vectors or checks against the integer model.
Two adapters connect it (format to be read from #5 itself):

- **#5 -> forge_testgen:** load #5's vectors for a block as `[[directed]]` spec entries
  (or a small loader that appends them to the `directed` group in `campaign.build_suite`),
  so they run alongside the generated tests and count toward coverage.
- **forge_testgen -> #5:** each run writes `runs/<block>/suite.json` (every vector with
  its origin) and per-run `stim.hex` / `exp.hex`; export these into #5's layout if #5
  should carry the generated suites as regression tests.

## Build 6 blocks: the success test

The brief's success test — generated tests catch injected bugs in Build 6 blocks,
proofs cover the key properties, no false positives on passing blocks — is **not yet**
run. For each Build 6 block:

1. `specs/<block>.toml`: ports from the RTL (`python3 -m forge_testgen check` lists any
   disagreement), legal ranges from the model configuration, and for streams the
   handshake names, `capacity` and `max_latency` from the block's design notes.
2. `golden/<block>.py`: the block's function written from the **integer model** (not
   from the RTL) in the golden DSL. Blocks whose model is a reduction over a stream
   (k inputs -> 1 output) need the packet extension listed under README limitations.
3. `python3 -m forge_testgen all specs/*.toml --out runs_build6 --results RESULTS_BUILD6.md`
   runs tests, coverage, formal, bug injection and the extra-seed false-positive check.
4. Read the result: a PASS on every passing block (no false positives), PROVEN or an
   honestly reported BOUNDED(n) per block, and the kill rates per block.

Do not touch Q7, Build 6 last-mile, b11 or the 3 GHz work while doing this: the tool
only reads RTL and writes under its own `runs*/` directories, and bug injection edits
copies under `runs*/<block>/mutants/`, never the source RTL.

## Gate mapping

`report.json["verdict"]` is one of `PASS`, `FAIL`, `INCOMPLETE` (formal UNKNOWN),
`SPEC-ERROR`, `TOOL-ERROR`. The Forge gate's PASS / FAIL / INCOMPLETE map directly; the
two error verdicts should block the gate as INCOMPLETE with the message from the report.
