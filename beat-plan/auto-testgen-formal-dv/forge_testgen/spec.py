"""Block spec loader + spec-vs-RTL port cross-check.

A spec is a TOML (or JSON) file describing one block: its ports as typed
fields, legal input ranges / constraints, the golden model, the interface
kind (comb or valid/ready stream) and optional coverage bins.  See
fixtures/specs/*.toml for examples and README.md for the full format.
"""

import json
import os

from . import tools
from .golden import Field, GoldenModel, GoldenError, _vname

try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    try:
        import tomli as _toml
    except ImportError:
        _toml = None


class SpecError(Exception):
    pass


STREAM_KEYS = ("clk", "rst", "in_valid", "out_valid")


def _load_raw(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if path.endswith(".json"):
        return json.loads(data.decode())
    if _toml is None:
        raise SpecError("TOML spec needs Python >= 3.11 (tomllib) or `pip install tomli`; "
                        "or use a .json spec")
    return _toml.loads(data.decode())


def _field(d, where):
    try:
        return Field(d["name"], d["width"], d.get("signed", False), d.get("count", 1),
                     d.get("port"), *(d.get("range") or (None, None)))
    except KeyError as ex:
        raise SpecError("%s: missing key %s" % (where, ex))
    except GoldenError as ex:
        raise SpecError("%s: %s" % (where, ex))


class Spec:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        raw = _load_raw(self.path)
        b = raw.get("block") or {}
        for k in ("name", "top", "kind", "rtl", "golden"):
            if k not in b:
                raise SpecError("%s: [block] needs %r" % (path, k))
        self.name, self.top, self.kind = b["name"], b["top"], b["kind"]
        if self.kind not in ("comb", "stream"):
            raise SpecError("block.kind must be 'comb' or 'stream'")
        self.rtl = [self._abs(p) for p in b["rtl"]]
        gpath, _, gfn = b["golden"].partition(":")
        self.golden_path = self._abs(gpath)
        self.golden_fn = gfn or self.name
        self.note = b.get("note", "")
        self.inputs = [_field(d, "input %d" % i) for i, d in enumerate(raw.get("input", []))]
        self.outputs = [_field(d, "output %d" % i) for i, d in enumerate(raw.get("output", []))]
        if not self.inputs or not self.outputs:
            raise SpecError("spec needs at least one [[input]] and one [[output]]")
        names = [f.name for f in self.inputs + self.outputs]
        if len(set(names)) != len(names):
            raise SpecError("field names must be unique")
        self.constraints = list((raw.get("constraints") or {}).get("expr", []))
        cov = raw.get("coverage") or {}
        self.user_bins = dict(cov.get("bins", {}))
        self.auto_bins_enabled = cov.get("auto", True)
        self.gen = dict(raw.get("gen") or {})
        self.directed = list(raw.get("directed") or [])
        self.stream = dict(raw.get("stream") or {})
        self.formal = dict(raw.get("formal") or {})
        self.mutation = dict(raw.get("mutation") or {})
        if self.kind == "stream":
            for k in STREAM_KEYS:
                if k not in self.stream:
                    raise SpecError("[stream] needs %r" % k)
            self.stream.setdefault("rst_active", "high")
            self.stream.setdefault("in_ready", None)
            self.stream.setdefault("out_ready", None)
            self.stream.setdefault("max_latency", 16)
        self.bins = self._make_bins()
        self._model = None

    def _abs(self, p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.dir, p))

    # -- coverage bins (DSL expressions over inputs + outputs) --------------
    def _make_bins(self):
        bins = {}
        if self.auto_bins_enabled:
            for kind, fields in (("in", self.inputs), ("out", self.outputs)):
                for f in fields:
                    lo, hi = (f.lo, f.hi) if kind == "in" else f.type_range()
                    elems = ["%s[%d]" % (f.name, i) for i in range(f.count)] if f.is_vector else [f.name]
                    for i, e in enumerate(elems):
                        tag = "%s.%s%s" % (kind, f.name, "[%d]" % i if f.is_vector else "")
                        bins[tag + ".min"] = "%s == %d" % (e, lo)
                        bins[tag + ".max"] = "%s == %d" % (e, hi)
                        if lo < 0 < hi:
                            bins[tag + ".zero"] = "%s == 0" % e
                    if f.is_vector and f.count > 1:
                        bins["%s.%s.all_equal" % (kind, f.name)] = "min(%s) == max(%s)" % (f.name, f.name)
                        bins["%s.%s.tie_at_max" % (kind, f.name)] = (
                            "sum(int(v == max(%s)) for v in %s) >= 2" % (f.name, f.name))
        for k, v in self.user_bins.items():
            bins["bin." + k] = v
        seen = {}
        for k in bins:
            vk = _vname(k)
            if vk in seen:
                raise SpecError("coverage bins %r and %r collide" % (seen[vk], k))
            seen[vk] = k
        return bins

    @property
    def model(self):
        if self._model is None:
            if not os.path.exists(self.golden_path):
                raise SpecError("golden model file missing: %s" % self.golden_path)
            self._model = GoldenModel(self.golden_path, self.golden_fn, self.inputs, self.outputs,
                                      self.constraints, self.bins)
        return self._model

    # -- spec vs RTL ----------------------------------------------------------
    def rtl_ports(self, workdir):
        tools.require("yosys")
        missing = [p for p in self.rtl if not os.path.exists(p)]
        if missing:
            raise SpecError("RTL file(s) missing: %s" % ", ".join(missing))
        workdir = os.path.abspath(workdir)
        out = os.path.join(workdir, "ports.json")
        script = "read_verilog -sv %s; hierarchy -top %s; proc; write_json %s" % (
            " ".join('"%s"' % p for p in self.rtl), self.top, out)
        rc, log, _ = tools.run(["yosys", "-q", "-p", script], cwd=workdir, timeout=300)
        if rc != 0:
            raise SpecError("yosys could not read the RTL:\n" + log[-3000:])
        with open(out) as fh:
            mod = json.load(fh)["modules"][self.top]
        ports = {}
        for name, p in mod["ports"].items():
            ports[name] = {"dir": p["direction"], "width": len(p["bits"]),
                           "signed": bool(p.get("signed", 0))}
        return ports

    def check_against_rtl(self, workdir):
        """Return a list of human-readable spec/RTL disagreements (empty = consistent)."""
        ports = self.rtl_ports(workdir)
        issues = []
        used = set()

        def expect(port, direction, width, signed=None):
            used.add(port)
            p = ports.get(port)
            if p is None:
                issues.append("spec port %r not found in RTL module %s" % (port, self.top))
                return
            if p["dir"] != direction:
                issues.append("port %s is %s in RTL, spec says %s" % (port, p["dir"], direction))
            if p["width"] != width:
                issues.append("port %s is %d bits in RTL, spec says %d" % (port, p["width"], width))
            if signed is not None and p["signed"] != signed:
                issues.append("note: port %s signedness differs (RTL %s, spec %s); bits are compared "
                              "as-is, so this only matters for readability" % (
                                  port, "signed" if p["signed"] else "unsigned",
                                  "signed" if signed else "unsigned"))

        for f in self.inputs:
            expect(f.port, "input", f.total_bits, f.signed if not f.is_vector else None)
        for f in self.outputs:
            expect(f.port, "output", f.total_bits, f.signed if not f.is_vector else None)
        if self.kind == "stream":
            s = self.stream
            expect(s["clk"], "input", 1)
            expect(s["rst"], "input", 1)
            expect(s["in_valid"], "input", 1)
            expect(s["out_valid"], "output", 1)
            if s.get("in_ready"):
                expect(s["in_ready"], "output", 1)
            if s.get("out_ready"):
                expect(s["out_ready"], "input", 1)
        for name, p in ports.items():
            if name not in used:
                issues.append("RTL port %s (%s, %d bits) is not described by the spec" % (
                    name, p["dir"], p["width"]))
        return issues

    def summary(self):
        return {
            "name": self.name, "top": self.top, "kind": self.kind,
            "rtl": [os.path.relpath(p, self.dir) for p in self.rtl],
            "golden": "%s:%s" % (os.path.relpath(self.golden_path, self.dir), self.golden_fn),
            "inputs": [_fdesc(f) for f in self.inputs],
            "outputs": [_fdesc(f) for f in self.outputs],
            "constraints": self.constraints,
            "bins": len(self.bins),
            "note": self.note,
        }


def _fdesc(f):
    d = "%s:%s%d" % (f.name, "s" if f.signed else "u", f.width)
    if f.is_vector:
        d += "x%d" % f.count
    tlo, thi = f.type_range()
    if (f.lo, f.hi) != (tlo, thi):
        d += " in [%d,%d]" % (f.lo, f.hi)
    return d
