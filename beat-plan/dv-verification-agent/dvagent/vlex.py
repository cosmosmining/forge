"""A small Verilog/SystemVerilog lexer for the mutation engine.

It keeps exact character offsets so a mutation is a precise text splice, and
it never looks inside comments, strings or compiler directives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Tok:
    kind: str    # ws nl comment string directive number ident sysid op
    text: str
    start: int
    end: int
    line: int
    col: int


_OPS = sorted("""<<<= >>>= <<< >>> === !== ==? !=? <-> ->> <<= >>= += -= *= /= %= &= |= ^=
** << >> <= >= == != && || ~& ~| ~^ ^~ -> ++ -- +: -: :: '{ .* @@
+ - * / % & | ^ ~ ! < > = ? : ; , . ( ) [ ] { } # @ ' $""".split(), key=len, reverse=True)

_BASED = re.compile(r"(?:\d[\d_]*\s*)?'[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ?_]+")
_UNBASED = re.compile(r"'[01xXzZ](?![0-9A-Za-z_])")
_REAL = re.compile(r"\d[\d_]*\.\d[\d_]*(?:[eE][+-]?\d+)?")
_DEC = re.compile(r"\d[\d_]*")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_SYSID = re.compile(r"\$[A-Za-z_][A-Za-z0-9_$]*")
_ESC = re.compile(r"\\\S+")
_WS = re.compile(r"[ \t\r\f\v]+")
_STR = re.compile(r'"(?:\\.|[^"\\\n])*"')
_LINE_DIRECTIVES = {"define", "timescale", "include", "default_nettype", "undef", "resetall",
                    "celldefine", "endcelldefine", "line", "pragma", "begin_keywords",
                    "end_keywords", "unconnected_drive", "nounconnected_drive"}


def tokenize(text: str) -> list:
    toks = []
    i, n, line, line_start = 0, len(text), 1, 0

    def add(kind, j):
        nonlocal i
        toks.append(Tok(kind, text[i:j], i, j, line, i - line_start + 1))
        i = j

    while i < n:
        c = text[i]
        if c == "\n":
            add("nl", i + 1)   # advances i past the newline
            line += 1
            line_start = i     # first character of the new line
            continue
        m = _WS.match(text, i)
        if m:
            add("ws", m.end())
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            add("comment", n if j < 0 else j)
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg_lines = text.count("\n", i, j)
            start_line = line
            toks.append(Tok("comment", text[i:j], i, j, start_line, i - line_start + 1))
            if seg_lines:
                line += seg_lines
                line_start = text.rfind("\n", i, j) + 1
            i = j
            continue
        if c == '"':
            m = _STR.match(text, i)
            add("string", m.end() if m else i + 1)
            continue
        if c == "`":
            m = _IDENT.match(text, i + 1)
            if m and m.group(0) in _LINE_DIRECTIVES:
                j = i
                while True:  # to end of line, following backslash continuations
                    k = text.find("\n", j)
                    if k < 0:
                        k = n
                        break
                    if text[k - 1] == "\\":
                        j = k + 1
                        continue
                    break
                seg_lines = text.count("\n", i, k)
                toks.append(Tok("directive", text[i:k], i, k, line, i - line_start + 1))
                if seg_lines:
                    line += seg_lines
                    line_start = text.rfind("\n", i, k) + 1
                i = k
                continue
            add("directive", m.end() if m else i + 1)
            continue
        m = None
        if c.isdigit() or c == "'":
            for rx in (_BASED, _UNBASED, _REAL, _DEC):
                m = rx.match(text, i)
                if m:
                    break
        if m:
            add("number", m.end())
            continue
        m = _SYSID.match(text, i)
        if m:
            add("sysid", m.end())
            continue
        m = _IDENT.match(text, i) or _ESC.match(text, i)
        if m:
            add("ident", m.end())
            continue
        for op in _OPS:
            if text.startswith(op, i):
                add("op", i + len(op))
                break
        else:
            add("op", i + 1)
    return toks


def significant(toks: list) -> list:
    return [t for t in toks if t.kind not in ("ws", "nl", "comment")]


_NUM_PARTS = re.compile(r"^(?:(\d[\d_]*)\s*)?'([sS]?)([bBoOdDhH])\s*([0-9a-fA-F_]+)$")
_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


def parse_number(text: str):
    """(size|None, signed, base_char|None, value) or None for x/z/real literals."""
    t = text.strip()
    if re.fullmatch(r"\d[\d_]*", t):
        return (None, True, None, int(t.replace("_", "")))
    if t in ("'0", "'1"):
        return (None, False, "'", int(t[1]))
    m = _NUM_PARTS.match(t)
    if not m:
        return None
    size, sgn, base, digits = m.groups()
    base = base.lower()
    try:
        value = int(digits.replace("_", ""), _BASES[base])
    except ValueError:
        return None
    return (int(size.replace("_", "")) if size else None, bool(sgn), base, value)


def format_number(size, signed, base, value) -> str:
    if base is None:
        return str(value)
    if base == "'":
        return f"'{value}"
    digits = {"b": format(value, "b"), "o": format(value, "o"), "d": str(value),
              "h": format(value, "x")}[base]
    return f"{size if size is not None else ''}'{'s' if signed else ''}{base}{digits}"
