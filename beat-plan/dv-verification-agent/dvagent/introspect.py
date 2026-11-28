"""Read the port list of an RTL top module (yosys JSON), and draft manifests."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass

from . import tools


@dataclass
class Port:
    name: str
    direction: str  # input | output | inout
    width: int
    signed: bool


class IntrospectError(Exception):
    pass


def _yosys_read_cmds(rtl_files, include_dirs, defines) -> str:
    flags = ["-sv"]
    for d in include_dirs:
        flags.append(f"-I{d}")
    for k, v in (defines or {}).items():
        flags.append(f"-D{k}={v}" if v not in (None, "", True) else f"-D{k}")
    q = " ".join(f'"{f}"' for f in rtl_files)
    return f"read_verilog {' '.join(flags)} {q}"


def _chparams(parameters: dict) -> str:
    out = []
    for k, v in (parameters or {}).items():
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, int):
            out.append(f"-chparam {k} {v}")
        else:
            out.append(f'-chparam {k} "{v}"')
    return " ".join(out)


def yosys_ports(rtl_files, top, include_dirs=(), defines=None, parameters=None):
    """Return ([Port], log) for module `top` after parameter overrides."""
    if tools.which("yosys") is None:
        raise IntrospectError("yosys not installed")
    with tempfile.TemporaryDirectory(prefix="dvagent_intro_") as td:
        js = os.path.join(td, "ports.json")
        script = "; ".join([
            _yosys_read_cmds(rtl_files, include_dirs, defines),
            f"hierarchy -top {top} {_chparams(parameters)}".strip(),
            "proc",
            f'write_json "{js}"',
        ])
        r = tools.run(["yosys", "-q", "-p", script], timeout=300)
        if not r.ok or not os.path.isfile(js):
            raise IntrospectError(f"yosys could not elaborate {top}:\n{r.out[-3000:]}")
        with open(js) as f:
            data = json.load(f)
    mods = data.get("modules", {})
    mod = mods.get(top)
    if mod is None:  # parameterised top may carry a $paramod name
        for name, cand in mods.items():
            if str(cand.get("attributes", {}).get("top", "0")).strip("0") == "1" or name.endswith("\\" + top):
                mod = cand
                break
    if mod is None:
        raise IntrospectError(f"top module {top} not in yosys output ({list(mods)})")
    ports = []
    for name, p in mod["ports"].items():
        ports.append(Port(name=name, direction=p["direction"], width=len(p["bits"]),
                          signed=bool(p.get("signed", 0))))
    return ports, r.out


_ANSI_PORT = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|logic|reg|var)?\s*(signed)?\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*([A-Za-z_]\w*)")


def regex_ports(rtl_text: str, top: str):
    """Fallback for simple ANSI headers with numeric widths. Best effort only."""
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b(.*?);", rtl_text, re.S)
    if not m:
        raise IntrospectError(f"module {top} not found by regex fallback")
    ports = []
    for d, s, hi, lo, name in _ANSI_PORT.findall(m.group(1)):
        width = abs(int(hi) - int(lo)) + 1 if hi else 1
        ports.append(Port(name, d, width, bool(s)))
    if not ports:
        raise IntrospectError("regex fallback found no ports")
    return ports


def ports_for_manifest(m):
    """Ports of the manifest's top, honouring per-port signedness overrides."""
    ports, _ = yosys_ports(m.rtl_paths, m.top, m.include_paths, m.defines, m.parameters)
    for p in ports:
        cfg = m.port_cfg.get(p.name, {})
        if "signed" in cfg:
            p.signed = bool(cfg["signed"])
    names = {p.name for p in ports}
    for sig in [m.clock, m.reset, m.in_valid, m.in_ready, m.out_valid, m.out_ready, m.in_last]:
        if sig and sig not in names:
            raise IntrospectError(f"interface names port {sig!r}, but {m.top} has ports {sorted(names)}")
    for p in ports:
        if p.direction == "inout":
            raise IntrospectError(f"inout port {p.name} is not supported by the testbench generator")
    return ports


# ---- draft manifest ---------------------------------------------------------

_CLK = re.compile(r"^(clk|clock|aclk|i_clk|clk_i)$", re.I)
_RST = re.compile(r"^(rst|rst_n|reset|reset_n|resetn|aresetn|areset|rst_ni|i_rst|i_rst_n)$", re.I)


def draft_manifest(rtl_files, top, include_dirs=(), defines=None, parameters=None,
                   golden="golden.py:model", base_dir: str | None = None) -> str:
    """A starting manifest from the port list. A person or agent must check it."""
    ports, _ = yosys_ports(rtl_files, top, include_dirs, defines, parameters)
    ins = [p for p in ports if p.direction == "input"]
    outs = [p for p in ports if p.direction == "output"]
    clk = next((p.name for p in ins if _CLK.match(p.name)), "")
    rst = next((p.name for p in ins if _RST.match(p.name)), "")
    low = bool(rst) and (rst.lower().endswith("n") or rst.lower().startswith("aresetn"))

    def find(cands, suffixes):
        for p in cands:
            for s in suffixes:
                if p.name.lower().endswith(s):
                    return p.name
        return ""

    in_valid = find(ins, ["in_valid", "s_valid", "valid_i", "i_valid", "in_vld", "tvalid"])
    out_ready = find(ins, ["out_ready", "m_ready", "ready_i", "o_ready_i"])
    in_ready = find(outs, ["in_ready", "s_ready", "ready_o", "tready"])
    out_valid = find(outs, ["out_valid", "m_valid", "valid_o", "o_valid", "out_vld"])
    in_last = find(ins, ["in_last", "last", "tlast", "last_i"])
    protocol = "comb" if not clk else ("stream" if (in_ready or out_ready) else "pipe")
    style = "stream" if in_last else "map"
    rel = []
    for f in rtl_files:  # manifest-relative, or absolute when that would climb far up
        r = os.path.relpath(os.path.abspath(f), base_dir or os.getcwd())
        rel.append(os.path.abspath(f) if r.split(os.sep).count("..") > 2 else r)
    lines = [
        "# DRAFT generated by `dv introspect` - check every line before trusting it.",
        "[block]",
        f'name = "{top}"',
        f'top = "{top}"',
        "rtl = [" + ", ".join(f'"{r}"' for r in rel) + "]",
        "",
        "[interface]",
        f'protocol = "{protocol}"   # comb | pipe | stream',
    ]
    if clk:
        lines += [f'clock = "{clk}"', f'reset = "{rst}"', f"reset_active_low = {str(low).lower()}",
                  "reset_cycles = 3"]
    for k, v in [("in_valid", in_valid), ("in_ready", in_ready), ("out_valid", out_valid),
                 ("out_ready", out_ready), ("in_last", in_last)]:
        if v:
            lines.append(f'{k} = "{v}"')
    if protocol == "pipe" and not out_valid:
        lines.append("latency = 1   # TODO: clock edges from input capture to output sample")
    lines += ["", "[golden]", f'model = "{golden}"   # TODO: write the golden model',
              f'style = "{style}"', "", "# Ports seen by yosys:"]
    for p in ports:
        lines.append(f"#   {p.direction:6s} {'signed ' if p.signed else ''}[{p.width}] {p.name}")
    return "\n".join(lines) + "\n"
