"""Golden for the `argmax8` FIXTURE (not a Forge Build 6 block)."""


def argmax8(x):
    best = 0
    for i in range(1, 8):
        if x[i] > x[best]:
            best = i
    cover("winner_tied", sum(int(v == x[best]) for v in x) >= 2)
    cover("winner_last", best == 7)
    return {"idx": best, "vmax": x[best]}
