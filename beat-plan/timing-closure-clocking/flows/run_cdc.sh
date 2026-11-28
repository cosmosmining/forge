#!/usr/bin/env bash
# run_cdc.sh -- structural CDC check (tools/cdc_check.py) on the pack and its tests.
# Every case states the verdict it must produce; negative tests must fail with the
# named error kind, so the checker itself is tested. Writes results/cdc/.
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/cdc
BUILD=build/cdc
mkdir -p "$OUT" "$BUILD"
: > "$OUT/summary.txt"
fail=0

# case <top> <expected PASS|FAIL> <expected kind or -> "<checker args>" <extra files...>
case_() {
  local top=$1 exp=$2 kind=$3 args=$4; shift 4
  if ! yosys -q -p "read_verilog -sv rtl/*.sv $*; hierarchy -check -top $top; proc; flatten; opt_dff; memory_collect; opt_clean; write_json $BUILD/$top.json" \
       > "$BUILD/$top.yosys.log" 2>&1; then
    echo "MISMATCH $top (yosys failed; see $BUILD/$top.yosys.log)" | tee -a "$OUT/summary.txt"; fail=1; return
  fi
  python3 tools/cdc_check.py "$BUILD/$top.json" --top "$top" $args --json "$OUT/$top.json" > "$OUT/$top.txt" 2>&1
  local line verdict ok=1
  line=$(grep -m1 '^CDC_RESULT' "$OUT/$top.txt" || echo "CDC_RESULT ERROR")
  verdict=$(echo "$line" | awk '{print $2}')
  [ "$verdict" = "$exp" ] || ok=0
  if [ "$kind" != "-" ] && ! grep -q "$kind" "$OUT/$top.txt"; then ok=0; fi
  if [ $ok = 1 ]; then tag=MATCH; else tag=MISMATCH; fail=1; fi
  printf "%-8s %-28s expected=%-4s %-20s :: %s\n" "$tag" "$top" "$exp" "$kind" "${line#CDC_RESULT }" | tee -a "$OUT/summary.txt"
}

# Pack primitives on their own (their reset ports are bridged by the caller).
case_ cdc_async_fifo  PASS - "--sync-reset wrst_n=wclk --sync-reset rrst_n=rclk"
case_ cdc_handshake   PASS - "--sync-reset rst_src_n=clk_src --sync-reset rst_dst_n=clk_dst"
case_ cdc_pulse_sync  PASS - "--sync-reset rst_src_n=clk_src --sync-reset rst_dst_n=clk_dst"
# Integration example: three clocks, every crossing through a pack primitive.
case_ three_domain_top PASS - "" examples/three_domain_top.sv
# Checker tests.
case_ cdc_pos_gray_bus          PASS -                 "" tools/cdc_tests/cdc_pos_gray_bus.sv
case_ cdc_warn_divergent        PASS divergent_sync    "" tools/cdc_tests/cdc_warn_divergent.sv
case_ cdc_neg_unsync            FAIL unsynchronized    "" tools/cdc_tests/cdc_neg_unsync.sv
case_ cdc_neg_logic_before_sync FAIL logic_before_sync "" tools/cdc_tests/cdc_neg_logic_before_sync.sv
case_ cdc_neg_binary_bus        FAIL multibit_not_gray "" tools/cdc_tests/cdc_neg_binary_bus.sv
case_ cdc_neg_short_sync        FAIL sync_too_short    "" tools/cdc_tests/cdc_neg_short_sync.sv
case_ cdc_neg_raw_reset         FAIL reset_not_bridged "" tools/cdc_tests/cdc_neg_raw_reset.sv
case_ cdc_neg_reset_cross       FAIL reset_not_bridged "" tools/cdc_tests/cdc_neg_reset_cross.sv

n_ok=$(grep -c '^MATCH' "$OUT/summary.txt"); n_all=$(grep -cE '^(MATCH|MISMATCH)' "$OUT/summary.txt")
echo "CDC ${n_ok}/${n_all} cases match expectation" | tee -a "$OUT/summary.txt"
exit $fail
