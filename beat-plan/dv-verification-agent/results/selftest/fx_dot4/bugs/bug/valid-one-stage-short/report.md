# DV report: fx_dot4 (fx_dot4)

**Verdict: FAIL**  (seed 1)

Reasons:
- iverilog: 4024 of 4024 output beats differ from the golden model
- iverilog: 1 output beats contain X/Z
- verilator: 4024 of 4024 output beats differ from the golden model

Stimulus: 4024 input beats -> 4024 golden output beats; sources {'directed': 0, 'formal_counterexample': 0, 'corner_sample': 1024, 'random_mix': 3000}; idle cycles 3621; stall cycles 0

| check | status | detail |
|---|---|---|
| lint | pass | errors 0, risk 0, style 0, waived 0 |
| structural | pass | errors 0, risk 0, style 0, waived 0 |
| sim iverilog | fail | beats 4024, mismatched 4024, X 1, missing 0, extra 0, 0.09 s |
| sim verilator | fail | beats 4024, mismatched 4024, X 0, missing 0, extra 0, 8.16 s |

| number | value | kind | source |
|---|---|---|---|
| golden model line coverage | 100.0% | measured | sys.settrace over golden model |
| iverilog: output beats bit-exact | 0 of 4024 | measured | run_iverilog/iverilog_out.txt |
| verilator: output beats bit-exact | 0 of 4024 | measured | run_verilator/verilator_out.txt |

First mismatches (iverilog):
- beat 0 port y: expected -1431657750, got 0xxxxxxxxx (xor None) - X/Z on output: uninitialised state, missing reset, or undriven logic
- beat 1 port y: expected 536874751, got 0xaaaaa2ea (xor 0x8aaaac15) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x20000eff (xor 0xa0005b01) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0x800055fe (xor 0x3fff95fe) - value differs: check the datapath against the golden model
- beat 4 port y: expected 2, got 0xbfffc000 (xor 0xbfffc002) - value differs: check the datapath against the golden model

First mismatches (verilator):
- beat 0 port y: expected -1431657750, got 0x9ed615f6 (xor 0x347cb71c) - value differs: check the datapath against the golden model
- beat 1 port y: expected 536874751, got 0xaaaaa2ea (xor 0x8aaaac15) - value differs: check the datapath against the golden model
- beat 2 port y: expected -2147461634, got 0x20000eff (xor 0xa0005b01) - value differs: check the datapath against the golden model
- beat 3 port y: expected -1073758208, got 0x800055fe (xor 0x3fff95fe) - value differs: check the datapath against the golden model
- beat 4 port y: expected 2, got 0xbfffc000 (xor 0xbfffc002) - value differs: check the datapath against the golden model

