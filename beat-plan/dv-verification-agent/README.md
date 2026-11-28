# Forge feature 1 of 8 — DV / verification agent (#3)

The agent takes a block's RTL, a short manifest and a Python golden model, and then:

- **writes the testbench:** a self-checking SystemVerilog testbench with generated stimulus;
- **checks bit-exactness:** every output is compared with the golden model on two
  simulators (Icarus, Verilator);
- **runs lint and structure checks:** Verilator lint and a yosys structural check;
- **measures coverage:** of the RTL and of the golden model;
- **grades its own testbench:** by injecting bugs, with every surviving bug classified by
  formal tools (yosys `equiv`, SymbiYosys).

The verdict follows the gate on the Forge page: **PASS, FAIL or INCOMPLETE. Only PASS
counts**, and no check is relaxed to get one.

## Status — 28 November 2026

| item | result | kind |
|---|---|---|
| Agent built (`dvagent/`, `./dv`) and unit-tested | 17 of 17 unit tests pass | measured: `python3 -m unittest discover -s tests` |
| Self-test on 5 stand-in blocks | **PASS** (details below) | measured: [`results/selftest/summary.md`](results/selftest/summary.md) |
| Learning loop on deliberately weak testbenches | **PASS**: 6 of 6 escapes found by formal were killed after learning | measured: [`results/learning_demo/summary.md`](results/learning_demo/summary.md) |
| **Success test on the Build 6 blocks** | **not run** | **not yet**: the Build 6 RTL is not in this checkout (see below) |

### Self-test results

Measured on 5 stand-in blocks, Icarus Verilog 13.0, Verilator 5.054, Yosys 0.71:

- **No false positives:** 15 of 15 clean runs PASS (5 blocks × 3 seeds, each on both
  simulators). 10 of 10 behaviour-preserving rewrites PASS: reordered sums, De Morgan,
  inverted muxes, explicit case items, shifts written as slices.
- **Hand-injected bugs caught:** 26 of 26 FAIL, each with a triage hint. They are typical
  RTL bugs: rounding constant one bit off, logical vs arithmetic shift, clamp bound off by
  one, zero- vs sign-extension, lane slice off by one, valid pipeline one stage short,
  ready ignoring back-pressure, accumulator not cleared, tie-break wrong, unsigned compare.
- **Automatic bugs (mutation campaign):** 322 single-point mutants, 0 failed to compile,
  274 killed (272 by the bit-exact simulation, 2 by lint/structure only). Of the 48
  survivors:
  - 45 are **formally proven equivalent** (no input can tell them apart);
  - 2 are **timing-only**: only the cycle on which a handshake happens changes; values and
    order of transactions do not;
  - 1 is **needs-review**: an asynchronous reset made synchronous, which this testbench
    cannot see;
  - **0 are escapes**, i.e. real functional differences the tests missed.

  Score = killed ÷ (compiled − proven equivalent) = 274 ÷ 277 = 98.9% (derived from the
  measured counts above).
- **A real bug caught on the first run.** The agent found an actual bug in one of the
  stand-ins I had just written (`fx_pwl`), before any bug injection: 8,191 of 65,536 outputs
  wrong. It reported "only the sign bit differs: signedness or sign extension", which was
  right. An unsigned `{...}` concatenation had silently turned `>>>` into a logical shift.
  Evidence: [`results/organic_catch_fx_pwl/`](results/organic_catch_fx_pwl/).

**What these numbers do and don't cover.** The stand-in blocks
(`selftest/fixtures/fx_*`) were written in this session only to exercise the agent. They
are **not Forge RTL and not Build 6 blocks**. The numbers above say how well the agent
works, not anything about Forge's design.

### Why the Build 6 success test was not run

This cloud session's copy of `cosmosmining/forge` holds only the public website (`CNAME`,
`index.html`). These are not in it:

- the Build 6 RTL;
- the integer model;
- `STRATEGY.md`, `BEAT_PLAN.md`, `HANDOFF.md`;
- `beat-plan/strategy/` (PPA_LOOP_PLAN, PROBLEMS_AND_IMPROVEMENTS, CLOCK_3GHZ_PLAN);
- `chip-design-skills/` and the `forge/` Claude pack (chip-verification, chip-formal,
  chip-rtl-design SKILL.md files).

None of those could be read here. I did not invent stand-ins for them; the design follows
the brief and the gate described on `index.html`. Attaching the likely source repository
(`cosmosmining/asic`) was refused by this session's permission check, and the laptop is not
connected to the session.

