# env.sh -- put the pack's tools on PATH. Sourced by every flows/run_*.sh.
# These are the locations used in the cloud session that produced results/ (see
# TOOLS.md). On another machine (for example Johnson's laptop), put yosys, yosys-abc,
# yosys-smtbmc, sby, yices-smt2, iverilog, vvp, verilator and sta on PATH instead: the
# flows only call tools by name. Directories that do not exist are skipped.
for _d in /opt/eda/envs/eda/bin /opt/eda/yices/bin /opt/eda/opensta/bin; do
  if [ -d "$_d" ]; then
    case ":$PATH:" in *":$_d:"*) ;; *) PATH="$_d:$PATH" ;; esac
  fi
done
unset _d
export PATH
