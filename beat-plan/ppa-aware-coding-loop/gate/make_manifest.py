#!/usr/bin/env python3
"""Writes gate/blocks.json: the six blocks, their golden sources (with SHA-256),
stimulus specs, simulation length and formal depth. Run once before locking.

Golden sources come from OpenROAD-flow-scripts tag 26Q3
(commit adeb389e7fbf06ef6a939a895c014f69e6f7aa00). They are not copied into
this repository; the gate reads them from the pinned ORFS checkout and refuses
to run if any hash differs.
"""
import hashlib
import json
import os

ORFS_ROOT = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
ORFS_COMMIT = "adeb389e7fbf06ef6a939a895c014f69e6f7aa00"
SRC = "flow/designs/src"

RISCV_FILES = ["adder", "alu", "aludec", "controller", "datapath", "flopenr", "flopens", "flopr",
               "magcompare2b", "magcompare2c", "magcompare32", "maindec", "mux2", "mux3", "mux4",
               "mux5", "mux8", "regfile", "riscv", "shifter", "signext"]

BLOCKS = {
    "gcd": {
        "top": "gcd",
        "golden_files": [SRC + "/gcd/gcd.v"],
        "stim": {"clock": "clk", "inputs": {
            "reset": {"kind": "reset", "active": 1, "type": "sync", "init_cycles": 3, "p": 0.0005},
            "req_val": {"kind": "bit", "p1": 0.5},
            "resp_rdy": {"kind": "bit", "p1": 0.7},
            "req_msg": {"kind": "data", "fields": [16, 16], "corner_pct": 45}}},
        "sim": {"cycles": 40000, "seeds": [1, 2, 3, 4, 5]},
        "formal": {"depth": 40},
    },
    "aes_cipher_top": {
        "top": "aes_cipher_top",
        "golden_files": [SRC + "/aes/" + f for f in
                         ["aes_cipher_top.v", "aes_key_expand_128.v", "aes_rcon.v", "aes_sbox.v", "timescale.v"]],
        "include_only": ["timescale.v"],
        "stim": {"clock": "clk", "inputs": {
            "rst": {"kind": "reset", "active": 0, "type": "sync", "init_cycles": 3, "p": 0.0005},
            "ld": {"kind": "bit", "p1": 0.07},
            "key": {"kind": "data", "corner_pct": 10},
            "text_in": {"kind": "data", "corner_pct": 10}}},
        "sim": {"cycles": 30000, "seeds": [1, 2, 3, 4]},
        "formal": {"depth": 14},
    },
    "riscv": {
        "top": "riscv",
        "golden_files": [SRC + "/riscv32i/%s.v" % f for f in RISCV_FILES],
        "stim": {"clock": "clk", "inputs": {
            "reset": {"kind": "reset", "active": 1, "type": "async", "init_cycles": 3, "p": 0.0003,
                      "p_glitch": 0.0003},
            "instr": {"kind": "riscv_instr"},
            "readdata": {"kind": "data", "corner_pct": 30}}},
        "sim": {"cycles": 30000, "seeds": [1, 2, 3, 4]},
        "formal": {"depth": 8},
    },
    "dct_mac": {
        "top": "dct_mac",
        "golden_files": [SRC + "/jpeg/dct_mac.v"],
        "stim": {"clock": "clk", "inputs": {
            "ena": {"kind": "bit", "p1": 0.85},
            "dclr": {"kind": "bit", "p1": 0.15},
            "din": {"kind": "data", "corner_pct": 30},
            "coef": {"kind": "data", "corner_pct": 30}}},
        "sim": {"cycles": 50000, "seeds": [1, 2, 3, 4, 5]},
        "formal": {"depth": 12},
    },
    "dctub": {
        "top": "dctub",
        "golden_files": [SRC + "/jpeg/" + f for f in
                         ["dctub.v", "dctu.v", "dct_mac.v", "include/dct_cos_table.v"]],
        "include_only": ["dct_cos_table.v"],
        "stim": {"clock": "clk", "inputs": {
            "ena": {"kind": "bit", "p1": 0.85},
            "ddgo": {"kind": "bit", "p1": 0.1},
            "x": {"kind": "data", "corner_pct": 10},
            "y": {"kind": "data", "corner_pct": 10},
            "ddin": {"kind": "data", "corner_pct": 30}}},
        "sim": {"cycles": 30000, "seeds": [1, 2, 3, 4]},
        "formal": {"depth": 10},
    },
    "jpeg_qnr": {
        "top": "jpeg_qnr",
        "golden_files": [SRC + "/jpeg/" + f for f in ["jpeg_qnr.v", "div_su.v", "div_uu.v"]],
        "stim": {"clock": "clk", "inputs": {
            "rst": {"kind": "reset", "active": 0, "type": "async", "init_cycles": 3, "p": 0.0005,
                    "p_glitch": 0.0005},
            "ena": {"kind": "bit", "p1": 0.9},
            "dstrb": {"kind": "bit", "p1": 0.03},
            "din": {"kind": "data", "corner_pct": 30},
            "qnt_val": {"kind": "data", "corner_pct": 30}}},
        "sim": {"cycles": 50000, "seeds": [1, 2, 3, 4, 5]},
        "formal": {"depth": 24},
    },
}


def main():
    for name, b in BLOCKS.items():
        b["golden_sha256"] = {}
        for rel in b["golden_files"]:
            with open(os.path.join(ORFS_ROOT, rel), "rb") as f:
                b["golden_sha256"][rel] = hashlib.sha256(f.read()).hexdigest()
    out = {"orfs_commit": ORFS_COMMIT, "blocks": BLOCKS}
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "blocks.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", os.path.join(here, "blocks.json"))


if __name__ == "__main__":
    main()
