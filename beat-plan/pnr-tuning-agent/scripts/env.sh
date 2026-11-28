# source this file: puts the tools on PATH and sets the platform/test paths.
# Override PNR_TOOLS_PREFIX if setup_tools.sh installed somewhere else.
PNR_TOOLS_PREFIX="${PNR_TOOLS_PREFIX:-$HOME/.local/pnr-agent-tools}"
if [ -d /opt/eda/result ] && [ ! -d "$PNR_TOOLS_PREFIX/tools" ]; then
  # layout used in the Forge cloud session that produced RESULTS.md
  export PATH="/opt/eda/result/bin:/opt/eda/result-2/bin:/opt/eda/result-3/bin:/opt/eda/result-4/bin:$PATH"
  export OPENROAD_TEST_DIR="${OPENROAD_TEST_DIR:-/opt/eda/openroad-src/test}"
else
  for d in "$PNR_TOOLS_PREFIX"/tools*; do export PATH="$d/bin:$PATH"; done
  export OPENROAD_TEST_DIR="${OPENROAD_TEST_DIR:-$PNR_TOOLS_PREFIX/openroad-src/test}"
fi
export PNR_PLATFORM_DIR="${PNR_PLATFORM_DIR:-$OPENROAD_TEST_DIR/Nangate45}"
