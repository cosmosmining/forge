#!/usr/bin/env python3
"""cdc_check.py -- structural clock-domain-crossing check on a yosys JSON netlist.

Forge Feature 5 (timing-closure / clocking pack).

Netlist recipe (flows/run_cdc.sh does this):
    yosys -p "read_verilog -sv <files>; hierarchy -top <top>; proc; flatten;
              opt_dff; memory_collect; opt_clean; write_json <out>.json"
No opt_merge / memory_dff: those would merge duplicate synchronizers or fold a
capture flop into a memory read port and hide a crossing.

Every flop bit (and every memory write port) is an endpoint. For each endpoint we walk
its input cones backwards through combinational cells to flop outputs, memory read
data and primary inputs. A source in another clock domain is a crossing, and each
crossing gets exactly one class:

  SYNC        endpoint is the first flop of an ASYNC_REG chain, the source is one flop,
              with no logic between them, and the chain is >= --min-stages deep.
              A multi-bit chain group needs its source register marked (* cdc_gray *).
  QUALIFIED   data captured under an enable (or through a mux) whose control comes
              from a synchronizer output of this domain, within two flop stages
              (handshake capture, async FIFO memory read). Needs the max_delay
              constraint and a formal proof; both are in this pack.
  WAIVED      endpoint register carries (* cdc_waive = "reason" *). Listed, not hidden.
  ERROR       anything else: unsynchronized crossing, logic in front of a
              synchronizer, too few stages, binary bus through bit synchronizers.

Reset rule: an asynchronous reset pin must be driven by the last flop of a reset
bridge (flop marked (* cdc_reset_sync *)) of the same domain, or by a port declared
with --sync-reset port=domain. Raw resets may only enter reset bridges.

Exit status: 0 if no ERROR, 1 otherwise. --json writes the full report.
"""
import argparse
import json
import sys
from collections import defaultdict

FF_TYPES = {
    "$dff", "$dffe", "$adff", "$adffe", "$sdff", "$sdffe", "$sdffce",
    "$dffsr", "$dffsre", "$aldff", "$aldffe",
}
LATCH_TYPES = {"$dlatch", "$adlatch", "$dlatchsr", "$sr"}
ASYNC_RESET_PORTS = ("ARST", "CLR", "SET", "ALOAD", "AD")
DATA_PORTS = ("D", "EN", "SRST")
MUX_TYPES = {"$mux", "$pmux", "$bmux", "$_MUX_"}


def truthy(v):
    if isinstance(v, str):
        s = v.strip().strip('"').lower()
        if set(s) <= {"0", "1"} and s:
            return int(s, 2) != 0
        return s in ("true", "yes", "1")
    return bool(v)


class Netlist:
    def __init__(self, data, top):
        if top not in data["modules"]:
            raise SystemExit(f"top module {top} not in netlist")
        m = data["modules"][top]
        self.cells = m["cells"]
        self.ports = m["ports"]
        self.netnames = m["netnames"]
        self.driver = {}                     # bit -> (cell, port, index) or ("PI", port, index)
        self.bit_names = defaultdict(list)   # bit -> [(netname, index)]
        for pname, p in self.ports.items():
            if p["direction"] in ("input", "inout"):
                for i, b in enumerate(p["bits"]):
                    if isinstance(b, int):
                        self.driver[b] = ("PI", pname, i)
        for cname, c in self.cells.items():
            for port, bits in c["connections"].items():
                if c.get("port_directions", {}).get(port) == "output":
                    for i, b in enumerate(bits):
                        if isinstance(b, int):
                            self.driver[b] = (cname, port, i)
        for nname, n in self.netnames.items():
            for i, b in enumerate(n["bits"]):
                if isinstance(b, int):
                    self.bit_names[b].append((nname, i))

    def name_of(self, bit):
        names = self.bit_names.get(bit, [])
        if not names:
            return f"<bit {bit}>"
        # prefer user-visible names
        vis = [n for n in names if not self.netnames[n[0]].get("hide_name", 0)]
        nm, i = (vis or names)[0]
        width = len(self.netnames[nm]["bits"])
        return nm if width == 1 else f"{nm}[{i}]"

    def wire_attr(self, bit, key):
        """Value of attribute `key` (case-insensitive) on any net that holds this bit."""
        for nm, _ in self.bit_names.get(bit, []):
            for k, v in self.netnames[nm].get("attributes", {}).items():
                if k.lower() == key.lower():
                    return v
        return None


