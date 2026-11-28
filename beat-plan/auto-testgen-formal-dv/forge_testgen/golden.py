"""Golden-model DSL: restricted Python that runs directly as the simulation
oracle AND translates bit-exactly into a Verilog reference module that the
formal flow compares against the RTL.

Why both from one source: the simulation scoreboard and the formal
equivalence proof then check the RTL against the *same* golden, and the
translation itself is cross-checked (tests/test_golden.py and the `selfcheck`
step of every run) so a translator bug shows up as a failed self-check, not as
a false PASS.

Supported subset (anything else is rejected with a line number):
  statements : x = e ; a, b = e1, e2 ; x += e (and -=, *=, <<=, >>=, &=, |=, ^=)
               for i in range(const...) / for x in <list>   (unrolled)
               if / elif / else on data-dependent conditions (merged into muxes)
               cover("name", cond)  ; pass ; docstrings
               return {...}  (last statement of the golden function)
  expressions: int / bool literals, + - * // % (// and % only by power-of-two
               constants), << >> & | ^ ~, unary -, not/and/or, comparisons
               (chains allowed), a if c else b, list literals/comprehensions,
               list[const], min/max/abs/sum/len/int/bool, clamp/sat/wrap/
               rshift_round (golden_lib), calls to helper functions defined in
               the same file (inlined), module-level int / list-of-int constants.

Every intermediate value gets an exact integer interval; its Verilog wire is
signed and wide enough for that interval, so fixed-width Verilog arithmetic
equals Python's unbounded arithmetic.
"""

import ast
import importlib.util
import os

from . import golden_lib


class GoldenError(Exception):
    pass


def sbits(lo, hi):
    """Bits of a signed two's-complement wire that holds every value in [lo, hi]."""

    def b(v):
        return v.bit_length() + 1 if v >= 0 else (-v - 1).bit_length() + 1

    return max(1, b(lo), b(hi))


def vlit(value, width):
    """Signed sized Verilog literal with exactly `width` bits."""
    width = max(width, sbits(value, value))
    return "%d'sh%x" % (width, value & ((1 << width) - 1))


CMP_OPS = ("lt", "le", "gt", "ge", "eq", "ne")


def _py(op, v):
    """Python semantics of one graph op on concrete ints."""
    if op == "add":
        return v[0] + v[1]
    if op == "sub":
        return v[0] - v[1]
    if op == "mul":
        return v[0] * v[1]
    if op == "neg":
        return -v[0]
    if op == "shl":
        return v[0] << v[1]
    if op == "shr":
        return v[0] >> v[1]
    if op == "band":
        return v[0] & v[1]
    if op == "bor":
        return v[0] | v[1]
    if op == "bxor":
        return v[0] ^ v[1]
    if op == "bnot":
        return ~v[0]
    if op == "lt":
        return int(v[0] < v[1])
    if op == "le":
        return int(v[0] <= v[1])
    if op == "gt":
        return int(v[0] > v[1])
    if op == "ge":
        return int(v[0] >= v[1])
    if op == "eq":
        return int(v[0] == v[1])
    if op == "ne":
        return int(v[0] != v[1])
    if op == "mux":
        return v[1] if v[0] else v[2]
    if op == "lnot":
        return int(not v[0])
    if op == "min2":
        return v[1] if v[1] < v[0] else v[0]
    if op == "max2":
        return v[1] if v[1] > v[0] else v[0]
    if op == "abs":
        return -v[0] if v[0] < 0 else v[0]
    if op == "clamp":
        return v[1] if v[0] < v[1] else (v[2] if v[0] > v[2] else v[0])
    raise GoldenError("internal: unknown op %r" % op)


class Node:
    __slots__ = ("id", "op", "args", "lo", "hi", "val", "name")

    def __init__(self, nid, op, args, lo, hi, val=None, name=None):
        self.id, self.op, self.args = nid, op, args
        self.lo, self.hi, self.val, self.name = lo, hi, val, name

    @property
    def width(self):
        return sbits(self.lo, self.hi)

    @property
    def const(self):
        return self.op == "const"

    def __repr__(self):
        return "n%d<%s [%d,%d]>" % (self.id, self.op, self.lo, self.hi)


