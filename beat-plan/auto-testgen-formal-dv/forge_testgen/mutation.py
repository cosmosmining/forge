"""Bug injection (mutation testing): how good are the generated tests and proofs?

Each mutant is the original RTL with ONE source-level change of a kind real
datapath/control bugs take.  For every mutant:
  stillborn    does not compile (excluded)
  killed       a generated simulation test fails, and/or a formal check fails
               with a counterexample that REPLAYS in simulation
  equivalent   survived; formal miter proves it equals the original RTL
               (not a bug, excluded from the denominator)
  conformant   survived; behaves differently from the original but still
               satisfies the spec (golden + protocol) -- e.g. a FIFO that
               stalls one entry early.  Not a bug by the spec's definition.
  survived     none of the above: a test/proof gap.  Listed one by one.
"""

import json
import os
import random
import re
import shutil
import time
from concurrent.futures import ProcessPoolExecutor

from . import campaign, formal, tools
from .spec import Spec

# --------------------------------------------------------------------------
# finding mutation sites


def strip_comments(text):
    """Replace comments with spaces (offsets preserved)."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif text[i] == '"':
            j = text.find('"', i + 1)
            i = n if j < 0 else j + 1
        else:
            i += 1
    return "".join(out)


_SKIP_LINE = re.compile(r"^\s*(module|endmodule|input|output|inout|localparam|parameter|function|"
                        r"endfunction|task|endtask|integer|genvar|generate|endgenerate|for\b|end\b|"
                        r"begin\b|else\s*$|`)")
_DECL = re.compile(r"^\s*(wire|reg|logic)\b")
_ASSIGN = re.compile(r"^\s*assign\b")
_NBA = re.compile(r"^\s*(?:else\s+)?(?:if\s*\(.*\)\s*)?([A-Za-z_]\w*(?:\[[^\]]*\])?)\s*<=")
_BA = re.compile(r"^\s*(?:else\s+)?(?:if\s*\(.*\)\s*)?([A-Za-z_]\w*(?:\[[^\]]*\])?)\s*=(?!=)")
_IF = re.compile(r"\bif\s*\(")


def _match_paren(s, i):
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if depth == 0:
                return k
    return -1


def _regions(line):
    """[(start, end, kind)] of expression text in one comment-free line."""
    regs = []
    if _SKIP_LINE.match(line) and not re.match(r"^\s*(end|else)\b.*\bif\s*\(", line):
        return regs
    for m in _IF.finditer(line):
        open_i = m.end() - 1
        close_i = _match_paren(line, open_i)
        if close_i > 0:
            regs.append((open_i + 1, close_i, "if"))
    if _DECL.match(line) or _ASSIGN.match(line):
        eq = re.search(r"(?<![<>=!])=(?!=)", line)
        if eq:
            regs.append((eq.end(), len(line), "expr"))
        return regs
    m = _NBA.match(line)
    if m:
        regs.append((m.end(), len(line), "nba"))
        return regs
    m = _BA.match(line)
    if m:
        regs.append((m.end(), len(line), "expr"))
    return regs


# (class, regex on region text, replacement)
_BINOP_PREV = r"(?<=[\w)\]'])\s*"
OPS = [
    ("arith", re.compile(_BINOP_PREV + r"\+(?![+:])"), " - "),
    ("arith", re.compile(_BINOP_PREV + r"-(?![-:>])"), " + "),
    ("relational", re.compile(r"(?<![<>=!])<(?![<=])"), "<="),
    ("relational", re.compile(r"(?<![<>=!])<="), "<"),
    ("relational", re.compile(r"(?<![<>=!-])>(?![>=])"), ">="),
    ("relational", re.compile(r"(?<![<>=!])>="), ">"),
    ("relational", re.compile(r"=="), "!="),
    ("relational", re.compile(r"!="), "=="),
    ("logical", re.compile(r"&&"), "||"),
    ("logical", re.compile(r"\|\|"), "&&"),
    ("bitwise", re.compile(_BINOP_PREV + r"&(?!&)"), " | "),
    ("bitwise", re.compile(_BINOP_PREV + r"\|(?!\|)"), " & "),
    ("bitwise", re.compile(_BINOP_PREV + r"\^"), " & "),
    ("shift", re.compile(r">>>"), ">>"),
    ("shift", re.compile(r"<<<"), "<<"),
    ("unary", re.compile(r"!(?!=)"), ""),
    ("unary", re.compile(r"~(?![&|^])"), ""),
    ("signedness", re.compile(r"\$signed\s*\("), "$unsigned("),
]
_SIZED = re.compile(r"(\d+)'(s?)([dhb])([0-9a-fA-F_]+)")
_DEC = re.compile(r"(?<![\w'.$])(\d+)(?![\w'.])")


class Mutant:
    def __init__(self, mid, path, line, col, cls, orig, repl, new_text):
        self.id, self.path, self.line, self.col = mid, path, line, col
        self.cls, self.orig, self.repl, self.new_text = cls, orig, repl, new_text

    def describe(self):
        return "%s:%d: [%s] '%s' -> '%s'" % (os.path.basename(self.path), self.line, self.cls,
                                             self.orig.strip(), self.repl.strip())

    def to_dict(self):
        return {"id": self.id, "file": os.path.basename(self.path), "line": self.line,
                "class": self.cls, "from": self.orig.strip(), "to": self.repl.strip()}


def generate(paths):
    mutants, n = [], 0
    for path in paths:
        with open(path) as fh:
            text = fh.read()
        code = strip_comments(text)
        line_starts = [0] + [m.end() for m in re.finditer("\n", code)]
        lines = code.split("\n")
        cont = False
        for ln, line in enumerate(lines):
            base = line_starts[ln]
            regs = _regions(line)
            if not regs and cont:
                regs = [(0, len(line), "expr")]
            if regs and not line.rstrip().endswith((";", "begin")) and regs[-1][2] != "if":
                cont = True
            elif line.rstrip().endswith(";"):
                cont = False
            edits = []
            for start, end, kind in regs:
                seg = line[start:end]
                for cls, rx, rep in OPS:
                    for m in rx.finditer(seg):
                        edits.append((start + m.start(), start + m.end(), cls, m.group(0), rep))
                for m in _SIZED.finditer(seg):
                    width, s, radix, digits = m.groups()
                    base_n = {"d": 10, "h": 16, "b": 2}[radix]
                    try:
                        val = int(digits.replace("_", ""), base_n)
                    except ValueError:
                        continue
                    for nv in (val + 1, val - 1):
                        if nv < 0 or nv >= (1 << int(width)):
                            continue
                        lit = "%s'%s%s%s" % (width, s, radix, format(nv, {"d": "d", "h": "x", "b": "b"}[radix]))
                        edits.append((start + m.start(), start + m.end(), "constant", m.group(0), lit))
                masked = _SIZED.sub(lambda mm: " " * len(mm.group(0)), seg)
                masked = re.sub(r"\[[^\]]*\]", lambda mm: mm.group(0).replace(":", " "), masked)
                for m in _DEC.finditer(masked):
                    val = int(m.group(1))
                    for nv in (val + 1, val - 1):
                        if nv >= 0:
                            edits.append((start + m.start(), start + m.end(), "constant", m.group(1), str(nv)))
                if kind == "if":
                    cond = seg
                    edits.append((start, end, "condition", cond, "!(%s)" % cond.strip()))
                    edits.append((start, end, "condition", cond, "1'b1"))
                    edits.append((start, end, "condition", cond, "1'b0"))
                if kind == "nba":
                    m = _NBA.match(line)
                    lhs = m.group(1)
                    semi = seg.rfind(";")
                    if semi >= 0:
                        edits.append((start, start + semi, "dropped-update", seg[:semi], " " + lhs))
            for s0, e0, cls, orig, rep in edits:
                a, b = base + s0, base + e0
                new_text = text[:a] + rep + text[b:]
                if new_text == text:
                    continue
                n += 1
                mutants.append(Mutant(n, path, ln + 1, s0 + 1, cls, orig, rep, new_text))
    # de-duplicate identical sources
    seen, out = set(), []
    for m in mutants:
        key = (m.path, m.new_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    for i, m in enumerate(out, 1):
        m.id = i
    return out


# --------------------------------------------------------------------------
# evaluating one mutant


def _load_suite(spec, outdir):
    with open(os.path.join(outdir, "suite.json")) as fh:
        data = json.load(fh)
    suite = campaign.Suite(spec)
    for grp, items in data["groups"].items():
        for it in items:
            out, _ = spec.model.evaluate(it["vec"])
            suite.add(grp, it["origin"], it["vec"], out)
    suite.scenarios = [tuple(s) for s in data["scenarios"]]
    return suite


def _evaluate(args):
    spec_path, outdir, mdict, new_text, do_formal, simulator = args
    spec = Spec(spec_path)
    wd = os.path.join(outdir, "mutants", "m%03d" % mdict["id"])
    if os.path.isdir(wd):
        shutil.rmtree(wd)
    os.makedirs(wd)
    target = [p for p in spec.rtl if os.path.basename(p) == mdict["file"]][0]
    mfile = os.path.join(wd, os.path.basename(target))
    with open(mfile, "w") as fh:
        fh.write(new_text)
    rtl = [mfile if p == target else p for p in spec.rtl]
    rec = dict(mdict)
    t0 = time.time()
    rc, log, _ = tools.run(["iverilog", "-g2012", "-o", os.path.join(wd, "chk.vvp")] + rtl,
                           cwd=wd, timeout=120)
    if rc != 0:
        rec["status"] = "stillborn"
        rec["why"] = log.strip().splitlines()[-1:] if log.strip() else []
        return rec
    rc, log, _ = tools.run(["yosys", "-q", "-p", "read_verilog -sv %s; hierarchy -top %s; proc" % (
        " ".join(rtl), spec.top)], cwd=wd, timeout=120)
    if rc != 0:
        rec["status"] = "stillborn"
        rec["why"] = ["yosys: " + (log.strip().splitlines() or [""])[-1]]
        return rec
    suite = _load_suite(spec, outdir)
    sims = campaign.run_sims(spec, suite, os.path.join(wd, "sim"), rtl=rtl, simulator=simulator)
    killed_groups = sorted({name.split(".")[0] for name, e in sims.items() if not e["ok"]})
    rec["killed_by_groups"] = killed_groups
    rec["sim_killed"] = bool(killed_groups)
    rec["sim_first_message"] = next((e["messages"][0] for e in sims.values()
                                     if not e["ok"] and e["messages"]), None)
    rec["formal"] = None
    if do_formal:
        if spec.kind == "comb":
            res = formal.comb_equiv(spec, os.path.join(wd, "formal"), rtl=rtl,
                                    timeout=int(spec.formal.get("prove_timeout", 600)))
            fv = {"verdict": res.verdict, "failed": res.failed}
            if res.verdict == "FAIL":
                vec = getattr(res, "cex_vector", None)
                fv["replay"] = (campaign.replay_comb(spec, vec, os.path.join(wd, "replay"), rtl, simulator)
                                if vec else {"confirmed": False})
        else:
            depth = int(spec.mutation.get("formal_depth", spec.formal.get("depth", 20)))
            fdir = os.path.join(wd, "formal")
            os.makedirs(fdir, exist_ok=True)
            ref_path, tr = formal.write_ref(spec, fdir)
            wrap = os.path.join(fdir, "fv_stream.sv")
            with open(wrap, "w") as fh:
                fh.write(formal.stream_wrapper(spec, tr))
            files = list(rtl) + [ref_path, wrap]
            script = formal._read_lines(files) + ["prep -flatten -top fv_stream"]
            res = formal.run_sby(fdir, "bmc", "bmc", script, files, ["smtbmc bitwuzla"], depth=depth,
                                 timeout=int(spec.formal.get("prove_timeout", 300)))
            if res.status == "FAIL" and res.failed:
                fv = {"verdict": "FAIL", "failed": res.failed}
                seq = formal.stream_cex_inputs(spec, res.cex_trace)
                fv["replay"] = campaign.replay_stream(spec, seq, os.path.join(wd, "replay"), rtl, simulator)
            elif res.status == "PASS":
                fv = {"verdict": "BOUNDED(%d)" % depth, "failed": []}
            else:
                fv = {"verdict": "UNKNOWN", "failed": [], "status": res.status}
        rec["formal"] = fv
    formal_killed = bool(rec["formal"] and rec["formal"]["verdict"] == "FAIL"
                         and rec["formal"].get("replay", {}).get("confirmed"))
    rec["formal_killed"] = formal_killed
    rec["formal_unconfirmed"] = bool(rec["formal"] and rec["formal"]["verdict"] == "FAIL"
                                     and not formal_killed)
    if rec["sim_killed"] or formal_killed:
        rec["status"] = "killed"
    elif do_formal:
        eq, mres = formal.miter(spec, os.path.join(wd, "miter"), [mfile],
                                depth=int(spec.mutation.get("formal_depth", spec.formal.get("depth", 20))),
                                timeout=int(spec.mutation.get("miter_timeout", 120)))
        rec["miter"] = eq
        if eq.startswith("EQUIVALENT"):
            rec["status"] = "equivalent" if eq == "EQUIVALENT" else "equivalent-bounded"
        elif eq == "DIFFERENT" and rec["formal"]["verdict"] != "FAIL":
            rec["status"] = "conformant"
        else:
            rec["status"] = "survived"
    else:
        rec["status"] = "survived"
    rec["seconds"] = round(time.time() - t0, 1)
    return rec


def run(spec_path, outdir, seed=1, max_mutants=None, do_formal=True, simulator="iverilog",
        workers=None, log=print):
    spec = Spec(spec_path)
    outdir = os.path.abspath(outdir)
    if not os.path.exists(os.path.join(outdir, "suite.json")):
        campaign.run_block(spec_path, outdir, seed=seed, simulator=simulator, do_formal=do_formal)
    muts = generate(spec.rtl)
    total_sites = len(muts)
    if max_mutants and len(muts) > max_mutants:
        rnd = random.Random(seed)
        muts = sorted(rnd.sample(muts, max_mutants), key=lambda m: m.id)
    t0 = time.time()
    jobs = [(spec.path, outdir, m.to_dict(), m.new_text, do_formal, simulator) for m in muts]
    workers = workers or max(1, min(4, os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        records = list(ex.map(_evaluate, jobs))
    res = summarize(spec, records)
    res["formal_mode"] = ("comb: complete equivalence proof per mutant" if spec.kind == "comb" else
                          "stream: BMC depth %d per mutant" % int(spec.mutation.get(
                              "formal_depth", spec.formal.get("depth", 20))))
    res["mutation_sites_found"] = total_sites
    res["sampled"] = len(muts)
    res["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(outdir, "mutation.json"), "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    return res


def summarize(spec, records):
    by = lambda st: [r for r in records if r["status"] == st]
    stillborn = by("stillborn")
    valid = [r for r in records if r["status"] != "stillborn"]
    killed = by("killed")
    equiv = [r for r in records if r["status"] in ("equivalent", "equivalent-bounded")]
    conformant = by("conformant")
    survived = by("survived")
    denom = len(valid) - len(equiv) - len(conformant)

    def rate(n):
        return "%d/%d = %.1f%%" % (n, denom, 100.0 * n / denom) if denom else "n/a"

    groups = sorted({g for r in valid for g in r.get("killed_by_groups", [])})
    s = {
        "mutants_total": len(records),
        "stillborn": len(stillborn),
        "valid": len(valid),
        "killed_by_sim": sum(1 for r in valid if r.get("sim_killed")),
        "killed_by_formal": sum(1 for r in valid if r.get("formal_killed")),
        "killed_any": len(killed),
        "proven_equivalent": len([r for r in equiv if r["status"] == "equivalent"]),
        "bounded_equivalent": len([r for r in equiv if r["status"] == "equivalent-bounded"]),
        "spec_conformant_behavior_change": len(conformant),
        "survived": len(survived),
        "formal_cex_not_confirmed_by_replay": sum(1 for r in valid if r.get("formal_unconfirmed")),
        "denominator": denom,
        "combined_kill_rate": rate(len(killed)),
        "sim_kill_rate": rate(sum(1 for r in valid if r.get("sim_killed"))),
        "formal_kill_rate": rate(sum(1 for r in valid if r.get("formal_killed"))),
    }
    for g in ("directed", "random", "closure"):
        s["%s_only_kill_rate" % g] = rate(sum(1 for r in valid if g in r.get("killed_by_groups", [])))
    by_class = {}
    for r in valid:
        c = by_class.setdefault(r["class"], {"valid": 0, "killed": 0, "equivalent": 0, "survived": 0})
        c["valid"] += 1
        if r["status"] == "killed":
            c["killed"] += 1
        elif r["status"].startswith("equivalent") or r["status"] == "conformant":
            c["equivalent"] += 1
        else:
            c["survived"] += 1
    return {
        "block": spec.name,
        "summary": s,
        "by_class": by_class,
        "survivors": ["m%03d %s:%d [%s] '%s' -> '%s'" % (r["id"], r["file"], r["line"], r["class"],
                                                          r["from"], r["to"]) for r in survived],
        "conformant": ["m%03d %s:%d [%s] '%s' -> '%s'" % (r["id"], r["file"], r["line"], r["class"],
                                                           r["from"], r["to"]) for r in conformant],
        "records": records,
    }
