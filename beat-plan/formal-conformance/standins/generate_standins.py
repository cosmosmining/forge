#!/usr/bin/env python3
"""Generate the stand-in blocks used to exercise the formal tool in this checkout.

WHY STAND-INS: the Forge generated blocks (the agent-written SystemVerilog for the
engine) are not present in this repository checkout, and no RTL may be invented.
So the formal tool is exercised on RTL produced by a real third-party generator,
the Amaranth HDL standard library. Nothing here was hand-written RTL: every .v file
is emitted by amaranth.back.verilog.convert from an Amaranth stdlib class.

These results say nothing about Forge hardware. They show that the tool runs on
machine-generated Verilog, that its properties can fail (mutation), and what its
evidence files look like.

Run with the venv that has amaranth installed:
    /opt/forge-oss-eda/bin/python standins/generate_standins.py
"""
import hashlib
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE / "rtl"

# (module name, amaranth class path, constructor kwargs, port attribute names)
BLOCKS = [
    ("syncfifo_w8_d4", "amaranth.lib.fifo.SyncFIFO", {"width": 8, "depth": 4},
     ["w_data", "w_rdy", "w_en", "w_level", "r_data", "r_rdy", "r_en", "r_level", "level"]),
    ("gray_encoder_w8", "amaranth.lib.coding.GrayEncoder", {"width": 8}, ["i", "o"]),
    ("gray_decoder_w8", "amaranth.lib.coding.GrayDecoder", {"width": 8}, ["i", "o"]),
]


def _load(path):
    mod_name, cls_name = path.rsplit(".", 1)
    with warnings.catch_warnings():
        # amaranth.lib.coding is deprecated in 0.5 (removal planned); it still ships and works.
        warnings.simplefilter("ignore", DeprecationWarning)
        module = __import__(mod_name, fromlist=[cls_name])
    return getattr(module, cls_name)


def main():
    import amaranth
    from amaranth.back import verilog

    RTL.mkdir(parents=True, exist_ok=True)
    records = []
    for name, cls_path, kwargs, ports in BLOCKS:
        cls = _load(cls_path)
        if "coding" in cls_path:
            inst = cls(kwargs["width"])
        else:
            inst = cls(**kwargs)
        text = verilog.convert(inst, name=name, ports=[getattr(inst, p) for p in ports],
                               emit_src=False)
        out = RTL / f"{name}.v"
        out.write_text(text)
        records.append({
            "module": name,
            "file": f"standins/rtl/{name}.v",
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "generator": f"{cls_path}({', '.join(f'{k}={v}' for k, v in kwargs.items())})",
            "ports_requested": ports,
        })
    import importlib.metadata as md
    prov = {
        "schema": "forge.standins.provenance/v1",
        "what": "Stand-in generated blocks for exercising the formal tool. NOT Forge blocks.",
        "generator": {
            "amaranth": md.version("amaranth"),
            "amaranth-yosys": md.version("amaranth-yosys"),
            "python": sys.version.split()[0],
            "call": "amaranth.back.verilog.convert(inst, name=..., ports=[...], emit_src=False)",
        },
        "hand_written_rtl": False,
        "blocks": records,
    }
    (HERE / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n")
    for r in records:
        print(f"{r['file']}  sha256={r['sha256'][:16]}  <- {r['generator']}")


if __name__ == "__main__":
    main()
