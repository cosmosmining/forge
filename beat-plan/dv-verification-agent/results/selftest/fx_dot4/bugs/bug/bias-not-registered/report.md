# DV report: fx_dot4 (fx_dot4)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 3978 of 4024 output beats differ from the golden model
- verilator: 3978 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 1, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 3978, X 0, missing 0, extra 0, 0.09 s |
| sim verilator | fail | beats 4024, mismatched 3978, X 0, missing 0, extra 0, 8.16 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 46 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 46 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port y: expected -1431657750, got 0x1ffff83f (xor 0xb5555ad5) - value differs: check the datapath against the golden model
- beat 1 port y: expected 536874751, got 0x80000efe (xor 0xa0000001) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0xc0005600 (xor 0x400003fe) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0xffffc002 (xor 0x40000002) - value differs: check the datapath against the golden model
- beat 4 port y: expected 2, got 0x80000000 (xor 0x80000002) - RTL saturated but golden did not: clamp bound or compare wrong

First mismatches (verilator):
- beat 0 port y: expected -1431657750, got 0x1ffff83f (xor 0xb5555ad5) - value differs: check the datapath against the golden model
- beat 1 port y: expected 536874751, got 0x80000efe (xor 0xa0000001) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0xc0005600 (xor 0x400003fe) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0xffffc002 (xor 0x40000002) - value differs: check the datapath against the golden model
- beat 4 port y: expected 2, got 0x80000000 (xor 0x80000002) - RTL saturated but golden did not: clamp bound or compare wrong

