"""Runtime helpers available inside golden-model functions.

Golden models are plain Python functions over Python ints (unbounded, two's
complement semantics for bitwise ops, floor semantics for >>).  Every helper
here is defined in terms of operators the translator in golden.py lowers in
exactly the same way, so `python golden(x)` and the generated Verilog
reference agree bit for bit.  Do not change a definition here without
changing its lowering in golden.py (tests/test_golden.py checks both).
"""

_COVER_SINK = None  # set by golden.GoldenModel.evaluate while a call runs


def clamp(x, lo, hi):
    """lo if x < lo else (hi if x > hi else x)."""
    return lo if x < lo else (hi if x > hi else x)


def sat(x, width, signed=True):
    """Saturate x to a `width`-bit signed or unsigned range."""
    if signed:
        return clamp(x, -(1 << (width - 1)), (1 << (width - 1)) - 1)
    return clamp(x, 0, (1 << width) - 1)


def wrap(x, width, signed=True):
    """Two's-complement wrap of x to `width` bits (what a narrow register keeps)."""
    mask = (1 << width) - 1
    if signed:
        half = 1 << (width - 1)
        return ((x + half) & mask) - half
    return x & mask


def rshift_round(x, s):
    """Arithmetic right shift by s with round-half-up (toward +inf).

    (x + ((1 << s) >> 1)) >> s  ==  x for s == 0, and
    floor((x + 2**(s-1)) / 2**s) for s > 0.  s must be >= 0.
    """
    return (x + ((1 << s) >> 1)) >> s


def cover(name, cond):
    """Record a golden-model coverage event.  No effect on the result."""
    if _COVER_SINK is not None and cond:
        _COVER_SINK.add(name)


EXPORTS = {
    "clamp": clamp,
    "sat": sat,
    "wrap": wrap,
    "rshift_round": rshift_round,
    "cover": cover,
}