class Graph:
    """Hash-consed DAG of integer ops with exact intervals."""

    MAX_SHIFT = 4096

    def __init__(self):
        self.nodes = []
        self.memo = {}
        self.warnings = []

    def _new(self, op, args, lo, hi, val=None, name=None):
        key = (op, tuple(a.id for a in args), val, name)
        hit = self.memo.get(key)
        if hit is not None:
            return hit
        n = Node(len(self.nodes), op, tuple(args), lo, hi, val, name)
        self.nodes.append(n)
        self.memo[key] = n
        return n

    def const(self, v):
        v = int(v)
        return self._new("const", (), v, v, val=v)

    def inp(self, name, lo, hi):
        return self._new("in", (), lo, hi, name=name)

    def op(self, op, *a):
        if all(x.const for x in a):
            if op in ("shl", "shr") and a[1].val < 0:
                raise GoldenError("negative constant shift amount")
            return self.const(_py(op, [x.val for x in a]))
        # Safe algebraic simplifications (exact under Python semantics).
        if op == "add":
            if a[1].const and a[1].val == 0:
                return a[0]
            if a[0].const and a[0].val == 0:
                return a[1]
        if op == "sub" and a[1].const and a[1].val == 0:
            return a[0]
        if op == "mul":
            for x, y in ((a[0], a[1]), (a[1], a[0])):
                if x.const and x.val == 1:
                    return y
                if x.const and x.val == 0:
                    return self.const(0)
        if op in ("shl", "shr") and a[1].const and a[1].val == 0:
            return a[0]
        if op == "mux":
            if a[0].const:
                return a[1] if a[0].val else a[2]
            if a[1] is a[2]:
                return a[1]
        if op in CMP_OPS:
            folded = self._fold_cmp(op, a[0], a[1])
            if folded is not None:
                return self.const(folded)
        lo, hi = self._interval(op, a)
        return self._new(op, a, lo, hi)

    @staticmethod
    def _fold_cmp(op, x, y):
        if op == "lt":
            return 1 if x.hi < y.lo else (0 if x.lo >= y.hi else None)
        if op == "le":
            return 1 if x.hi <= y.lo else (0 if x.lo > y.hi else None)
        if op == "gt":
            return 1 if x.lo > y.hi else (0 if x.hi <= y.lo else None)
        if op == "ge":
            return 1 if x.lo >= y.hi else (0 if x.hi < y.lo else None)
        disjoint = x.hi < y.lo or y.hi < x.lo
        if op == "eq":
            return 0 if disjoint else None
        if op == "ne":
            return 1 if disjoint else None
        return None

    def _interval(self, op, a):
        if op == "add":
            return a[0].lo + a[1].lo, a[0].hi + a[1].hi
        if op == "sub":
            return a[0].lo - a[1].hi, a[0].hi - a[1].lo
        if op == "mul":
            c = [x * y for x in (a[0].lo, a[0].hi) for y in (a[1].lo, a[1].hi)]
            return min(c), max(c)
        if op == "neg":
            return -a[0].hi, -a[0].lo
        if op in ("shl", "shr"):
            slo, shi = a[1].lo, a[1].hi
            if shi < 0:
                raise GoldenError("shift amount is always negative")
            if slo < 0:
                self.warnings.append(
                    "shift amount may be negative (Python raises for those inputs; "
                    "safe only if every such path is guarded)")
                slo = 0
            if shi > self.MAX_SHIFT:
                raise GoldenError("shift amount range [%d,%d] too large to translate" % (slo, shi))
            if op == "shl":
                c = [x << s for x in (a[0].lo, a[0].hi) for s in (slo, shi)]
            else:
                c = [x >> s for x in (a[0].lo, a[0].hi) for s in (slo, shi)]
            return min(c), max(c)
        if op == "bnot":
            return -a[0].hi - 1, -a[0].lo - 1
        if op == "band":
            if a[0].lo >= 0 and a[1].lo >= 0:
                return 0, min(a[0].hi, a[1].hi)
            if a[0].lo >= 0:
                return 0, a[0].hi
            if a[1].lo >= 0:
                return 0, a[1].hi
            w = max(a[0].width, a[1].width)
            return -(1 << (w - 1)), (1 << (w - 1)) - 1
        if op in ("bor", "bxor"):
            if a[0].lo >= 0 and a[1].lo >= 0:
                w = max(a[0].hi.bit_length(), a[1].hi.bit_length())
                return 0, (1 << w) - 1
            w = max(a[0].width, a[1].width)
            return -(1 << (w - 1)), (1 << (w - 1)) - 1
        if op in CMP_OPS or op == "lnot":
            return 0, 1
        if op == "mux":
            return min(a[1].lo, a[2].lo), max(a[1].hi, a[2].hi)
        if op == "min2":
            return min(a[0].lo, a[1].lo), min(a[0].hi, a[1].hi)
        if op == "max2":
            return max(a[0].lo, a[1].lo), max(a[0].hi, a[1].hi)
        if op == "abs":
            lo, hi = a[0].lo, a[0].hi
            if lo >= 0:
                return lo, hi
            if hi <= 0:
                return -hi, -lo
            return 0, max(-lo, hi)
        if op == "clamp":
            x, l, h = a
            if l.const and h.const:
                c = lambda v: l.val if v < l.val else (h.val if v > h.val else v)
                vals = [c(x.lo), c(x.hi)]
                return min(vals), max(vals)
            lo = min(l.lo, h.lo, max(x.lo, l.lo))
            hi = max(l.hi, h.hi, min(x.hi, h.hi))
            return lo, hi
        raise GoldenError("internal: no interval rule for %r" % op)

    # -- boolean helpers (operands are 0/1 nodes) --------------------------
    def truth(self, n):
        n = _scalar(n)
        if n.lo >= 0 and n.hi <= 1:
            return n
        return self.op("ne", n, self.const(0))

    def band_b(self, x, y):
        return self.op("mux", x, y, self.const(0))

    def bor_b(self, x, y):
        return self.op("mux", x, self.const(1), y)

    def bnot_b(self, x):
        return self.op("lnot", x)

    # -- Python-semantics evaluation of the graph (self-check) -------------
    def evaluate(self, roots, inputs):
        """Evaluate nodes reachable from `roots` with Python semantics.

        Asserts that every non-poisoned value lies inside its interval, which
        is what makes the fixed-width Verilog exact.  Returns {node_id: value}.
        A node is 'poisoned' when it depends on a shift by a negative amount
        that Python would never execute (guarded by a mux).
        """
        need = self.cone(roots)
        vals, poison = {}, set()
        for n in self.nodes:
            if n.id not in need:
                continue
            if n.op == "in":
                v = inputs[n.name]
            elif n.op == "const":
                v = n.val
            elif n.op == "mux":
                c = vals[n.args[0].id]
                pick = n.args[1] if c else n.args[2]
                v = vals[pick.id]
                if n.args[0].id in poison or pick.id in poison:
                    poison.add(n.id)
            else:
                args = [vals[a.id] for a in n.args]
                if any(a.id in poison for a in n.args):
                    poison.add(n.id)
                    v = 0
                elif n.op in ("shl", "shr") and args[1] < 0:
                    poison.add(n.id)
                    v = 0
                else:
                    v = _py(n.op, args)
            if n.id not in poison and not (n.lo <= v <= n.hi):
                raise GoldenError("internal: interval unsound at %r value %d" % (n, v))
            vals[n.id] = v
        return vals, poison

    def cone(self, roots):
        need, stack = set(), [r for r in roots]
        while stack:
            n = stack.pop()
            if n.id in need:
                continue
            need.add(n.id)
            stack.extend(n.args)
        return need


