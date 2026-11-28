#!/usr/bin/env bash
# Install the open-source EDA tools this agent drives, from the NixOS binary cache.
# Pinned nixpkgs: nixos-25.11 at revision b6018f87da91 (the snapshot used for every
# result in RESULTS.md): openroad 2.0-unstable-2025-03-01, yosys 0.55,
# iverilog 12.0, verilator 5.040.  Also fetches the OpenROAD source tree, whose
# test/ directory holds the Nangate45 platform files and the stand-in designs.
#
# Needs: nix (https://nixos.org/download).  Free, no account.  On macOS without
# nix, use OpenROAD-flow-scripts' docker image instead and set the same env vars.
set -euo pipefail
PREFIX="${PNR_TOOLS_PREFIX:-$HOME/.local/pnr-agent-tools}"
NIXPKGS_URL="https://releases.nixos.org/nixos/25.11/nixos-25.11.12484.b6018f87da91/nixexprs.tar.xz"
mkdir -p "$PREFIX"
cd "$PREFIX"
if [ ! -d nixpkgs ]; then
  curl -fsSL -o nixexprs.tar.xz "$NIXPKGS_URL" || \
    curl -fsSL -o nixexprs.tar.xz https://channels.nixos.org/nixos-25.11/nixexprs.tar.xz
  mkdir nixpkgs && tar -xJf nixexprs.tar.xz -C nixpkgs --strip-components=1
fi
nix-build ./nixpkgs -A openroad -A yosys -A iverilog -A verilator --out-link "$PREFIX/tools"
nix-build ./nixpkgs -A openroad.src --out-link "$PREFIX/openroad-src"
echo "Installed under $PREFIX. Now: source $(dirname "$0")/env.sh"
