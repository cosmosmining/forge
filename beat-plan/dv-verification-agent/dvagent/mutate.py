"""Source-level mutation (bug injection) for Verilog / SystemVerilog RTL.

A small structural scanner finds where a mutation means something:
right-hand sides, if/case conditions, case labels, declaration initialisers,
sensitivity lists, signed declarations and assignment statements. Operators:

  AOR  binary + <-> -                     LOR  & <-> |, ^ -> |, && <-> ||
  ROR  < <-> <=, > <-> >=, == <-> !=      SOR  >>> <-> >>, << -> >>
  UOD  delete unary ~ ! -                 CR   literal +-1, '0 <-> '1
  SLICE shift a constant part-select [h:l] by +-1 (same width)
  TERN swap the arms of ?:                IFN  if (c) -> if (!(c))
  STMT delete an assignment statement     EDGE posedge <-> negedge
  SGN  delete $signed / $unsigned / the signed keyword

Each mutant changes exactly one place. Mutants that do not compile are
"stillborn" and are left out of the kill rate (see campaign.py).
"""

from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass

from . import vlex

ALWAYS_KW = {"always", "always_ff", "always_comb", "always_latch"}
DECL_KW = {"input", "output", "inout", "wire", "reg", "logic", "bit", "byte", "shortint", "int",
           "longint", "integer", "time", "real", "localparam", "parameter", "var", "tri",
           "wand", "wor", "supply0", "supply1", "const", "automatic", "static", "signed", "unsigned"}
SKIP_TO_SEMI = {"typedef", "import", "export", "timeunit", "timeprecision", "genvar", "defparam",
                "default", "assert", "assume", "cover", "restrict", "let", "bind", "alias"}
BLOCK_END = {"property": "endproperty", "sequence": "endsequence", "covergroup": "endgroup",
             "clocking": "endclocking", "class": "endclass", "specify": "endspecify",
             "checker": "endchecker", "config": "endconfig"}