def _scalar(v, what="value"):
    if not isinstance(v, Node):
        raise GoldenError("%s must be a scalar integer here, got %s" % (what, type(v).__name__))
    return v


class _Undef:
    def __init__(self, name):
        self.name = name


class _SymExec:
    def __init__(self, graph, mod_globals, funcs, src_name):
        self.g = graph
        self.globals = mod_globals
        self.funcs = funcs
        self.covers = {}
        self.src = src_name
        self.depth = 0
        self.boundaries = []  # (line, kind, lhs node, rhs node, path condition)

    def note_boundary(self, where, kind, a, b, pc):
        """Remember a decision point (comparison/clamp/min/max) of the golden."""
        if not (isinstance(a, Node) and isinstance(b, Node)) or (a.const and b.const):
            return
        if a.hi - b.lo < -1 or a.lo - b.hi > 1:
            return  # operands can never be within 1 of each other
        self.boundaries.append((getattr(where, "lineno", 0), kind, a, b, pc))

    def err(self, node, msg):
        line = getattr(node, "lineno", "?")
        ex = GoldenError("%s:%s: %s" % (self.src, line, msg))
        ex.located = True
        raise ex

    # -- statements --------------------------------------------------------
    def run(self, fdef, args, pc, top):
        env = dict(args)
        body = [s for s in fdef.body]
        for i, st in enumerate(body):
            if isinstance(st, ast.Return):
                if i != len(body) - 1:
                    self.err(st, "return must be the last statement of the function body")
                if st.value is None:
                    self.err(st, "return needs a value")
                return self.eval(st.value, env, pc)
            self.stmt(st, env, pc)
        self.err(fdef, "function %s must end with a return statement" % fdef.name)

    def stmt(self, st, env, pc):
        g = self.g
        if isinstance(st, ast.Assign):
            if len(st.targets) != 1:
                self.err(st, "chained assignment not supported")
            self.bind(st.targets[0], self.eval(st.value, env, pc), env)
        elif isinstance(st, ast.AnnAssign):
            if st.value is None:
                return
            self.bind(st.target, self.eval(st.value, env, pc), env)
        elif isinstance(st, ast.AugAssign):
            if not isinstance(st.target, ast.Name):
                self.err(st, "augmented assignment only to plain names")
            cur = self.lookup(st.target.id, env, st)
            env[st.target.id] = self.binop(st.op, cur, self.eval(st.value, env, pc), st)
        elif isinstance(st, ast.For):
            if st.orelse:
                self.err(st, "for/else not supported")
            items = self.iterate(st.iter, env, pc)
            for item in items:
                self.bind(st.target, item, env)
                for b in st.body:
                    if isinstance(b, (ast.Break, ast.Continue, ast.Return)):
                        self.err(b, "break/continue/return inside a loop not supported")
                    self.stmt(b, env, pc)
        elif isinstance(st, ast.If):
            c = g.truth(self.eval(st.test, env, pc))
            if c.const:
                for b in (st.body if c.val else st.orelse):
                    self.stmt(b, env, pc)
                return
            e1, e2 = dict(env), dict(env)
            for b in st.body:
                self.stmt(b, e1, g.band_b(pc, c))
            for b in st.orelse:
                self.stmt(b, e2, g.band_b(pc, g.bnot_b(c)))
            for k in set(e1) | set(e2):
                v1, v2 = e1.get(k), e2.get(k)
                if v1 is None or v2 is None or isinstance(v1, _Undef) or isinstance(v2, _Undef):
                    env[k] = _Undef(k)
                else:
                    env[k] = self.merge(c, v1, v2, st)
        elif isinstance(st, ast.Expr):
            v = st.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return  # docstring
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                    and v.func.id == "cover"):
                if len(v.args) != 2 or not isinstance(v.args[0], ast.Constant) \
                        or not isinstance(v.args[0].value, str):
                    self.err(st, 'cover() needs ("name", condition)')
                name = v.args[0].value
                cond = g.band_b(pc, g.truth(self.eval(v.args[1], env, pc)))
                prev = self.covers.get(name)
                self.covers[name] = cond if prev is None else g.bor_b(prev, cond)
                return
            self.err(st, "only cover(...) calls may appear as statements")
        elif isinstance(st, ast.Pass):
            return
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            return
        else:
            self.err(st, "statement %s not supported" % type(st).__name__)

    def bind(self, target, val, env):
        if isinstance(target, ast.Name):
            env[target.id] = val
        elif isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(val, (tuple, list)) or len(val) != len(target.elts):
                self.err(target, "cannot unpack value into %d names" % len(target.elts))
            for t, v in zip(target.elts, val):
                self.bind(t, v, env)
        else:
            self.err(target, "assignment target %s not supported" % type(target).__name__)

    def merge(self, c, a, b, where):
        if isinstance(a, Node) and isinstance(b, Node):
            return self.g.op("mux", c, a, b)
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
            out = [self.merge(c, x, y, where) for x, y in zip(a, b)]
            return out if isinstance(a, list) else tuple(out)
        self.err(where, "branches assign values of different shapes")

    def lookup(self, name, env, where):
        if name in env:
            v = env[name]
            if isinstance(v, _Undef):
                self.err(where, "%r is not assigned on every path" % name)
            return v
        if name in self.globals:
            gv = self.globals[name]
            if isinstance(gv, bool) or isinstance(gv, int):
                return self.g.const(int(gv))
            if isinstance(gv, (list, tuple)) and all(isinstance(x, int) for x in gv):
                return [self.g.const(x) for x in gv]
        self.err(where, "unknown name %r" % name)

    def iterate(self, it, env, pc):
        if (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"):
            args = []
            for a in it.args:
                v = _scalar(self.eval(a, env, pc))
                if not v.const:
                    self.err(it, "range() bounds must be constants")
                args.append(v.val)
            return [self.g.const(k) for k in range(*args)]
        v = self.eval(it, env, pc)
        if isinstance(v, (list, tuple)):
            return list(v)
        self.err(it, "can only iterate over range(const) or a list")

    # -- expressions -------------------------------------------------------
    def eval(self, e, env, pc):
        try:
            return self._eval(e, env, pc)
        except GoldenError as ex:
            if getattr(ex, "located", False):
                raise
            self.err(e, str(ex))

    def _eval(self, e, env, pc):
        g = self.g
        if isinstance(e, ast.Constant):
            if isinstance(e.value, bool) or isinstance(e.value, int):
                return g.const(int(e.value))
            if isinstance(e.value, str):
                return e.value
            self.err(e, "only integer constants are supported")
        if isinstance(e, ast.Name):
            return self.lookup(e.id, env, e)
        if isinstance(e, ast.BinOp):
            return self.binop(e.op, self.eval(e.left, env, pc), self.eval(e.right, env, pc), e)
        if isinstance(e, ast.UnaryOp):
            v = self.eval(e.operand, env, pc)
            if isinstance(e.op, ast.Not):
                return g.bnot_b(g.truth(v))
            v = _scalar(v)
            if isinstance(e.op, ast.USub):
                return g.op("neg", v)
            if isinstance(e.op, ast.UAdd):
                return v
            if isinstance(e.op, ast.Invert):
                return g.op("bnot", v)
        if isinstance(e, ast.BoolOp):
            vals = [self.eval(x, env, pc) for x in e.values]
            r = _scalar(vals[0])
            for v in vals[1:]:
                v = _scalar(v)
                if isinstance(e.op, ast.And):
                    r = g.op("mux", g.truth(r), v, r)
                else:
                    r = g.op("mux", g.truth(r), r, v)
            return r
        if isinstance(e, ast.Compare):
            names = {ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
                     ast.Eq: "eq", ast.NotEq: "ne"}
            left = self.eval(e.left, env, pc)
            result = None
            for op, comp in zip(e.ops, e.comparators):
                if type(op) not in names:
                    self.err(e, "comparison %s not supported" % type(op).__name__)
                right = self.eval(comp, env, pc)
                if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
                    c = self.list_eq(left, right, e)
                    if isinstance(op, ast.NotEq):
                        c = g.bnot_b(c)
                    elif not isinstance(op, ast.Eq):
                        self.err(e, "only == and != are supported between lists")
                else:
                    c = g.op(names[type(op)], _scalar(left), _scalar(right))
                    self.note_boundary(e, "cmp_" + names[type(op)], left, right, pc)
                result = c if result is None else g.band_b(result, c)
                left = right
            return result
        if isinstance(e, ast.IfExp):
            c = g.truth(self.eval(e.test, env, pc))
            if c.const:
                return self.eval(e.body if c.val else e.orelse, env, pc)
            return self.merge(c, self.eval(e.body, env, pc), self.eval(e.orelse, env, pc), e)
        if isinstance(e, ast.Call):
            return self.call(e, env, pc)
        if isinstance(e, ast.Subscript):
            base = self.eval(e.value, env, pc)
            if not isinstance(base, (list, tuple)):
                self.err(e, "can only index lists")
            sl = e.slice
            if isinstance(sl, ast.Slice):
                bounds = []
                for part in (sl.lower, sl.upper, sl.step):
                    if part is None:
                        bounds.append(None)
                    else:
                        v = _scalar(self.eval(part, env, pc))
                        if not v.const:
                            self.err(e, "slice bounds must be constants")
                        bounds.append(v.val)
                return list(base)[slice(*bounds)]
            idx = _scalar(self.eval(sl, env, pc))
            if idx.const:
                try:
                    return base[idx.val]
                except IndexError:
                    self.err(e, "index %d out of range" % idx.val)
            # Data-dependent index: mux chain over the index's interval
            # (Python semantics incl. negative indices; out-of-range values
            # would raise in Python, so they are don't-care here).
            n = len(base)
            lo, hi = max(idx.lo, -n), min(idx.hi, n - 1)
            if lo > hi:
                self.err(e, "index is always out of range")
            if idx.lo < -n or idx.hi > n - 1:
                self.g.warnings.append("list index may be out of range (Python raises there)")
            if any(not isinstance(base[k], Node) for k in range(lo, hi + 1)):
                self.err(e, "data-dependent indexing only into lists of scalars")
            result = base[hi]
            for k in range(hi - 1, lo - 1, -1):
                result = self.g.op("mux", self.g.op("eq", idx, self.g.const(k)), base[k], result)
            return result
        if isinstance(e, (ast.List, ast.Tuple)):
            vals = [self.eval(x, env, pc) for x in e.elts]
            return vals if isinstance(e, ast.List) else tuple(vals)
        if isinstance(e, (ast.ListComp, ast.GeneratorExp)):
            return self.comprehension(e, env, pc)
        if isinstance(e, ast.Dict):
            out = {}
            for k, v in zip(e.keys, e.values):
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                    self.err(e, "dict keys must be string constants")
                out[k.value] = self.eval(v, env, pc)
            return out
        self.err(e, "expression %s not supported" % type(e).__name__)

    def comprehension(self, e, env, pc):
        if len(e.generators) != 1:
            self.err(e, "only single-generator comprehensions supported")
        gen = e.generators[0]
        items = self.iterate(gen.iter, env, pc)
        out = []
        for item in items:
            local = dict(env)
            self.bind(gen.target, item, local)
            keep = True
            for cond in gen.ifs:
                c = self.g.truth(self.eval(cond, local, pc))
                if not c.const:
                    self.err(e, "comprehension filters must be constant after unrolling")
                keep = keep and bool(c.val)
            if keep:
                out.append(self.eval(e.elt, local, pc))
        return out

    def list_eq(self, a, b, where):
        g = self.g
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return g.const(0)  # Python: a list never equals an int
        if len(a) != len(b):
            return g.const(0)
        r = g.const(1)
        for x, y in zip(a, b):
            if isinstance(x, (list, tuple)) or isinstance(y, (list, tuple)):
                c = self.list_eq(x, y, where)
            else:
                c = g.op("eq", _scalar(x), _scalar(y))
            r = g.band_b(r, c)
        return r

    def binop(self, op, l, r, where):
        g = self.g
        if isinstance(op, ast.Add) and isinstance(l, list) and isinstance(r, list):
            return l + r
        l, r = _scalar(l, "left operand"), _scalar(r, "right operand")
        simple = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.LShift: "shl",
                  ast.RShift: "shr", ast.BitAnd: "band", ast.BitOr: "bor", ast.BitXor: "bxor"}
        if type(op) in simple:
            return g.op(simple[type(op)], l, r)
        if isinstance(op, (ast.FloorDiv, ast.Mod)):
            if not (r.const and r.val > 0 and (r.val & (r.val - 1)) == 0):
                self.err(where, "// and % only by positive power-of-two constants")
            if isinstance(op, ast.FloorDiv):
                return g.op("shr", l, g.const(r.val.bit_length() - 1))
            return g.op("band", l, g.const(r.val - 1))
        if isinstance(op, ast.Pow):
            if l.const and r.const and r.val >= 0:
                return g.const(l.val ** r.val)
            self.err(where, "** only on constants (use 1 << s for powers of two)")
        self.err(where, "operator %s not supported" % type(op).__name__)

    def call(self, e, env, pc):
        g = self.g
        if not isinstance(e.func, ast.Name):
            self.err(e, "only calls to plain function names are supported")
        fn = e.func.id
        args = [self.eval(a, env, pc) for a in e.args]
        kw = {k.arg: self.eval(k.value, env, pc) for k in e.keywords}

        def const_arg(v, what):
            v = _scalar(v, what)
            if not v.const:
                self.err(e, "%s of %s() must be a constant" % (what, fn))
            return v.val

        if fn in ("min", "max"):
            if kw:
                self.err(e, "%s() keyword arguments not supported" % fn)
            items = args[0] if (len(args) == 1 and isinstance(args[0], (list, tuple))) else args
            if not items:
                self.err(e, "%s() of an empty sequence" % fn)
            m = _scalar(items[0])
            for x in items[1:]:
                self.note_boundary(e, fn, _scalar(x), m, pc)
                m = g.op("min2" if fn == "min" else "max2", m, _scalar(x))
            return m
        if fn == "abs":
            self.note_boundary(e, "abs", _scalar(args[0]), g.const(0), pc)
            return g.op("abs", _scalar(args[0]))
        if fn == "clamp":
            x, lo, hi = (_scalar(a) for a in args)
            self.note_boundary(e, "clamp_lo", x, lo, pc)
            self.note_boundary(e, "clamp_hi", x, hi, pc)
            return g.op("clamp", x, lo, hi)
        if fn in ("sat", "wrap"):
            x = _scalar(args[0])
            width = const_arg(args[1] if len(args) > 1 else kw.get("width"), "width")
            signed = args[2] if len(args) > 2 else kw.get("signed", g.const(1))
            signed = const_arg(signed, "signed")
            if fn == "sat":
                lo, hi = ((-(1 << (width - 1)), (1 << (width - 1)) - 1) if signed
                          else (0, (1 << width) - 1))
                self.note_boundary(e, "sat_lo", x, g.const(lo), pc)
                self.note_boundary(e, "sat_hi", x, g.const(hi), pc)
                return g.op("clamp", x, g.const(lo), g.const(hi))
            mask = g.const((1 << width) - 1)
            if signed:
                half = g.const(1 << (width - 1))
                return g.op("sub", g.op("band", g.op("add", x, half), mask), half)
            return g.op("band", x, mask)
        if fn == "rshift_round":
            x, s = _scalar(args[0]), _scalar(args[1])
            bias = g.op("shr", g.op("shl", g.const(1), s), g.const(1))
            return g.op("shr", g.op("add", x, bias), s)
        if fn == "int":
            return _scalar(args[0])
        if fn == "bool":
            return g.truth(args[0])
        if fn == "len":
            if not isinstance(args[0], (list, tuple)):
                self.err(e, "len() of a non-list")
            return g.const(len(args[0]))
        if fn == "sum":
            seq = args[0]
            if not isinstance(seq, (list, tuple)):
                self.err(e, "sum() needs a list or generator")
            acc = _scalar(args[1]) if len(args) > 1 else g.const(0)
            for x in seq:
                acc = g.op("add", acc, _scalar(x))
            return acc
        if fn == "dict":
            return dict(kw)
        if fn == "cover":
            self.err(e, "cover() must be used as a statement")
        if fn in self.funcs:
            return self.inline(self.funcs[fn], args, kw, pc, e)
        self.err(e, "call to unsupported function %r" % fn)

    def inline(self, fdef, args, kw, pc, where):
        self.depth += 1
        if self.depth > 32:
            self.err(where, "helper call depth > 32 (recursion is not supported)")
        params = [a.arg for a in fdef.args.args]
        defaults = fdef.args.defaults
        bound = {}
        for i, p in enumerate(params):
            if i < len(args):
                bound[p] = args[i]
            elif p in kw:
                bound[p] = kw[p]
            else:
                di = i - (len(params) - len(defaults))
                if di < 0:
                    self.err(where, "missing argument %r for %s()" % (p, fdef.name))
                bound[p] = self.eval(defaults[di], {}, pc)
        result = self.run(fdef, bound, pc, top=False)
        self.depth -= 1
        return result


