"""Golden model template. The golden model is the reference: derive it from the
integer model / spec, never from the RTL.

map style:    def model(beat: dict) -> dict          one output beat per input beat
stream style: def model(beats: list) -> list[dict]   whole input stream -> output beats

Values are Python ints in each port's signedness. Use the dvagent.gm helpers for
bit-accurate arithmetic; write saturation / rounding / special cases as explicit
branches so golden-model line coverage shows what the stimulus reached.
"""
from dvagent import gm


def my_model(beat):
    x = gm.lanes(beat["act"], 16, 8, signed=True)       # example: 16 int8 lanes
    acc = sum(x)
    if acc > gm.smax(16):
        acc = gm.smax(16)
    elif acc < gm.smin(16):
        acc = gm.smin(16)
    return {"sum": acc}
