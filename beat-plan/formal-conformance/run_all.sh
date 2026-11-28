#!/usr/bin/env bash
# Regenerate every result in this directory, in order:
#   stand-ins (if amaranth is installed) -> formal run -> mutation -> discover -> summary
#   -> conformance pack build -> pack verify -> leak scan of this directory -> tests
#
# Tools: OSS CAD Suite on PATH, or the PyPI builds in a venv:
#   FORGE_EDA_BIN=/opt/forge-oss-eda/bin ./run_all.sh
# A FAIL or INCOMPLETE verdict does not stop the script; the exit status reports it.
set -uo pipefail
cd "$(dirname "$0")"
if [ -n "${FORGE_EDA_BIN:-}" ]; then export PATH="$FORGE_EDA_BIN:$PATH"; fi
PY="${FORGE_PY:-python3}"
VENV_PY="${FORGE_EDA_BIN:+$FORGE_EDA_BIN/python}"
status=0
step() { echo; echo "== $*"; }

if [ -n "$VENV_PY" ] && "$VENV_PY" -c 'import amaranth' 2>/dev/null; then
  step "regenerate stand-in RTL (Amaranth stdlib)"
  "$VENV_PY" standins/generate_standins.py || status=1
fi

step "formal: structure + prove + cover"
"$PY" formal/forge_formal.py run formal/specs/*.json formal/controls/*.json || status=1

step "formal: mutation analysis"
for s in formal/specs/*.json formal/controls/*.json; do "$PY" formal/forge_formal.py mutate "$s" || status=1; done

step "inventory of RTL in the whole checkout"
"$PY" formal/forge_formal.py discover ../.. --out results/discover_checkout.json || status=1

step "summary"
"$PY" formal/forge_formal.py summarize --discover results/discover_checkout.json || status=1

step "conformance pack: build (records results, runs no simulation) and verify"
"$PY" conformance/forge_conformance.py build || status=1
"$PY" conformance/forge_conformance.py verify || status=1

step "leak scan of this whole directory"
"$PY" conformance/leak_scan.py . --allow conformance/leak_allowlist.json \
  --report results/leak_scan_feature_dir.json || status=1

if "${VENV_PY:-$PY}" -c 'import pytest' 2>/dev/null; then
  step "tests"
  "${VENV_PY:-$PY}" -m pytest -q tests || status=1
fi
echo
echo "run_all.sh exit status: $status"
exit $status
