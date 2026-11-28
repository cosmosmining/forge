# HANDOFF

## 2026-11-28 · Forge feature 2 of 8 · PnR tuning agent (#2) · BUILT, verified on stand-ins; Build 6 not yet run

Cloud session, branch `claude/laughing-mendel-pj7z9x` of `cosmosmining/forge`.
Merge this section into `~/Desktop/startup/HANDOFF.md`; copy
`beat-plan/pnr-tuning-agent/` to `~/Desktop/startup/beat-plan/pnr-tuning-agent/`.

### What is missing, and why the success test did not run
This cloud copy of the repo held only the website (`index.html`, `CNAME`).
STRATEGY.md, BEAT_PLAN.md, HANDOFF.md, `beat-plan/strategy/*.md` (PPA_LOOP_PLAN,
PROBLEMS_AND_IMPROVEMENTS, CLOCK_3GHZ_PLAN), the `chip-design-skills/` and
`forge/` SKILL.md files, and **all Build 6 files** were absent, so none were read.
The laptop folder was not attached to the session, and attaching
`cosmosmining/asic` / `cosmosmining/claude` was refused by the session's
permission check. **The Build 6 success test has not been run.** Nothing was
invented in their place.

### What was built (`beat-plan/pnr-tuning-agent/`)
A closed loop with these parts:
- **Flow:** OpenROAD reference flow in 5 cached stages.
- **Sign-off:** a separate OpenSTA process reading only the golden SDC and RCX parasitics.
- **Diagnosis:** worst-path anatomy, congestion, and how far routing moved timing from the optimizer's estimate.
- **Typed action catalog:** floorplan, optimization-only constraints, placement, CTS, routing, ECO, re-synthesis, and RTL *proposals* only.
- **Guardrails:** the clock, I/O budget and timing exceptions can never change.
- **Proof and record:** Yosys equivalence proof, a clean-cache re-run, and `LEDGER.md` + `ledger.json` per block.

39 unit tests pass, including a mutation test showing the equivalence check catches a one-gate logic change. A `SKILL.md` lets a Claude Code session drive it step by step (`diagnose` / `try`). The PACT paper (arXiv:2608.23602) was readable only at abstract level; its lessons (fine-grained actions, strict per-action validation) shaped the catalog.

### Measured results (stand-ins, NOT Build 6)
| Stand-in | Before | After | Verdict |
|---|---|---|---|
| OpenROAD aes netlist, Nangate45 slow corner, **4.0 ns / 250 MHz** | WNS -0.1299 ns, TNS -1.337 ns, 20 violators | WNS **+0.0412 ns**, TNS **0**; one edit (routing-aware ECO), +0.45% area | **CLOSED**: equivalent, reproduced |
| OpenROAD gcd reference config, 0.485 ns | WNS -0.0463 ns, TNS -0.410 ns | WNS -0.0345 ns, TNS -0.296 ns; 6 edits | **not closed**: deep logic, RTL proposal recorded |

Details: `beat-plan/pnr-tuning-agent/RESULTS.md` and `runs/*/LEDGER.md`.
Tools: OpenROAD 2.0-unstable-2025-03-01, OpenSTA 2.6.0, Yosys 0.55 from the
NixOS 25.11 binary cache. OSS CAD Suite was not used because GitHub release
downloads are blocked from this session.

### Next steps (on the laptop, in order)
1. Install the tools: `bash scripts/setup_tools.sh` (Linux; on a Mac see README).
2. Per failing Build 6 block, copy `designs/build6_TEMPLATE.toml` and fill in the netlist, golden SDC, die/core and corner.
3. Run `python3 -m pnr_agent diagnose designs/build6_<block>.toml` and confirm the baseline reproduces Build 6's ~-0.050 ns. If it doesn't, set `[knobs]` to Build 6's flow first.
4. Run `python3 -m pnr_agent run designs/build6_*.toml --out runs/build6` and read `runs/build6/SUMMARY.md`.

### Decisions that are Johnson's
- Sign-off corner for Build 6: typical vs slow (`platforms/nangate45*.toml`).
- Area-growth limit per block. The stand-ins used +10%. For gcd, the best rejected candidate (WNS -0.0330) failed only that limit.
- Whether the agent may *apply* RTL changes. Today it only writes proposals, because they change latency and must re-pass the gate.
