"""Helpers for writing bit-accurate golden models in plain Python integers.

Golden models import these so that sign handling, lane packing, rounding and
saturation are written once and tested once (see tests/test_gm.py).

Conventions
- A port value is a Python int. Signed ports may be given as a signed value or
  as the raw two's-complement bit pattern; the agent normalises both.
- Packed lanes: lane 0 sits in the least significant bits.
- Python's >> on negative ints is an arithmetic (floor) shift, the same as
  SystemVerilog >>> on a signed operand.
"""

from __future__ import annotations


def mask(width: int) -> int:
    return (1 << width) - 1


def to_unsigned(v: int, width: int) -> int:
    return v & mask(width)


def to_signed(v: int, width: int) -> int:
    v &= mask(width)
    return v - (1 << width) if (v >> (width - 1)) & 1 else v


def wrap(v: int, width: int, signed: bool = True) -> int:
    """Two's-complement wrap-around, as a fixed-width register would do."""
    return to_signed(v, width) if signed else to_unsigned(v, width)


def smin(width: int) -> int:
    return -(1 << (width - 1))


def smax(width: int) -> int:
    return (1 << (width - 1)) - 1


def sat(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def sat_signed(v: int, width: int) -> int:
    return sat(v, smin(width), smax(width))


def sat_unsigned(v: int, width: int) -> int:
    return sat(v, 0, mask(width))


def lanes(v: int, n: int, width: int, signed: bool = True) -> list:
    """Unpack n lanes of `width` bits from integer v (lane 0 = LSBs)."""
    out = []
    for i in range(n):
        x = (v >> (i * width)) & mask(width)
        out.append(to_signed(x, width) if signed else x)
    return out


def pack(values, width: int) -> int:
    """Pack lane values (signed or unsigned) into one integer (lane 0 = LSBs)."""
    acc = 0
    for i, x in enumerate(values):
        acc |= (x & mask(width)) << (i * width)
    return acc


def sra(v: int, s: int) -> int:
    """Arithmetic shift right (floor division by 2**s)."""
    return v >> s


def shift_round_half_up(v: int, s: int) -> int:
    """(v + 2**(s-1)) >> s, the usual hardware rounding shift. s == 0 returns v."""
    if s == 0:
        return v
    return (v + (1 << (s - 1))) >> s
