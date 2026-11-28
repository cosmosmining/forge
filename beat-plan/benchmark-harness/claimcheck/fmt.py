"""Number formatting for reports. Formatting never changes a number's label."""

from __future__ import annotations

import math

_SI = ((1e18, "E"), (1e15, "P"), (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"))


def sig(x: float, digits: int = 3) -> str:
    """Round to `digits` significant figures, with thousands separators and no exponent."""
    if x == 0:
        return "0"
    mag = int(math.floor(math.log10(abs(x))))
    decimals = max(0, digits - 1 - mag)
    return "{:,.{d}f}".format(round(x, decimals), d=decimals)


def si(x: float, unit: str, digits: int = 3) -> str:
    for scale, prefix in _SI:
        if abs(x) >= scale:
            return "%s %s%s" % (sig(x / scale, digits), prefix, unit)
    return "%s %s" % (sig(x, digits), unit)


def plain(value) -> str:
    """Exact rendering of a registry value: integers get separators, floats keep their digits."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer() and abs(value) >= 1000):
        return "{:,}".format(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def number(n: dict, value=None) -> str:
    """Display a registry number: its own 'display' string if it has one, else the value."""
    if n.get("display"):
        return n["display"]
    v = n.get("value") if value is None else value
    if v is None:
        return "none"
    if isinstance(v, float) and not v.is_integer():
        s = "%.6g" % v
        return s if "e" not in s else sig(v, 4)
    return plain(v)
