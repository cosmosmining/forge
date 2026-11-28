"""Golden model for the fx_argmax_stream self-test fixture (not Forge, not Build 6)."""


def argmax(beats):
    out = []
    best, best_i, i = None, 0, 0
    for bt in beats:
        v = bt["x"]
        if best is None or v > best:
            best, best_i = v, i
        if bt["in_last"]:
            out.append({"idx": best_i, "max_val": best})
            best, best_i, i = None, 0, 0
        else:
            i += 1
    return out
