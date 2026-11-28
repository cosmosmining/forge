# Feature 3 — PPA-aware coding loop

An agent edits RTL using **routed** (post-route) results, behind a correctness
gate it cannot change. This directory holds the loop, the gate, the flow
harness, the measured experiment and the comparison against a loop that only
sees pre-layout estimates.

Results: [`results/REPORT.md`](results/REPORT.md) (written after the run).

## How the loop works

```
          +-----------------------------+
          |  agent (Claude Code)        |  reads feedback, edits candidate RTL
          +--------------+--------------+
                         | loop.py new / edit cNN/rtl/*.v
                         v
          +-----------------------------+   LOCK.sha256 checked before every call
          |  gate  (locked)             |   lint, structure, X-aware co-simulation
          |  PASS / FAIL / INCOMPLETE   |   against the original, ABC formal proof
          +--------------+--------------+
                         | only PASS candidates may be evaluated
                         v
          +-----------------------------+
          |  feedback at T1             |   prelayout: synthesis + STA, no wires
          |  (arm decides which)        |   postroute: full ORFS flow, OpenRCX, STA
          +--------------+--------------+
                         | feedback.txt: WNS/TNS, worst paths in RTL names,
                         | load per stage, fanout, area and power vs reference
                         v
                   back to the agent  ...  loop.py final cNN
```

Two arms, identical except for the feedback:

| arm | feedback the agent may use | budget per block |
|---|---|---|
| `prelayout` | synthesis + static timing, no placement, no wires, ideal clocks | 20 pre-layout evaluations |
| `postroute` | full place and route at T1 with extracted parasitics (+ pre-layout screening) | 6 post-route + 20 pre-layout evaluations |

Both arms are judged the same way: the declared final candidate is re-gated
and run through the full flow at T1. Success for a block: setup WNS ≥ 0,
hold WNS ≥ 0, 0 DRC errors, area ≤ +5 % and power ≤ +5 % versus the references
in `targets/targets.json`.

## Directory map

| path | what | locked |
|---|---|---|
| `env/install_tools.sh` | installs OSS CAD Suite, OpenROAD 26Q3 (nix), ORFS 26Q3 | |
| `blocks/BLOCKS.md` | the six public blocks, provenance, why they were chosen | |
| `gate/` | `gate.py`, `tbgen.py`, `blocks.json` (golden hashes, stimulus, formal depth) | yes |
| `flow/` | `run_flow.py`, `sta_report.tcl`, `flow_config.json` | yes |
| `targets/` | `measure.py` (baselines), `targets.json` (T0, T1, references) | yes |
| `loop/` | `loop.py` (the agent's only entry point), `AGENT_PROMPT.md` | yes |
| `LOCK.sha256` | SHA-256 of every locked file + tool versions checked at run time | |
| `ledger/ledger.jsonl` | append-only record of every new/gate/eval/final action | |
| `candidates/<arm>/<block>/cNN/` | every candidate the agents wrote, with gate and eval reports | |
| `results/` | final evaluation, comparison, report | |

## Running it

```bash
EDA_ROOT=/opt/eda bash env/install_tools.sh
```

```bash
python3 loop/loop.py status --arm postroute --block dct_mac
```

```bash
python3 loop/loop.py new --arm postroute --block dct_mac
```

```bash
python3 loop/loop.py gate --arm postroute --block dct_mac --cand c01
```

```bash
python3 loop/loop.py eval --arm postroute --block dct_mac --cand c01 --mode postroute
```

## Putting Forge's own blocks in

1. Add the block to `gate/make_manifest.py` (top, golden files, stimulus spec,
   formal depth) and regenerate `gate/blocks.json`.
2. Add its flow settings to `flow/flow_config.json` (`clock_latency_ns: null`
   to calibrate it).
3. `python3 targets/measure.py --block NAME` → T0, T1 and references.
4. `python3 targets/combine.py` then `python3 make_lock.py`.
5. Give the agent `loop/AGENT_PROMPT.md` with its arm section filled in.

Forge's gate checks values at token checkpoints, not every cycle. For blocks
whose latency may change, the gate's simulation check would need a
transaction-level comparison mode; the six blocks here use cycle-exact
comparison only.
