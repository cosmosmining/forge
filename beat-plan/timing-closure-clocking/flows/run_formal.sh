#!/usr/bin/env bash
# run_formal.sh -- every SymbiYosys task of the Feature 5 pack.
# Usage: flows/run_formal.sh [sby-name ...]     (default: all .sby files in formal/)
# A task "matches" when its status equals the expectation written in the .sby file:
# proofs and covers must PASS, mutants (tasks tagged mutfail) must FAIL.
# Writes results/formal/<sby>_<task>.log and results/formal/summary.txt.
set -u
cd "$(dirname "$0")/.."
source flows/env.sh
OUT=results/formal
WORK=build/formal
mkdir -p "$OUT" "$WORK"
: > "$OUT/summary.txt"
fail=0

files=("$@")
if [ ${#files[@]} -eq 0 ]; then files=(async_fifo handshake pulse_sync streams); fi

for f in "${files[@]}"; do
  sbyfile="formal/$f.sby"
  tasks=$(awk '/^\[tasks\]/{t=1;next} /^\[/{t=0} t && NF {print $1}' "$sbyfile")
  for t in $tasks; do
    expect=PASS
    if awk -v t="$t" '/^\[tasks\]/{s=1;next} /^\[/{s=0} s && $1==t {for(i=2;i<=NF;i++) if($i=="mutfail") f=1} END{exit !f}' "$sbyfile"; then expect=FAIL; fi
    start=$(date +%s)
    # sby resolves [files] relative to the working directory, so run it from formal/
    ( cd formal && timeout "${FORMAL_TASK_TIMEOUT:-1800}" sby -f -d "../$WORK/${f}_$t" "$f.sby" "$t" ) > "$OUT/${f}_$t.log" 2>&1
    rc=$?
    secs=$(( $(date +%s) - start ))
    status=$(grep -oE 'DONE \((PASS|FAIL|UNKNOWN|ERROR|TIMEOUT)' "$OUT/${f}_$t.log" | tail -1 | sed 's/DONE (//')
    [ -z "$status" ] && status=ERROR
    [ $rc -eq 124 ] && status=TIMEOUT
    if [ "$status" = "$expect" ]; then verdict=MATCH; else verdict=MISMATCH; fail=1; fi
    printf "%-8s %-28s status=%-7s expected=%-4s %4ss\n" "$verdict" "${f}:$t" "$status" "$expect" "$secs" | tee -a "$OUT/summary.txt"
  done
done

n_ok=$(grep -c '^MATCH' "$OUT/summary.txt"); n_all=$(grep -cE '^(MATCH|MISMATCH)' "$OUT/summary.txt")
echo "FORMAL ${n_ok}/${n_all} tasks match expectation" | tee -a "$OUT/summary.txt"
exit $fail
