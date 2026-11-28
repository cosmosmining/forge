# Benchmark rerun (forge-benchmark-rerun)

> **Provenance.** The `forge-benchmark-rerun` SKILL.md was not in this checkout. This describes the `rerun` command
> built here. Reconcile it with the real SKILL.md on merge. Numbers in this file are settings or examples, not results.

## Purpose

Turn a benchmark command (an RTL token simulation, an FPGA run script, a reference run) into a run record whose numbers
trace to a saved log. That is the difference between "the site says about 580,000 cycles per token" (MEASURED as
reported, evidence not here) and a number the harness has seen being printed.

## Command

```bash
python3 -m claimcheck rerun --kind rtl-sim --run-id <id> --model <model name> --cwd <checkout that holds the testbench> --cmd "<command that runs the benchmark>" --extract cycles_per_token='<regex with one capture group>'
```

- The command runs without a shell (arguments are split shlex-style) and has a one-hour timeout.
- stdout and stderr are saved together to `runs/logs/<id>.log`, and their sha256 goes into the record's `evidence`.
- Each `--extract NAME=REGEX` takes the **last** match of its single capture group from the log. A missing match is
  reported as a problem, never filled in.
- Tool version lines (python, iverilog, yosys, verilator, sby, openroad) are captured into `toolchain`.
- `--synthetic` marks a test fixture. Synthetic records never reach reports or comparisons.

## After the run

1. Complete the record: `workload` (batch, input and output lengths) and, for FPGA runs, everything
   `protocol/FPGA_MEASUREMENT_PROTOCOL.md` requires.
2. For `rtl-sim` runs, the cycle count is MEASURED, but tokens per second needs a clock. Add
   `"clock_assumption": {"period_ns": <period>, "source": "<which timing report, at what size>"}`. The harness then
   reports tok/s at that clock as **MODELLED**, never as MEASURED.
3. Run `python3 -m claimcheck check`, then `python3 -m claimcheck report`.

## Status in this checkout

The Forge RTL, its testbench and the command that prints cycles per token are **not in this checkout**, so no rerun was
performed here. Nothing was guessed: the command and the regex must come from the real testbench. Open-source simulators
were installed for the next session (iverilog 12.0, yosys 0.33, verilator 5.020, from Ubuntu packages, because the OSS
CAD Suite download was blocked by the network policy). See `out/ENVIRONMENT.md`.

## Rules

- Never edit a log after the run. The sha256 in the record ties every number to it.
- One run record per workload. Do not average across runs inside a record. Keep the repetitions and let the report
  aggregate them.
- A failed or mismatching run is kept and marked, not deleted.