class Field:
    """One input or output of a block as the golden model sees it."""

    def __init__(self, name, width, signed=False, count=1, port=None, lo=None, hi=None):
        self.name, self.width, self.signed, self.count = name, int(width), bool(signed), int(count)
        self.port = port or name
        tlo, thi = self.type_range()
        self.lo = tlo if lo is None else max(tlo, int(lo))
        self.hi = thi if hi is None else min(thi, int(hi))
        if self.lo > self.hi:
            raise GoldenError("field %s: empty range [%d,%d]" % (name, self.lo, self.hi))

    def type_range(self):
        if self.signed:
            return -(1 << (self.width - 1)), (1 << (self.width - 1)) - 1
        return 0, (1 << self.width) - 1

    @property
    def is_vector(self):
        return self.count > 1

    @property
    def total_bits(self):
        return self.width * self.count

    def encode(self, value):
        """Python value (int or list) -> unsigned packed bits (element 0 at LSB)."""
        vals = value if self.is_vector else [value]
        if len(vals) != self.count:
            raise GoldenError("field %s expects %d elements" % (self.name, self.count))
        mask, out = (1 << self.width) - 1, 0
        for i, v in enumerate(vals):
            out |= (int(v) & mask) << (i * self.width)
        return out

    def decode(self, bits):
        mask, out = (1 << self.width) - 1, []
        for i in range(self.count):
            v = (bits >> (i * self.width)) & mask
            if self.signed and v >> (self.width - 1):
                v -= 1 << self.width
            out.append(v)
        return out if self.is_vector else out[0]

    def fits(self, value):
        tlo, thi = self.type_range()
        vals = value if isinstance(value, (list, tuple)) else [value]
        if self.is_vector and len(vals) != self.count:
            return False
        return all(isinstance(v, int) and tlo <= int(v) <= thi for v in vals)


