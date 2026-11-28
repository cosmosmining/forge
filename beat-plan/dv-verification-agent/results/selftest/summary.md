# DV agent self-test

Result: **PASS**  (251.0 s, started 2026-11-28T01:00:05)

Every number below is **measured**: printed by the tools in this run (files under this directory).
The fixtures are stand-ins written to exercise the agent. They are **not Forge RTL and not Build 6**;
these numbers say nothing about Forge's design.

Tools: yosys Yosys 0.71+post (git sha1 v0.71, Release, GNU /nix/store/ii6p6kc1brz3vycqg88q4zb4xd2dmqwp-gcc-wrapper-16.2.0/bin/g++ 16.2.0), iverilog Icarus Verilog version 13.0 (stable) (v13_0), verilator Verilator 5.054 2026-11-01 rev v5.054, sby /nix/var/nix/profiles/default/bin/sby, yices-smt2 Yices 2.7.0, z3 Z3 version 5.4.1 - 64 bit, bitwuzla 0.9.1

Seeds [1, 2, 3], simulators ['iverilog', 'verilator'], formal on.

## 1. False positives (clean RTL and behaviour-preserving rewrites must PASS)

| fixture | clean runs PASS | output beats/run | DUT line cov | DUT toggle cov | golden cov | rewrites PASS |
|---|---|---|---|---|---|---|
| fx_argmax_stream | 3/3 | 244 | 100.0% | 92.2% | 100% | 2/2 |
| fx_dot4 | 3/3 | 4024 | 100.0% | 99.9% | 100% | 2/2 |
| fx_mac_stream | 3/3 | 288 | 100.0% | 99.6% | 100% | 2/2 |
| fx_pwl | 3/3 | 65536 | 100.0% | 91.5% | 100% | 2/2 |
| fx_requant | 3/3 | 4024 | 100.0% | 87.7% | 100% | 2/2 |

## 2. Hand-written injected bugs (each must FAIL)

