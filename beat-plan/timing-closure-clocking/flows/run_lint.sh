#!/usr/bin/env bash
# run_lint.sh -- Verilator -Wall lint and yosys elaboration of every pack module.
# Writes results/lint/summary.txt. Exit 0 only if every module is clean in both tools.
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/lint
mkdir -p "$OUT"
: > "$OUT/summary.txt"
fail=0

lint() {  # top [extra files] [-G params]
  local top=$1 extra=${2:-} gparams=${3:-}
  local tag="$top${gparams:+ $gparams}"
  local v y
  v=$(verilator --lint-only -Wall --top-module "$top" $gparams rtl/*.sv $extra 2>&1 | grep -cE '%(Warning|Error)')
  y=$(yosys -q -p "read_verilog -sv rtl/*.sv $extra; hierarchy -check -top $top; proc" 2>&1 | grep -ciE 'error')
  if [ "$v" = 0 ] && [ "$y" = 0 ]; then echo "PASS $tag" | tee -a "$OUT/summary.txt"
  else echo "FAIL $tag (verilator issues=$v, yosys errors=$y)" | tee -a "$OUT/summary.txt"; fail=1; fi
}

for m in cdc_sync_bit cdc_reset_sync cdc_pulse_sync cdc_handshake cdc_async_fifo \
         skid_buffer sync_fifo_lutram slr_crossing pipe_reg dot_reduce; do
  lint "$m"
done
# parameter corners that change structure
lint cdc_async_fifo  "" "-GDEPTH=64 -GWIDTH=64 -GSTAGES=3"
lint slr_crossing    "" "-GFWD_STAGES=1 -GBWD_STAGES=1 -GFIFO_DEPTH=4"
lint slr_crossing    "" "-GFWD_STAGES=4 -GBWD_STAGES=4 -GFIFO_DEPTH=16"
lint pipe_reg        "" "-GSTAGES=0"
lint pipe_reg        "" "-GSTAGES=1"
lint dot_reduce      "" "-GPIPE_TREE=1 -GPIPE_OUT=3"
lint three_domain_top examples/three_domain_top.sv

n_pass=$(grep -c '^PASS' "$OUT/summary.txt"); n_all=$(wc -l < "$OUT/summary.txt")
echo "LINT ${n_pass}/${n_all} modules clean" | tee -a "$OUT/summary.txt"
exit $fail
