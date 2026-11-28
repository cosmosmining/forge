#!/usr/bin/env bash
# run_sim.sh -- multi-clock simulation matrix for the Feature 5 pack (Icarus Verilog).
# Usage: flows/run_sim.sh            (from beat-plan/timing-closure-clocking/)
# Writes results/sim/<case>.log and results/sim/summary.txt. Exit 0 only if every case
# prints "TB_RESULT PASS".
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/sim
BUILD=build/sim
mkdir -p "$OUT" "$BUILD"
: > "$OUT/summary.txt"
fail=0

run_case() {   # name top tbfile "iverilog -P params" "plusargs"
  local name=$1 top=$2 tb=$3 params=$4 plus=$5
  if ! iverilog -g2012 -Wall -Wno-timescale -Wno-implicit-dimensions -o "$BUILD/$name.vvp" -s "$top" $params rtl/*.sv "tb/$tb" > "$OUT/$name.compile.log" 2>&1; then
    echo "FAIL $name (compile; see $OUT/$name.compile.log)" | tee -a "$OUT/summary.txt"; fail=1; return
  fi
  vvp -n "$BUILD/$name.vvp" $plus > "$OUT/$name.log" 2>&1
  local line
  line=$(grep -m1 "TB_RESULT" "$OUT/$name.log" || echo "TB_RESULT FAIL no result line")
  if [[ "$line" == *"TB_RESULT PASS"* ]]; then
    echo "PASS $name :: ${line#TB_RESULT PASS }" | tee -a "$OUT/summary.txt"
  else
    echo "FAIL $name :: $line" | tee -a "$OUT/summary.txt"; fail=1
  fi
}

# Async FIFO: writer faster, reader faster, near-equal with heavy jitter, 13:1 both ways.
run_case afifo_d8_s2_w250_r161  tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=8 -Ptb_async_fifo.STAGES=2"  "+WHALF=2000 +RHALF=3100 +JIT=60 +PUSH=80 +POP=50 +SEED=11"
run_case afifo_d8_s2_rfast      tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=8 -Ptb_async_fifo.STAGES=2"  "+WHALF=2000 +RHALF=850 +JIT=50 +PUSH=90 +POP=25 +SEED=12"
run_case afifo_d16_s3_neareq    tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=16 -Ptb_async_fifo.STAGES=3" "+WHALF=1000 +RHALF=1013 +JIT=200 +PUSH=75 +POP=70 +SEED=13"
run_case afifo_d4_s2_wfast13x   tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=4 -Ptb_async_fifo.STAGES=2"  "+WHALF=500 +RHALF=6500 +JIT=30 +PUSH=50 +POP=95 +SEED=14 +N=3000"
run_case afifo_d4_s3_rfast13x   tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=4 -Ptb_async_fifo.STAGES=3"  "+WHALF=6500 +RHALF=500 +JIT=30 +PUSH=95 +POP=2 +SEED=15 +N=3000"

# Handshake and pulse synchronizer.
run_case hs_s2_sfast            tb_handshake  tb_handshake.sv  "-Ptb_handshake.STAGES=2"  "+SHALF=1000 +DHALF=1700 +JIT=40 +SEED=21"
run_case hs_s3_dfast            tb_handshake  tb_handshake.sv  "-Ptb_handshake.STAGES=3"  "+SHALF=3000 +DHALF=700 +JIT=40 +SEED=22"
run_case hs_s2_neareq           tb_handshake  tb_handshake.sv  "-Ptb_handshake.STAGES=2"  "+SHALF=1000 +DHALF=1001 +JIT=300 +SEED=23"
run_case pulse_s2_sfast         tb_pulse_sync tb_pulse_sync.sv "-Ptb_pulse_sync.STAGES=2" "+SHALF=1000 +DHALF=2300 +JIT=40 +SEED=31"
run_case pulse_s3_dfast         tb_pulse_sync tb_pulse_sync.sv "-Ptb_pulse_sync.STAGES=3" "+SHALF=2300 +DHALF=1000 +JIT=40 +SEED=32"
run_case pulse_s2_neareq        tb_pulse_sync tb_pulse_sync.sv "-Ptb_pulse_sync.STAGES=2" "+SHALF=1000 +DHALF=1000 +JIT=300 +SEED=33"

# Reset bridge.
run_case rsync_s2               tb_reset_sync tb_reset_sync.sv "-Ptb_reset_sync.STAGES=2" ""
run_case rsync_s3               tb_reset_sync tb_reset_sync.sv "-Ptb_reset_sync.STAGES=3" ""

# Valid/ready channels.
run_case skid                   tb_stream tb_stream.sv "-Ptb_stream.USE_SLR=0" "+SEED=41"
run_case slr_f1_b1_d4           tb_stream tb_stream.sv "-Ptb_stream.USE_SLR=1 -Ptb_stream.FWD_STAGES=1 -Ptb_stream.BWD_STAGES=1 -Ptb_stream.FIFO_DEPTH=4"  "+SEED=42"
run_case slr_f2_b2_d8           tb_stream tb_stream.sv "-Ptb_stream.USE_SLR=1 -Ptb_stream.FWD_STAGES=2 -Ptb_stream.BWD_STAGES=2 -Ptb_stream.FIFO_DEPTH=8"  "+SEED=43"
run_case slr_f3_b2_d8           tb_stream tb_stream.sv "-Ptb_stream.USE_SLR=1 -Ptb_stream.FWD_STAGES=3 -Ptb_stream.BWD_STAGES=2 -Ptb_stream.FIFO_DEPTH=8"  "+SEED=44"
run_case slr_f4_b4_d16          tb_stream tb_stream.sv "-Ptb_stream.USE_SLR=1 -Ptb_stream.FWD_STAGES=4 -Ptb_stream.BWD_STAGES=4 -Ptb_stream.FIFO_DEPTH=16" "+SEED=45 +READY=30"

# Pipelining variants of the stand-in datapath and the pipeline register.
run_case dot_t0_o0              tb_dot_reduce tb_dot_reduce.sv "-Ptb_dot_reduce.PIPE_TREE=0 -Ptb_dot_reduce.PIPE_OUT=0" ""
run_case dot_t1_o0              tb_dot_reduce tb_dot_reduce.sv "-Ptb_dot_reduce.PIPE_TREE=1 -Ptb_dot_reduce.PIPE_OUT=0" ""
run_case dot_t0_o3              tb_dot_reduce tb_dot_reduce.sv "-Ptb_dot_reduce.PIPE_TREE=0 -Ptb_dot_reduce.PIPE_OUT=3" ""
run_case pipe_s0                tb_pipe_reg tb_pipe_reg.sv "-Ptb_pipe_reg.STAGES=0" ""
run_case pipe_s1                tb_pipe_reg tb_pipe_reg.sv "-Ptb_pipe_reg.STAGES=1" ""
run_case pipe_s3                tb_pipe_reg tb_pipe_reg.sv "-Ptb_pipe_reg.STAGES=3" ""

n_pass=$(grep -c '^PASS' "$OUT/summary.txt"); n_all=$(wc -l < "$OUT/summary.txt")
echo "SIM ${n_pass}/${n_all} cases pass" | tee -a "$OUT/summary.txt"

# Mutants: the same testbenches must catch each injected bug (expected FAIL), except the
# binary-pointer FIFO, which zero-delay RTL simulation cannot catch (expected PASS):
# that blind spot is why the formal metastability model exists.
: > "$OUT/mutants.txt"
mut() {  # name define top tb params plus expected
  local name=$1 def=$2 top=$3 tb=$4 params=$5 plus=$6 exp=$7 got line
  iverilog -g2012 -Wno-timescale -D"$def" -o "$BUILD/mut_$name.vvp" -s "$top" $params rtl/*.sv "tb/$tb" > "$OUT/mut_$name.compile.log" 2>&1
  line=$(timeout 600 vvp -n "$BUILD/mut_$name.vvp" $plus 2>&1 | grep -m1 TB_RESULT || echo "TB_RESULT FAIL no result")
  got=FAIL; [[ "$line" == *"TB_RESULT PASS"* ]] && got=PASS
  if [ "$got" = "$exp" ]; then tag=MATCH; else tag=MISMATCH; fail=1; fi
  printf "%-8s %-18s %-34s sim=%s expected=%s\n" "$tag" "$name" "$def" "$got" "$exp" | tee -a "$OUT/mutants.txt"
}
mut afifo_full_noinv CDC_MUTANT_FULL_NOINV           tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=8" "+WHALF=2000 +RHALF=3100 +JIT=60 +PUSH=80 +POP=50 +SEED=11" FAIL
mut afifo_binptr     CDC_MUTANT_BINPTR               tb_async_fifo tb_async_fifo.sv "-Ptb_async_fifo.DEPTH=8" "+WHALF=2000 +RHALF=3100 +JIT=60 +PUSH=80 +POP=50 +SEED=11" PASS
mut hs_no_ack_wait   CDC_MUTANT_NO_ACK_WAIT          tb_handshake  tb_handshake.sv  ""                         "+SHALF=1000 +DHALF=1700 +JIT=40 +SEED=21" FAIL
mut pulse_no_busy    CDC_MUTANT_NO_BUSY              tb_pulse_sync tb_pulse_sync.sv ""                         "+SHALF=1000 +DHALF=2300 +JIT=40 +SEED=31" FAIL
mut skid_no_bp       CDC_MUTANT_SKID_NO_BACKPRESSURE tb_stream     tb_stream.sv     "-Ptb_stream.USE_SLR=0"    "+SEED=41" FAIL
mut slr_skid_short   CDC_MUTANT_SLR_SKID_SHORT       tb_stream     tb_stream.sv     "-Ptb_stream.USE_SLR=1 -Ptb_stream.FWD_STAGES=2 -Ptb_stream.BWD_STAGES=2 -Ptb_stream.FIFO_DEPTH=8" "+SEED=43" FAIL
n_ok=$(grep -c '^MATCH' "$OUT/mutants.txt")
echo "SIM_MUTANTS ${n_ok}/6 behave as expected" | tee -a "$OUT/mutants.txt"
exit $fail
