# HANDOFF

> This cloud worktree (`cosmosmining/forge`, branch `claude/inspiring-lamport-pfcf1k`) had no
> HANDOFF.md, so this file holds only the Feature 1 entry. When merging, append the entry
> below to `~/Desktop/startup/HANDOFF.md` and copy `beat-plan/dv-verification-agent/` to
> `~/Desktop/startup/beat-plan/`.

## 2026-11-28 — Feature 1 of 8: DV / verification agent (#3)

**What it is.** An agent that writes a self-checking testbench for a block, checks the block
bit-exactly against its golden model, runs lint/structural checks, and grades its own
testbench with injected bugs.

- **Code:** `beat-plan/dv-verification-agent/`.
- **Docs:** `README.md` (start there) and `SKILL.md` (how a Claude session drives it).
- **Inputs:** RTL, a TOML manifest and a Python golden model.
- **Checks:** every output beat compared bit-exactly on Icarus and Verilator; Verilator lint
  (risk/style classes, reasoned waivers only); yosys structural check; coverage.
- **Testbench grading:** a mutation campaign, with every survivor classified by yosys
  `equiv` and SymbiYosys (bitwuzla BMC, ABC PDR), trace replay and extra seeds.
- **Verdict:** PASS / FAIL / INCOMPLETE; only PASS counts.

**Results (measured, on 5 stand-in blocks written for this purpose, NOT Forge RTL, NOT Build 6).**
Source: `results/selftest/summary.md`.

- **No false positives:** clean runs 15/15 PASS (5 blocks × 3 seeds × Icarus and
  Verilator); behaviour-preserving rewrites 10/10 PASS.
- **Hand-injected bugs:** 26/26 FAIL.
- **Mutation:** 322 mutants, 274 killed (272 by simulation). The 48 survivors: 45 proven
  equivalent, 2 timing-only, 1 needs-review, 0 escapes.
- **Learning loop** (deliberately weak testbenches, `results/learning_demo/summary.md`):
  formal found 6 escapes, and all 6 were killed after the counterexamples were added as test
  input.
- **A real catch:** on its first run the agent found a real signedness bug in one stand-in
  (an unsigned concat turned `>>>` into `>>`). Evidence: `results/organic_catch_fx_pwl/`.

**Not done.**

- **Success test on the Build 6 blocks: not yet.** The Build 6 RTL and the integer model are
  not in this checkout. The repository holds only the website.
- **Not read, because they are not in this checkout:** STRATEGY.md, BEAT_PLAN.md,
  HANDOFF.md, beat-plan/strategy/* (PPA_LOOP_PLAN, PROBLEMS_AND_IMPROVEMENTS,
  CLOCK_3GHZ_PLAN), chip-design-skills/ and forge/ SKILL.md files (chip-verification,
  chip-formal, chip-rtl-design).
- **Attaching `cosmosmining/asic`** (a guess at where Build 6 lives) was refused by this
  session's permission check.
- **Toolchain:** the OSS CAD Suite tarball (GitHub releases) is blocked by this session's
  network policy (403). I installed the same open-source tools from the Nix cache: Yosys
  0.71, sby 0.70, Icarus 13.0, Verilator 5.054, bitwuzla 0.9.1, yices 2.7.0. OpenROAD was
  not installed (not in OSS CAD Suite; not used for DV).

**Next (on the laptop, ~/Desktop/startup).**

1. Install the OSS CAD Suite, then:
   ```bash
   cd beat-plan/dv-verification-agent && ./dv doctor && ./dv selftest --quick
   ```
2. Set up each Build 6 block:
   - `./dv introspect <rtl> --top <top> --draft blocks/<name>/manifest.toml`, and check it;
   - write `blocks/<name>/golden.py` from the integer model;
   - optionally add a `bugs.toml`.
3. Run `./dv verify … --seeds 1-3`, `./dv campaign … --formal` and `./dv bugs …`.
   - Success: 0 false positives, all hand-written bugs FAIL, 0 escapes, 0 unexplained.
   - Review the timing-only, bounded and needs-review survivors by hand.
4. Optionally copy `SKILL.md` into the Forge Claude pack as the verification-agent skill.
