# HANDOFF

> This checkout of `cosmosmining/forge` had no `HANDOFF.md`. This file holds **only the Feature 6 entry**, between the
> markers below. When merging into `~/Desktop/startup/HANDOFF.md`, append that block and leave the other features'
> entries alone.

<!-- FEATURE-6 BEGIN -->
## Feature 6: Benchmark harness and vendor-claim checker (2026-11-28, cloud session, branch `claude/charming-einstein-gv6wha`)

**Status: built and verified.** 59 tests pass. `python3 -m claimcheck check` reports 0 errors. The report and lint pass
the "every number is labelled" checks. All work is in `beat-plan/benchmark-harness/`, and nothing outside it was touched
except this file.

**What it is.** `beat-plan/benchmark-harness/` (Python standard library, no installs) holds:
- a claims registry where every number carries MEASURED, MODELLED or VENDOR-CLAIM (NOT-YET when no number exists), with
  source and method;
- a validator that enforces the rules, including a label lock that keeps the beat-plan figure MODELLED;
- re-derivation of arithmetic, consistency and comparability checks, and an analytical transformer model for checking
  vendor tok/s claims;
- a run-record path from benchmark logs (the only route to a MEASURED tok/s);
- a document linter for tok/s figures;
- three protocols named after the feature skills.

Start with `beat-plan/benchmark-harness/README.md`. The verdicts are in `beat-plan/benchmark-harness/out/REPORT.md`.

**Verdicts (each labelled):**
- 474,713 tok/s is MODELLED arithmetic and NOT a measurement. Its label is locked. It is NOT REPRODUCIBLE here because
  its derivation (`BEAT_PLAN.md`) was not in this checkout.
- Etched's figure of over 500,000 tok/s is a VENDOR-CLAIM and unverified (per Etched: Llama-3 70B, 8xSohu, FP8,
  2,048 in / 128 out; wording from a search summary because etched.com was unreachable).
- 474,713 vs 500,000 is NOT A MEASURED COMPARISON, and COMPARABILITY is UNVERIFIED: no conditions are known for the
  Forge figure. The ratio, 0.949 (modelled), is arithmetic only.
- Measured Forge tok/s: none, NOT-YET, because no FPGA or silicon run exists. The only Forge tok/s with a recorded basis
  is about 862 tok/s, modelled arithmetic: Qwen2.5-0.5B, one engine, batch 1, from the site's 1.16 ms per token. It is
  not comparable with Etched's figure.
- Etched's figure implies (modelled) 8.74 PFLOP/s of FP8 per Sohu chip if input+output tokens count, or 149 PFLOP/s if
  output only. Etched's own H100 baseline (a vendor claim of about 23,000 tok/s per 8xH100) is physically possible only
  with input+output counting: 20.3% versus 345% of the H100 dense FP8 peak.

**Blocked or missing (stated, not worked around):**
- Not in this checkout: `STRATEGY.md`, `BEAT_PLAN.md`, the laptop `HANDOFF.md`, `beat-plan/strategy/*`,
  `chip-design-skills/`, the `forge/` skill pack, and the SKILL.md files for forge-benchmark-rerun,
  forge-vendor-claim-check and forge-fpga-measurement. The repo holds only `index.html` and `CNAME`. Attaching another
  repo was denied, and no computer was connected.
- Network: etched.com, gwern.net, theregister.com, huggingface.co and github.com release downloads were blocked. So OSS
  CAD Suite was not installed. Instead iverilog 12.0, yosys 0.33 and verilator 5.020 came from Ubuntu packages (sby and
  openroad are unavailable there). No RTL was available or written, and no rerun was performed.

**Next (founder, on the laptop):**
1. Put the 474,713 formula, inputs and conditions from `BEAT_PLAN.md` into `beat-plan/benchmark-harness/data/claims.json`,
   then run `python3 -m claimcheck report`.
2. Run `python3 -m claimcheck lint ~/Desktop/startup` (from `beat-plan/benchmark-harness/`) to find unlabelled or
   mislabelled tok/s figures in the strategy docs.
3. Save Etched's page under `data/sources/` to verify the quote word for word.
4. First FPGA run following `protocol/FPGA_MEASUREMENT_PROTOCOL.md`.
<!-- FEATURE-6 END -->
