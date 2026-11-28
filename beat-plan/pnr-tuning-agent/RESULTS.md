# Results: PnR tuning agent (feature 2)

Every number below is **measured**: printed by OpenROAD / OpenSTA / Yosys, and
the file is named. Nothing here is a Build 6 result.

## The Build 6 success test: not run

The brief's success test is "closes timing on the Build 6 blocks that are
0.050 ns short of 250 MHz". This cloud copy of the repo contained no Build 6
netlists, SDCs, floorplans or reports (it held only the website), the laptop
folder was not attached, and attaching other repositories was refused. The
agent was therefore verified on two stand-ins, both public OpenROAD designs,
labeled as stand-ins in every file. Running it on Build 6 is step 1 of
"Next steps" below.

## Stand-ins

| | Stand-in A: aes at 250 MHz | Stand-in B: gcd at OpenROAD's reference clock |
|---|---|---|
| Netlist | OpenROAD `test/aes_nangate45.v` (aes_cipher_top, 16.7k instances), unmodified | OpenROAD `test/gcd_nangate45.v` (363 instances), unmodified |
| Library | Nangate45 **slow** corner (SS, 0.95 V, 125 C) | Nangate45 typical |
| Clock | **4.0 ns = 250 MHz** (Build 6's target) | 0.485 ns (OpenROAD's reference) |
| Chosen by us | the corner and the 250 MHz clock (not tuned to any miss) | nothing |
| Baseline miss after routing | (filled from ledger below) | -0.0463 ns, i.e. 9.5% of the period |

Why these: no Build 6 files were available. gcd is a *natural* near-miss
(46 ps, close to Build 6's 50 ps) but proportionally much harder (9.5% of the
period vs Build 6's 1.25%). aes at the slow corner sits at Build 6's actual
frequency with the same 45 nm library family, and its miss comes from the
same place post-route misses usually do: the optimizer closes on placement
estimates, then routing adds delay.

Calibration runs (reference flow, aes, slow corner) also showed the miss is
set by post-route degradation, not by the period: -0.187 ns at 3.6 ns,
-0.189 ns at 3.8 ns, -0.130 ns at 4.0 ns.

## Stand-in A: aes at 250 MHz, slow corner

(filled in when the run finishes)

## Stand-in B: gcd at 0.485 ns, typical corner: improved, NOT closed

Ledger: [runs/standin_gcd/LEDGER.md](runs/standin_gcd/LEDGER.md) · 32 flow
evaluations in 8 rounds, 4 min 35 s wall on 4 vCPUs.

| Independent sign-off (OpenSTA, golden SDC, RCX) | Before | After |
|---|---|---|
| Setup WNS | -0.0463 ns | **-0.0345 ns** |
| Setup TNS | -0.4096 ns | -0.2959 ns |
| Violating setup endpoints | 22 | 19 |
| Hold WNS | +0.0503 ns | +0.0567 ns |
| Routing DRC / antenna / slew-cap-fanout violations | 0 / 0 / 0 | 0 / 0 / 0 |
| Cell area | 550.1 um^2 | 599.6 um^2 (+9.0%, limit +10%) |
| Power (default activity) | 2.23 mW | 2.63 mW |

Accepted edits, in order (each validated by sign-off + guardrails): routing-aware
ECO after global route (`repair_timing` on GRT parasitics, +47 ps margin);
CTS buffers BUF_X4 -> BUF_X8; post-CTS repair guard-band +38 ps; IO pin
annealing; gate cloning on; guard-band raised to +73 ps. The final recipe was
proven logically equivalent to the golden netlist (54 points, 36 register bits)
and reproduced bit-for-bit from an empty cache.

Why it stops at -0.0345 ns: the diagnosis after the last edit has no
POST_ROUTE_DEGRADATION left. What remains is a 14-stage, 1%-wire path that
also pays 48 ps of clock insertion delay against an ideal-clock output budget.
The best rejected candidate (placement density 0.3 -> 0.45: WNS -0.0330,
TNS -0.162) was turned down only by the +10% area limit. Delay-targeted
re-synthesis (Yosys/ABC) made WNS 7x worse and was dropped after one try.
The ledger records an RTL proposal (pipeline or rebalance the cone), which
would need Forge's gate.

## How each result is checked

- **Sign-off**: a separate OpenSTA process reads only the routed netlist, the
  OpenRCX SPEF, the liberty and the golden SDC (clock periods checked equal to
  target).
- **Guardrails** on every candidate: golden inputs unchanged (sha256), routed
  with 0 DRC, legal placement, no new hold violations, no new slew/cap/fanout
  violations, antennas not worse, area within limit, optimization overlay
  whitelisted.
- **Equivalence**: Yosys proof, golden vs. routed netlist, registers matched by
  name. A one-gate mutation (NAND2 -> NOR2) is reported not equivalent
  (`tests/test_equiv_mutation.py`). Also checked on aes: 694 points / 565
  register bits proven in 53 s.
- **Reproduction**: final recipe re-run from an empty cache must match WNS,
  TNS and hold.

## Tools

OpenROAD 2.0-unstable-2025-03-01 (e794373d), OpenSTA 2.6.0, Yosys 0.55, from
nixpkgs nixos-25.11 rev b6018f87da91 (binary cache). Platform files: OpenROAD
source `test/Nangate45`. 4 vCPU / 15 GB cloud container.

## Problems found while building (kept for the record)

- OpenROAD `restructure -target timing` in this build discards every ABC result
  (delay reported as FLT_MAX), so it is wired but never proposed.
- The first "more effort" action set `repair_timing -max_passes 10`; the real
  default is 10000, so it *cut* effort. Validation rejected it (WNS -0.083 ns);
  the action was removed.
- A cache key that covered knob values but not the script generator reused a
  stale checkpoint after a script fix; the key now hashes the generator too.
- A Yosys run with `-l` (full log) wrote 58 GB; all Yosys calls now run `-q`
  with warnings-only logs and a timeout.
