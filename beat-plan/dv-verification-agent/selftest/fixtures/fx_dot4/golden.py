"""Golden model for the fx_dot4 self-test fixture (not Forge, not Build 6)."""
from dvagent import gm


def dot4(x):
    a = gm.lanes(x["a"], 4, 8, signed=True)
    b = gm.lanes(x["b"], 4, 8, signed=True)
    total = x["bias"] + sum(ai * bi for ai, bi in zip(a, b))
    return {"y": gm.wrap(total, 32)}
