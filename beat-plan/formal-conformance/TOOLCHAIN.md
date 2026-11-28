# Toolchain used in this checkout

**OSS CAD Suite was not installed.** Its download (GitHub release assets) was refused by this
environment's network policy (HTTP 403 from the egress proxy). The same open-source tools
were installed from package registries instead:

| Tool | Version recorded in the evidence | Source |
|---|---|---|
| yosys, SymbiYosys, yosys-smtbmc, yosys-witness | Yosys 0.71 (git sha1 b4c586fd3), sby bundled with it | PyPI `yowasp-yosys==0.71.0.0.post1285` (WebAssembly build of the YosysHQ sources) |
| z3 | 4.15.4 | PyPI `z3-solver==4.15.4.0` (the wheel ships the `z3` binary) |
| Amaranth HDL (stand-in generator only) | 0.5.10 with amaranth-yosys 0.71.0.0.post135 | PyPI |
| pytest | 9.2.0 | PyPI |
| iverilog 12.0, verilator 5.020 | installed, not used | Ubuntu 24.04 apt. The pack never simulates, and the formal flow does not need them |
| yosys 0.33, yosys-abc 0.33, z3 4.8.12 | installed, not used (see below) | Ubuntu 24.04 apt |
| OpenROAD | not installed | not needed: this feature does no place and route |

What was run:

```bash
apt-get install -y yosys yosys-abc iverilog verilator z3
python3 -m venv /opt/forge-oss-eda
/opt/forge-oss-eda/bin/pip install -r requirements.txt
FORGE_EDA_BIN=/opt/forge-oss-eda/bin ./run_all.sh
```

With OSS CAD Suite on `PATH` (the laptop setup), `forge_formal.py` uses the native
`sby` + `yosys` + `yosys-smtbmc` set automatically. `FORGE_SBY`, `FORGE_YOSYS`,
`FORGE_SMTBMC`, `FORGE_WITNESS` and `FORGE_SOLVER` override each tool.

## Tool problems found here, and what was done

1. **z3 4.8.12 (apt) hangs on the FIFO model.** It spent more than 5 minutes at step 0 of a
   71 KB SMT2 model and then died (sby: "Unexpected EOF response from solver"). z3 4.15.4
   proves the same model (basecase to step 7 in 0.58 s, induction in 0.28 s). The flow uses 4.15.4.
2. **`abc pdr` is unusable with this mix.** sby 0.71 calls `pdr -v -l`. The only standalone
   abc here is yosys-abc 0.33, which rejects `-l`, so the engine returned UNKNOWN. That was
   recorded as a tool failure, not a result. Unbounded proofs use k-induction (smtbmc).
   OSS CAD Suite ships a matching abc, so `abc pdr` can be added there as a second engine.
3. **The WebAssembly yosys only sees files under its working directory.** The tool copies
   every input into a per-job directory and passes relative paths only. That also keeps
   absolute paths out of the evidence.
