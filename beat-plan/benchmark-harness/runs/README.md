# runs/: measured run records

This folder holds one JSON file per measured run (schema `forge-claimcheck-run/1`), plus `logs/` with the evidence
files those records hash.

**It is empty on purpose.** No Forge FPGA, silicon or rerun-able simulation run was available to this session. Nothing
here was invented, and the harness reports Forge's measured tok/s as NOT-YET.

- How to record an FPGA run: `../protocol/FPGA_MEASUREMENT_PROTOCOL.md`.
- How to capture a run from a command's log: `../protocol/BENCHMARK_RERUN.md` (`python3 -m claimcheck rerun ...`).
- Test fixtures are built in temporary directories by the test suite and are marked `"synthetic": true`. Synthetic records
  are never used in reports, even if one is copied here.
