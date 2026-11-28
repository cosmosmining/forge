#!/usr/bin/env python3
"""Builds the exact prompt given to the RTL-editing agent for one (arm, block).
Both arms get AGENT_PROMPT.md word for word; only the arm section and the
assignment numbers differ. Writes loop/prompts/<arm>_<block>.md and prints it."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ARM_SECTION = {
    "prelayout": """You are in the **prelayout** arm. Your only PPA feedback is
`eval --mode prelayout`: yosys/ABC synthesis at T1 followed by static timing on
the synthesized netlist, with no placement, no wires and ideal clocks (the kind
of number a synthesis-level gate reports). You have up to 20 such evaluations.
`eval --mode postroute` is not available to you, and you must not obtain
post-route information any other way (do not read `targets/`, baseline files,
other arms' files or run directories).

You will still be judged post-route. Pre-layout numbers leave out wire
capacitance, clock-tree skew and the sizing and buffering that the flow does
after placement, so they can be off in either direction. How much margin to
keep is your decision. The area and power references in your reports are
pre-layout numbers of the original RTL.""",
    "postroute": """You are in the **postroute** arm. You have two kinds of feedback:

- `eval --mode postroute`: the full flow at T1 (floorplan, placement, clock
  tree, global and detailed routing, OpenRCX extraction), then static timing
  with the extracted parasitics and propagated clocks. Up to 6 evaluations.
  This is exactly how you will be judged.
- `eval --mode prelayout`: synthesis + static timing without wires, ideal
  clocks. Fast; up to 20 evaluations; use it to screen ideas.

Pre-layout numbers leave out wires, clock skew and the sizing and buffering the
flow does after placement, so they can be off in either direction; decide with
the post-route numbers. Do not read `targets/`, baseline files, other arms'
files or run directories.""",
}

ASSIGNMENT = """
## Your assignment

- arm: **{arm}**
- block: **{block}** (top module `{top}`). `loop.py new` copies the original RTL into a candidate.
- repository root: `/home/user/forge` — run every command from there.
- T0 = {t0:.4f} ns (the fastest clock the original RTL closes at after routing).
  **Target T1 = {t1:.4f} ns.**
- Budget: {budget}.
- Long commands: a gate run or a post-route evaluation can take longer than the
  10-minute limit of a foreground Bash call (several agents share 4 CPU cores).
  Run `gate` and `eval` with the Bash tool's `run_in_background: true` and wait
  for the completion notification; read the printed report or the saved
  `feedback.txt` / `gate_report.json` afterwards. Do not poll with sleep loops.
- Do not use git. Do not start other agents. Work autonomously; nobody will
  answer questions.
- When you finish, reply with: the final candidate id, one line per candidate
  (what changed, gate verdict, key numbers), and what you think limited the result.
"""


def build(arm, block):
    tmpl = open(os.path.join(HERE, "AGENT_PROMPT.md")).read()
    tg = json.load(open(os.path.join(ROOT, "targets", "targets.json")))["blocks"][block]
    flow = json.load(open(os.path.join(ROOT, "flow", "flow_config.json")))["blocks"][block]
    budget = ("20 pre-layout evaluations" if arm == "prelayout"
              else "6 post-route evaluations and 20 pre-layout evaluations")
    text = tmpl.replace("{ARM_SECTION}", ARM_SECTION[arm])
    text += ASSIGNMENT.format(arm=arm, block=block, top=flow["top"], t0=tg["T0_ns"], t1=tg["T1_ns"],
                              budget=budget)
    os.makedirs(os.path.join(HERE, "prompts"), exist_ok=True)
    open(os.path.join(HERE, "prompts", "%s_%s.md" % (arm, block)), "w").write(text)
    return text


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
