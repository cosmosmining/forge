"""The record: what the agent changed, why, and the before/after timing."""
from __future__ import annotations

import difflib
import json
from pathlib import Path

from . import tcl
from .recipe import STAGES, diff


def _f(v, fmt="{:+.4f}"):
    return "n/a" if v is None else fmt.format(v)


def script_diff(design, base_recipe: dict, final_recipe: dict) -> str:
    """Unified diff of the generated OpenROAD scripts + overlay, baseline -> final."""
    chunks = []
    for stage in STAGES:
        prev = None if stage == "floorplan" else Path(f"<run>/{STAGES[STAGES.index(stage) - 1]}")
        prev_odb = None if prev is None else prev / "x.odb"
        lib = Path("<run>/abc_dont_use.lib")
        a = tcl.stage_script(design, base_recipe, stage, prev_odb, Path(f"<run>/{stage}"), None, 1, lib)
        b = tcl.stage_script(design, final_recipe, stage, prev_odb, Path(f"<run>/{stage}"), None, 1, lib)
        d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), f"baseline/{stage}.tcl",
                                      f"final/{stage}.tcl", lineterm="", n=1))
        if d:
            chunks.append("\n".join(d))
    oa, ob = tcl.overlay_sdc(base_recipe), tcl.overlay_sdc(final_recipe)
    if oa != ob:
        chunks.append("\n".join(difflib.unified_diff(oa.splitlines(), ob.splitlines(),
                                                     "baseline/opt_constraints.sdc",
                                                     "final/opt_constraints.sdc", lineterm="")))
    return "\n".join(chunks)


ROWS = [
    ("Setup WNS (ns)", "wns_ns", "{:+.4f}"),
    ("Setup TNS (ns)", "tns_ns", "{:+.4f}"),
    ("Violating setup endpoints", "setup_violators", "{}"),
    ("Hold WNS (ns)", "hold_wns_ns", "{:+.4f}"),
    ("Violating hold endpoints", "hold_violators", "{}"),
    ("Routing DRC violations", "drc", "{}"),
    ("Antenna nets", "antenna_nets", "{}"),
    ("Slew/cap/fanout violations", "drv_violations", "{}"),
    ("Cell area (um^2)", "area_um2", "{:.1f}"),
    ("Total power (W, default activity)", "power_w", "{:.4e}"),
    ("Routed wirelength, GRT (um)", "wirelength_um", "{:.0f}"),
]


