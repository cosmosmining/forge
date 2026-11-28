#!/usr/bin/env bash
# run_asic_modelled.sh -- 3 GHz ASIC track. MODELLED ONLY: ASAP7 predictive 7 nm PDK,
# pre-layout (no wires, ideal clocks, no clock tree), yosys + ABC mapping, OpenSTA.
# Nothing produced here is a silicon or measured-chip result; every row is labelled
# "modelled" in results/asic_modelled/summary.tsv.
#
# Mapping follows ORFS for asap7: dfflibmap, then `abc -script abc_speed.script -constr`
# (driver BUFx2, load 3.898 fF); the retime variant first runs ORFS' `abc -dff -script
# abc_retime.script` on generic gates. Both scripts are copied verbatim from ORFS
# (flows/asic/orfs_abc_*.script, provenance in TOOLS.md).
# Env: ASAP7_LIB_DIR  ORFS flow/platforms/asap7/lib/NLDM (default: the cloud-session path)
#      CORNERS        "TT SS" by default (TT primary, SS sensitivity)
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/asic_modelled
BUILD=build/asic
LIB=build/asap7
ASAP7_LIB_DIR=${ASAP7_LIB_DIR:-/opt/eda/src/orfs/flow/platforms/asap7/lib/NLDM}
CORNERS=${CORNERS:-"TT SS"}
PERIOD=333.333          # 3 GHz, in ps
mkdir -p "$OUT" "$BUILD"

python3 tools/asap7_prepare_libs.py --src "$ASAP7_LIB_DIR" --out "$LIB" --corners $CORNERS > "$OUT/libs.txt" || {
  echo "ASAP7 libraries missing or not matching the pinned hashes; see $OUT/libs.txt"; exit 2; }
printf 'set_driving_cell BUFx2_ASAP7_75t_R\nset_load 3.898\n' > "$BUILD/abc.constr"   # ORFS asap7 ABC_DRIVER_CELL / ABC_LOAD_IN_FF

printf "label\tcase\tcorner\ttop\tparams\tclocks\tretime\trtl\tarea_um2\tflops\tcells\tworst_slack_ps\tworst_kind\tworst_path_cells\treg2reg_worst_slack_ps\tcdc_worst_slack_ps\n" > "$OUT/summary.tsv"
fail=0

run() {  # name top "chparam" "clocks" retime(0/1) [prefix]
  local name=$1 top=$2 params=$3 clocks=$4 retime=$5 rtlset=${6:-fixed}
  local files="rtl/*.sv"
  if [ "$rtlset" = prefix ]; then
    files="$(ls rtl/*.sv | grep -vE '/(cdc_async_fifo|sync_fifo_lutram)\.sv$' | tr '\n' ' ') flows/asic/prefix/*.sv"
  fi
  for C in $CORNERS; do
    local d="$BUILD/$name.$C"; mkdir -p "$d"
    local SEQ="$LIB/asap7sc7p5t_SEQ_RVT_${C}_nldm_220123.lib" COMB="$LIB/asap7sc7p5t_COMB_RVT_${C}_merged.lib"
    local chp=""; [ -n "$params" ] && chp="chparam $params $top;"
    local map="dfflibmap -liberty $SEQ; abc -script flows/asic/orfs_abc_speed.script -constr $BUILD/abc.constr -liberty $COMB;"
    if [ "$retime" = 1 ]; then
      # ORFS SYNTH_RETIME_MODULES recipe, then the normal mapping.
      map="opt -fast -full; memory_map; opt -full; techmap; abc -dff -script flows/asic/orfs_abc_retime.script; $map"
    fi
    if ! yosys -q -l "$d/yosys.log" -p "read_verilog -sv $files; $chp synth -top $top -flatten; $map opt_clean -purge; hilomap -singleton -hicell TIEHIx1_ASAP7_75t_R H -locell TIELOx1_ASAP7_75t_R L; setundef -zero; splitnets -ports; opt_clean -purge; tee -q -o $d/stat.txt stat -liberty $SEQ -liberty $COMB; write_verilog -noattr -noexpr -nohex -nodec $d/netlist.v" > /dev/null 2>&1; then
      echo "FAIL $name.$C (yosys; see $d/yosys.log)"; fail=1; continue
    fi
    STA_LIBS="$SEQ $COMB" STA_NETLIST="$d/netlist.v" STA_TOP="$top" STA_CLOCKS="$clocks" STA_PERIOD=$PERIOD \
      STA_UNCERTAINTY=0 STA_SDC=constraints/asic_3ghz_modelled.sdc STA_OUT="$d/sta" \
      timeout 900 sta -no_init -exit flows/asic/sta_block.tcl > "$d/sta.log" 2>&1
    # Every copied report carries the label in its first line.
    for pair in "sta.summary:sta.summary" "sta.worst_path.rpt:worst_path.rpt" "stat.txt:area.txt"; do
      { echo "# MODELLED -- ASAP7 predictive 7 nm PDK, RVT $C corner, 3 GHz, pre-layout (ideal clocks, no wires). Not silicon, not measured."
        cat "$d/${pair%%:*}"; } > "$OUT/$name.$C.${pair#*:}" 2>/dev/null
    done
    python3 - "$d" "$name" "$C" "$top" "$params" "$clocks" "$retime" "$rtlset" >> "$OUT/summary.tsv" <<'EOF'
import re, sys
d, name, C, top, params, clocks, retime, rtlset = sys.argv[1:]
stat = open(f"{d}/stat.txt").read()
NUM = r"[0-9.]+(?:[Ee][+-]?[0-9]+)?"          # yosys prints large areas as 1.49E+03
area = re.findall(r"Chip area for (?:module|top module) '\\?[^']*': (" + NUM + ")", stat)
cells = re.findall(r"^\s+(\d+)\s+" + NUM + r"\s+cells$", stat, re.M)
flops = sum(int(n) for n, c in re.findall(r"^\s+(\d+)\s+" + NUM + r"\s+(\S*DFF\S*)$", stat, re.M))
summ = open(f"{d}/sta.summary").read()
paths = re.findall(r"path kind=(\S+) launch=\S+ capture=\S+ slack_ps=(-?[0-9.]+) arrival_ps=\S+ cells=(\d+)", summ)
ws = min((float(s) for _, s, _ in paths), default=float("nan"))
worst = min(paths, key=lambda p: float(p[1])) if paths else ("-", "nan", "-")
r2r = min((float(s) for k, s, _ in paths if k == "reg2reg"), default=float("nan"))
cdc = min((float(s) for k, s, _ in paths if k == "cdc_max_delay"), default=float("nan"))
unclk = re.search(r"unclocked_flop_clock_pins (\d+)", summ)
if unclk and int(unclk.group(1)) != 0:
    print(f"# WARNING {name}.{C}: {unclk.group(1)} unclocked flop clock pins", file=sys.stderr)
print("\t".join(["MODELLED", name, C, top, params or "-", clocks, retime, rtlset, area[-1] if area else "nan",
                 str(flops), cells[-1] if cells else "nan", f"{ws:.2f}", worst[0], worst[2], f"{r2r:.2f}", f"{cdc:.2f}"]))
EOF
    echo "done $name.$C"
  done
}

