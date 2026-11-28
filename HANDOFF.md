# HANDOFF

<!-- This checkout had no HANDOFF.md. Only the Feature 3 section below belongs to this
     session; merge it into ~/Desktop/startup/HANDOFF.md next to the other features. -->

## Feature 3 — PPA-aware coding loop (cloud session, branch `claude/keen-mayer-vg4cga`)

**Status: in progress (2026-11-28).** Work lives only in `beat-plan/ppa-aware-coding-loop/`.

- Inputs named in the brief were **not in this checkout**: `STRATEGY.md`, `BEAT_PLAN.md`,
  `HANDOFF.md`, `beat-plan/strategy/{PPA_LOOP_PLAN,PROBLEMS_AND_IMPROVEMENTS,CLOCK_3GHZ_PLAN}.md`,
  `chip-design-skills/`, the Forge Claude pack (`forge/`, skills `forge-ppa-agent-prior-art`,
  `ppa-closing-rtl-loop`, `eda-ppa-benchmarking`) and Forge's block RTL. The repo held only the
  website (`index.html`, `CNAME`). Attaching another repo to look for them was denied. Everything
  here is built from scratch on public tools and public RTL; nothing was invented to stand in for
  Forge's blocks.
- Tools installed (free, open source): OSS CAD Suite 2026-11-26 (yosys 0.71+128, iverilog,
  verilator, sby, eqy), OpenROAD 26Q3 from nixpkgs, OpenROAD-flow-scripts tag 26Q3
  (`adeb389e`), nangate45. Reproducible with `env/install_tools.sh`.
- Six public blocks fixed before any measurement (`blocks/BLOCKS.md`): gcd, aes_cipher_top,
  riscv32i core, jpeg `dct_mac`, `dctub`, `jpeg_qnr`.
- Built: locked gate (`gate/`), flow harness (`flow/`), loop CLI + agent instructions (`loop/`).
  Gate verified: golden RTL of all six blocks PASSes; a corner-case arithmetic bug, an
  async-to-sync reset change, an `initial` block and a port change all FAIL; a bug on one
  specific 24-bit input pair passed simulation and was caught by formal (ABC dprove).
- Next: baselines (T0, T1 = 0.9·T0, references) → lock → run both arms → final evaluation →
  `results/REPORT.md`.
