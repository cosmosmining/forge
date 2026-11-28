# Verification of the pack

Forge Feature 5 (timing-closure / clocking pack). Every claim below has a result file;
`results/LEDGER.md` lists them with their kinds. All of this is simulation, formal
proof and static checks of RTL. Nothing has run on an FPGA or a chip.

## 1. Three methods, because each one is blind somewhere

| Method | What it sees | What it cannot see | Where |
|---|---|---|---|
| Lint (Verilator `-Wall`, yosys elaboration) | width, unused, multi-driven, elaboration errors, for every module and the structurally different parameter corners | behaviour | `flows/run_lint.sh`, `results/lint/` |
| Multi-clock simulation (Icarus) | real data through real clock ratios: 13:1 both ways, 250 vs 161 MHz, near-equal clocks with heavy jitter, synchronizer depths 2 and 3, FIFO depths 4/8/16 | metastability: zero-delay simulation changes every bit of a bus at once, so a binary pointer looks fine | `flows/run_sim.sh`, `results/sim/` |
| Formal (SymbiYosys, ABC PDR, yices) | every interleaving of the two clocks, unbounded (k-induction / IC3), with a metastability model in the synchronizers | only the properties written down; covers show they are not vacuous | `flows/run_formal.sh`, `formal/*.sby`, `results/formal/` |
| Structural CDC check (`tools/cdc_check.py`) | every flop and memory endpoint whose input cone reaches another clock domain, and every async reset pin | timing (that is the constraints' job) and function | `flows/run_cdc.sh`, `results/cdc/` |

## 2. What is proved (unbounded, any clock interleaving)

| Block | Properties |
|---|---|
| `cdc_async_fifo` (4 and 8 deep, 2 and 3 stages, metastability model on) | never more than DEPTH words; full whenever DEPTH words are held (no overflow); empty whenever none (no underflow); Gray pointers change at most one bit per step; the word read at pointer p equals the word written at pointer p (arbitrary p and value: data integrity and order); `rlevel` and `wfree` never over-report |
| `cdc_handshake` (2 and 3 stages, model on) | the n-th accepted word is delivered as the n-th word, unchanged (arbitrary n and value); at most two words in flight; an offered word is not withdrawn or changed until taken |
| `cdc_pulse_sync` (2 and 3 stages, model on) | delivered events never exceed accepted events, at most one in flight; `src_busy` is high whenever one is in flight |
| `skid_buffer` | no loss, duplication, reordering or corruption; occupancy equals the two valid bits; hold rule on the output; a consumer that is always ready never stalls the producer |
| `slr_crossing` (1+1/4, 2+2/8, 3+2/8 stages/depth) | the receive FIFO is never pushed while full; no loss, duplication, reordering or corruption; every sent word is in the pipe or in the FIFO; with a producer always valid and a consumer always ready, `s_ready` is high every cycle after BWD_STAGES (full throughput) |

Covers (reachability, so the proofs are not vacuous): the async FIFO fills and then
drains, three words / events get through the handshake and the pulse synchronizer,
and the SLR receive FIFO fills. (`skid_buffer` has a cover statement but no cover task
yet; its proof's throughput and occupancy assertions do exercise the skid register.)

## 3. Mutants: the checks have teeth

Each primitive has a test-only mutation hook (`ifdef CDC_MUTANT_*`, never defined in a
build). Each mutant must be caught:

| Mutant | Simulation | Formal | Note |
|---|---|---|---|
| FIFO full compare without the MSB inversion | caught | caught | |
| FIFO crosses binary pointers | **not caught (passes)** | caught, only with the metastability model | see finding 1 |
| handshake source does not wait for the acknowledge | caught | caught | |
| pulse synchronizer ignores busy | caught | caught | |
| skid buffer always ready | caught | caught | |
| SLR crossing reserves one entry too few (SKID-1) | caught | caught | so the margin FWD+BWD is exact, not generous |

The CDC checker has its own negative tests (unsynchronized flop, logic in front of a
synchronizer, binary bus through bit synchronizers, single-flop "synchronizer", raw
async reset, reset from another domain) and one warning test (divergent
synchronization). Each must produce its named error.

## 4. Findings worth keeping

1. **Binary pointers do not break a FIFO's full/empty flags, they break its levels.**
   With registered, equality-compared flags, a synchronized pointer that is garbage for
   one cycle can enable at most one extra push or pop, and the real pointer has just
   moved by one, so the flags stay safe; the proof shows exactly that. The binary
   mutant fails only on "rlevel never over-reports", the first place the synchronized
   pointer is used as a number. That is why the pack's FIFO exposes conservative
   `rlevel`/`wfree` (needed anyway to issue bursts) and proves them. RTL simulation
   cannot see any of this (the binary mutant passes all simulations), and neither can
   formal without a metastability model (the `mut_binptr_nometa` control task passes).
2. **The first handshake proof failed, and the bug was in the property**: a `$past()`
   in a destination-clock block read an undefined value at the first edge. Fixed with
   a destination-clock "past valid" flag. The design was not changed.
3. **z3 4.8.12 was not usable for these models** (a FIFO cover sat at step 0 for ten
   minutes and the run exhausted memory); yices 2.8.0 does the same covers in under a
   second.
4. **Re-verification after the 3 GHz timing fix**: the FIFO and SLR changes
   (registered pointer conversion, registered flags) were re-run through lint, all
   simulations and every formal task before their timing was quoted.

## 5. Not covered

* Gate-level simulation with SDF timing, and real metastability (needs a physical
  model; the formal model is the substitute).
* Vivado `report_cdc` and Questa/JasperGold-class CDC signoff (not available).
* Resetting one side of a FIFO while the other side runs (not supported; stated in the
  RTL).
* The Forge engine's own crossings (its RTL is not in this checkout).