def load_module(path):
    path = os.path.abspath(path)
    spec = importlib.util.spec_from_file_location("forge_golden_%d" % abs(hash(path)), path)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(golden_lib.EXPORTS)
    spec.loader.exec_module(mod)
    return mod


class GoldenModel:
    """A golden function plus its translation to a Verilog reference."""

    def __init__(self, path, func, inputs, outputs, constraints=(), bins=None):
        self.path, self.func_name = path, func
        self.inputs, self.outputs = list(inputs), list(outputs)
        self.constraints = list(constraints)
        self.bins = dict(bins or {})
        self.module = load_module(path)
        if not hasattr(self.module, func):
            raise GoldenError("%s has no function %r" % (path, func))
        self.fn = getattr(self.module, func)
        with open(path) as fh:
            self.source = fh.read()
        self.tree = ast.parse(self.source, filename=path)
        self.funcs = {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        if func not in self.funcs:
            raise GoldenError("%s: %r must be a top-level def" % (path, func))
        self._bin_code = {k: compile(v, "<bin %s>" % k, "eval") for k, v in self.bins.items()}
        self._con_code = [compile(c, "<constraint>", "eval") for c in self.constraints]
        self.translation = None

    # -- Python side ---------------------------------------------------------
    def evaluate(self, vec):
        """Run the golden on one input vector -> (outputs dict, golden cover events)."""
        sink = set()
        golden_lib._COVER_SINK = sink
        try:
            out = self.fn(**{f.name: vec[f.name] for f in self.inputs})
        finally:
            golden_lib._COVER_SINK = None
        if not isinstance(out, dict):
            raise GoldenError("golden %s must return a dict" % self.func_name)
        names = {f.name for f in self.outputs}
        if set(out) != names:
            raise GoldenError("golden returned keys %s, spec outputs are %s"
                              % (sorted(out), sorted(names)))
        clean = {}
        for f in self.outputs:
            v = out[f.name]
            if isinstance(v, (list, tuple)):
                v = [int(x) for x in v]
            else:
                v = int(v)
            if not f.fits(v):
                raise GoldenError("golden output %s=%r does not fit %s%d%s" % (
                    f.name, v, "s" if f.signed else "u", f.width,
                    "x%d" % f.count if f.is_vector else ""))
            clean[f.name] = v
        return clean, sink

    def namespace(self, vec, out=None):
        ns = dict(golden_lib.EXPORTS)
        ns.update({k: v for k, v in vars(self.module).items() if not k.startswith("__")})
        ns.update(vec)
        if out:
            ns.update(out)
        return ns

    def legal(self, vec):
        for f in self.inputs:
            vals = vec[f.name] if f.is_vector else [vec[f.name]]
            if any(not (f.lo <= v <= f.hi) for v in vals):
                return False
        if not self._con_code:
            return True
        ns = self.namespace(vec)
        return all(bool(eval(c, ns)) for c in self._con_code)

    def bin_hits(self, vec, out):
        ns = self.namespace(vec, out)
        return {k for k, c in self._bin_code.items() if eval(c, ns)}

    # -- translation ---------------------------------------------------------
    def translate(self):
        if self.translation is None:
            self.translation = Translation(self)
        return self.translation


class Translation:
    """Symbolic execution of the golden into a Graph + Verilog emission."""

    def __init__(self, gm):
        self.gm = gm
        g = self.g = Graph()
        self.in_nodes = {}
        env = {}
        for f in gm.inputs:
            tlo, thi = f.type_range()
            if f.is_vector:
                elems = [g.inp("%s[%d]" % (f.name, i), tlo, thi) for i in range(f.count)]
                env[f.name] = elems
                for i, n in enumerate(elems):
                    self.in_nodes[(f.name, i)] = n
            else:
                n = g.inp(f.name, tlo, thi)
                env[f.name] = n
                self.in_nodes[(f.name, 0)] = n
        mod_globals = {k: v for k, v in vars(gm.module).items() if not k.startswith("__")}
        sx = _SymExec(g, mod_globals, gm.funcs, os.path.basename(gm.path))
        fdef = gm.funcs[gm.func_name]
        params = [a.arg for a in fdef.args.args]
        if sorted(params) != sorted(f.name for f in gm.inputs):
            raise GoldenError("golden %s(%s) parameters must match spec inputs %s" % (
                gm.func_name, ", ".join(params), sorted(f.name for f in gm.inputs)))
        result = sx.run(fdef, env, g.const(1), top=True)
        if not isinstance(result, dict):
            raise GoldenError("golden %s must return a dict literal" % gm.func_name)
        self.out_nodes = {}
        for f in gm.outputs:
            if f.name not in result:
                raise GoldenError("golden does not return output %r" % f.name)
            v = result[f.name]
            elems = v if f.is_vector else [v]
            if f.is_vector and (not isinstance(v, (list, tuple)) or len(v) != f.count):
                raise GoldenError("output %s must be a list of %d" % (f.name, f.count))
            for i, n in enumerate(elems):
                self.out_nodes[(f.name, i)] = _scalar(n, "output %s" % f.name)
        extra = set(result) - {f.name for f in gm.outputs}
        if extra:
            raise GoldenError("golden returns unknown outputs %s" % sorted(extra))
        self.golden_covers = sx.covers

        # Decision-boundary bins: for every comparison / clamp / sat / min /
        # max / abs the golden evaluates, the operand difference hits -1, 0, +1
        # (only while that code is on the executed path).
        self.boundary_bins, self.boundary_desc = {}, {}
        seen, per_line, seen_nodes = set(), {}, set()
        fname = os.path.basename(gm.path)
        for line, kind, a, b, pc in sx.boundaries:
            key = (a.id, b.id, pc.id, kind)
            if key in seen:
                continue
            seen.add(key)
            per_line[line] = per_line.get(line, 0) + 1
            diff = g.op("sub", a, b)
            for k, tag in ((-1, "m1"), (0, "eq"), (1, "p1")):
                if not (diff.lo <= k <= diff.hi):
                    continue
                node = g.band_b(pc, g.op("eq", diff, g.const(k)))
                if (node.const and not node.val) or node.id in seen_nodes:
                    continue
                seen_nodes.add(node.id)
                name = "boundary.L%d.%s%d.%s" % (line, kind, per_line[line], tag)
                self.boundary_bins[name] = node
                self.boundary_desc[name] = "%s:%d %s #%d: lhs - rhs == %+d" % (
                    fname, line, kind, per_line[line], k)

        # Output-fit check: interval proves fit, else runtime 'ok' term.
        ok = g.const(1)
        self.fit_proven = True
        for f in gm.outputs:
            tlo, thi = f.type_range()
            for i in range(f.count):
                n = self.out_nodes[(f.name, i)]
                if n.lo < tlo or n.hi > thi:
                    self.fit_proven = False
                    inside = g.band_b(g.op("ge", n, g.const(tlo)), g.op("le", n, g.const(thi)))
                    ok = g.band_b(ok, inside)
        self.ok = ok

        # Constraints (field ranges + spec expressions) over inputs.
        cons = g.const(1)
        for f in gm.inputs:
            tlo, thi = f.type_range()
            for i in range(f.count):
                n = self.in_nodes[(f.name, i)]
                if f.lo > tlo:
                    cons = g.band_b(cons, g.op("ge", n, g.const(f.lo)))
                if f.hi < thi:
                    cons = g.band_b(cons, g.op("le", n, g.const(f.hi)))
        cx = _SymExec(g, mod_globals, gm.funcs, "<constraints>")
        for text in gm.constraints:
            node = cx.eval(ast.parse(text, mode="eval").body, dict(env), g.const(1))
            cons = g.band_b(cons, g.truth(node))
        self.constraints_ok = cons

        # Spec coverage bins over inputs + golden outputs.
        benv = dict(env)
        for f in gm.outputs:
            benv[f.name] = ([self.out_nodes[(f.name, i)] for i in range(f.count)]
                            if f.is_vector else self.out_nodes[(f.name, 0)])
        self.spec_bins = {}
        for name, text in gm.bins.items():
            node = cx.eval(ast.parse(text, mode="eval").body, dict(benv), g.const(1))
            self.spec_bins[name] = g.truth(node)

    # -- checks --------------------------------------------------------------
    def roots(self):
        r = list(self.out_nodes.values()) + [self.ok, self.constraints_ok]
        r += list(self.golden_covers.values()) + list(self.spec_bins.values())
        r += list(self.boundary_bins.values())
        return r

    def evaluate(self, vec):
        """Evaluate the translated graph (Python semantics) on one vector."""
        inputs = {}
        for f in self.gm.inputs:
            vals = vec[f.name] if f.is_vector else [vec[f.name]]
            for i, v in enumerate(vals):
                inputs[self.in_nodes[(f.name, i)].name] = int(v)
        vals, poison = self.g.evaluate(self.roots(), inputs)
        outs = {}
        for f in self.gm.outputs:
            elems = []
            for i in range(f.count):
                n = self.out_nodes[(f.name, i)]
                if n.id in poison:
                    raise GoldenError("output %s depends on a negative shift for this input" % f.name)
                elems.append(vals[n.id])
            outs[f.name] = elems if f.is_vector else elems[0]
        covers = {k for k, n in self.golden_covers.items() if vals[n.id]}
        bins = {k for k, n in self.spec_bins.items() if vals[n.id]}
        bins |= {k for k, n in self.boundary_bins.items() if vals[n.id]}
        return outs, covers, bins, bool(vals[self.ok.id]), bool(vals[self.constraints_ok.id])

    def stats(self):
        need = self.g.cone(self.roots())
        live = [n for n in self.g.nodes if n.id in need]
        muls = [n for n in live if n.op == "mul" and not any(a.const for a in n.args)]
        return {
            "nodes": len(live),
            "max_width": max([n.width for n in live] or [0]),
            "multipliers": ["%dx%d" % (n.args[0].width, n.args[1].width) for n in muls],
            "output_fit_proven_by_intervals": self.fit_proven,
            "boundary_bins": len(self.boundary_bins),
            "warnings": sorted(set(self.g.warnings)),
        }

    # -- Verilog -------------------------------------------------------------
    def verilog(self, module):
        gm, g = self.gm, self.g
        need = g.cone(self.roots())
        lines = ["// Generated by forge_testgen.golden from %s:%s -- do not edit."
                 % (os.path.basename(gm.path), gm.func_name),
                 "// Bit-exact with the Python golden: every wire is signed and sized",
                 "// from an exact interval of the values it can hold.",
                 "module %s (" % module]
        ports = []
        for f in gm.inputs:
            ports.append("  input  %s[%d:0] g_%s" % ("signed " if f.signed and not f.is_vector else "",
                                                    f.total_bits - 1, f.name))
        for f in gm.outputs:
            ports.append("  output %s[%d:0] g_%s" % ("signed " if f.signed and not f.is_vector else "",
                                                    f.total_bits - 1, f.name))
        ports.append("  output ok")
        ports.append("  output constraints_ok")
        for k in sorted(self.golden_covers):
            ports.append("  output gcov_%s" % _vname(k))
        for k in sorted(self.spec_bins):
            ports.append("  output bin_%s" % _vname(k))
        for k in sorted(self.boundary_bins):
            ports.append("  output bnd_%s" % _vname(k))
        lines.append(",\n".join(ports))
        lines.append(");")
        by_name = {}
        for f in gm.inputs:
            for i in range(f.count):
                by_name[self.in_nodes[(f.name, i)].name] = (f, i)
        for n in g.nodes:
            if n.id not in need:
                continue
            w = n.width
            decl = "  wire signed [%d:0] n%d" % (w - 1, n.id)
            if n.op == "const":
                lines.append("%s = %s;" % (decl, vlit(n.val, w)))
                continue
            if n.op == "in":
                f, i = by_name[n.name]
                src = "g_%s" % f.name
                if f.is_vector:
                    src = "g_%s[%d +: %d]" % (f.name, i * f.width, f.width)
                if f.signed:
                    expr = "$signed(%s)" % src
                else:
                    expr = "$signed({1'b0, %s})" % src
                lines.append("%s = %s;" % (decl, expr))
                continue
            a = ["n%d" % x.id for x in n.args]
            if n.op in ("add", "sub", "mul", "band", "bor", "bxor"):
                sym = {"add": "+", "sub": "-", "mul": "*", "band": "&", "bor": "|", "bxor": "^"}[n.op]
                expr = "%s %s %s" % (a[0], sym, a[1])
            elif n.op == "neg":
                expr = "-%s" % a[0]
            elif n.op == "bnot":
                expr = "~%s" % a[0]
            elif n.op == "shl":
                expr = "%s <<< %s" % (a[0], a[1])
            elif n.op == "shr":
                expr = "%s >>> %s" % (a[0], a[1])
            elif n.op in CMP_OPS:
                sym = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "==", "ne": "!="}[n.op]
                expr = "{1'b0, (%s %s %s)}" % (a[0], sym, a[1])
            elif n.op == "lnot":
                expr = "{1'b0, ~(|%s)}" % a[0]
            elif n.op == "mux":
                expr = "(|%s) ? %s : %s" % (a[0], a[1], a[2])
            elif n.op == "min2":
                expr = "(%s < %s) ? %s : %s" % (a[1], a[0], a[1], a[0])
            elif n.op == "max2":
                expr = "(%s > %s) ? %s : %s" % (a[1], a[0], a[1], a[0])
            elif n.op == "abs":
                expr = "(%s < 0) ? -%s : %s" % (a[0], a[0], a[0])
            elif n.op == "clamp":
                expr = "(%s < %s) ? %s : ((%s > %s) ? %s : %s)" % (a[0], a[1], a[1], a[0], a[2], a[2], a[0])
            else:
                raise GoldenError("internal: cannot emit %s" % n.op)
            lines.append("%s;" % decl)
            lines.append("  assign n%d = %s;" % (n.id, expr))
        for f in gm.outputs:
            for i in range(f.count):
                n = self.out_nodes[(f.name, i)]
                ext = max(n.width, f.width)
                tmp = "o_%s_%d" % (f.name, i)
                lines.append("  wire signed [%d:0] %s = n%d;" % (ext - 1, tmp, n.id))
                dst = "g_%s[%d +: %d]" % (f.name, i * f.width, f.width) if f.is_vector else "g_%s" % f.name
                lines.append("  assign %s = %s[%d:0];" % (dst, tmp, f.width - 1))
        lines.append("  assign ok = n%d[0];" % self.ok.id)
        lines.append("  assign constraints_ok = n%d[0];" % self.constraints_ok.id)
        for k in sorted(self.golden_covers):
            lines.append("  assign gcov_%s = n%d[0];" % (_vname(k), self.golden_covers[k].id))
        for k in sorted(self.spec_bins):
            lines.append("  assign bin_%s = n%d[0];" % (_vname(k), self.spec_bins[k].id))
        for k in sorted(self.boundary_bins):
            lines.append("  assign bnd_%s = n%d[0];" % (_vname(k), self.boundary_bins[k].id))
        lines.append("endmodule")
        return "\n".join(lines) + "\n"


def _vname(name):
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    return out
