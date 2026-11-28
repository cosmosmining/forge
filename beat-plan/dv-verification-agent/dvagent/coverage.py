"""Verilator coverage (line, branch, toggle) restricted to the DUT's own files."""

from __future__ import annotations

import os
import re

_REC = re.compile(r"^C '(.*)' (\d+)\s*$")


def parse(path: str, dut_files: list) -> dict:
    """Return {"line": {...}, "branch": {...}, "toggle": {...}, "uncovered": [...]}"""
    want_abs = {os.path.realpath(f) for f in dut_files}
    want_base = {os.path.basename(f) for f in dut_files}
    stats = {k: {"hit": 0, "total": 0} for k in ("line", "branch", "toggle")}
    uncovered = []
    if not path or not os.path.isfile(path):
        return {"available": False, **stats, "uncovered": uncovered}
    with open(path, encoding="latin-1") as f:
        for raw in f:
            m = _REC.match(raw.rstrip("\n"))
            if not m:
                continue
            body, count = m.group(1), int(m.group(2))
            kv = {}
            for part in body.split("\x01"):
                if "\x02" in part:
                    k, v = part.split("\x02", 1)
                    kv[k] = v
            fname = kv.get("f", "")
            if os.path.realpath(fname) not in want_abs and os.path.basename(fname) not in want_base:
                continue
            page = kv.get("page", "")
            kind = "toggle" if page.startswith("v_toggle") else (
                "branch" if page.startswith("v_branch") else (
                    "line" if page.startswith("v_line") else None))
            if kind is None:
                continue
            stats[kind]["total"] += 1
            if count > 0:
                stats[kind]["hit"] += 1
            elif kind in ("line", "branch"):
                uncovered.append({"kind": kind, "file": os.path.basename(fname),
                                  "line": int(kv.get("l", 0) or 0), "what": kv.get("o", "")})
    for k in stats:
        t = stats[k]["total"]
        stats[k]["ratio"] = (stats[k]["hit"] / t) if t else None
    uncovered.sort(key=lambda u: (u["file"], u["line"]))
    return {"available": True, **stats, "uncovered": uncovered[:50]}