class Checker:
    def __init__(self, nl, min_stages, same_groups, sync_resets, input_domains):
        self.nl = nl
        self.min_stages = min_stages
        self.alias = {}
        for grp in same_groups:
            names = [x.strip() for x in grp.split(",") if x.strip()]
            for n in names:
                self.alias[n] = names[0]
        self.sync_resets = sync_resets        # port -> domain
        self.input_domains = input_domains    # port -> domain
        self.ff = {}                          # (cell, i) -> dict
        self.q_bit_to_ff = {}                 # bit -> (cell, i)
        self.mems = {}                        # cell -> dict
        self.findings = []
        self._collect()

    # ---------------------------------------------------------------- domains
    def clock_domain(self, bit):
        seen = 0
        while isinstance(bit, int) and seen < 32:
            seen += 1
            d = self.nl.driver.get(bit)
            if d is None:
                return "undriven:" + self.nl.name_of(bit)
            if d[0] == "PI":
                name = d[1]
                return self.alias.get(name, name)
            cell = self.nl.cells[d[0]]
            if cell["type"] in ("$not", "$_NOT_", "$buf", "$_BUF_", "$pos"):
                ins = cell["connections"].get("A")
                bit = ins[d[2]] if ins and len(ins) > d[2] else ins[0]
                continue
            nm = self.nl.name_of(bit)
            return self.alias.get("gen:" + nm, "gen:" + nm)
        return "const"

    # ---------------------------------------------------------------- collect
    def _collect(self):
        for cname, c in self.nl.cells.items():
            t = c["type"]
            conn = c["connections"]
            if t in LATCH_TYPES:
                self.findings.append(dict(level="ERROR", kind="latch", where=cname,
                                          msg=f"latch {cname} ({t}) in a CDC-checked design"))
                continue
            if t in FF_TYPES:
                dom = self.clock_domain(conn["CLK"][0])
                width = len(conn["Q"])
                for i in range(width):
                    qbit = conn["Q"][i]
                    entry = dict(cell=cname, i=i, domain=dom, q=qbit, inputs={})
                    for p in DATA_PORTS + ASYNC_RESET_PORTS:
                        if p in conn:
                            bits = conn[p]
                            entry["inputs"][p] = bits[i] if len(bits) == width else bits[0]
                    entry["async_reg"] = truthy(self.nl.wire_attr(qbit, "ASYNC_REG") or "0") \
                        or truthy(c.get("attributes", {}).get("ASYNC_REG", "0"))
                    entry["reset_bridge"] = truthy(self.nl.wire_attr(qbit, "cdc_reset_sync") or "0")
                    entry["waive"] = self.nl.wire_attr(qbit, "cdc_waive")
                    self.ff[(cname, i)] = entry
                    if isinstance(qbit, int):
                        self.q_bit_to_ff[qbit] = (cname, i)
            elif t == "$mem_v2":
                p = c["parameters"]
                nwr = int(str(p["WR_PORTS"]), 2) if isinstance(p["WR_PORTS"], str) else int(p["WR_PORTS"])
                wr_doms = set()
                if nwr:
                    clks = conn["WR_CLK"]
                    for k in range(nwr):
                        wr_doms.add(self.clock_domain(clks[k]))
                self.mems[cname] = dict(domains=wr_doms, conn=conn, params=p)

    # ---------------------------------------------------------------- cones
    def sources(self, bit, _memo={}):
        """Set of (kind, ident, domain, through_logic) reaching this bit."""
        key = (id(self), bit)
        if key in _memo:
            return _memo[key]
        _memo[key] = set()                       # cycle guard
        out = set()
        if not isinstance(bit, int):
            _memo[key] = out
            return out
        d = self.nl.driver.get(bit)
        if d is None:
            pass
        elif d[0] == "PI":
            dom = self.input_domains.get(d[1])
            out.add(("PI", d[1], dom, False))
        else:
            cname, port, idx = d
            cell = self.nl.cells[cname]
            t = cell["type"]
            if t in FF_TYPES:
                out.add(("FF", (cname, idx), self.ff[(cname, idx)]["domain"], False))
            elif t == "$mem_v2":
                m = self.mems[cname]
                for dom in m["domains"]:
                    out.add(("MEM", cname, dom, True))
                # the read address is a combinational input of an async read port
                for b in cell["connections"].get("RD_ADDR", []):
                    for s in self.sources(b):
                        out.add((s[0], s[1], s[2], True))
            else:
                for p, bits in cell["connections"].items():
                    if cell.get("port_directions", {}).get(p) == "input":
                        for b in bits:
                            for s in self.sources(b):
                                out.add((s[0], s[1], s[2], True))
        _memo[key] = out
        return out

    def control_bits(self, bit, _memo={}):
        """Bits that act as mux selects anywhere in the combinational cone of `bit`."""
        key = (id(self), bit)
        if key in _memo:
            return _memo[key]
        _memo[key] = set()
        out = set()
        d = self.nl.driver.get(bit) if isinstance(bit, int) else None
        if d is not None and d[0] != "PI":
            cname = d[0]
            cell = self.nl.cells[cname]
            if cell["type"] not in FF_TYPES and cell["type"] != "$mem_v2":
                if cell["type"] in MUX_TYPES:
                    out.update(b for b in cell["connections"].get("S", []) if isinstance(b, int))
                for p, bits in cell["connections"].items():
                    if cell.get("port_directions", {}).get(p) == "input":
                        for b in bits:
                            out |= self.control_bits(b)
            elif cell["type"] == "$mem_v2":
                pass
        _memo[key] = out
        return out

    # ---------------------------------------------------------------- analysis
    def run(self):
        nl = self.nl
        # synchronizer chains: next-stage map (same domain, ASYNC_REG, D driven directly by Q)
        nxt = defaultdict(list)
        for k, f in self.ff.items():
            dbit = f["inputs"].get("D")
            if isinstance(dbit, int) and dbit in self.q_bit_to_ff:
                src = self.q_bit_to_ff[dbit]
                if self.ff[src]["domain"] == f["domain"] and f["async_reg"] and self.ff[src]["async_reg"]:
                    nxt[src].append(k)

        def chain_len(k, depth=0):
            if depth > 16:
                return depth
            return 1 + max((chain_len(n, depth + 1) for n in nxt[k]), default=0)

        def chain_ends(k, depth=0):
            if not nxt[k] or depth > 16:
                return [k]
            ends = []
            for n in nxt[k]:
                ends += chain_ends(n, depth + 1)
            return ends

        # synchronizer outputs per domain (data synchronizers and reset bridges)
        synced = defaultdict(set)       # domain -> set of q bits (chain final stages)
        reset_out = defaultdict(set)    # domain -> q bits of reset bridge final stages
        first_stages = []
        has_pred = {d for dsts in nxt.values() for d in dsts}
        for k, f in self.ff.items():
            if not f["async_reg"]:
                continue
            dbit = f["inputs"].get("D")
            srcs = self.sources(dbit) if isinstance(dbit, int) else set()
            cross = {s for s in srcs if s[2] is not None and s[2] != f["domain"]}
            is_first = bool(cross)
            if f["reset_bridge"] and k not in has_pred:
                for e in chain_ends(k):
                    reset_out[self.ff[e]["domain"]].add(self.ff[e]["q"])
            if is_first:
                first_stages.append(k)
                for e in chain_ends(k):
                    synced[self.ff[e]["domain"]].add(self.ff[e]["q"])

        # sync-derived flops (one and two flop stages after a synchronizer output)
        def derived(level_bits, dom):
            out = set()
            for k, f in self.ff.items():
                if f["domain"] != dom:
                    continue
                for p in ("D", "EN"):
                    b = f["inputs"].get(p)
                    if not isinstance(b, int):
                        continue
                    for s in self.sources(b):
                        if s[0] == "FF" and self.ff[s[1]]["q"] in level_bits:
                            out.add(f["q"])
            return out

        qual = {}
        for dom, bits in synced.items():
            l1 = derived(bits, dom)
            l2 = derived(bits | l1, dom)
            qual[dom] = bits | l1 | l2

        def is_qualifying_bit(b, dom):
            for s in self.sources(b) | {("FF", self.q_bit_to_ff.get(b), dom, False)}:
                if s[0] == "FF" and s[1] is not None and self.ff[s[1]]["domain"] == dom \
                        and self.ff[s[1]]["q"] in qual.get(dom, set()):
                    return True
            return False

        crossings = []
        gray_groups = defaultdict(list)   # dst bus netname -> [(src bit)]
        diverge = defaultdict(set)        # (src ff, dst domain) -> set(first-stage ff)

        def classify(endpoint, dom, port, bit, f=None):
            srcs = self.sources(bit) if isinstance(bit, int) else set()
            cross = [s for s in srcs if s[2] is not None and s[2] != dom]
            if not cross:
                return
            where = endpoint
            src_desc = sorted({f"{s[0]}:{self.describe(s)}@{s[2]}" for s in cross})
            rec = dict(endpoint=where, domain=dom, port=port, sources=src_desc)
            if f is not None and f.get("waive"):
                rec.update(cls="WAIVED", msg=f"waived: {f['waive']}")
            elif f is not None and f["async_reg"] and port == "D":
                logic = any(s[3] for s in cross)
                n_src = len({(s[0], s[1]) for s in cross})
                k = (f["cell"], f["i"])
                depth = chain_len(k)
                if logic or n_src != 1:
                    rec.update(cls="ERROR", kind="logic_before_sync",
                               msg="combinational logic (or several sources) in front of a synchronizer")
                elif depth < self.min_stages:
                    rec.update(cls="ERROR", kind="sync_too_short",
                               msg=f"synchronizer chain is {depth} flop(s), need >= {self.min_stages}")
                else:
                    rec.update(cls="SYNC", msg=f"{depth}-flop synchronizer")
                    s = cross[0]
                    if s[0] == "FF":
                        diverge[(s[1], dom)].add(k)
                        bus = self.bus_of(f["q"])
                        gray_groups[(bus, dom)].append(self.ff[s[1]]["q"])
            else:
                ctrl = set()
                if f is not None and isinstance(f["inputs"].get("EN"), int):
                    ctrl.add(f["inputs"]["EN"])
                ctrl |= self.control_bits(bit)
                if any(is_qualifying_bit(b, dom) for b in ctrl):
                    rec.update(cls="QUALIFIED",
                               msg="captured under control from a synchronizer of this domain")
                else:
                    rec.update(cls="ERROR", kind="unsynchronized",
                               msg="crossing without synchronizer or qualifying enable")
            crossings.append(rec)

        for k, f in self.ff.items():
            name = f"{nl.name_of(f['q'])}"
            for p in DATA_PORTS:
                if p in f["inputs"]:
                    classify(name, f["domain"], p, f["inputs"][p], f)
        for mname, m in self.mems.items():
            conn = m["conn"]
            for dom in m["domains"]:
                for p in ("WR_EN", "WR_ADDR", "WR_DATA"):
                    for b in conn.get(p, []):
                        classify(f"{mname}.{p}", dom, p, b, None)

        # multi-bit synchronizer groups need Gray-coded sources
        for (bus, dom), src_bits in gray_groups.items():
            if len(src_bits) > 1:
                missing = [nl.name_of(b) for b in src_bits if not truthy(nl.wire_attr(b, "cdc_gray") or "0")]
                if missing:
                    crossings.append(dict(endpoint=bus, domain=dom, port="D", sources=missing,
                                          cls="ERROR", kind="multibit_not_gray",
                                          msg=f"{len(src_bits)}-bit bus synchronized bit by bit; "
                                              f"source not marked cdc_gray: {', '.join(missing[:4])}"))
        for (src, dom), firsts in diverge.items():
            if len(firsts) > 1:
                self.findings.append(dict(level="WARNING", kind="divergent_sync",
                                          where=nl.name_of(self.ff[src]["q"]),
                                          msg=f"one source synchronized {len(firsts)} times into {dom}: "
                                              "copies can disagree for a cycle (reconvergence risk)"))

        # resets
        for k, f in self.ff.items():
            for p in ("ARST", "CLR", "SET"):
                b = f["inputs"].get(p)
                if not isinstance(b, int):
                    continue
                if f["reset_bridge"]:
                    continue
                srcs = self.sources(b)
                ok = True
                why = []
                for s in srcs:
                    if s[0] == "FF" and self.ff[s[1]]["q"] in reset_out.get(f["domain"], set()):
                        continue
                    if s[0] == "PI" and self.sync_resets.get(s[1]) == f["domain"]:
                        continue
                    ok = False
                    why.append(f"{s[0]}:{self.describe(s)}@{s[2]}")
                if not ok:
                    crossings.append(dict(endpoint=nl.name_of(f["q"]), domain=f["domain"], port=p,
                                          sources=sorted(set(why)), cls="ERROR", kind="reset_not_bridged",
                                          msg="async reset not driven by a reset bridge of this domain"))

        self.crossings = crossings
        return crossings

    def describe(self, s):
        if s[0] == "FF":
            return self.nl.name_of(self.ff[s[1]]["q"])
        return str(s[1])

    def bus_of(self, qbit):
        names = self.nl.bit_names.get(qbit, [])
        vis = [n for n in names if not self.nl.netnames[n[0]].get("hide_name", 0)]
        return (vis or names or [("?", 0)])[0][0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("netlist")
    ap.add_argument("--top", required=True)
    ap.add_argument("--min-stages", type=int, default=2)
    ap.add_argument("--same", action="append", default=[], help="clkA,clkB: treat as one domain")
    ap.add_argument("--sync-reset", action="append", default=[], help="port=domain: port is an already-bridged reset")
    ap.add_argument("--input-domain", action="append", default=[], help="port=domain for a data input")
    ap.add_argument("--json", help="write the full report here")
    a = ap.parse_args()
    sys.setrecursionlimit(200000)

    data = json.load(open(a.netlist))
    nl = Netlist(data, a.top)
    kv = lambda items: dict(x.split("=", 1) for x in items)
    ck = Checker(nl, a.min_stages, a.same, kv(a.sync_reset), kv(a.input_domain))
    crossings = ck.run()

    counts = defaultdict(int)
    for c in crossings:
        counts[c["cls"]] += 1
    errors = [c for c in crossings if c["cls"] == "ERROR"] + [f for f in ck.findings if f["level"] == "ERROR"]
    warnings = [f for f in ck.findings if f["level"] == "WARNING"]
    domains = sorted({f["domain"] for f in ck.ff.values()})

    print(f"cdc_check top={a.top} domains={','.join(domains)} flops={len(ck.ff)} memories={len(ck.mems)}")
    for cls in ("SYNC", "QUALIFIED", "WAIVED", "ERROR"):
        print(f"  {cls:9s} {counts.get(cls, 0)}")
    for c in crossings:
        if c["cls"] != "SYNC":
            print(f"  [{c['cls']}] {c.get('kind', '')} {c['endpoint']} ({c['domain']}.{c['port']}) <- "
                  f"{'; '.join(c['sources'][:3])}{' ...' if len(c['sources']) > 3 else ''} :: {c['msg']}")
    for f in ck.findings:
        print(f"  [{f['level']}] {f['kind']} {f['where']} :: {f['msg']}")
    verdict = "FAIL" if errors else "PASS"
    print(f"CDC_RESULT {verdict} top={a.top} errors={len(errors)} warnings={len(warnings)} "
          f"sync={counts.get('SYNC', 0)} qualified={counts.get('QUALIFIED', 0)} waived={counts.get('WAIVED', 0)}")
    if a.json:
        json.dump(dict(top=a.top, domains=domains, counts=counts, crossings=crossings,
                       findings=ck.findings, verdict=verdict), open(a.json, "w"), indent=1, default=str)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
