"""Golden model for the fx_pwl self-test fixture (not Forge, not Build 6)."""
from dvagent import gm

# (base, slope) per segment, segment = x[15:13]
TABLE = [(0, 24), (768, 30), (1728, 31), (2720, 32),
         (-18000, -2), (-18064, 3), (-17968, 60), (-16048, 100)]


def pwl(x):
    raw = gm.to_unsigned(x["x"], 16)
    seg = raw >> 13
    frac = raw & 0x1FFF
    base, slope = TABLE[seg]
    return {"y": gm.wrap(base + ((slope * frac) >> 8), 16)}
