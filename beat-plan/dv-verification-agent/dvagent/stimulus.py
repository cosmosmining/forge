"""Stimulus generation.

Per data input port the generator mixes three kinds of value:
  corner  - range ends, 0, +-1, powers of two near the top, 0x55../0xAA.. patterns
  uniform - uniform over the legal range
  small   - small magnitudes, which make ties, carries and rounding edges likely
It also adds the cross product of corner values (capped), every input
combination when the input domain is small, directed beats from the manifest,
and counterexample beats found by formal (see formal.py).

For handshake blocks it also makes idle gaps before input beats and an
out_ready stall pattern, all from one seeded RNG so runs are reproducible.
"""

from __future__ import annotations

import itertools
import json
import os
import random
from dataclasses import dataclass, field

from . import gm


@dataclass
class PortGen:
    name: str
    width: int
    signed: bool
    lo: int
    hi: int
    lanes: int = 1
    lane_signed: bool = True
    lane_lo: int = 0
    lane_hi: int = 0
    values: list | None = None
    corners_extra: list = field(default_factory=list)
    hold: bool = False

    @property
    def lane_width(self) -> int:
        return self.width // self.lanes

    def domain_size(self) -> int:
        if self.values:
            return len(self.values)
        if self.lanes > 1:
            return (self.lane_hi - self.lane_lo + 1) ** self.lanes
        return self.hi - self.lo + 1

    def all_values(self):
        if self.values:
            return list(self.values)
        if self.lanes > 1:
            lane_vals = range(self.lane_lo, self.lane_hi + 1)
            return [self._from_lanes(c) for c in itertools.product(lane_vals, repeat=self.lanes)]
        return list(range(self.lo, self.hi + 1))

    def _from_lanes(self, lane_vals) -> int:
        raw = gm.pack(lane_vals, self.lane_width)
        return gm.to_signed(raw, self.width) if self.signed else raw


def make_portgens(ports, manifest) -> list:
    """PortGen for every data input (everything except clock/reset/valid/ready)."""
    gens = []
    hold_all = not manifest.stimulus.get("junk_when_idle", True)
    for p in ports:
        if p.direction != "input" or p.name in manifest.control_inputs:
            continue
        cfg = manifest.port_cfg.get(p.name, {})
        signed = bool(cfg.get("signed", p.signed))
        lo_full, hi_full = (gm.smin(p.width), gm.smax(p.width)) if signed else (0, gm.mask(p.width))
        lo, hi = cfg.get("range", [lo_full, hi_full])
        lo, hi = int(lo), int(hi)
        if not (lo_full <= lo <= hi <= hi_full):
            raise ValueError(f"port {p.name}: range [{lo}, {hi}] outside [{lo_full}, {hi_full}]")
        n_lanes = int(cfg.get("lanes", 1))
        if n_lanes < 1 or p.width % n_lanes:
            raise ValueError(f"port {p.name}: width {p.width} not divisible into {n_lanes} lanes")
        lw = p.width // n_lanes
        lane_signed = bool(cfg.get("lane_signed", True))
        llo_full, lhi_full = (gm.smin(lw), gm.smax(lw)) if lane_signed else (0, gm.mask(lw))
        llo, lhi = cfg.get("lane_range", [llo_full, lhi_full])
        values = cfg.get("values")
        if p.name == manifest.in_last:
            values = values or [0, 1]
        g = PortGen(name=p.name, width=p.width, signed=signed, lo=lo, hi=hi,
                    lanes=n_lanes, lane_signed=lane_signed, lane_lo=int(llo), lane_hi=int(lhi),
                    values=[int(v) for v in values] if values else None,
                    corners_extra=[int(v) for v in cfg.get("corners", [])],
                    hold=hold_all or bool(cfg.get("hold", False)))
        gens.append(g)
    return gens


# ---- value pickers -----------------------------------------------------------

def scalar_corners(lo: int, hi: int, width: int, signed: bool, extra=()) -> list:
    c = {lo, hi, lo + 1, hi - 1, 0, 1, -1, 2, -2}
    for k in range(max(0, width - 3), width + 1):
        c |= {1 << k, (1 << k) - 1, -(1 << k), -(1 << k) + 1}
    k = width // 2
    c |= {1 << k, (1 << k) - 1, -(1 << k)}
    for pat in ("01", "10"):
        raw = int((pat * width)[:width], 2)
        c.add(gm.to_signed(raw, width) if signed else raw)
    c |= set(extra)
    return sorted(v for v in c if lo <= v <= hi)


