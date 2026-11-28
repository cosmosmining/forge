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

### What was built (status: in progress — final numbers below once the full run ends)
`forge_testgen`, a stdlib-only Python package: block spec (TOML/JSON) + golden model in a
restricted-Python DSL -> directed/pairwise/pattern/constrained-random tests, valid/ready
protocol scenarios, coverage (data, golden events, automatic decision-boundary bins,
protocol) with closure by formal witnesses and unreachability proofs, self-checking
testbenches (Icarus/Verilator) with Python re-check, SymbiYosys proofs (comb
equivalence vs golden; stream protocol + liveness-bounded + per-transaction golden
equivalence + covers), counterexample replay in simulation, and a bug-injection
campaign with formal equivalent-mutant detection. Verified on four fixture blocks
written in this session (NOT Build 6 blocks). See `README.md`, `INTEGRATION.md`,
`skill/SKILL.md` in that directory.

### Next (on the laptop)
Follow `beat-plan/auto-testgen-formal-dv/INTEGRATION.md`: reconcile with formal tool #4
and conformance pack #5, then write a spec + golden per Build 6 block and run
`python3 -m forge_testgen all` — that is the brief's success test, **not yet** run.
