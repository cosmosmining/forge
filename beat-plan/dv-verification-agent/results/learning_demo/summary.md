# Learning-loop demo

Result: **PASS**

Deliberately weak testbenches on two self-test fixtures (not Forge RTL, not Build 6). Escapes are
found by formal, their counterexamples become directed input, and the re-run must kill them while
the clean RTL still passes. All numbers measured in this run.

## weak_mac
- mutants 43, killed by the weak test 31, survivors {'equivalent': 8, 'escape': 2, 'timing-only': 2}
- escapes found by formal: 2; learned inputs: 3
- clean RTL with learned input: PASS; escapes killed after learning: 2/2
  - L28 CR `15` -> `14` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it
  - L44 STMT `acc_q     <= '0;` -> `;` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it

## weak_requant
- mutants 55, killed by the weak test 37, survivors {'equivalent': 14, 'escape': 4}
- escapes found by formal: 4; learned inputs: 4
- clean RTL with learned input: PASS; escapes killed after learning: 4/4
  - L30 CR `49'sd0` -> `49'sd1` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it
  - L30 CR `49'sd1` -> `49'sd0` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it
  - L33 CR `50'sd127` -> `50'sd128` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it
  - L35 CR `50'sd128` -> `50'sd129` (sby cycle bmc + replay): functional difference the random tests missed; the replayed trace kills it

