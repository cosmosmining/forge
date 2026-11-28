#!/usr/bin/env bash
# run_fpga.sh -- FPGA (AMD UltraScale+) checks with the open yosys synth_xilinx flow.
# This is an early, open check of mapping and logic depth, not Vivado timing:
#   * LUTRAM inference for the FIFOs (RAM32M16 / RAM64M8, not FFs, not BRAM);
#   * no SRL packing of synchronizer or SLR pipeline flops;
#   * register-to-register logic levels of the stand-in datapath, before and after
#     structural pipelining and yosys/ABC9 sequential mapping (-dff).
# Writes results/fpga/<case>.{log,depth.txt,depth.json} and results/fpga/summary.tsv.
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/fpga
BUILD=build/fpga
mkdir -p "$OUT" "$BUILD"
printf "case\ttop\tparams\topts\tLUT\tFF\tLUTRAM_cells\tSRL\tDSP\tCARRY\tmax_levels\tmax_lut_levels\tcarry_collapsed\n" > "$OUT/summary.tsv"
fail=0

run() {  # name top "chparam args" "synth options" [extra files]
  local name=$1 top=$2 params=$3 opts=$4 extra=${5:-}
  local chp=""
  [ -n "$params" ] && chp="chparam $params $top;"
  if ! yosys -p "read_verilog -sv rtl/*.sv $extra; $chp synth_xilinx -family xcup -top $top -noiopad -noclkbuf -flatten $opts; stat; write_json $BUILD/$name.json" \
       > "$OUT/$name.log" 2>&1; then
    echo "FAIL $name (yosys; see $OUT/$name.log)"; fail=1; return
  fi
  python3 tools/logic_depth.py "$BUILD/$name.json" --top "$top" --paths 1 --json "$OUT/$name.depth.json" > "$OUT/$name.depth.txt"
  python3 - "$OUT/$name.depth.json" "$name" "$top" "$params" "$opts" >> "$OUT/summary.tsv" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); c = d["cell_counts"]
s = lambda pre: sum(v for k, v in c.items() if k.startswith(pre))
lut = s("comb:LUT"); ff = s("seq:FD"); lr = s("lutram:"); srl = s("seq:SRL"); dsp = s("seq:DSP")
carry = s("comb:CARRY")
print("\t".join(map(str, [sys.argv[2], sys.argv[3], sys.argv[4] or "-", sys.argv[5] or "-", lut, ff, lr, srl, dsp, carry,
                          d["max_levels"], d["max_lut_levels"], d["max_carry_collapsed_levels"]])))
EOF
  echo "done $name"
}

# CDC primitives and FIFOs
run afifo_w64_d16   cdc_async_fifo   "-set WIDTH 64 -set DEPTH 16"  ""
run afifo_w64_d64   cdc_async_fifo   "-set WIDTH 64 -set DEPTH 64"  ""
run sfifo_w64_d16   sync_fifo_lutram "-set WIDTH 64 -set DEPTH 16"  ""
run handshake_w32   cdc_handshake    "-set WIDTH 32"                ""
run pulse_sync      cdc_pulse_sync   ""                             ""
# SLR crossing, wide
run slr_w512_f2b2   slr_crossing     "-set WIDTH 512 -set FWD_STAGES 2 -set BWD_STAGES 2 -set FIFO_DEPTH 8" ""
run skid_w512       skid_buffer      "-set WIDTH 512"               ""
# Integration example
run three_domain    three_domain_top ""                             "" examples/three_domain_top.sv
# SRL probe: yosys ignores shreg_extract="no" (Vivado honours it), so a 4-deep pipe_reg
# is packed into SRL16E here. Everything below that measures pipelining uses -nosrl.
run pipe_w8_s4_srlprobe pipe_reg   "-set WIDTH 8 -set STAGES 4"     ""
# Stand-in datapath, LUT-only (-nodsp) so the depth is visible in the fabric.
run dot_t0o0_nodsp      dot_reduce "-set PIPE_TREE 0 -set PIPE_OUT 0" "-nodsp -nosrl"
run dot_t1o0_nodsp      dot_reduce "-set PIPE_TREE 1 -set PIPE_OUT 0" "-nodsp -nosrl"
run dot_t0o3_nodsp      dot_reduce "-set PIPE_TREE 0 -set PIPE_OUT 3" "-nodsp -nosrl"
run dot_t0o3_nodsp_dff  dot_reduce "-set PIPE_TREE 0 -set PIPE_OUT 3" "-nodsp -nosrl -dff"
# ...and with DSP48E2 inference, as a real build would use. logic_depth.py treats a
# DSP48E2 as a register boundary, so the multiplier's own delay is not in these counts.
run dot_t0o0_dsp        dot_reduce "-set PIPE_TREE 0 -set PIPE_OUT 0" "-nosrl"
run dot_t1o0_dsp        dot_reduce "-set PIPE_TREE 1 -set PIPE_OUT 0" "-nosrl"

python3 -c "import sys; rows=[l.rstrip(\"\\n\").split(\"\\t\") for l in open(sys.argv[1])]; w=[max(len(r[i]) for r in rows) for i in range(len(rows[0]))]; [print(\"  \".join(c.ljust(w[i]) for i,c in enumerate(r))) for r in rows]" "$OUT/summary.tsv"
exit $fail
