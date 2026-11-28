"""Design and platform configuration (TOML).

A design config names the *golden* inputs that the agent must never change:
the synthesized netlist (or RTL), the sign-off SDC, the target clock period
and, optionally, a fixed die.  Everything the agent is allowed to change lives
in the recipe (see recipe.py).
"""
from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


def _resolve(value: str, base: Path) -> Path:
    expanded = os.path.expandvars(value)
    if "$" in expanded:
        raise ConfigError(
            f"unresolved environment variable in path {value!r}; "
            "run scripts/env.sh or export the variable first")
    p = Path(expanded)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Platform:
    name: str
    tech_lef: Path
    std_cell_lef: Path
    liberty: Path
    site: str
    pdn_cfg: Path
    tracks: Path
    layer_rc: Path
    rcx_rules: Path | None
    io_hor_layer: str
    io_ver_layer: str
    tapcell_args: str
    tielo_port: str
    tiehi_port: str
    dont_use: list[str]
    filler_cells: str
    min_routing_layer: str
    max_routing_layer: str
    signal_layers: str
    clock_layers: str
    macro_halo: list[float]
    tie_separation: float
    diode_cell: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Platform":
        data = tomllib.loads(path.read_text())["platform"]
        base = _resolve(data.get("dir", "."), path.parent)

        def f(key):
            return _resolve(data[key], base)

        return cls(
            name=data["name"],
            tech_lef=f("tech_lef"),
            std_cell_lef=f("std_cell_lef"),
            liberty=f("liberty"),
            site=data["site"],
            pdn_cfg=f("pdn_cfg"),
            tracks=f("tracks"),
            layer_rc=f("layer_rc"),
            rcx_rules=f("rcx_rules") if data.get("rcx_rules") else None,
            io_hor_layer=data["io_hor_layer"],
            io_ver_layer=data["io_ver_layer"],
            tapcell_args=data["tapcell_args"],
            tielo_port=data["tielo_port"],
            tiehi_port=data["tiehi_port"],
            dont_use=list(data.get("dont_use", [])),
            filler_cells=data["filler_cells"],
            min_routing_layer=data["min_routing_layer"],
            max_routing_layer=data["max_routing_layer"],
            signal_layers=data["signal_layers"],
            clock_layers=data["clock_layers"],
            macro_halo=list(data.get("macro_halo", [22.4, 15.12])),
            tie_separation=float(data.get("tie_separation", 5)),
            diode_cell=data.get("diode_cell"),
        )


@dataclass
class Design:
    name: str
    top: str
    platform: Platform
    netlist: Path
    sdc: Path
    target_period_ns: float
    config_path: Path
    sdc_prelude: Path | None = None
    die_area: list[float] | None = None
    core_area: list[float] | None = None
    floorplan_fixed: bool = True
    max_area_growth: float = 0.10
    extra_lef: list[Path] = field(default_factory=list)
    extra_lib: list[Path] = field(default_factory=list)
    knobs: dict = field(default_factory=dict)
    rtl: list[Path] = field(default_factory=list)
    description: str = ""
    is_standin: bool = False

    @classmethod
    def load(cls, path: Path | str) -> "Design":
        path = Path(path).resolve()
        raw = tomllib.loads(path.read_text())
        d = raw["design"]
        base = path.parent
        platform = Platform.load(_resolve(d["platform"], base))
        design = cls(
            name=d["name"],
            top=d["top"],
            platform=platform,
            netlist=_resolve(d["netlist"], base),
            sdc=_resolve(d["sdc"], base),
            target_period_ns=float(d["target_period_ns"]),
            config_path=path,
            sdc_prelude=_resolve(d["sdc_prelude"], base) if d.get("sdc_prelude") else None,
            die_area=[float(x) for x in d["die_area"]] if d.get("die_area") else None,
            core_area=[float(x) for x in d["core_area"]] if d.get("core_area") else None,
            floorplan_fixed=bool(d.get("floorplan_fixed", True)),
            max_area_growth=float(d.get("max_area_growth", 0.10)),
            extra_lef=[_resolve(x, base) for x in d.get("extra_lef", [])],
            extra_lib=[_resolve(x, base) for x in d.get("extra_lib", [])],
            knobs=dict(raw.get("knobs", {})),
            rtl=[_resolve(x, base) for x in d.get("rtl", [])],
            description=d.get("description", ""),
            is_standin=bool(d.get("is_standin", False)),
        )
        design.check()
        return design

    def check(self) -> None:
        missing = [p for p in [self.netlist, self.sdc, self.platform.liberty,
                               self.platform.tech_lef, self.platform.std_cell_lef,
                               *self.extra_lef, *self.extra_lib]
                   if not p.exists()]
        if self.sdc_prelude and not self.sdc_prelude.exists():
            missing.append(self.sdc_prelude)
        if missing:
            raise ConfigError("missing input files: " + ", ".join(map(str, missing)))
        if (self.die_area is None) != (self.core_area is None):
            raise ConfigError("give both die_area and core_area, or neither")

    def golden_fingerprint(self) -> dict:
        """Hashes of everything that defines 'the same problem'.

        The agent records these at baseline and re-checks them at every
        sign-off: if any of them changes, the result does not count.
        """
        fp = {
            "netlist_sha256": sha256_file(self.netlist),
            "sdc_sha256": sha256_file(self.sdc),
            "liberty_sha256": sha256_file(self.platform.liberty),
            "target_period_ns": self.target_period_ns,
        }
        if self.sdc_prelude:
            fp["sdc_prelude_sha256"] = sha256_file(self.sdc_prelude)
        return fp
