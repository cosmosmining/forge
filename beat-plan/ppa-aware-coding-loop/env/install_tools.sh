#!/usr/bin/env bash
# Reproducible install of the free, open-source tools used by the PPA-aware coding loop.
# Nothing here needs an account, a licence or money.
#
#   OSS CAD Suite 2026-11-26  -> yosys, yosys-abc, iverilog, verilator, sby, eqy (+ slang plugin)
#   OpenROAD 26Q3 (nixpkgs)   -> openroad, sta (OpenSTA 3.1.0)
#   OpenROAD-flow-scripts 26Q3 (commit adeb389e7fbf06ef6a939a895c014f69e6f7aa00)
#                             -> nangate45 platform files, flow Makefile/scripts, block sources
#
# Usage: EDA_ROOT=/opt/eda bash install_tools.sh
set -euo pipefail
EDA_ROOT=${EDA_ROOT:-/opt/eda}
mkdir -p "$EDA_ROOT"
cd "$EDA_ROOT"

# 1. OSS CAD Suite (YosysHQ nightly build of 2026-11-26)
if [ ! -x oss-cad-suite/bin/yosys ]; then
  curl -fL --retry 4 -o oss-cad-suite.tgz \
    https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-11-26/oss-cad-suite-linux-x64-20261126.tgz
  tar xzf oss-cad-suite.tgz && rm oss-cad-suite.tgz
fi

# 2. OpenROAD 26Q3 from the nixpkgs binary cache (OSS CAD Suite does not ship OpenROAD)
if [ ! -x openroad/bin/openroad ]; then
  nix build nixpkgs#openroad -o "$EDA_ROOT/openroad"
fi

# 3. OpenROAD-flow-scripts at the tag matching OpenROAD 26Q3 (sparse checkout)
if [ ! -d orfs ]; then
  git clone --depth 1 --branch 26Q3 --filter=blob:none --sparse \
    https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git orfs
  (cd orfs && git sparse-checkout set --no-cone \
     '/flow/Makefile' '/flow/scripts/' '/flow/util/' \
     '/flow/platforms/nangate45/' '/flow/platforms/common/' \
     '/flow/designs/nangate45/' '/flow/designs/src/gcd/' '/flow/designs/src/aes/' \
     '/flow/designs/src/jpeg/' '/flow/designs/src/riscv32i/' '/LICENSE')
fi
(cd orfs && test "$(git rev-parse HEAD)" = adeb389e7fbf06ef6a939a895c014f69e6f7aa00) \
  || { echo "ORFS is not at the pinned commit"; exit 1; }

echo "yosys:    $("$EDA_ROOT"/oss-cad-suite/bin/yosys -V)"
echo "openroad: $("$EDA_ROOT"/openroad/bin/openroad -version 2>&1 | tail -1)"