ASSIGN_OPS = {"=", "<=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "<<<=", ">>>="}
OPERAND_END_KINDS = {"ident", "number", "string"}


@dataclass
class Mutant:
    id: str
    op: str
    file: str
    line: int
    col: int
    start: int
    end: int
    old: str
    new: str
    desc: str

    def apply(self, text: str) -> str:
        assert text[self.start:self.end] == self.old, f"{self.id}: source changed under the mutant"
        return text[:self.start] + self.new + text[self.end:]

    def as_dict(self):
        return {k: getattr(self, k) for k in ("id", "op", "file", "line", "col", "old", "new", "desc")}


class _Scan:
    def __init__(self, toks):
        self.t = toks
        self.n = len(toks)
        self.regions = []    # (start, end, kind): significant-token index range [start, end)
        self.ifconds = []    # (lparen, rparen)
        self.stmts = []      # (first, semicolon, kind)
        self.edges = []      # token index
        self.signed_kw = []  # token index

    def tx(self, i):
        return self.t[i].text if 0 <= i < self.n else ""

    def match_close(self, i):
        """Index just past the bracket that closes the one at i."""
        pairs = {"(": ")", "[": "]", "{": "}", "'{": "}"}
        depth = 0
        j = i
        while j < self.n:
            x = self.tx(j)
            if x in pairs:
                depth += 1
            elif x in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return self.n

    def stmt_end(self, i):
        """Index of the ';' ending the statement that starts at i (depth 0)."""
        depth = 0
        j = i
        while j < self.n:
            x = self.tx(j)
            if x in ("(", "[", "{", "'{"):
                depth += 1
            elif x in (")", "]", "}"):
                depth -= 1
            elif x == ";" and depth <= 0:
                return j
            elif depth <= 0 and x in ("endmodule", "end", "endcase", "endfunction", "endtask"):
                return j - 1 if j > i else j
            j += 1
        return self.n - 1

    def skip_to_kw(self, i, kw):
        while i < self.n and self.tx(i) != kw:
            i += 1
        return i + 1

    # ---- top level --------------------------------------------------------
    def run(self):
        i = 0
        while i < self.n:
            x = self.tx(i)
            if x in ("module", "macromodule", "interface", "program"):
                i = self.module(i)
            elif x == "package":
                i = self.items(i + 2, {"endpackage"})
            else:
                i += 1
        return self

    def module(self, i):
        end_kw = {"module": "endmodule", "macromodule": "endmodule",
                  "interface": "endinterface", "program": "endprogram"}[self.tx(i)]
        j = i + 1
        while j < self.n and self.tx(j) in ("automatic", "static"):
            j += 1
        j += 1  # module name
        while j < self.n and self.tx(j) == "import":
            j = self.stmt_end(j) + 1
        if self.tx(j) == "#":
            j = self.match_close(j + 1)
        if self.tx(j) == "(":
            close = self.match_close(j)
            for k in range(j, close):
                if self.tx(k) == "signed":
                    self.signed_kw.append(k)
            j = close
        j = self.stmt_end(j) + 1
        return self.items(j, {end_kw})

    def items(self, i, stop):
        while i < self.n and self.tx(i) not in stop:
            x = self.tx(i)
            if x in ALWAYS_KW:
                i = self.always(i)
            elif x in ("initial", "final"):
                i = self.skip_stmt(i + 1)
            elif x == "assign":
                i = self.cont_assign(i)
            elif x in DECL_KW:
                i = self.decl(i)
            elif x in ("function", "task"):
                i = self.func(i)
            elif x in ("generate", "endgenerate", "else"):
                i += 1
            elif x == "begin":
                i += 1
                if self.tx(i) == ":":
                    i += 2
            elif x == "end":
                i += 1
                if self.tx(i) == ":":
                    i += 2
            elif x in ("for", "if"):
                i = self.match_close(i + 1)          # generate header: not mutated
            elif x == "case":
                i = self.skip_to_kw(i, "endcase")
            elif x in BLOCK_END:
                i = self.skip_to_kw(i, BLOCK_END[x])
            elif x in SKIP_TO_SEMI or self.t[i].kind in ("ident", "sysid", "directive"):
                i = self.stmt_end(i) + 1 if self.t[i].kind != "directive" else i + 1
            else:
                i += 1
        return i + 1

    def skip_stmt(self, i):
        """Skip one procedural statement without recording anything."""
        x = self.tx(i)
        if x == "begin":
            depth = 0
            while i < self.n:
                y = self.tx(i)
                if y in ("begin", "fork"):
                    depth += 1
                elif y in ("end", "join", "join_any", "join_none"):
                    depth -= 1
                    if depth == 0:
                        i += 1
                        if self.tx(i) == ":":
                            i += 2
                        return i
                i += 1
            return i
        if x in ("@", "#"):
            i += 1
            if self.tx(i) == "(":
                i = self.match_close(i)
            else:
                i += 1
            return self.skip_stmt(i)
        return self.stmt_end(i) + 1

    def always(self, i):
        i += 1
        if self.tx(i) == "@":
            i += 1
            if self.tx(i) == "(":
                close = self.match_close(i)
                for k in range(i, close):
                    if self.tx(k) in ("posedge", "negedge"):
                        self.edges.append(k)
                i = close
            elif self.tx(i) in ("*", "(*)"):
                i += 1
            else:
                i += 1
        return self.stmt(i)

    def cont_assign(self, i):
        end = self.stmt_end(i)
        k = i + 1
        if self.tx(k) == "#":
            k = self.match_close(k + 1) if self.tx(k + 1) == "(" else k + 2
        depth = 0
        while k < end:
            x = self.tx(k)
            if x in ("(", "[", "{"):
                depth += 1
            elif x in (")", "]", "}"):
                depth -= 1
            elif x == "=" and depth == 0:
                break
            k += 1
        if k < end:
            self.regions.append((k + 1, end, "assign_rhs"))
            self.stmts.append((i, end, "assign"))
        return end + 1

    def decl(self, i):
        end = self.stmt_end(i)
        depth = 0
        eq = None
        for k in range(i, end):
            x = self.tx(k)
            if x in ("(", "[", "{"):
                depth += 1
            elif x in (")", "]", "}"):
                depth -= 1
            elif x == "signed" and depth == 0:
                self.signed_kw.append(k)
            elif x == "=" and depth == 0 and eq is None:
                eq = k
        if eq is not None:
            self.regions.append((eq + 1, end, "decl_init"))
        return end + 1

    def func(self, i):
        end_kw = "endfunction" if self.tx(i) == "function" else "endtask"
        j = self.stmt_end(i) + 1          # header up to ';'
        while j < self.n and self.tx(j) != end_kw:
            if self.tx(j) in DECL_KW:
                j = self.decl(j)
            else:
                j = self.stmt(j)
        j += 1
        if self.tx(j) == ":":
            j += 2
        return j

    # ---- procedural statements ----------------------------------------------
    def stmt(self, i):
        if i >= self.n:
            return i
        x = self.tx(i)
        if x == "begin":
            i += 1
            if self.tx(i) == ":":
                i += 2
            while i < self.n and self.tx(i) != "end":
                if self.tx(i) in DECL_KW:
                    i = self.decl(i)
                else:
                    nxt = self.stmt(i)
                    i = nxt if nxt > i else i + 1
            i += 1
            if self.tx(i) == ":":
                i += 2
            return i
        if x in ("unique", "unique0", "priority"):
            return self.stmt(i + 1)
        if x == "if":
            lp = i + 1
            rp = self.match_close(lp) - 1
            self.regions.append((lp + 1, rp, "cond"))
            self.ifconds.append((lp, rp))
            j = self.stmt(rp + 1)
            if self.tx(j) == "else":
                j = self.stmt(j + 1)
            return j
        if x in ("case", "casez", "casex"):
            lp = i + 1
            rp = self.match_close(lp) - 1
            self.regions.append((lp + 1, rp, "case_expr"))
            j = rp + 1
            while j < self.n and self.tx(j) != "endcase":
                if self.tx(j) == "default":
                    j += 1
                    if self.tx(j) == ":":
                        j += 1
                    j = self.stmt(j)
                    continue
                k, depth = j, 0
                while k < self.n:
                    y = self.tx(k)
                    if y in ("(", "[", "{"):
                        depth += 1
                    elif y in (")", "]", "}"):
                        depth -= 1
                    elif y == ":" and depth == 0:
                        break
                    elif y == "endcase":
                        break
                    k += 1
                if self.tx(k) != ":":
                    j = k
                    break
                self.regions.append((j, k, "case_label"))
                j = self.stmt(k + 1)
            return j + 1
        if x == "for":
            lp = i + 1
            rp = self.match_close(lp) - 1
            semis = [k for k in range(lp + 1, rp) if self.tx(k) == ";"]
            if len(semis) >= 2:
                self.regions.append((semis[0] + 1, semis[1], "for_cond"))
            return self.stmt(rp + 1)
        if x in ("while", "repeat"):
            lp = i + 1
            rp = self.match_close(lp) - 1
            return self.stmt(rp + 1)
        if x in ("forever",):
            return self.stmt(i + 1)
        if x == ";":
            return i + 1
        if x in ("@", "#", "wait", "fork"):
            return self.skip_stmt(i)
        if x == "return":
            end = self.stmt_end(i)
            self.regions.append((i + 1, end, "return"))
            return end + 1
        if self.t[i].kind == "sysid" or x in ("disable", "break", "continue", "->", "assert",
                                               "assume", "cover", "void"):
            return self.stmt_end(i) + 1
        end = self.stmt_end(i)
        depth, k = 0, i
        while k < end:
            y = self.tx(k)
            if y in ("(", "[", "{"):
                depth += 1
            elif y in (")", "]", "}"):
                depth -= 1
            elif depth == 0 and y in ASSIGN_OPS:
                break
            k += 1
        if k < end:
            self.regions.append((k + 1, end, "rhs"))
            self.stmts.append((i, end, "nba" if self.tx(k) == "<=" else "blocking"))
        return end + 1


def _operand_end(tok) -> bool:
    return tok is not None and (tok.kind in OPERAND_END_KINDS or tok.text in (")", "]", "}"))


def _mk(fid, op, toks, i_first, i_last, new, desc, text):
    a, b = toks[i_first], toks[i_last]
    old = text[a.start:b.end]
    h = hashlib.sha1(f"{fid}:{a.start}:{b.end}:{new}".encode()).hexdigest()[:8]
    return Mutant(id=f"{op}-{os.path.basename(fid)}-L{a.line}-{h}", op=op, file=fid,
                  line=a.line, col=a.col, start=a.start, end=b.end, old=old, new=new, desc=desc)


def generate(path: str, text: str | None = None) -> list:
    """All single-point mutants of one RTL file."""
    if text is None:
        with open(path) as f:
            text = f.read()
    toks = vlex.significant(vlex.tokenize(text))
    sc = _Scan(toks).run()
    out = []
    seen = set()

    def add(m: Mutant):
        key = (m.start, m.end, m.new)
        if key not in seen and m.old != m.new:
            seen.add(key)
            out.append(m)

    binary_swap = {"+": ("-", "AOR"), "-": ("+", "AOR"), "&": ("|", "LOR"), "|": ("&", "LOR"),
                   "^": ("|", "LOR")}
    always_swap = {"&&": ("||", "LOR"), "||": ("&&", "LOR"), "<": ("<=", "ROR"), "<=": ("<", "ROR"),
                   ">": (">=", "ROR"), ">=": (">", "ROR"), "==": ("!=", "ROR"), "!=": ("==", "ROR"),
                   "===": ("!==", "ROR"), "!==": ("===", "ROR"), ">>>": (">>", "SOR"),
                   ">>": (">>>", "SOR"), "<<": (">>", "SOR")}

    for (s, e, kind) in sc.regions:
        for k in range(s, e):
            t = toks[k]
            prev = toks[k - 1] if k - 1 >= s else None
            nxt = toks[k + 1] if k + 1 < len(toks) else None
            if t.kind == "op":
                if t.text in binary_swap and _operand_end(prev) and kind != "case_label":
                    new, op = binary_swap[t.text]
                    add(_mk(path, op, toks, k, k, new, f"binary '{t.text}' -> '{new}'", text))
                elif t.text in always_swap and kind != "case_label":
                    new, op = always_swap[t.text]
                    add(_mk(path, op, toks, k, k, new, f"'{t.text}' -> '{new}'", text))
                elif t.text in ("~", "!") and not _operand_end(prev):
                    add(_mk(path, "UOD", toks, k, k, "", f"delete unary '{t.text}'", text))
                elif t.text == "-" and not _operand_end(prev) and kind != "case_label":
                    add(_mk(path, "UOD", toks, k, k, "", "delete unary '-'", text))
                elif t.text == "[" and k + 4 < e and toks[k + 2].text == ":" and toks[k + 4].text == "]" \
                        and toks[k + 1].kind == "number" and toks[k + 3].kind == "number":
                    hi, lo = vlex.parse_number(toks[k + 1].text), vlex.parse_number(toks[k + 3].text)
                    if hi and lo and hi[2] is None and lo[2] is None:
                        h, l_ = hi[3], lo[3]
                        add(_mk(path, "SLICE", toks, k, k + 4, f"[{h + 1}:{l_ + 1}]",
                                f"part-select [{h}:{l_}] -> [{h + 1}:{l_ + 1}]", text))
                        if l_ >= 1:
                            add(_mk(path, "SLICE", toks, k, k + 4, f"[{h - 1}:{l_ - 1}]",
                                    f"part-select [{h}:{l_}] -> [{h - 1}:{l_ - 1}]", text))
                elif t.text == "?":
                    _ternary(path, toks, k, e, text, add)
            elif t.kind == "number":
                in_slice = (prev is not None and prev.text in ("[", ":") and nxt is not None
                            and nxt.text in (":", "]") and not (prev.text == "[" and nxt.text == "]"))
                if in_slice or (nxt is not None and nxt.text == "{"):
                    continue  # width-changing: left to SLICE, replication counts untouched
                pn = vlex.parse_number(t.text)
                if pn is None:
                    continue
                size, sgn, base, val = pn
                if base == "'":
                    add(_mk(path, "CR", toks, k, k, f"'{1 - val}", f"'{val} -> '{1 - val}", text))
                    continue
                limit = (1 << size) if size else None
                for nv in (val + 1, val - 1):
                    if nv < 0 or (limit is not None and nv >= limit):
                        continue
                    new = vlex.format_number(size, sgn, base, nv)
                    add(_mk(path, "CR", toks, k, k, new, f"constant {t.text} -> {new}", text))
            elif t.kind == "sysid" and t.text in ("$signed", "$unsigned"):
                add(_mk(path, "SGN", toks, k, k, "", f"delete {t.text}", text))

    for (lp, rp) in sc.ifconds:
        inner = text[toks[lp + 1].start:toks[rp - 1].end] if rp - 1 > lp else ""
        if inner:
            add(_mk(path, "IFN", toks, lp, rp, f"(!({inner}))", "negate if condition", text))
    for (a, b, kind) in sc.stmts:
        add(_mk(path, "STMT", toks, a, b, ";" if kind != "assign" else "",
                f"delete {kind} statement", text))
    for k in sc.edges:
        new = "negedge" if toks[k].text == "posedge" else "posedge"
        add(_mk(path, "EDGE", toks, k, k, new, f"{toks[k].text} -> {new}", text))
    for k in sc.signed_kw:
        add(_mk(path, "SGN", toks, k, k, "", "delete 'signed' keyword", text))
    out.sort(key=lambda m: (m.line, m.col, m.op, m.new))
    return out


def _ternary(path, toks, q, e, text, add):
    """Swap the arms of the ?: whose '?' is at token q (region ends at e)."""
    depth, nest, k = 0, 0, q + 1
    colon = None
    while k < e:
        x = toks[k].text
        if x in ("(", "[", "{"):
            depth += 1
        elif x in (")", "]", "}"):
            if depth == 0:
                break
            depth -= 1
        elif x == "?" and depth == 0:
            nest += 1
        elif x == ":" and depth == 0:
            if nest == 0:
                colon = k
                break
            nest -= 1
        k += 1
    if colon is None or colon == q + 1:
        return
    depth, nest, k = 0, 0, colon + 1
    while k < e:
        x = toks[k].text
        if x in ("(", "[", "{"):
            depth += 1
        elif x in (")", "]", "}"):
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and x in (",", ";"):
            break
        elif depth == 0 and x == "?":
            nest += 1
        elif depth == 0 and x == ":":
            if nest == 0:
                break
            nest -= 1
        k += 1
    last = k - 1
    if last <= colon:
        return
    a_txt = text[toks[q + 1].start:toks[colon - 1].end]
    b_txt = text[toks[colon + 1].start:toks[last].end]
    new = f"? {b_txt} : {a_txt}"
    add(_mk(path, "TERN", toks, q, last, new, "swap ?: arms", text))


def generate_for(rtl_files: list) -> list:
    out = []
    for f in rtl_files:
        out.extend(generate(f))
    return out


def sample(mutants: list, max_n: int | None, seed: int = 1) -> list:
    """Deterministic, operator-stratified sample (all of them if max_n is None or large)."""
    if not max_n or len(mutants) <= max_n:
        return list(mutants)
    rng = random.Random(seed)
    by_op = {}
    for m in mutants:
        by_op.setdefault(m.op, []).append(m)
    for v in by_op.values():
        rng.shuffle(v)
    out = []
    while len(out) < max_n:
        for op in sorted(by_op):
            if by_op[op] and len(out) < max_n:
                out.append(by_op[op].pop())
    return sorted(out, key=lambda m: (m.file, m.line, m.col, m.op))
