#!/usr/bin/env bash
# run_all.sh -- the Feature 5 gate: lint, simulation, formal, CDC structure, FPGA open
# flow, ASIC 3 GHz (MODELLED), then the evidence ledger and one verdict:
# PASS / FAIL / INCOMPLETE (tools/ledger.py). Exit 0 only on PASS.
# Takes roughly 25-40 minutes on 4 cores (formal and the ASAP7 runs dominate).
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
mkdir -p results

missing=""
for t in yosys yosys-abc yosys-smtbmc sby yices-smt2 iverilog vvp verilator sta python3; do
  command -v "$t" > /dev/null 2>&1 || missing="$missing $t"
done
if [ -n "$missing" ]; then
  echo "missing tools:$missing (the steps that need them will be INCOMPLETE)"
fi

step() {  # name script
  local name=$1 script=$2 t0 rc
  t0=$(date +%s)
  "$script" > "results/step_$name.log" 2>&1
  rc=$?
  echo "step $name: exit $rc ($(( $(date +%s) - t0 )) s)"
}

step lint   flows/run_lint.sh
step sim    flows/run_sim.sh
step formal flows/run_formal.sh
step cdc    flows/run_cdc.sh
step fpga   flows/run_fpga.sh
step asic   flows/run_asic_modelled.sh

python3 tools/ledger.py --results results --out results/LEDGER.md --json results/ledger.json --missing-tools "$missing"