| fixture | bug | caught | caught by | first evidence |
|---|---|---|---|---|
| fx_argmax_stream | ties-pick-latest: ties take the latest index instead of the earliest | yes | sim:iverilog, sim:verilator | iverilog: beat 1 idx expected 0 got 0x0f (value differs: check the datapath against the golden model) |
| fx_argmax_stream | unsigned-compare: comparison done unsigned: negative values beat positive ones | yes | sim:iverilog, sim:verilator | iverilog: beat 45 idx expected 1 got 0x00 (output is zero: not updated, cleared too early, or wrong select) |
| fx_argmax_stream | count-not-reset: position counter not reset at the end of a packet | yes | sim:iverilog, sim:verilator | iverilog: beat 2 idx expected 0 got 0x0f (value differs: check the datapath against the golden model) |
| fx_argmax_stream | first-flag-not-set: next packet compares against the previous packet's maximum | yes | sim:iverilog, sim:verilator | iverilog: beat 44 max_val expected 9 got 0x7fff (RTL saturated but golden did not: clamp bound or compare wrong) |
| fx_argmax_stream | max-ignores-last-beat: the last beat can win the index but not the value | yes | sim:iverilog, sim:verilator | iverilog: beat 0 max_val expected -32768 got 0x0000 (output is zero: not updated, cleared too early, or wrong select) |
| fx_dot4 | lane1-slice-low: lane 1 of a sliced one bit low | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -1431657750 got 0xaaaaa0fa (value differs: check the datapath against the golden model) |
| fx_dot4 | lane3-zero-extended: lane 3 of b zero-extended | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -1431657750 got 0xaaaab2ea (value differs: check the datapath against the golden model) |
| fx_dot4 | valid-one-stage-short: valid pipeline one stage shorter than the data pipeline | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -1431657750 got 0xxxxxxxxx (X/Z on output: uninitialised state, missing reset, or undriven logic) |
| fx_dot4 | bias-not-registered: bias read from the live input instead of the stage-1 register | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -1431657750 got 0x1ffff83f (value differs: check the datapath against the golden model) |
| fx_dot4 | lane2-wrong-weight: lane 2 multiplies the wrong lane of b | yes | sim:iverilog, sim:verilator | iverilog: beat 1024 y expected 536883363 got 0x20002313 (value differs: check the datapath against the golden model) |
| fx_mac_stream | accumulator-not-cleared: accumulator not cleared after the last beat: packets leak into each other | yes | sim:iverilog, sim:verilator | iverilog: beat 2 acc_out expected -13589 got 0x00001ceb (value differs: check the datapath against the golden model) |
| fx_mac_stream | ready-ignores-backpressure: input accepted while the output slot is full: results are overwritten | yes | sim:iverilog, sim:verilator | iverilog: beat 3 acc_out expected -5207 got 0xffffe77a (value differs: check the datapath against the golden model) |
| fx_mac_stream | last-beat-not-added: the last beat's product is not added | yes | sim:iverilog, sim:verilator | iverilog: beat 0 acc_out expected 12288 got 0x00000000 (output is zero: not updated, cleared too early, or wrong select) |
| fx_mac_stream | valid-never-cleared: out_valid stays high after the handshake: duplicate outputs | yes | sim:iverilog, sim:verilator | iverilog: beat 1 acc_out expected 22272 got 0x00003000 (value differs: check the datapath against the golden model) |
| fx_mac_stream | product-zero-extended: negative products zero-extended into the accumulator | yes | sim:iverilog, sim:verilator | iverilog: beat 1 acc_out expected 22272 got 0x00065700 (only high bits differ: sign extension, overflow width or carry) |
| fx_pwl | table-entry-off-by-one: one table base value off by one | yes | sim:iverilog, sim:verilator | iverilog: beat 8192 y expected -18064 got 0xb971 (off by one: rounding constant, rounding direction or truncation) |
| fx_pwl | fraction-sign-extended: unsigned fraction treated as signed | yes | sim:iverilog, sim:verilator | iverilog: beat 4096 y expected -18032 got 0xb9d0 (value differs: check the datapath against the golden model) |
| fx_pwl | shift-seven: slope product scaled by 2**-7 instead of 2**-8 | yes | sim:iverilog, sim:verilator | iverilog: beat 65 y expected -18001 got 0xb9ae (off by one: rounding constant, rounding direction or truncation) |
| fx_pwl | segment-bits: segment index taken from the wrong bits | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -18000 got 0x0000 (output is zero: not updated, cleared too early, or wrong select) |
| fx_pwl | unsigned-concat: the bug the agent found on its first run: an unsigned concat makes >>> a logical shift | yes | sim:iverilog, sim:verilator | iverilog: beat 1 y expected -18001 got 0x39af (only the sign bit differs: signedness or sign extension) |
| fx_requant | round-constant-position: rounding constant one bit too high: 2**shift instead of 2**(shift-1) | yes | sim:iverilog, sim:verilator | iverilog: beat 5 y expected -16 got 0xf1 (off by one: rounding constant, rounding direction or truncation) |
| fx_requant | logical-shift: logical instead of arithmetic shift: negative values lose their sign | yes | sim:iverilog, sim:verilator | iverilog: beat 0 y expected -128 got 0x7f (golden value is saturated: check clamp bounds and overflow detection) |
| fx_requant | clamp-high-bound: upper clamp off by one: 128 wraps to -128 | yes | sim:iverilog, sim:verilator | iverilog: beat 561 y expected 127 got 0x80 (golden value is saturated: check clamp bounds and overflow detection) |
| fx_requant | zero-point-zero-extended: negative zero points become large positive offsets | yes | sim:iverilog, sim:verilator | iverilog: beat 4 y expected -127 got 0x7f (RTL saturated but golden did not: clamp bound or compare wrong) |
| fx_requant | shift-zero-not-special: shift = 0 not special-cased: rounding term wraps to 2**31 | yes | sim:iverilog, sim:verilator | iverilog: beat 13 y expected -128 got 0x7f (golden value is saturated: check clamp bounds and overflow detection) |
| fx_requant | multiplier-sign-extended: unsigned multiplier treated as signed | yes | sim:iverilog, sim:verilator | iverilog: beat 8 y expected -128 got 0x7f (golden value is saturated: check clamp bounds and overflow detection) |