def write_markdown(record: dict, path: Path) -> None:
    d = record["design"]
    b, f = record["baseline"]["summary"], record["final"]["summary"]
    L = []
    title = f"# PnR timing-closure ledger: {d['name']}"
    L.append(title)
    if d["is_standin"]:
        L.append("\n> **STAND-IN, NOT BUILD 6.** " + d["description"] + "\n")
    L.append(f"- Target clock: **{d['target_period_ns']} ns** ({1000 / d['target_period_ns']:.1f} MHz), "
             f"fixed. Golden SDC sha256 `{d['fingerprint']['sdc_sha256'][:16]}...`, "
             f"netlist sha256 `{d['fingerprint']['netlist_sha256'][:16]}...`")
    L.append(f"- Tools: {record['tools']['openroad']} / {record['tools']['opensta']} / {record['tools']['yosys']}")
    L.append(f"- Started {record['started']}, finished {record['finished']}; "
             f"{record['evaluations']} flow evaluations, {record['rounds']} rounds")
    verdict = "**CLOSED**" if record["final"]["closed"] else "**NOT CLOSED**"
    L.append(f"\n## Verdict: {verdict}\n")
    L.append(record["final"]["verdict_detail"])
    L.append("\n| Metric (independent OpenSTA sign-off, golden SDC, RCX parasitics) | Before | After |")
    L.append("|---|---|---|")
    for label, key, fmt in ROWS:
        L.append(f"| {label} | {_f(b.get(key), fmt)} | {_f(f.get(key), fmt)} |")
    eq = record["final"].get("equivalence") or {}
    rp = record["final"].get("reproduction") or {}
    L.append("")
    L.append(f"- Logic equivalence, golden netlist vs routed netlist (Yosys): "
             f"**{'PASS' if eq.get('ok') else 'FAIL'}**, {eq.get('message', 'not run')}")
    if rp:
        L.append(f"- Reproduced from an empty cache with the final recipe: "
                 f"**{'yes' if rp.get('match') else 'NO'}** (WNS {_f(rp.get('wns_ns'))} ns, "
                 f"TNS {_f(rp.get('tns_ns'))} ns, hold {_f(rp.get('hold_wns_ns'))} ns)")
    L.append("- Guardrails on the final result: " + ", ".join(
        f"{c['name']}: {'ok' if c['ok'] else 'FAIL'}" for c in record["final"]["checks"]))

    L.append("\n## What the agent changed (accepted edits, in order)\n")
    if not record["accepted"]:
        L.append("Nothing was accepted.")
    for i, a in enumerate(record["accepted"], 1):
        ch = ", ".join(f"`{k}`: {v[0]!r} -> {v[1]!r}" for k, v in a["changes"].items())
        L.append(f"{i}. **{a['action']}** ({a['category']}), round {a['round']}: {ch}")
        L.append(f"   - Why: {a['rationale']}")
        if a.get("evidence"):
            L.append(f"   - Evidence: {'; '.join(a['evidence'])}")
        L.append(f"   - Effect: WNS {a['before']['wns_ns']:+.4f} -> {a['after']['wns_ns']:+.4f} ns, "
                 f"TNS {a['before']['tns_ns']:+.4f} -> {a['after']['tns_ns']:+.4f} ns, "
                 f"hold {a['before']['hold_wns_ns']:+.4f} -> {a['after']['hold_wns_ns']:+.4f} ns, "
                 f"area {a['before']['area_um2']:.1f} -> {a['after']['area_um2']:.1f} um^2")

    bd = record["baseline"]["diagnosis"]
    L.append("\n## Baseline diagnosis\n")
    wp = bd.get("worst_path") or {}
    if wp:
        L.append(f"- Worst path: `{wp['startpoint']}` -> `{wp['endpoint']}` ({wp['type']}), slack "
                 f"{wp['slack_ns']:+.4f} ns, {wp['stages']} stages, cell {wp['cell_delay_ns']:.4f} ns + "
                 f"wire {wp['wire_delay_ns']:.4f} ns (wire {100 * wp['wire_fraction']:.0f}%), max fanout "
                 f"{wp['max_fanout']}, max slew {wp['max_slew_ns']:.4f} ns, launch/capture clock latency "
                 f"{wp['launch_latency_ns']:.4f}/{wp['capture_latency_ns']:.4f} ns")
    for t, e in (bd.get("tags") or {}).items():
        L.append(f"- `{t}`: {e}")

    L.append("\n## Every candidate evaluated\n")
    L.append("| Round | Action | Category | Change | WNS (ns) | TNS (ns) | Hold WNS (ns) | DRC | Area (um^2) | Guardrails | Decision |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in record["candidates"]:
        s = c.get("summary") or {}
        ch = "; ".join(f"{k}={v[1]!r}" for k, v in c["changes"].items())
        if len(ch) > 90:
            ch = ch[:87] + "..."
        g = "ok" if c.get("valid") else ("; ".join(x["name"] for x in c.get("checks", []) if not x["ok"])
                                          or c.get("error", "error"))
        L.append(f"| {c['round']} | {c['action']} | {c['category']} | `{ch}` | {_f(s.get('wns_ns'))} | "
                 f"{_f(s.get('tns_ns'))} | {_f(s.get('hold_wns_ns'))} | {s.get('drc', 'n/a')} | "
                 f"{_f(s.get('area_um2'), '{:.1f}')} | {g} | {c['decision']} |")

    if record.get("rtl_proposals"):
        L.append("\n## RTL proposals (recorded, not applied)\n")
        for p in record["rtl_proposals"]:
            L.append(f"- **{p['title']}**: {p['detail']}")

    L.append("\n## Generated-script diff, baseline -> final\n")
    L.append("```diff\n" + (record.get("script_diff") or "(no difference)") + "\n```")
    L.append("\n## Final recipe changes vs baseline\n")
    L.append("```json\n" + json.dumps(record["final"]["recipe_diff"], indent=1, default=list) + "\n```")
    path.write_text("\n".join(L) + "\n")


def recipe_diff(base: dict, final: dict) -> dict:
    return diff(base, final)
