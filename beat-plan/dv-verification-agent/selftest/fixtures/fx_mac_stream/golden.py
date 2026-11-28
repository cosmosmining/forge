"""Golden model for the fx_mac_stream self-test fixture (not Forge, not Build 6)."""
from dvagent import gm


def mac(beats):
    out, acc = [], 0
    for bt in beats:
        acc = gm.wrap(acc + bt["a"] * bt["b"], 32)
        if bt["in_last"]:
            out.append({"acc_out": acc})
            acc = 0
    return out
