# The six blocks

Forge's own block RTL (the engine's nine blocks and `llm_core`) is **not in this
checkout**, so the loop was measured on six existing, public RTL blocks. None of
this RTL was written for this experiment. The blocks were fixed on 2026-11-28,
before any baseline or loop was run, using these criteria:

1. Existing open-source RTL with a stated origin, taken unmodified from
   OpenROAD-flow-scripts (ORFS) tag `26Q3`, commit
   `adeb389e7fbf06ef6a939a895c014f69e6f7aa00`.
2. A datapath close to one of Forge's blocks where possible (multiply-accumulate,
   coefficient storage beside the multipliers, requantize = divide + round), plus
   three standard ORFS benchmark designs.
3. Small enough (0.4k–13k µm² after synthesis on nangate45) to run full place and
   route several times per block.
4. One clock and a fixed cycle-level interface, so a candidate can be checked
   cycle by cycle against the original.

| Block (top module) | Source in ORFS | Origin and licence | Pre-layout area* | Closest Forge analogue |
|---|---|---|---|---|
| `gcd` | `flow/designs/src/gcd/gcd.v` | PyMTL-generated GcdUnit, re-used from the Celerity project (ORFS README). No licence file ships with it. | 398 µm² | iterative datapath with valid/ready handshake |
| `aes_cipher_top` | `flow/designs/src/aes/` (cipher top, key expansion, rcon, sbox) | OpenCores `aes_core` (Rudolf Usselmann); BSD-style ASICS World Services licence in ORFS | 13,379 µm² | wide XOR/table datapath, 12-cycle iterative core |
| `riscv` | `flow/designs/src/riscv32i/` (21 files; not `top.v`, `dmem.v`, `rom.v`) | Single-cycle RV32I core, Oklahoma State University course (James E. Stine); Apache-2.0 | 11,569 µm² | control + ALU datapath (sequencer) |
| `dct_mac` | `flow/designs/src/jpeg/dct_mac.v` | OpenCores `video_systems` JPEG encoder (Richard Herveille); BSD-style ASICS World Services licence | 1,335 µm² | multiply-accumulate unit (int8 × int16 → 27-bit) |
| `dctub` | `flow/designs/src/jpeg/dctub.v`, `dctu.v`, `dct_mac.v`, `include/dct_cos_table.v` | same JPEG encoder | 7,679 µm² | a row of 8 MAC units, each with its coefficient table beside it |
| `jpeg_qnr` | `flow/designs/src/jpeg/jpeg_qnr.v`, `div_su.v`, `div_uu.v` | same JPEG encoder | 4,153 µm² | requantize: pipelined signed divide, then round to nearest |

\* yosys `synth` + ABC mapped to `NangateOpenCellLibrary_typical.lib`, area mode,
before any flow settings (survey numbers used only for selection).

## Notes

- `dct_mac` is also inside `dctub`. They are kept as separate blocks because the
  critical paths differ: in `dct_mac` the multiplier is fed straight from the
  input ports; in `dctub` it is fed from the coefficient-table registers, and
  eight units share the same inputs.
- The golden sources are **not copied into this repository**. The gate reads
  them from the pinned ORFS checkout and refuses to run if any SHA-256 differs
  from `gate/blocks.json`. `env/install_tools.sh` fetches that checkout.
- Candidate RTL written by the agent is a modified copy of these files. The
  original headers and licence notices stay in the files.
- Nothing about Forge's real blocks can be read off these numbers. They show
  whether the loop works, on RTL that exists and that anyone can rerun.
