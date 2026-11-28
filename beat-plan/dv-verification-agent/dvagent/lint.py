"""Lint and structural checks.

verilator --lint-only -Wall
    errors always fail. Warnings are split into
      risk  - can change behaviour (width, latch, multidriven, comb loop, ...)
      style - cannot change behaviour (unused, file name, naming, ...)
    risk warnings fail the gate, style warnings are reported and fail only
    with checks.lint_strict = true. Unknown warning codes count as risk.
    A warning can be waived only by a manifest waiver that states a reason;
    waived warnings stay in the report.

yosys (proc; flatten; check)
    latches, logic loops, multiple or missing drivers fail the gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import tools

STYLE_CODES = {
    "DECLFILENAME", "UNUSED", "UNUSEDSIGNAL", "UNUSEDPARAM", "UNUSEDGENVAR", "UNUSEDLOOP",
    "PINCONNECTEMPTY", "VARHIDDEN", "GENUNNAMED", "EOFNEWLINE", "TIMESCALEMOD",
    "SYMRSVDWORD", "INCABSPATH", "PROCASSINIT", "DEFPARAM", "LITENDIAN", "ASCRANGE",
    "PINNOCONNECT", "IMPORTSTAR", "STATICVAR", "VARHIDDEN", "BADSTDPRAGMA", "PKGNODECL",
    "NONSTD", "PREPROCZERO", "RISEFALLDLY", "STMTDLY", "MINTYPMAXDLY", "CONSTRAINTIGN",
}
# Everything else (WIDTH*, LATCH, MULTIDRIVEN, UNDRIVEN, UNOPTFLAT, BLKSEQ, COMBDLY,
# CASEINCOMPLETE, CASEOVERLAP, SELRANGE, CMPCONST, IMPLICIT, PINMISSING, ...) is risk.

_VLINE = re.compile(r"^%(Warning|Error)(?:-([A-Z0-9_]+))?:\s*(?:([^:\s][^:]*):(\d+):(?:\d+:)?)?\s*(.*)$")


@dataclass
class Issue:
    tool: str
    code: str
    severity: str      # error | risk | style
    file: str
    line: int
    msg: str
    waived: str | None = None

    def as_dict(self):
        return {k: getattr(self, k) for k in ("tool", "code", "severity", "file", "line", "msg", "waived")}


@dataclass
class LintResult:
    tool: str
    ran: bool
    issues: list = field(default_factory=list)
    log: str = ""
    note: str = ""

    def failing(self, strict: bool) -> list:
        out = []
        for i in self.issues:
            if i.waived:
                continue
            if i.severity in ("error", "risk") or (strict and i.severity == "style"):
                out.append(i)
        return out


def _apply_waivers(issues, waivers):
    for i in issues:
        if i.severity == "error":
            continue
        for w in waivers or []:
            if str(w.get("code")) != i.code:
                continue
            match = str(w.get("match", "")).strip()
            where = f"{i.file}:{i.line} {i.msg}"
            if match and match not in where:
                continue
            i.waived = str(w.get("reason"))
            break


def _gparams(parameters: dict) -> list:
    out = []
    for k, v in (parameters or {}).items():
        if isinstance(v, bool):
            v = int(v)
        out.append(f"-G{k}={v}" if isinstance(v, int) else f'-G{k}="{v}"')
    return out


def verilator_lint(top, rtl_files, include_dirs=(), defines=None, parameters=None,
                   waivers=None, timeout_s=300) -> LintResult:
    if tools.which("verilator") is None:
        return LintResult("verilator", False, note="verilator not installed")
    cmd = ["verilator", "--lint-only", "-Wall", "--top-module", top]
    cmd += [f"-I{d}" for d in include_dirs]
    for k, v in (defines or {}).items():
        cmd.append(f"-D{k}={v}" if v not in (None, "", True) else f"-D{k}")
    cmd += _gparams(parameters) + list(rtl_files)
    r = tools.run(cmd, timeout=timeout_s)
    issues = []
    for line in r.out.splitlines():
        m = _VLINE.match(line.strip())
        if not m:
            continue
        kind, code, f, ln, msg = m.groups()
        if kind == "Error" and code is None and (msg.startswith("Exiting due to") or not f):
            if msg.startswith("Exiting due to"):
                continue
        if kind == "Error":
            sev, code = "error", code or "ERROR"
        else:
            sev = "style" if code in STYLE_CODES else "risk"
        issues.append(Issue("verilator", code, sev, f or "", int(ln or 0), msg.strip()))
    if r.timed_out:
        issues.append(Issue("verilator", "TIMEOUT", "error", "", 0, "verilator lint timed out"))
    elif r.rc != 0 and not issues:
        issues.append(Issue("verilator", "ERROR", "error", "", 0, r.out.strip()[-500:]))
    _apply_waivers(issues, waivers)
    return LintResult("verilator", True, issues, r.out)


def yosys_structural(top, rtl_files, include_dirs=(), defines=None, parameters=None,
                     timeout_s=300) -> LintResult:
    if tools.which("yosys") is None:
        return LintResult("yosys", False, note="yosys not installed")
    from .introspect import _chparams, _yosys_read_cmds
    script = "; ".join([
        _yosys_read_cmds(rtl_files, include_dirs, defines),
        f"hierarchy -check -top {top} {_chparams(parameters)}".strip(),
        "proc", "flatten", "opt_clean", "check", "stat",
    ])
    r = tools.run(["yosys", "-p", script], timeout=timeout_s)
    issues = []
    text = r.out
    for m in re.finditer(r"Latch inferred for signal `([^']*)'", text):
        issues.append(Issue("yosys", "LATCH", "risk", "", 0, f"latch inferred for {m.group(1)}"))
    for m in re.finditer(r"^ERROR:\s*(.*)$", text, re.M):
        if "Latch inferred" in m.group(1):
            continue  # always_comb latch: reported above as a LATCH risk, not a compile error
        issues.append(Issue("yosys", "ERROR", "error", "", 0, m.group(1).strip()))
    for pat, code in [(r"found logic loop", "LOGIC_LOOP"),
                      (r"multiple conflicting drivers", "MULTIDRIVEN"),
                      (r"is used but has no driver", "UNDRIVEN"),
                      (r"Drivers conflicting with a constant", "CONSTDRIVER")]:
        for m in re.finditer(r"^.*" + pat + r".*$", text, re.M):
            issues.append(Issue("yosys", code, "risk", "", 0, m.group(0).strip()[:300]))
    m = re.search(r"Found and reported (\d+) problems", text)
    if m and int(m.group(1)) > 0 and not any(i.code in ("LOGIC_LOOP", "MULTIDRIVEN", "UNDRIVEN", "CONSTDRIVER")
                                             for i in issues):
        issues.append(Issue("yosys", "CHECK", "risk", "", 0, f"yosys check reported {m.group(1)} problems"))
    latches = re.findall(r"\$_?(?:a?dlatch|dlatchsr|sr)\w*\s+(\d+)", text)
    if any(int(n) > 0 for n in latches) and not any(i.code == "LATCH" for i in issues):
        issues.append(Issue("yosys", "LATCH", "risk", "", 0, "latch cells present after proc"))
    if r.timed_out:
        issues.append(Issue("yosys", "TIMEOUT", "error", "", 0, "yosys timed out"))
    elif r.rc != 0 and not issues:
        issues.append(Issue("yosys", "ERROR", "error", "", 0, text.strip()[-500:]))
    return LintResult("yosys", True, issues, text[-20000:])
