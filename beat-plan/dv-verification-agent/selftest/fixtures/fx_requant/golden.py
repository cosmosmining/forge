"""Golden model for the fx_requant self-test fixture (not Forge, not Build 6)."""
from dvagent import gm


def requant(x):
    acc, mult, shift, zp = x["acc"], x["mult"], x["shift"], x["zp"]
    prod = acc * mult
    if shift == 0:
        shifted = prod
    else:
        shifted = (prod + (1 << (shift - 1))) >> shift
    biased = shifted + zp
    if biased > gm.smax(8):
        y = gm.smax(8)
    elif biased < gm.smin(8):
        y = gm.smin(8)
    else:
        y = biased
    return {"y": y}