## 3. Mutation campaign (automatic single-point bugs)

| fixture | mutants | stillborn | killed (by simulation) | survived | survivor classes | escapes | unexplained | score |
|---|---|---|---|---|---|---|---|---|
| fx_argmax_stream | 54 | 0 | 44 (43) | 10 | {'equivalent': 9, 'timing-only': 1} | 0 | 0 | 97.8% |
| fx_dot4 | 75 | 0 | 68 (68) | 7 | {'equivalent': 6, 'needs-review': 1} | 0 | 0 | 98.6% |
| fx_mac_stream | 43 | 0 | 34 (33) | 9 | {'equivalent': 8, 'timing-only': 1} | 0 | 0 | 97.1% |
| fx_pwl | 95 | 0 | 87 (87) | 8 | {'equivalent': 8} | 0 | 0 | 100.0% |
| fx_requant | 55 | 0 | 41 (41) | 14 | {'equivalent': 14} | 0 | 0 | 100.0% |

score = killed / (compiled - proven equivalent). Survivors by class:

- fx_argmax_stream L20 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_argmax_stream L31 LOR `||` -> `&&`: **timing-only** (sby cycle bmc + replay + extra seeds) cycle-level difference (formal trace); transactions equal on the replayed trace and on 8 extra random seeds
- fx_argmax_stream L38 STMT `best_idx_q <= '0;` -> `;`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L38 CR `'0` -> `'1`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L39 STMT `best_q     <= '0;` -> `;`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L39 CR `'0` -> `'1`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L42 STMT `idx        <= '0;` -> `;`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L42 CR `'0` -> `'1`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L43 STMT `max_val    <= '0;` -> `;`: **equivalent** (sby abc pdr (unbounded)) 
- fx_argmax_stream L43 CR `'0` -> `'1`: **equivalent** (sby abc pdr (unbounded)) 
- fx_dot4 L14 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L16 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L18 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L19 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L20 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L21 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_dot4 L33 EDGE `negedge` -> `posedge`: **needs-review** (none) clock/reset edge change; cycle-based formal cannot judge it and the testbench did not catch it - review by hand
- fx_mac_stream L14 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L15 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L19 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L21 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L22 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L23 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_mac_stream L29 LOR `||` -> `&&`: **timing-only** (sby cycle bmc + replay + extra seeds) cycle-level difference (formal trace); transactions equal on the replayed trace and on 8 extra random seeds
- fx_mac_stream L36 STMT `acc_out   <= '0;` -> `;`: **equivalent** (sby abc pdr (unbounded)) 
- fx_mac_stream L36 CR `'0` -> `'1`: **equivalent** (sby abc pdr (unbounded)) 
- fx_pwl L10 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L11 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L15 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L16 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L17 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L18 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L20 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_pwl L39 CR `15` -> `14`: **equivalent** (sby abc pdr (unbounded)) 
- fx_requant L10 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L13 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L14 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L16 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L17 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L20 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L21 SGN `signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L32 SGN `$signed` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L32 CR `48` -> `47`: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L33 ROR `>` -> `>=`: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L33 CR `50'sd127` -> `50'sd126`: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L35 ROR `<` -> `<=`: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L35 CR `50'sd128` -> `50'sd127`: **equivalent** (yosys equiv_simple/equiv_induct) 
- fx_requant L36 UOD `-` -> ``: **equivalent** (yosys equiv_simple/equiv_induct) 

## 4. Learning loop (formal counterexample -> new test vectors)

- fx_argmax_stream: no escapes
- fx_dot4: no escapes
- fx_mac_stream: no escapes
- fx_pwl: no escapes
- fx_requant: no escapes
