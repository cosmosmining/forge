# Forge benchmark harness and vendor-claim checker (feature 6)

`claimcheck` keeps every Forge performance number honest. Each number carries exactly one label, **MEASURED**,
**MODELLED** or **VENDOR-CLAIM** (**NOT-YET** when no number exists), together with its source and method. The tool:

- re-derives arithmetic claims from their inputs,
- tests vendor tok/s claims (Etched-style) against an analytical transformer model,
- refuses comparisons whose conditions differ or are unknown,
- turns benchmark logs into run records, the only route to a MEASURED tok/s,
- lints documents so that no tok/s figure appears without its label, and so that the beat-plan figure is never
  called measured.

Standard library only, Python 3.9 or newer, no installs. Run every command from this folder.

```bash
python3 -m claimcheck check
python3 -m claimcheck report
python3 -m claimcheck lint ../../HANDOFF.md ../../index.html
python3 -m unittest discover -s tests -t .
```

## Current verdicts

The full, regenerated output is `out/REPORT.md`, and `out/report.json` has the same content for machines.

- **474,713 tok/s is MODELLED (arithmetic), not a measurement.** Its formula, inputs and conditions (in `BEAT_PLAN.md`
  on the laptop) are not in this checkout, so it is NOT REPRODUCIBLE here. Its label is locked: the validator refuses a
  MEASURED label for it, with or without evidence fields.
- **Etched's figure of over 500,000 tok/s is a VENDOR-CLAIM**, unverified. Per Etched: Llama-3 70B, one 8xSohu server,
  FP8, 2,048 input and 128 output tokens. Etched's page was unreachable from this session, so the wording comes from a
  search summary.
- **474,713 vs 500,000: NOT A MEASURED COMPARISON; COMPARABILITY UNVERIFIED.** The Forge figure states none of model,
  chips, precision, metric, token counting, lengths or batch. Their ratio, 0.949 (modelled), is arithmetic only.
- **Measured Forge tok/s: none (NOT-YET).** `runs/` is empty because no FPGA or silicon run exists.
- The only Forge tok/s with a recorded basis is about 862 tok/s, which is modelled arithmetic: Qwen2.5-0.5B, one engine,
  batch 1, computed as 1000 / 1.16 ms. The 1.16 ms comes from about 580,000 cycles (measured in simulation, as reported by
  the site) times the 2.0 ns clock met at reduced size. It is not comparable with Etched's figure.
- What Etched's figure implies (modelled): each Sohu chip must sustain 8.74 PFLOP/s of FP8 compute if all 2,176 tokens
  of a request are counted, or 149 PFLOP/s if only the 128 output tokens are. Etched's own 8xH100 figure (a vendor claim
  of about 23,000 tok/s) fits under the H100's dense FP8 peak only if input tokens count, so input+output is the likely
  convention.

## How it is built

| Path | What |
|---|---|
| `data/claims.json` | The registry: sources, numbers (label, source, method, conditions, formula), consistency checks, comparisons, vendor analyses |
| `data/models/*.json` | Published architectures (Llama-3-70B, Qwen2.5-0.5B) read from torchtune 0.6.1 and litgpt 0.5.13 wheels, whose hashes match PyPI, with a field-by-field cross-check |
| `claimcheck/registry.py` | The labelling rules (validator) |
| `claimcheck/formula.py` | A safe arithmetic evaluator for MODELLED derivations; registry files can never run code |
| `claimcheck/transformer.py` | FLOP, parameter, KV and weight-byte model of a decoder transformer |
| `claimcheck/checks.py` | Reproduction, consistency, comparability and vendor-claim analysis |
| `claimcheck/runs.py` | Run records, same-run measured arithmetic, `rerun` capture, toolchain versions |
| `claimcheck/lint.py` | Document lint for tok/s figures, plus the tag check for generated reports |
| `claimcheck/report.py` | `out/REPORT.md` and `out/report.json`. It refuses to write if any numeric line lacks a label tag |
| `protocol/` | FPGA measurement, benchmark rerun and vendor-claim procedures (the three feature skills) |
| `runs/` | Measured run records. Empty: nothing has been measured on hardware |
| `tests/` | 59 unit and end-to-end tests |

### The labelling rules the validator enforces

- Every number has a label, at least one known source, a method, and a unit.
- A NOT-YET entry has no value. A labelled number has a value or a formula.
- **MEASURED** needs `measured_on` (what ran) and `evidence`. Evidence that is present is checked by sha256. A number
  computed by a formula can never be MEASURED.
- **MODELLED** needs a basis (`arithmetic` or `analytical-model`). Formula inputs must resolve to registered numbers. An
  arithmetic number with no formula is flagged DERIVATION-MISSING.
- **VENDOR-CLAIM** needs `stated_by`, `claim_type` and the vendor's wording in `quote`, with a `quote_status`.
  Search-summary wording is flagged.
- **`label_lock`** pins a label. The beat-plan figure, 474,713 tok/s, is locked to MODELLED (arithmetic).
- Same-run arithmetic on a run's own measured counts (tokens ÷ seconds, joules ÷ tokens) is MEASURED. Anything that moves
  a number to other conditions (a clock, more chips, another model) is MODELLED.

## What this session could and could not do

- **Not in this checkout:** `STRATEGY.md`, `BEAT_PLAN.md`, the laptop's `HANDOFF.md`, `beat-plan/strategy/`
  (`PPA_LOOP_PLAN.md`, `PROBLEMS_AND_IMPROVEMENTS.md`, `CLOCK_3GHZ_PLAN.md`), `chip-design-skills/`, the `forge/` skill
  pack, and the three SKILL.md files. The attached repo holds only the public site (`index.html`, `CNAME`). The harness
  was built from the brief, the site's evidence ledger and public sources.
- **Network:** github.com release downloads, huggingface.co, etched.com, gwern.net and theregister.com were blocked or
  unresolvable. PyPI and Ubuntu packages were reachable.
- **EDA tools:** the OSS CAD Suite download was blocked (github.com 403). iverilog 12.0, yosys 0.33 and verilator 5.020 were
  installed from Ubuntu packages instead, and sby and openroad are not packaged there (`out/ENVIRONMENT.md`). No RTL was
  available to run, and none was written.

## Next steps (in order)

1. Copy the 474,713 derivation from `BEAT_PLAN.md` into `data/claims.json` (`formula`, `inputs`, `conditions`), then run
   `python3 -m claimcheck report`. The harness recomputes it and checks it against Etched's stated conditions.
2. Save Etched's announcement page under `data/sources/`, then set `quote_status` to `verbatim-primary` once the wording
   is checked.
3. Add sha256-pinned evidence for the site's measured numbers (proof logs, gate, timing and power reports).
4. Run `python3 -m claimcheck lint ~/Desktop/startup` on the laptop to find every unlabelled or mislabelled tok/s figure in
   the strategy docs.
5. First FPGA run following `protocol/FPGA_MEASUREMENT_PROTOCOL.md`. That produces Forge's first measured tok/s.