## Run the success test on Build 6 (on the laptop)

1. **Tools:** the OSS CAD Suite (yosys, sby, iverilog, verilator, solvers). Put its `bin` on
   `PATH`, or set `DVAGENT_TOOL_PATH`. Python 3.11+ (for `tomllib`). No Python packages are
   needed.
   ```bash
   cd ~/Desktop/startup/beat-plan/dv-verification-agent && ./dv doctor && ./dv selftest --quick
   ```
2. **For each Build 6 block**, in its own folder, e.g. `blocks/<name>/` (create it):
   - Draft the manifest from the ports, then check every line:
     ```bash
     ./dv introspect <rtl files> --top <top> --draft blocks/<name>/manifest.toml
     ```
     Ports, protocol, handshake names, `latency`, value ranges and lanes are described
     in [`templates/manifest.toml`](templates/manifest.toml).
   - Write `blocks/<name>/golden.py` by calling or transcribing the **integer model**
     (template: [`templates/golden.py`](templates/golden.py)). Never derive it from the RTL.
   - Optionally write `blocks/<name>/bugs.toml`: realistic bugs that must FAIL and
     rewrites that must PASS. Format as in `selftest/fixtures/*/bugs.toml`.
3. **Run the checks:**
   ```bash
   ./dv verify blocks/<name>/manifest.toml --seeds 1-3
   ```
   ```bash
   ./dv campaign blocks/<name>/manifest.toml --formal
   ```
   ```bash
   ./dv bugs blocks/<name>/manifest.toml blocks/<name>/bugs.toml
   ```
4. **Success** means all of the following:
   - every clean block PASSes on all seeds on both simulators (no false positives);
   - every hand-written bug FAILs and every rewrite PASSes;
   - each campaign has `escapes = 0` and `unexplained = 0`;
   - every timing-only, bounded-equivalent or needs-review survivor has been read and
     accepted by a person.

If a block uses SystemVerilog constructs that yosys cannot read, `introspect` will say so.
The fallback is to list the ports by hand in the manifest.

## What each check does and when it fails the gate

| check | tool | FAIL when |
|---|---|---|
| lint | `verilator --lint-only -Wall` | any error; any *risk* warning (WIDTH*, LATCH, MULTIDRIVEN, UNDRIVEN, CASEINCOMPLETE, unknown codes …) unless waived with a stated reason. *Style* warnings (UNUSED*, DECLFILENAME, …) fail only with `lint_strict` |
| structure | yosys `proc; flatten; check` | latch, logic loop, multiple or missing driver, async reset that does not synthesise |
| simulation | Icarus (4-state) and Verilator (random initial values) | any output beat ≠ golden; X/Z on outputs or handshakes; missing or extra outputs; inputs not all accepted; out_valid dropped or data changed before out_ready; cycle timeout; hang |
| self-check | testbench `!==` vs an independent Python compare | the two disagree → INCOMPLETE |
| coverage | Verilator line/branch/toggle on the DUT; line coverage of the golden model | below the manifest's thresholds → INCOMPLETE (default thresholds 0: report only) |
| test strength | mutation campaign; survivors classified by yosys `equiv`, sby BMC (bitwuzla), ABC PDR, trace replay, extra seeds | an escape or an unexplained survivor |

**Stimulus.** Corner values per port: range ends, 0, ±1, powers of two, 0x55/0xAA. On
top of that:

- the cross product of port corners, uniform values, and small values (which make ties,
  carries and rounding edges likely);
- every input combination when the input space is small;
- packets of length 1 and the maximum length for streams;
- random idle gaps, with junk data while `in_valid` is low;
- random `out_ready` back-pressure, including long stalls.

Inputs change 1 time unit after posedge and outputs are sampled at posedge. Every run is
seeded and reproducible.

## Commands

| command | what it does |
|---|---|
| `./dv doctor` | tool versions |
| `./dv introspect RTL… --top T [--draft M]` | ports via yosys; draft manifest |
| `./dv tbgen M [--out D]` | write the testbench and vectors only; also prints the plain `iverilog` command |
| `./dv verify M [--seeds 1-3] [--sims iverilog,verilator]` | full check → `report.md` and `report.json` per seed |
| `./dv mutants M` | list the bugs the mutation engine would inject |
| `./dv campaign M [--formal] [--max N]` | mutation campaign → `campaign.json` |
| `./dv bugs M BUGS.toml` | hand-written bugs (must FAIL) and rewrites (must PASS) |
| `./dv equiv M --gate RTL…` | is a changed RTL equivalent to the manifest's RTL? (yosys `equiv`, then sby) |
| `./dv selftest [--quick] [--learning-demo]` | the agent's own success test |

