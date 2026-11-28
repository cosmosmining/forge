# DV report: fx_pwl (fx_pwl)

**Verdict: PASS**  (seed 3)

Stimulus: 65536 input beats -> 65536 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'exhaustive': 65536}; idle cycles 0; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 1 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 65536, mismatched 0, X 0, missing 0, extra 0, 0.53 s |
| sim verilator | pass | beats 65536, mismatched 0, X 0, missing 0, extra 0, 4.85 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 65536 of 65536 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 65536 of 65536 | measured | run_verilator/verilator_out.txt |
| DUT line coverage | 100.0% (10/10 points) | measured | verilator coverage.dat |
| DUT toggle coverage | 91.5% (302/330 points) | measured | verilator coverage.dat |

