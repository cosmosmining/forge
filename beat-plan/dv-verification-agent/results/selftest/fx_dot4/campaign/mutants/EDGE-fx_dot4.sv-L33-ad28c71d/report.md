# DV report: fx_dot4 (fx_dot4)

**Verdict: PASS**  (seed 1)

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | pass | beats 4024, mismatched 0, X 0, missing 0, extra 0, 0.09 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 4024 of 4024 | measured | run_iverilog/iverilog_out.txt |

