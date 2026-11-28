# FPGA measurement protocol (forge-fpga-measurement)

> **Provenance.** The `forge-fpga-measurement` SKILL.md was not in this checkout. This protocol was written from the
> feature brief and from the Forge site's stated next step: "FPGA. Tokens per second, time to first token and power from
> a real board, at batch 1, 8 and 32, with the scripts published." On merge, reconcile it with the real SKILL.md.
> Every number in this file is a protocol setting (what to run), not a result.

## Why this exists

Forge has **no measured tok/s** today. The site says "no run yet" for FPGA tokens per second and watts. The beat-plan
figure of 474,713 tok/s is arithmetic (MODELLED), not a measurement. A run that follows this protocol, recorded under
`runs/`, is the only way the harness will label a Forge tok/s figure MEASURED.

## Before the timed run

1. **Freeze the build.** Record the RTL git commit, the synthesis and implementation tools with their version lines, the
   FPGA part, the bitstream sha256, and the Fmax from the implementation timing report. The run clock must not exceed
   that Fmax. Keep the timing report as evidence.
2. **Freeze the model.** Record the model name, the weights sha256 and the integer format (weight and activation widths).
3. **Correctness first.** Run tokens through the board and compare every output token, and ideally the same
   intermediate checkpoints the simulation proof uses, with the integer model. Record `correctness.mismatches`. A run with
   mismatches is a failed run: its speed is not reported.

## The timed run

- Workloads: batch 1, 8 and 32 (the site's commitment). For each batch, two prompt/output lengths: a short one
  (128 in / 128 out) and one matching the lengths in Etched's footnote (2,048 in / 128 out). These are settings.
- Warm up, then run at least five timed repetitions per workload, and keep every repetition.
- Count tokens two ways and record both raw counts: `raw.input_tokens` and `raw.output_tokens`. The harness reports
  output-only tok/s and input+output tok/s separately. Never publish one without saying which it is, because for a
  2,048 / 128 workload the two differ by a factor of seventeen.
- Time to first token: record it per request in `raw.ttft_s`.
- Wall time: from the first request sent to the last token received, on the host clock, in `raw.wall_s`. Say whether host
  overhead (tokenization, PCIe or Ethernet transfer) is inside the window. It should be.
- Power: an external meter on the board's supply, not only on-board sensors. Record `power_meter.instrument`, its sampling
  interval and where it sits. Record `raw.power_w` samples over the timed window, and the idle power separately in
  `raw.idle_power_w`. The harness reports wall power. Idle-subtracted power is a separate, labelled number.
- Keep the full console log and the power log as evidence files with sha256.

## The run record

Write `runs/<run_id>.json` (schema `forge-claimcheck-run/1`). Template, with placeholders only:

```json
{
  "schema": "forge-claimcheck-run/1",
  "run_id": "<board>-<model>-b<batch>-<in>x<out>-<yyyymmdd>",
  "kind": "fpga",
  "date_utc": "<ISO 8601 UTC>",
  "model": {"name": "Qwen2.5-0.5B-Instruct", "key": "qwen2.5-0.5b", "weights_sha256": "<sha256>", "precision": "<integer widths>"},
  "workload": {"batch": "<int>", "s_in": "<int>", "s_out": "<int>", "requests": "<int>", "warmup_requests": "<int>"},
  "system": {"board": "<board>", "part": "<FPGA part>", "chips": "<int>", "clock_mhz": "<run clock>",
             "fmax_mhz_reported": "<from timing report>", "bitstream_sha256": "<sha256>", "rtl_commit": "<git sha>"},
  "raw": {"output_tokens": "<int>", "input_tokens": "<int>", "wall_s": "<float>",
          "ttft_s": ["<float>"], "power_w": ["<float>"], "idle_power_w": "<float>"},
  "power_meter": {"instrument": "<make and model>", "sample_interval_s": "<float>", "placement": "<supply rail>"},
  "correctness": {"compared_to": "integer model", "mismatches": "<int>", "positions_checked": "<int>"},
  "evidence": [{"path": "logs/<run_id>.log", "sha256": "<sha256>"}, {"path": "logs/<run_id>.power.csv", "sha256": "<sha256>"}],
  "toolchain": {"<tool>": "<version line printed by the tool>"},
  "synthetic": false
}
```

`python3 -m claimcheck check` validates it. An FPGA run without a board, part, clock, bitstream hash, RTL commit,
correctness result, evidence with a matching sha256, or power-meter details is refused.

## What the harness does with it

- Same-run arithmetic is labelled **MEASURED**: output tokens ÷ wall seconds, (input + output) ÷ wall seconds, mean TTFT,
  mean power, and joules per output token.
- Anything that moves the number to other conditions is labelled **MODELLED**: another clock, more boards, an ASIC.
- A comparison with a claim is made only when model, batch, input and output lengths, chip count and token counting all
  match. A Qwen2.5-0.5B FPGA run is **never** comparable with Etched's Llama-3 70B server claim, and the checker says
  NOT COMPARABLE.

## Publishing

Publish the scripts, the run records and the evidence hashes with any number taken from them, as the site promises. Use
the phrasing in `protocol/VENDOR_CLAIM_CHECK.md`.
