"""Block manifest: what the agent needs to know about one RTL block.

A manifest is TOML (Python 3.11+, or with `tomli` installed) or JSON with the
same keys. Paths are relative to the manifest's directory. See
docs in README.md and the fixtures under selftest/fixtures for examples.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - older Pythons
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None

PROTOCOLS = ("comb", "pipe", "stream")
GOLDEN_STYLES = ("map", "stream")

DEFAULT_STIMULUS = {
    "vectors": 2000,          # map style: random beats (in addition to corners/directed)
    "packets": 150,           # stream style with in_last: number of packets
    "max_packet": 16,         # longest packet the generator makes
    "exhaustive_max": 65536,  # enumerate every input combination when the domain is this small
    "mix": {"corner": 0.30, "uniform": 0.45, "small": 0.25},
    "in_gap_prob": 0.30,      # chance of idle cycles before an input beat (needs in_valid)
    "out_stall_prob": 0.30,   # chance out_ready is low in a cycle (needs out_ready)
    "junk_when_idle": True,   # drive random data while in_valid is low
    "directed": None,         # optional JSON file of extra beats (map) or packets (stream)
    "corner_cross_max": 4096, # map style: full cross product of port corners up to this many beats
    "corner_packets": True,   # stream style: one packet per corner value of each port
}

DEFAULT_CHECKS = {
    "simulators": ["iverilog", "verilator"],
    "lint": True,
    "lint_strict": False,     # True: style warnings fail too
    "structural": True,       # yosys: latches, logic loops, multiple drivers
    "coverage": True,         # verilator line/toggle/branch coverage of the DUT
    "min_line_coverage": 0.0,     # below -> INCOMPLETE (0 = report only)
    "min_toggle_coverage": 0.0,
    "min_golden_coverage": 0.0,   # line coverage of the golden model itself
    "waivers": [],            # [{code=..., match=..., reason=...}], reason is mandatory
    "output_protocol": True,  # valid/ready outputs: valid and data hold until ready
    "sim_timeout_s": 300,
    "build_timeout_s": 600,
}

DEFAULT_FORMAL = {
    "enabled": False,
    "depth": 20,              # BMC depth in clock cycles for clocked blocks
    "engine": "smtbmc bitwuzla",   # measured once: depth-20 BMC ~1 s with bitwuzla, >150 s (timeout) with yices
    "txn_beats": 3,           # symbolic input beats in the (opt-in) transaction-level check
    "timeout_s": 300,
    "bmc_timeout_s": 120,     # counterexample search per surviving mutant
    "prove_timeout_s": 60,    # unbounded proof attempt after a clean BMC
    "prove_engine": "abc pdr",  # measured once: PDR proved a lockstep miter in 5 s where k-induction stayed UNKNOWN
    "extra_seeds": [2, 3, 4, 5, 6, 7, 8, 9],  # fresh random stimulus for cycle-level-only differences
    "txn_check": False,       # opt-in transaction-level BMC; measured: 118 s to find a known bug with
                              # 3 beats / depth 10 on fx_mac_stream, timeouts on equivalent cases
    "txn_depth": 10,
    "txn_timeout_s": 60,
}


class ManifestError(Exception):
    pass


@dataclass
class Manifest:
    path: str
    base_dir: str
    name: str
    top: str
    rtl: list
    include_dirs: list = field(default_factory=list)
    defines: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    protocol: str = "comb"
    clock: str | None = None
    reset: str | None = None
    reset_active_low: bool = True
    reset_cycles: int = 3
    latency: int = 0
    in_valid: str | None = None
    in_ready: str | None = None
    out_valid: str | None = None
    out_ready: str | None = None
    in_last: str | None = None
    timeout_cycles: int = 0
    port_cfg: dict = field(default_factory=dict)
    golden_model: str = ""
    golden_style: str = "map"
    stimulus: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    formal: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    # ---- derived helpers -------------------------------------------------
    @property
    def control_inputs(self) -> set:
        names = {self.clock, self.reset, self.in_valid, self.out_ready}
        return {n for n in names if n}

    @property
    def control_outputs(self) -> set:
        names = {self.in_ready, self.out_valid}
        return {n for n in names if n}

    def resolve(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(self.base_dir, rel))

    @property
    def rtl_paths(self) -> list:
        return [self.resolve(p) for p in self.rtl]

    @property
    def include_paths(self) -> list:
        return [self.resolve(p) for p in self.include_dirs]


def _none_if_empty(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _load_raw(path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".json"):
        return json.loads(data.decode("utf-8"))
    if _toml is None:
        raise ManifestError(
            "TOML manifests need Python 3.11+ (tomllib) or the tomli package; "
            "or write the manifest as JSON with the same keys")
    return _toml.loads(data.decode("utf-8"))


def _merge(defaults: dict, given: dict | None) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in (given or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load(path: str) -> Manifest:
    path = os.path.abspath(path)
    raw = _load_raw(path)
    base = os.path.dirname(path)
    blk = raw.get("block", {})
    itf = raw.get("interface", {})
    gold = raw.get("golden", {})

    for key in ("name", "top", "rtl"):
        if key not in blk:
            raise ManifestError(f"{path}: [block] needs '{key}'")
    if "model" not in gold:
        raise ManifestError(f"{path}: [golden] needs 'model' (file.py:function)")

    m = Manifest(
        path=path,
        base_dir=base,
        name=str(blk["name"]),
        top=str(blk["top"]),
        rtl=list(blk["rtl"]),
        include_dirs=list(blk.get("include_dirs", [])),
        defines=dict(blk.get("defines", {})),
        parameters=dict(blk.get("parameters", {})),
        protocol=str(itf.get("protocol", "comb")),
        clock=_none_if_empty(itf.get("clock")),
        reset=_none_if_empty(itf.get("reset")),
        reset_active_low=bool(itf.get("reset_active_low", True)),
        reset_cycles=int(itf.get("reset_cycles", 3)),
        latency=int(itf.get("latency", 0)),
        in_valid=_none_if_empty(itf.get("in_valid")),
        in_ready=_none_if_empty(itf.get("in_ready")),
        out_valid=_none_if_empty(itf.get("out_valid")),
        out_ready=_none_if_empty(itf.get("out_ready")),
        in_last=_none_if_empty(itf.get("in_last")),
        timeout_cycles=int(itf.get("timeout_cycles", 0)),
        port_cfg={k: dict(v) for k, v in raw.get("ports", {}).items()},
        golden_model=str(gold["model"]),
        golden_style=str(gold.get("style", "map")),
        stimulus=_merge(DEFAULT_STIMULUS, raw.get("stimulus")),
        checks=_merge(DEFAULT_CHECKS, raw.get("checks")),
        formal=_merge(DEFAULT_FORMAL, raw.get("formal")),
        raw=raw,
    )
    validate(m)
    return m


def validate(m: Manifest) -> None:
    errs = []
    if m.protocol not in PROTOCOLS:
        errs.append(f"interface.protocol must be one of {PROTOCOLS}, got {m.protocol!r}")
    if m.golden_style not in GOLDEN_STYLES:
        errs.append(f"golden.style must be one of {GOLDEN_STYLES}, got {m.golden_style!r}")
    if m.protocol == "comb":
        if m.golden_style != "map":
            errs.append("a comb block needs golden.style = 'map'")
        for k in ("clock", "in_valid", "in_ready", "out_valid", "out_ready"):
            if getattr(m, k):
                errs.append(f"a comb block cannot have interface.{k}")
    else:
        if not m.clock:
            errs.append(f"protocol {m.protocol!r} needs interface.clock")
    if m.protocol == "stream" and not (m.in_valid and m.out_valid):
        errs.append("protocol 'stream' needs in_valid and out_valid (ready signals optional)")
    if m.protocol == "pipe" and (m.in_ready or m.out_ready):
        errs.append("protocol 'pipe' has no ready signals; use 'stream'")
    if m.protocol == "pipe" and not m.out_valid and m.latency < 0:
        errs.append("interface.latency must be >= 0")
    if m.golden_style == "stream" and not m.out_valid:
        errs.append("golden.style = 'stream' needs interface.out_valid to know when outputs occur")
    if m.in_last and m.golden_style != "stream":
        errs.append("interface.in_last is only meaningful with golden.style = 'stream'")
    for w in m.checks.get("waivers", []):
        if not str(w.get("reason", "")).strip():
            errs.append(f"lint waiver {w} has no reason; every waiver must say why")
        if not str(w.get("code", "")).strip():
            errs.append(f"lint waiver {w} has no code")
    for p in m.rtl_paths:
        if not os.path.isfile(p):
            errs.append(f"RTL file not found: {p}")
    gm_file = m.golden_model.split(":")[0]
    if not os.path.isfile(m.resolve(gm_file)):
        errs.append(f"golden model file not found: {m.resolve(gm_file)}")
    if errs:
        raise ManifestError(f"{m.path}:\n  - " + "\n  - ".join(errs))
