# Tools used by the Feature 5 pack

All free, open-source. Installed in the cloud session that produced `results/`
(Ubuntu 24.04, 4 cores). No accounts were created, nothing was bought, no licence was
accepted beyond the open-source ones below.

## Why not OSS CAD Suite

The brief said to install the OSS CAD Suite if tools were missing. Its releases are
binary tarballs on `github.com/YosysHQ/oss-cad-suite-build/releases`. This session's
network policy serves only git clones of public GitHub repositories, not release
downloads: `github.com` answered 403 ("GitHub access to this repository is not
enabled for this session"), and `add_repo` confirmed that only anonymous git reads are
available. So the same tools were installed from package registries the policy
allows (conda-forge, Ubuntu apt) or built from their public git repositories. To use
the suite itself, allow release downloads from `github.com` in the cloud
environment's network settings, or install it on the laptop. The flows only call
tools by name; see `flows/env.sh`.

## Versions

| Tool | Version | From | Used for |
|---|---|---|---|
| yosys, yosys-abc, yosys-smtbmc | 0.71+ (git 10084e2a1), ABC 1.01 | conda-forge `yosys-0.71-py313h2af6b36_0` | synthesis (generic, `synth_xilinx -family xcup`, ASAP7), CDC netlists, formal front end |
| Icarus Verilog | 13.0 (stable) | conda-forge `iverilog-13_0-h44a529a_1` | multi-clock simulation |
| Verilator | 5.054 (2026-11-01) | conda-forge `verilator-5.054-py312pl5321h9d6c286_0` | `-Wall` lint |
| SymbiYosys | v0.71 (git 79fc9eddca5e33a28cc2f2cd19c9825efd9a7255) | `git clone --branch v0.71 github.com/YosysHQ/sby`, `make install` into the conda env (needs python `click`, conda-forge 8.5.1) | formal proofs, covers, mutants |
| Yices 2 | 2.8.0 (git 1fbee54ad4620893f40836a50d74f91d4bf58bb4, tag yices-2.8.0) | built from `github.com/SRI-CSL/yices2` (apt: gperf, libgmp-dev) | counterexample replay for ABC engines, cover mode |
| OpenSTA | 3.2.0 (git 39f9dec68a07d658b38d7d99a493479e077c1c30) | built from `github.com/The-OpenROAD-Project/OpenSTA` with `-DBUILD_TESTS=OFF` | static timing, ASAP7 (modelled) |
| CUDD | 3.0.0 (git f54f533303640afd5dbe47a05ebeabb3066f2a25) | built from `github.com/cuddorg/cudd` (`autoreconf -fi` first) | OpenSTA dependency |
| z3 | 4.8.12 | Ubuntu 24.04 apt | tried first as the SMT solver; too slow on these models (cover stuck at step 0 for 10 minutes and exhausted memory), replaced by yices |
| micromamba | 2.3.3 (sha256 e7274528ceb9c20d048a428d6c22d7e02e268f8ffb762c4c365422347c8b8ba2) | conda-forge package file | installing the conda-forge packages |
| Python | 3.12.16 (conda env), 3.13.18 (system) | | tools/*.py (standard library only) |

OpenROAD was not installed: the only prebuilt package found (litex-hub conda channel,
`openroad 2.0_12381`, March 2024) needs Anaconda's own `defaults` channel, and
building OpenROAD from source was out of scope. Nothing in the pack needs it; it would
be the next step for placement, clock-tree synthesis and routing on ASAP7 (see
docs/ASIC_3GHZ_MODELLED.md, "not yet").

## ASAP7 inputs (modelled track only)

* Liberty files: The-OpenROAD-Project/OpenROAD-flow-scripts, commit
  8ba54e723175036fbe1a3541c7a1141cfc4f83b9, `flow/platforms/asap7/lib/NLDM`, RVT,
  TT and SS corners. SHA-256 of every file is pinned in `tools/asap7_prepare_libs.py`,
  which refuses files that do not match. Not committed to this repo.
* `flows/asic/orfs_abc_speed.script` and `flows/asic/orfs_abc_retime.script`: copied
  verbatim from the same ORFS commit (`flow/scripts/`, BSD-3-Clause).
* dont_use list, ABC driver cell (BUFx2) and load (3.898 fF), tie cells: from ORFS
  `flow/platforms/asap7/config.mk` at that commit.

## Tool problems found and how the flows handle them

| Problem | Effect | Handling |
|---|---|---|
| yosys ignores `shreg_extract="no"` | `synth_xilinx` packs a 4-deep `pipe_reg` into 8 SRL16E | RTL keeps the attribute for Vivado; open-flow pipeline experiments use `-nosrl`; `results/fpga` has an explicit SRL probe case |
| yosys `ltp -noff` does not know UltraScale+ flop primitives | depth through FDRE/FDCE would be wrong | `tools/logic_depth.py` |
| yosys 0.71 merging the five ASAP7 libraries | INVBUF cells dropped, ABC fails with "Cannot find buffer gate" | `tools/asap7_prepare_libs.py` merges the combinational libraries itself (ORFS mergeLib style) and marks dont_use in the liberty |
| ABC default script on multipliers | 8+ minutes per 16-lane datapath run | ORFS `abc_speed.script`; datapath experiment at 4 lanes on the ASIC track |
| SymbiYosys parses one task tag per `[script]` line | stacked tags reach yosys as text | one tag per variant in every `.sby` |
| SymbiYosys resolves `[files]` from the working directory | file-not-found | `flows/run_formal.sh` runs sby from `formal/` |
| OpenSTA warning STA-1212 on ASAP7 | log noise | suppressed with the ORFS rationale (intentional FAx1/HAxp5 arcs) |