def _small(rng, lo, hi, width):
    k = max(1, width // 4)
    a, b = max(lo, -(1 << k)), min(hi, 1 << k)
    if a > b:  # range does not reach zero: stay near the closer end
        if lo > 0:
            a, b = lo, min(hi, lo + (1 << k))
        else:
            a, b = max(lo, hi - (1 << k)), hi
    return rng.randint(a, b)


def _pick_scalar(rng, mode, lo, hi, width, signed, corners):
    if mode == "corner":
        return rng.choice(corners)
    if mode == "small":
        return _small(rng, lo, hi, width)
    return rng.randint(lo, hi)


def pick(rng, g: PortGen, mode: str) -> int:
    if g.values:
        return rng.choice(g.values)
    if g.lanes > 1:
        lw = g.lane_width
        lc = scalar_corners(g.lane_lo, g.lane_hi, lw, g.lane_signed)
        lane_vals = []
        for _ in range(g.lanes):
            lane_mode = mode if rng.random() < 0.75 else rng.choice(["corner", "uniform", "small"])
            lane_vals.append(_pick_scalar(rng, lane_mode, g.lane_lo, g.lane_hi, lw, g.lane_signed, lc))
        return g._from_lanes(lane_vals)
    corners = scalar_corners(g.lo, g.hi, g.width, g.signed, g.corners_extra)
    return _pick_scalar(rng, mode, g.lo, g.hi, g.width, g.signed, corners)


def corner_set(g: PortGen) -> list:
    if g.values:
        return list(g.values)
    if g.lanes > 1:
        lc = scalar_corners(g.lane_lo, g.lane_hi, g.lane_width, g.lane_signed)
        uniform_lanes = [g._from_lanes([v] * g.lanes) for v in lc]
        return sorted(set(uniform_lanes))
    return scalar_corners(g.lo, g.hi, g.width, g.signed, g.corners_extra)


def _mode(rng, mix) -> str:
    r = rng.random() * sum(mix.values())
    for k, w in mix.items():
        if r < w:
            return k
        r -= w
    return "uniform"


# ---- beat sets ---------------------------------------------------------------

@dataclass
class Stimulus:
    beats: list                 # list of {port: int}
    gaps: list                  # idle cycles before each beat
    ready: list                 # out_ready per cycle after reset (empty = always 1)
    sources: dict               # how many beats came from each source
    seed: int = 0
    gens: dict = field(default_factory=dict)   # port name -> PortGen


def load_directed(path: str | None, base_dir: str) -> list:
    if not path:
        return []
    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if not os.path.isfile(full):
        return []
    with open(full) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("beats", [])


def _check_beat(beat: dict, gens: list, where: str) -> dict:
    out = {}
    for g in gens:
        if g.name not in beat:
            raise ValueError(f"{where}: beat {beat} lacks port {g.name}")
        v = int(beat[g.name])
        lo, hi = (gm.smin(g.width), gm.smax(g.width)) if g.signed else (0, gm.mask(g.width))
        if g.signed and v > hi:  # given as raw bits
            v = gm.to_signed(v, g.width)
        if not (lo <= v <= hi):
            raise ValueError(f"{where}: {g.name}={beat[g.name]} does not fit {g.width} bits")
        out[g.name] = v
    return out


def map_beats(gens, cfg, seed, directed, cex) -> tuple:
    """Independent beats for map-style golden models."""
    rng = random.Random(seed)
    beats, src = [], {}

    def add(lst, name):
        beats.extend(lst)
        src[name] = src.get(name, 0) + len(lst)

    add([_check_beat(b, gens, "directed") for b in directed], "directed")
    add([_check_beat(b, gens, "formal-cex") for b in cex], "formal_counterexample")

    domain = 1
    for g in gens:
        domain *= g.domain_size()
    if domain <= int(cfg.get("exhaustive_max", 0)):
        combos = itertools.product(*[g.all_values() for g in gens])
        add([dict(zip([g.name for g in gens], c)) for c in combos], "exhaustive")
        return beats, src, True

    csets = [corner_set(g) for g in gens]
    n_cross = 1
    for c in csets:
        n_cross *= len(c)
    cross_max = int(cfg.get("corner_cross_max", 4096))
    if n_cross <= cross_max:
        add([dict(zip([g.name for g in gens], c)) for c in itertools.product(*csets)], "corner_cross")
    else:
        add([{g.name: rng.choice(cs) for g, cs in zip(gens, csets)} for _ in range(cross_max // 4)],
            "corner_sample")
    rnd = []
    for _ in range(int(cfg.get("vectors", 2000))):
        rnd.append({g.name: pick(rng, g, _mode(rng, cfg["mix"])) for g in gens})
    add(rnd, "random_mix")
    return beats, src, False


def stream_beats(gens, cfg, seed, last_port, directed, cex) -> tuple:
    """Packets of beats for stream-style golden models."""
    rng = random.Random(seed)
    beats, src = [], {}
    max_len = max(1, int(cfg.get("max_packet", 16)))
    mix = dict(cfg["mix"])
    mix.setdefault("repeat", 0.15)

    def add_packet(pkt, name):
        if last_port:
            for i, b in enumerate(pkt):
                b[last_port] = 1 if i == len(pkt) - 1 else 0
        beats.extend(pkt)
        src[name] = src.get(name, 0) + 1

    for pkt in directed:
        add_packet([_check_beat({**b, **({last_port: 0} if last_port else {})}, gens, "directed")
                    for b in pkt], "directed_packets")
    for pkt in cex:
        add_packet([_check_beat({**b, **({last_port: 0} if last_port else {})}, gens, "formal-cex")
                    for b in pkt], "formal_counterexample_packets")

    data_gens = [g for g in gens if g.name != last_port]
    # every corner value of every port at least once, at both packet lengths 1 and max_len
    for g in (data_gens if cfg.get("corner_packets", True) else []):
        for v in corner_set(g):
            for n in sorted({1, max_len}):
                pkt = []
                for _ in range(n):
                    b = {h.name: pick(rng, h, "uniform") for h in data_gens}
                    b[g.name] = v
                    pkt.append(b)
                add_packet(pkt, "corner_packets")
    for _ in range(int(cfg.get("packets", 150))):
        r = rng.random()
        if r < 0.15 or max_len == 1:
            n = 1
        elif r < 0.30:
            n = max_len
        else:
            n = rng.randint(min(2, max_len), max_len)
        mode = _mode(rng, mix)
        if mode == "repeat":
            one = {g.name: pick(rng, g, rng.choice(["corner", "small", "uniform"])) for g in data_gens}
            pkt = [dict(one) for _ in range(n)]
        else:
            pkt = [{g.name: pick(rng, g, mode) for g in data_gens} for _ in range(n)]
        add_packet(pkt, f"random_{mode}_packets")
    return beats, src


def gaps_and_ready(n_beats: int, cfg: dict, seed: int, has_in_valid: bool, has_out_ready: bool):
    rng = random.Random(seed * 7919 + 17)
    gaps = [0] * n_beats
    p_gap = float(cfg.get("in_gap_prob", 0.0)) if has_in_valid else 0.0
    if p_gap > 0:
        for i in range(n_beats):
            if rng.random() < p_gap:
                gaps[i] = rng.choice([1, 1, 1, 2, 2, 3, 5, 8])
    ready = []
    p_stall = float(cfg.get("out_stall_prob", 0.0)) if has_out_ready else 0.0
    if p_stall > 0:
        n_cycles = 2 * (n_beats + sum(gaps)) + 64
        while len(ready) < n_cycles:
            if rng.random() < 0.03:
                ready.extend([0] * rng.randint(8, 24))  # long stall: fills pipelines
            else:
                ready.append(0 if rng.random() < p_stall else 1)
    return gaps, ready


def build(manifest, ports, seed: int, cex: list | None = None) -> Stimulus:
    gens = make_portgens(ports, manifest)
    cfg = manifest.stimulus
    directed = load_directed(cfg.get("directed"), manifest.base_dir)
    cex = cex or []
    if manifest.golden_style == "map":
        beats, src, _ = map_beats(gens, cfg, seed, directed, cex)
    else:
        beats, src = stream_beats(gens, cfg, seed, manifest.in_last, directed, cex)
    gaps, ready = gaps_and_ready(len(beats), cfg, seed, bool(manifest.in_valid), bool(manifest.out_ready))
    return Stimulus(beats=beats, gaps=gaps, ready=ready, sources=src, seed=seed,
                    gens={g.name: g for g in gens})
