# HANDOFF

## 2026-11-28 · Forge feature 2 of 8 · PnR tuning agent (#2) · IN PROGRESS

Cloud session, branch `claude/laughing-mendel-pj7z9x`. Merge this section into
`~/Desktop/startup/HANDOFF.md` and copy `beat-plan/pnr-tuning-agent/` to
`~/Desktop/startup/beat-plan/pnr-tuning-agent/`.

**Inputs missing in this cloud copy.** The repo held only the website
(`index.html`, `CNAME`). STRATEGY.md, BEAT_PLAN.md, HANDOFF.md,
beat-plan/strategy/*.md, chip-design-skills/ and forge/ SKILL.md files, and all
Build 6 files were absent, so none of them were read. The laptop folder was not
attached, and attaching `cosmosmining/asic` / `cosmosmining/claude` was refused
by the session's permission check. **So the Build 6 success test has not been run.**

**Built so far:** `beat-plan/pnr-tuning-agent/`: closed-loop agent (OpenROAD
flow, independent OpenSTA sign-off on the golden SDC, diagnosis, typed action
catalog, guardrails, Yosys equivalence proof, clean re-run, ledger). 39 unit
tests pass. Tools came from the NixOS binary cache (OSS CAD Suite and GitHub
release downloads are blocked here).

**Measured on stand-in 1 (gcd, OpenROAD reference config, NOT Build 6):** WNS
-0.0463 -> -0.0345 ns at 0.485 ns, not closed (deep-logic path, physical edits
cannot recover it). Stand-in 2 (aes at 250 MHz, slow corner) is running.
