"""Bit-exact comparison of observed output beats against golden output beats.

This is done in Python from the testbench's dump, independently of the
testbench's own `!==` check; the two must agree or the run is INCOMPLETE.
Each mismatch carries a triage hint (rounding, sign, saturation, stuck, ...).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import gm


@dataclass
class Mismatch:
    idx: int
    port: str
    expected: int
    got: str           # hex as printed by the simulator (may contain x/z)
    got_int: int | None
    xor: int | None
    hint: str

    def as_dict(self):
        return {"idx": self.idx, "port": self.port, "expected": self.expected,
                "expected_hex": None, "got": self.got, "got_int": self.got_int,
                "xor_hex": None if self.xor is None else hex(self.xor), "hint": self.hint}


@dataclass
class CompareResult:
    n_expected: int
    n_observed: int
    mismatch_beats: int
    x_beats: int
    missing: int
    extra: int
    mismatches: list = field(default_factory=list)  # first few Mismatch records

    @property
    def ok(self) -> bool:
        return self.mismatch_beats == 0 and self.x_beats == 0 and self.missing == 0 and self.extra == 0


def read_dump(path: str, n_ports: int) -> list:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) != n_ports + 1:
                continue
            rows.append((int(parts[0]), parts[1:]))
    return rows


def _hint(exp: int, got: int, width: int, signed: bool) -> str:
    if got is None:
        return "X/Z on output: uninitialised state, missing reset, or undriven logic"
    e_raw, g_raw = exp & gm.mask(width), got & gm.mask(width)
    x = e_raw ^ g_raw
    g_val = gm.to_signed(g_raw, width) if signed else g_raw
    e_val = gm.to_signed(e_raw, width) if signed else e_raw
    if g_raw == 0 and e_raw != 0:
        return "output is zero: not updated, cleared too early, or wrong select"
    if abs(g_val - e_val) == 1:
        return "off by one: rounding constant, rounding direction or truncation"
    if signed and e_val in (gm.smin(width), gm.smax(width)):
        return "golden value is saturated: check clamp bounds and overflow detection"
    if signed and g_val in (gm.smin(width), gm.smax(width)):
        return "RTL saturated but golden did not: clamp bound or compare wrong"
    if x == (1 << (width - 1)):
        return "only the sign bit differs: signedness or sign extension"
    if x and (x & -x) >= (1 << (width // 2)):
        return "only high bits differ: sign extension, overflow width or carry"
    if x and x.bit_length() <= max(2, width // 4):
        return "only low bits differ: rounding, shift amount or truncation"
    if signed and g_val == -e_val:
        return "sign flipped: negation or subtract/add swapped"
    return "value differs: check the datapath against the golden model"


def compare(expected: list, dump_rows: list, out_ports: list, max_report: int = 10) -> CompareResult:
    names = [p.name for p in out_ports]
    mism, mism_beats, x_beats, extra = [], 0, 0, 0
    seen = 0
    for idx, fields in dump_rows:
        if idx >= len(expected):
            extra += 1
            continue
        seen += 1
        bad, has_x = False, False
        for p, raw in zip(out_ports, fields):
            exp = expected[idx][p.name]
            if any(c in raw for c in "xXzZ"):
                has_x = True
                bad = True
                if len(mism) < max_report:
                    mism.append(Mismatch(idx, p.name, exp, raw, None, None, _hint(exp, None, p.width, p.signed)))
                continue
            got = int(raw, 16)
            if (exp & gm.mask(p.width)) != (got & gm.mask(p.width)):
                bad = True
                if len(mism) < max_report:
                    g_val = gm.to_signed(got, p.width) if p.signed else got
                    mism.append(Mismatch(idx, p.name, exp, raw, g_val,
                                         (exp & gm.mask(p.width)) ^ got, _hint(exp, got, p.width, p.signed)))
        if bad:
            mism_beats += 1
        if has_x:
            x_beats += 1
    missing = max(0, len(expected) - seen)
    _ = names
    return CompareResult(len(expected), len(dump_rows), mism_beats, x_beats, missing, extra, mism)