Exit status: 0 = everything as expected, 1 = FAIL, 2 = INCOMPLETE or usage error.

## Files

```
dv                 launcher (python3 -m dvagent works too)
SKILL.md           Claude skill: how an agent drives this tool, rules, triage table
dvagent/
  manifest.py      manifest loading and validation (waivers need a reason)
  introspect.py    ports via yosys write_json; draft manifests
  stimulus.py      corner / uniform / small / exhaustive / packets / gaps / back-pressure
  golden.py        load + run golden models, golden-model line coverage, range checks
  gm.py            bit-accurate helpers for golden models (sign, wrap, lanes, rounding, saturation)
  tbgen.py         self-checking testbench writer (comb / pipe / stream)
  sim.py           Icarus and Verilator runners
  compare.py       independent bit-exact compare with triage hints
  lint.py          Verilator lint (risk/style classes, waivers), yosys structural check
  coverage.py      Verilator coverage restricted to DUT files
  verify.py        one verification run -> verdict + report
  vlex.py          Verilog lexer (exact offsets; skips comments, strings, directives)
  mutate.py        mutation operators (AOR LOR ROR SOR UOD CR SLICE TERN IFN STMT EDGE SGN)
  campaign.py      mutation campaigns and hand-written bug runs
  formal.py        yosys equiv, sby wrappers (lockstep and transaction-level), trace replay
  selftest.py      the agent's own success test and the learning-loop demo
selftest/fixtures/ 5 stand-in blocks (NOT Forge, NOT Build 6): RTL, golden model, manifest, bugs.toml
selftest/learning_demo/  two deliberately weak manifests for the learning-loop demo
templates/         manifest and golden-model templates for Build 6 blocks
tests/             unit tests (python3 -m unittest discover -s tests)
results/           evidence: self-test and learning-demo summaries and reports, the fx_pwl catch
```

## Decisions and deviations from the brief

- **Toolchain.** The OSS CAD Suite tarball comes from GitHub releases, which this session's
  network policy blocks (HTTP 403). I installed the same open-source tools from the Nix
  binary cache instead: Yosys 0.71, sby 0.70, Icarus 13.0, Verilator 5.054, Yices 2.7.0,
  Bitwuzla 0.9.1, Z3. On the laptop, use the OSS CAD Suite as planned. OpenROAD was not
  installed: it is not part of the OSS CAD Suite and DV does not use it. Boolector has been
  dropped from current nixpkgs.
- **Stand-in blocks.** The Build 6 RTL was absent, so the agent was exercised on five small
  blocks written for that purpose. Each file's header says it is not Forge RTL. They cover
  every testbench path:
  - combinational;
  - a pipeline with valid;
  - two valid/ready streams with `last`;
  - a fixed-latency pipeline without a handshake.
- **Formal engines (measured on the fx_mac_stream survivors).**
  - Bitwuzla finished a depth-20 BMC in about 1 s, where Yices timed out at 150 s.
  - ABC PDR proved a lockstep equivalence in 5 s, where k-induction stayed UNKNOWN.
  - The transaction-level check is sound but slow: it took 118 s to find a known bug with
    3 beats at depth 10. It is therefore opt-in (`[formal] txn_check = true`).
- **Clock-edge soundness fix.** yosys `equiv` once "proved" that changing an output
  register from `posedge clk` to `negedge clk` was harmless. Cycle-based formal tools
  update every flop once per step, so they cannot judge clock edges. Two fixes followed:
  - the testbench now changes inputs at posedge + 1 instead of at negedge, and that
    mutant is now killed by simulation;
  - edge changes are never classified by formal; a surviving one becomes `needs-review`.

## Known limits

- One clock domain. No inout ports. No SystemVerilog interfaces or classes in the port
  reader.
- Reset is applied with the clock running, so an asynchronous reset made synchronous is not
  caught; it shows up as `needs-review`.
- Throughput and latency are not checked for handshake blocks; only the values and order
  of transactions are.
- `timing-only` means:
  - formal found a cycle-level difference;
  - the replayed formal trace and 8 extra random seeds showed equal transactions.

  It is not a proof unless the opt-in transaction-level check also passes.
- `bounded-equivalent` means no difference within 20 cycles from reset. It is not a proof.
