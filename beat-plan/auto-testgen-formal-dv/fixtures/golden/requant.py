"""Golden model for the `requant` FIXTURE (written in this session to exercise
forge_testgen; it is NOT a Forge Build 6 block).

int32 accumulator -> int8:  y = sat8(round_half_up(acc * mult / 2**shift) + zp)
"""


def requant(acc, mult, shift, zp):
    prod = acc * mult
    scaled = rshift_round(prod, shift)
    y = scaled + zp
    cover("sat_hi", y > 127)
    cover("sat_lo", y < -128)
    cover("round_tie", shift > 0 and (prod & ((1 << shift) - 1)) == ((1 << shift) >> 1))
    cover("neg_round_tie", shift > 0 and prod < 0 and (prod & ((1 << shift) - 1)) == ((1 << shift) >> 1))
    return {"y": sat(y, 8)}