# CDC primitives at 3 GHz on both sides (worst case), 3-stage synchronizers.
run pulse_s3                cdc_pulse_sync "-set STAGES 3"                               "clk_src clk_dst" 0
run handshake_w32_s3        cdc_handshake  "-set WIDTH 32 -set STAGES 3"                 "clk_src clk_dst" 0
run afifo_w32_d16_s3        cdc_async_fifo "-set WIDTH 32 -set DEPTH 16 -set STAGES 3"   "wclk rclk"       0
run afifo_w32_d16_s3_prefix cdc_async_fifo "-set WIDTH 32 -set DEPTH 16 -set STAGES 3"   "wclk rclk"       0 prefix
run afifo_w64_d64_s3        cdc_async_fifo "-set WIDTH 64 -set DEPTH 64 -set STAGES 3"   "wclk rclk"       0
# Valid/ready channel stages (long-route crossing on an ASIC).
run skid_w64                skid_buffer    "-set WIDTH 64"                               "clk"             0
run slr_w64_f2b2d8          slr_crossing   "-set WIDTH 64 -set FWD_STAGES 2 -set BWD_STAGES 2 -set FIFO_DEPTH 8" "clk" 0
run slr_w64_f2b2d8_prefix   slr_crossing   "-set WIDTH 64 -set FWD_STAGES 2 -set BWD_STAGES 2 -set FIFO_DEPTH 8" "clk" 0 prefix
# Stand-in datapath (NOT the Forge MAC row), 4 lanes of signed 8x8 (16 lanes took ~8
# minutes per ABC run here): pipelining and retiming at 3 GHz.
run dot4_t0o0               dot_reduce     "-set LANES 4 -set PIPE_TREE 0 -set PIPE_OUT 0" "clk"           0
run dot4_t1o0               dot_reduce     "-set LANES 4 -set PIPE_TREE 1 -set PIPE_OUT 0" "clk"           0
run dot4_t0o3               dot_reduce     "-set LANES 4 -set PIPE_TREE 0 -set PIPE_OUT 3" "clk"           0
run dot4_t0o3_retime        dot_reduce     "-set LANES 4 -set PIPE_TREE 0 -set PIPE_OUT 3" "clk"           1

# FO4 inverter delay of the library (modelled), per corner.
for C in $CORNERS; do
  STA_LIBS="$LIB/asap7sc7p5t_SEQ_RVT_${C}_nldm_220123.lib $LIB/asap7sc7p5t_COMB_RVT_${C}_merged.lib" \
    timeout 300 sta -no_init -exit flows/asic/fo4.tcl > "$BUILD/fo4.$C.log" 2>&1
  grep '^FO4' "$BUILD/fo4.$C.log" | sed "s/^/MODELLED corner=$C /" > "$OUT/fo4.$C.txt"
done

# Synchronizer stage resolution budget (modelled) and the MTBF sweep built on it.
for C in $CORNERS; do
  STA_LIBS="$LIB/asap7sc7p5t_SEQ_RVT_${C}_nldm_220123.lib $LIB/asap7sc7p5t_COMB_RVT_${C}_merged.lib" \
    timeout 300 sta -no_init -exit flows/asic/sync_stage.tcl > "$BUILD/sync_stage.$C.log" 2>&1
  grep '^SYNCSTAGE' "$BUILD/sync_stage.$C.log" | sed "s/^/MODELLED corner=$C /" > "$OUT/sync_stage.$C.txt"
done
python3 tools/mtbf_model.py --stage $(for C in $CORNERS; do echo "$OUT/sync_stage.$C.txt"; done) --json "$OUT/mtbf_model.json" > "$OUT/mtbf_model.txt"

python3 -c "import sys; rows=[l.rstrip('\n').split('\t') for l in open(sys.argv[1])]; w=[max(len(r[i]) for r in rows) for i in range(len(rows[0]))]; [print('  '.join(c.ljust(w[i]) for i,c in enumerate(r))) for r in rows]" "$OUT/summary.tsv"
cat "$OUT"/fo4.*.txt "$OUT"/sync_stage.*.txt "$OUT"/mtbf_model.txt
exit $fail
