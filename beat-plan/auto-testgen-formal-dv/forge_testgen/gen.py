"""Directed + constrained-random test generation and functional coverage."""

import ast
import random


class GenError(Exception):
    pass


def golden_cover_names(gm):
    """Names used in cover("name", ...) anywhere in the golden source."""
    names = set()
    for node in ast.walk(gm.tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "cover"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.add(node.args[0].value)
    return sorted(names)


PROTO_BINS = {
    "proto.backpressure": "bp",        # out_valid && !out_ready seen
    "proto.input_stall": "install",    # in_valid && !in_ready seen
    "proto.b2b_in": "b2b_in",          # inputs accepted on consecutive cycles
    "proto.b2b_out": "b2b_out",        # outputs on consecutive cycles
}


class Coverage:
    def __init__(self, spec):
        self.spec, self.gm = spec, spec.model
        self.data_bins = list(spec.bins)
        self.golden_bins = ["golden." + n for n in golden_cover_names(self.gm)]
        self.tr = self.gm.translate()
        self.boundary_bins = sorted(self.tr.boundary_bins)
        self.boundary_desc = dict(self.tr.boundary_desc)
        self.proto_bins = []
        if spec.kind == "stream":
            self.proto_bins = [b for b in PROTO_BINS
                               if not (b == "proto.input_stall" and not spec.stream.get("in_ready"))
                               and not (b == "proto.backpressure" and not spec.stream.get("out_ready"))]
            if spec.stream.get("capacity"):
                self.proto_bins.append("proto.full")
        self.hits = {b: 0 for b in self.all_bins}
        self.first = {}
        self.excluded = {}  # bin -> reason (formally unreachable etc.)

    @property
    def all_bins(self):
        return self.data_bins + self.golden_bins + self.boundary_bins + self.proto_bins

    def add(self, vec, out, gcov, origin):
        new = []
        for b in self.gm.bin_hits(vec, out):
            if self.hits[b] == 0:
                new.append(b)
                self.first[b] = origin
            self.hits[b] += 1
        for g in gcov:
            b = "golden." + g
            if b in self.hits:
                if self.hits[b] == 0:
                    new.append(b)
                    self.first[b] = origin
                self.hits[b] += 1
        if self.boundary_bins:
            for b in self.tr.evaluate(vec)[2]:
                if b.startswith("boundary."):
                    if self.hits[b] == 0:
                        new.append(b)
                        self.first[b] = origin
                    self.hits[b] += 1
        return new

    def add_proto(self, counts, origin):
        for b in self.proto_bins:
            if b == "proto.full":
                n = int(counts.get("max_inflight", 0) >= int(self.spec.stream["capacity"]))
            else:
                n = counts.get(PROTO_BINS[b], 0)
            if n and self.hits[b] == 0:
                self.first[b] = origin
            self.hits[b] += n

    def hit_by(self, b, vec, out, gcov):
        if b.startswith("golden."):
            return b[7:] in gcov
        if b.startswith("boundary."):
            return b in self.tr.evaluate(vec)[2]
        code = self.gm._bin_code[b]
        return bool(eval(code, self.gm.namespace(vec, out)))

    def holes(self, kinds=("data", "golden", "boundary", "proto")):
        pool = []
        if "data" in kinds:
            pool += self.data_bins
        if "golden" in kinds:
            pool += self.golden_bins
        if "boundary" in kinds:
            pool += self.boundary_bins
        if "proto" in kinds:
            pool += self.proto_bins
        return [b for b in pool if self.hits[b] == 0 and b not in self.excluded]

    def summary(self):
        considered = [b for b in self.all_bins if b not in self.excluded]
        hit = [b for b in considered if self.hits[b] > 0]
        return {
            "bins_total": len(self.all_bins),
            "bins_excluded_unreachable": len(self.excluded),
            "bins_considered": len(considered),
            "bins_hit": len(hit),
            "coverage_pct": round(100.0 * len(hit) / len(considered), 2) if considered else 100.0,
            "holes": [b for b in considered if self.hits[b] == 0],
            "by_kind": {kind: "%d/%d" % (sum(1 for b in bins if self.hits[b] > 0 and b not in self.excluded),
                                         sum(1 for b in bins if b not in self.excluded))
                        for kind, bins in (("data", self.data_bins), ("golden", self.golden_bins),
                                           ("boundary", self.boundary_bins), ("protocol", self.proto_bins))},
            "excluded": dict(self.excluded),
            "first_hit_by": {b: self.first.get(b) for b in hit},
        }


class Generator:
    def __init__(self, spec, seed=1):
        self.spec, self.gm = spec, spec.model
        self.seed = seed
        self.rnd = random.Random(seed)
        self.pools = {f.name: self._pool(f) for f in spec.inputs}
        self.dropped = []

    # -- value pools ---------------------------------------------------------
    @staticmethod
    def _decode(f, bits):
        bits &= (1 << f.width) - 1
        if f.signed and bits >> (f.width - 1):
            bits -= 1 << f.width
        return bits

    def _pool(self, f):
        lo, hi = f.lo, f.hi
        cand = {lo, lo + 1, hi - 1, hi, 0, 1, -1, (lo + hi) // 2}
        for k in range(f.width + 1):
            for v in (1 << k, (1 << k) - 1, -(1 << k), -(1 << k) + 1):
                cand.add(v)
        cand.add(self._decode(f, int("01" * f.width, 2)))
        cand.add(self._decode(f, int("10" * f.width, 2)))
        return sorted(v for v in cand if lo <= v <= hi)

    @staticmethod
    def corners(f):
        lo, hi = f.lo, f.hi
        c = [lo, lo + 1, -1, 0, 1, (lo + hi) // 2, hi - 1, hi]
        out = []
        for v in c:
            if lo <= v <= hi and v not in out:
                out.append(v)
        return out

    @staticmethod
    def nominal(f):
        if f.lo <= 1 <= f.hi:
            return 1
        if f.lo <= 0 <= f.hi:
            return 0
        return f.lo

    def _elem(self, f, mode=None):
        lo, hi = f.lo, f.hi
        r = self.rnd.random()
        if mode == "corner" or r < 0.15:
            return self.rnd.choice(self.pools[f.name])
        if r < 0.5:
            return self.rnd.randint(lo, hi)
        span = max(abs(lo), abs(hi))
        nb = self.rnd.randint(0, span.bit_length())
        mag = self.rnd.randint(0, (1 << nb) - 1) if nb else 0
        v = -mag if (lo < 0 and self.rnd.random() < 0.5) else mag
        return min(max(v, lo), hi)

    def value(self, f, mode=None):
        if f.is_vector:
            if self.rnd.random() < 0.1:
                pats = self.vector_patterns(f)
                return list(self.rnd.choice(pats))
            return [self._elem(f, mode) for _ in range(f.count)]
        return self._elem(f, mode)

    def random_vec(self, mode=None, fixed=None, tries=500):
        for _ in range(tries):
            vec = {f.name: self.value(f, mode) for f in self.spec.inputs}
            if fixed:
                vec.update(fixed)
            if self.gm.legal(vec):
                return vec
        if fixed:
            return None
        raise GenError("constraints too tight: %d random draws all violated them" % tries)

    # -- directed ------------------------------------------------------------
    def vector_patterns(self, f):
        n, lo, hi = f.count, f.lo, f.hi
        zero = 0 if lo <= 0 <= hi else lo
        pats = [[lo] * n, [hi] * n, [zero] * n, [self.nominal(f)] * n,
                [lo if i % 2 == 0 else hi for i in range(n)],
                [hi if i % 2 == 0 else lo for i in range(n)]]
        for i in range(n):
            pats.append([hi if j == i else lo for j in range(n)])
            pats.append([lo if j == i else hi for j in range(n)])
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        if len(pairs) > 40:
            pairs = [(i, i + 1) for i in range(n - 1)] + [(0, n - 1)]
        for i, j in pairs:
            pats.append([hi if k in (i, j) else lo for k in range(n)])          # tie at max
            mid = (lo + hi) // 2
            pats.append([mid if k in (i, j) else lo for k in range(n)])         # tie, not extreme
        step = (hi - lo) // max(1, n - 1)
        pats.append([lo + k * step for k in range(n)])                          # ramp up
        pats.append([hi - k * step for k in range(n)])                          # ramp down
        out = []
        for p in pats:
            if p not in out:
                out.append(p)
        return out

    def _pairwise(self, params):
        """Greedy all-pairs covering array over [(name, [values])]."""
        uncovered = set()
        for a in range(len(params)):
            for b in range(a + 1, len(params)):
                for va in range(len(params[a][1])):
                    for vb in range(len(params[b][1])):
                        uncovered.add((a, va, b, vb))
        rows = []
        while uncovered:
            row = [None] * len(params)
            a, va, b, vb = min(uncovered)
            row[a], row[b] = va, vb
            for k in range(len(params)):
                if row[k] is not None:
                    continue
                best, best_score = 0, -1
                for vk in range(len(params[k][1])):
                    score = 0
                    for j in range(len(params)):
                        if row[j] is None or j == k:
                            continue
                        key = (j, row[j], k, vk) if j < k else (k, vk, j, row[j])
                        score += key in uncovered
                    if score > best_score:
                        best, best_score = vk, score
                row[k] = best
            for x in range(len(params)):
                for y in range(x + 1, len(params)):
                    uncovered.discard((x, row[x], y, row[y]))
            rows.append({params[k][0]: params[k][1][row[k]] for k in range(len(params))})
        return rows

    def directed(self):
        spec = self.spec
        base = {f.name: ([self.nominal(f)] * f.count if f.is_vector else self.nominal(f))
                for f in spec.inputs}
        raw = [("directed.base", dict(base), set())]
        for f in spec.inputs:
            values = self.vector_patterns(f) if f.is_vector else self.corners(f)
            for v in values:
                vec = dict(base)
                vec[f.name] = list(v) if f.is_vector else v
                raw.append(("directed.ofat.%s" % f.name, vec, {f.name}))
        scalars = [f for f in spec.inputs if not f.is_vector]
        if len(scalars) >= 2:
            params = []
            for f in scalars:
                vals = [f.lo, f.hi]
                mid = 0 if f.lo < 0 < f.hi else (f.lo + f.hi) // 2
                if mid not in vals:
                    vals.append(mid)
                params.append((f.name, vals))
            for row in self._pairwise(params):
                vec = dict(base)
                vec.update(row)
                raw.append(("directed.pairwise", vec, set(row)))
        for i, entry in enumerate(spec.directed):
            vec = dict(base)
            vec.update({k: v for k, v in entry.items() if k != "note"})
            raw.append(("directed.spec[%d]" % i, vec, set(entry) - {"note"}))
        out, seen = [], set()
        for origin, vec, focus in raw:
            if not self.gm.legal(vec):
                fixed = {k: vec[k] for k in focus}
                vec = self.random_vec(mode="corner", fixed=fixed, tries=300)
                if vec is None:
                    self.dropped.append((origin, fixed))
                    continue
            key = repr(sorted(vec.items()))
            if key in seen:
                continue
            seen.add(key)
            out.append((origin, vec))
        return out

    def random(self, n):
        return [("random.seed%d" % self.seed, self.random_vec()) for _ in range(n)]

    def target(self, cov, bin_name, budget=20000):
        """Golden-guided search for a vector that hits `bin_name`."""
        for i in range(budget):
            vec = self.random_vec(mode="corner" if i % 2 else None)
            out, gcov = self.gm.evaluate(vec)
            if cov.hit_by(bin_name, vec, out, gcov):
                return vec
        return None

    # -- stream protocol scenarios ------------------------------------------
    def scenarios(self, n_txn):
        """[(name, gaps per txn, ready schedule)] for valid/ready blocks."""
        rnd = random.Random(self.seed * 7919 + 1)
        has_ready = bool(self.spec.stream.get("out_ready"))
        sc = [("b2b", [0] * n_txn, [1])]
        if has_ready:
            sc.append(("long_backpressure", [0] * n_txn, [0] * 20 + [1] * 5))
            sc.append(("ready_toggle", [0] * n_txn, [1, 0]))
        sc.append(("sparse_valid", [rnd.choice([0, 1, 2, 5]) for _ in range(n_txn)], [1]))
        rdy = [1 if (not has_ready or rnd.random() < 0.7) else 0 for _ in range(509)]
        sc.append(("random_mix", [0 if rnd.random() < 0.5 else rnd.randint(1, 4) for _ in range(n_txn)], rdy))
        return sc
