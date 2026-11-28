# PnR tuning agent: batch summary

| Block | Stand-in? | Target (ns) | WNS before -> after (ns) | TNS before -> after (ns) | Hold WNS after (ns) | DRC after | Accepted edits | Equivalence | Reproduced | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| [standin_aes_250mhz](standin_aes_250mhz/LEDGER.md) | yes | 4.0 | -0.1299 -> +0.0412 | -1.3371 -> +0.0000 | +0.1444 | 0 | routing_aware_eco_repair | PASS | yes | CLOSED |
| [standin_gcd](standin_gcd/LEDGER.md) | yes | 0.485 | -0.0463 -> -0.0345 | -0.4096 -> -0.2959 | +0.0567 | 0 | routing_aware_eco_repair, faster_clock_tree, guardband_setup_repair, anneal_io_pins, enable_gate_cloning, guardband_setup_repair | PASS | yes | NOT CLOSED |
