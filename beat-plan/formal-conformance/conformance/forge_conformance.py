#!/usr/bin/env python3
"""forge_conformance: build and verify a conformance pack that RECORDS results.

The pack never re-simulates or re-proves anything. It reads evidence files that the
gate, the proof runs or forge_formal already wrote, and records, per claim:
  * the value(s), each re-extracted from its evidence file by a JSON pointer,
  * the kind of number (measured / derived / model / not-yet) and its source file,
  * the SHA-256 of every evidence file, following the chain of custody
    (claim -> verdict.json -> every file that verdict lists with its hash).

Rules (a claim that breaks one is listed as NOT RECORDED, with the reason):
  * no evidence file named or found  -> not recorded (the number stays out)
  * a requirement in the claim fails (e.g. /verdict must be "PASS")
  * bit-exact claims need a zero mismatch count AND (compared > 0 OR a 'proven' status);
    a claim cannot relax this
  * derived numbers are recomputed here from recorded inputs with the given formula
  * model numbers must list their assumptions; not-yet claims carry no number
  * the pack must leak-scan clean (0 findings) or it is not written

    build   --claims conformance/claims.json --out pack/
    verify  pack/        re-hash every file, re-read every number, re-run the leak scan
"""
from __future__ import annotations

import argparse
import ast
import json
import operator
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fc_common import FC_ROOT, load_json, sha256_file, write_json  # noqa: E402
import leak_scan  # noqa: E402

CLAIMS_SCHEMA = "forge.conformance.claims/v1"
PACK_SCHEMA = "forge.conformance.pack/v1"
KINDS = {"measured", "derived", "model", "not-yet"}
DEFAULT_ALLOW = Path(__file__).resolve().parent / "leak_allowlist.json"


class Refused(Exception):
    pass


# ----------------------------------------------------------------- json pointers
def jptr(doc, pointer: str):
    """RFC 6901 JSON pointer lookup. Raises Refused if the path is absent."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise Refused(f"bad JSON pointer {pointer!r}")
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            if not tok.isdigit() or int(tok) >= len(cur):
                raise Refused(f"evidence lacks {pointer}")
            cur = cur[int(tok)]
        elif isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        else:
            raise Refused(f"evidence lacks {pointer}")
    return cur


# ----------------------------------------------------------------- safe arithmetic
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}


def safe_eval(expr: str, names: dict):
    """+ - * / over numbers and named inputs only. Nothing else is evaluated."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Name) and n.id in names:
            v = names[n.id]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise Refused(f"input {n.id} is not a number")
            return v
        raise Refused(f"formula element not allowed: {ast.dump(n)[:60]}")
    return ev(ast.parse(expr, mode="eval"))


# ----------------------------------------------------------------- evidence chain
def _resolve(rel: str, root: Path) -> Path:
    p = (root / rel).resolve()
    if not p.is_relative_to(root.resolve()):
        raise Refused(f"evidence path leaves the root: {rel}")
    return p


def collect_chain(rel: str, root: Path) -> tuple[dict, list[dict]]:
    """Load the evidence JSON and every file it lists, checking each listed hash."""
    p = _resolve(rel, root)
    if not p.is_file():
        raise Refused(f"evidence file not found: {rel}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Refused(f"evidence is not JSON: {rel}") from exc
    files = [{"file": rel, "sha256": sha256_file(p), "role": "evidence"}]
    for e in doc.get("evidence", []) if isinstance(doc, dict) else []:
        q = _resolve(e["file"], root)
        if not q.is_file():
            raise Refused(f"chain broken: {e['file']} listed by {rel} is missing")
        actual = sha256_file(q)
        if actual != e["sha256"]:
            raise Refused(f"chain broken: {e['file']} hash differs from the one {rel} records")
        files.append({"file": e["file"], "sha256": actual, "role": "listed by evidence"})
    inputs = (doc.get("inputs") or {}) if isinstance(doc, dict) else {}
    for key in ("spec", "spec_base"):           # the property definitions that were checked
        ref = inputs.get(key)
        if not ref:
            continue
        q = _resolve(ref["file"], root)
        if not q.is_file() or sha256_file(q) != ref["sha256"]:
            raise Refused(f"chain broken: {key} {ref['file']} missing or changed since the run")
        files.append({"file": ref["file"], "sha256": ref["sha256"], "role": key})
    return doc, files


def check_bit_exact(values: dict):
    mm = next((values[k] for k in ("mismatches", "counterexamples") if k in values), None)
    if mm is None:
        raise Refused("bit-exact claim records no mismatch/counterexample count")
    if mm != 0:
        raise Refused(f"bit-exact claim has {mm} mismatches/counterexamples")
    proven = values.get("bit_exact_status") == "proven"
    compared = values.get("compared")
    if not proven and not (isinstance(compared, int) and not isinstance(compared, bool) and compared > 0):
        raise Refused("bit-exact claim needs compared > 0 or a 'proven' status")


def record_claim(c: dict, root: Path, recorded: dict) -> dict:
    kind = c.get("kind")
    if kind not in KINDS:
        raise Refused(f"kind must be one of {sorted(KINDS)}")
    if kind == "not-yet":
        if "value" in c or c.get("evidence"):
            raise Refused("a not-yet claim carries no number and no evidence")
        return {"values": {}, "files": []}
    if kind == "derived":
        names = {}
        for alias, ref in c.get("inputs", {}).items():
            cid, _, field = ref.partition("#")
            if cid not in recorded:
                raise Refused(f"derived input {ref} is not a recorded claim (yet)")
            if field not in recorded[cid]["values"]:
                raise Refused(f"derived input {ref}: no such recorded value")
            names[alias] = recorded[cid]["values"][field]
        if not c.get("formula"):
            raise Refused("derived claim without a formula")
        val = safe_eval(c["formula"], names)
        if "value" in c and c["value"] != val:
            raise Refused(f"derived value {c['value']} != recomputed {val}")
        return {"values": {"value": val}, "inputs_used": names, "files": []}
    if kind == "model" and not c.get("assumptions"):
        raise Refused("model numbers must list their assumptions")
    ev = c.get("evidence")
    if not ev:
        raise Refused("no evidence file named")
    doc, files = collect_chain(ev, root)
    values = {name: jptr(doc, ptr) for name, ptr in (c.get("record") or {}).items()}
    if not values:
        raise Refused("claim records no value")
    for ptr, want in (c.get("require") or {}).items():
        got = jptr(doc, ptr)
        if got != want:
            raise Refused(f"requirement failed: {ptr} == {want!r} (evidence has {got!r})")
    if c.get("bit_exact"):
        check_bit_exact(values)
    for extra in c.get("supporting", []):
        q = _resolve(extra, root)
        if not q.is_file():
            raise Refused(f"supporting file missing: {extra}")
        files.append({"file": extra, "sha256": sha256_file(q), "role": "supporting"})
    return {"values": values, "files": files}


# ----------------------------------------------------------------- build
def build(claims_path: Path, out: Path, root: Path = FC_ROOT, allow_path: Path = DEFAULT_ALLOW) -> dict:
    cl = load_json(claims_path)
    if cl.get("schema") != CLAIMS_SCHEMA:
        raise SystemExit(f"claims schema must be {CLAIMS_SCHEMA}")
    recorded, not_recorded, order = {}, [], []
    for c in cl["claims"]:
        base = {k: c.get(k) for k in ("id", "statement", "kind", "bit_exact", "standin", "control",
                                      "claimed_in", "evidence_needed") if c.get(k) is not None}
        try:
            r = record_claim(c, root, recorded)
            entry = dict(base, **{k: v for k, v in r.items() if k != "files"})
            entry["evidence"] = c.get("evidence")
            entry["record_rules"] = c.get("record") or {}
            entry["require"] = c.get("require") or {}
            if c.get("formula"):
                entry["formula"] = c["formula"]
                entry["inputs"] = c.get("inputs", {})
            entry["files"] = r["files"]
            recorded[c["id"]] = entry
            order.append(c["id"])
        except Refused as exc:
            not_recorded.append(dict(base, reason=str(exc)))
    if out.exists():
        shutil.rmtree(out)
    (out / "files").mkdir(parents=True)
    copied = {}
    for cid in order:
        for f in recorded[cid]["files"]:
            if f["file"] in copied:
                continue
            dst = out / "files" / f["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / f["file"], dst)
            if sha256_file(dst) != f["sha256"]:
                raise SystemExit(f"copy of {f['file']} does not match its hash")
            copied[f["file"]] = f["sha256"]
    pack = {
        "schema": PACK_SCHEMA,
        "pack": cl.get("pack", {}),
        "rule": "records results from evidence files; runs no simulation and no proof",
        "recorded": [recorded[cid] for cid in order],
        "not_recorded": not_recorded,
        "counts": {"recorded": len(order), "not_recorded": len(not_recorded),
                   "bit_exact_recorded": sum(1 for cid in order if recorded[cid].get("bit_exact"))},
    }
    write_json(out / "pack.json", pack)
    (out / "PACK.md").write_text(render_pack_md(pack))
    rep = leak_scan.scan([out], leak_scan.load_allow(allow_path if allow_path.exists() else None), root=out)
    write_json(out / "leak_scan.json", rep)
    if rep["findings"]:
        bad = out.with_name(out.name + ".REJECTED")
        if bad.exists():
            shutil.rmtree(bad)
        out.rename(bad)
        raise SystemExit(f"leak scan found {rep['findings']} findings; pack moved to {bad.name}, not shipped")
    entries = []
    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = f.relative_to(out).as_posix()
        entries.append({"file": rel, "bytes": f.stat().st_size, "sha256": sha256_file(f)})
    write_json(out / "manifest.json", {"schema": "forge.conformance.manifest/v1",
                                       "files": entries, "count": len(entries) + 1})
    pack["manifest_sha256"] = sha256_file(out / "manifest.json")
    pack["file_count"] = len(entries) + 1
    pack["leak_findings"] = rep["findings"]
    return pack


def render_pack_md(pack: dict) -> str:
    p = pack["pack"]
    L = [f"# {p.get('title', 'Forge conformance pack')}", "",
         p.get("scope", ""), "",
         "This pack records results. It runs no simulation and no proof: every number below",
         "was read from the evidence file named next to it, and `verify` re-reads it.", "",
         f"## Recorded ({len(pack['recorded'])})", "",
         "| Claim | Kind | Bit-exact | Recorded values | Evidence |", "|---|---|---|---|---|"]
    for r in pack["recorded"]:
        vals = ", ".join(f"{k} = {json.dumps(v)}" for k, v in r["values"].items())
        if r["kind"] == "derived":
            ev = f"formula `{r['formula']}` over recorded claims"
        elif r.get("files"):
            ev = f"`{r['files'][0]['file']}` (sha256 {r['files'][0]['sha256'][:12]}…, +{len(r['files']) - 1} chained files)"
        else:
            ev = "-"
        tag = " (control)" if r.get("control") else (" (stand-in)" if r.get("standin") else "")
        L.append(f"| {r['statement']}{tag} | {r['kind']} | {'yes' if r.get('bit_exact') else 'no'} | {vals} | {ev} |")
    L += ["", f"## Not recorded ({len(pack['not_recorded'])})", "",
          "A claim stays out of the record until its evidence file is present and checks out.", "",
          "| Claim | Kind | Claimed in | Why not recorded | Evidence needed |", "|---|---|---|---|---|"]
    for n in pack["not_recorded"]:
        L.append(f"| {n.get('statement', n.get('id'))} | {n.get('kind', '?')} | {n.get('claimed_in', '-')} "
                 f"| {n['reason']} | {n.get('evidence_needed', '-')} |")
    L += ["", "## How to check this pack", "",
          "```", "python3 conformance/forge_conformance.py verify pack/", "```", "",
          "`verify` re-hashes every file against manifest.json, re-reads every recorded value from",
          "its evidence copy, re-checks the evidence chain and the bit-exact rule, and repeats the",
          "leak scan. It needs only Python; no EDA tool is run.", ""]
    return "\n".join(L)


# ----------------------------------------------------------------- verify
def verify(pack_dir: Path, allow_path: Path = DEFAULT_ALLOW) -> list[str]:
    problems = []
    man_p = pack_dir / "manifest.json"
    if not man_p.is_file():
        return ["manifest.json missing"]
    man = load_json(man_p)
    listed = set()
    for e in man["files"]:
        f = pack_dir / e["file"]
        listed.add(e["file"])
        if not f.is_file():
            problems.append(f"missing: {e['file']}")
        elif f.stat().st_size != e["bytes"] or sha256_file(f) != e["sha256"]:
            problems.append(f"changed: {e['file']}")
    for f in pack_dir.rglob("*"):
        rel = f.relative_to(pack_dir).as_posix()
        if f.is_file() and rel != "manifest.json" and rel not in listed:
            problems.append(f"not in manifest: {rel}")
    if man.get("count") != len(man["files"]) + 1:
        problems.append("manifest count does not match its file list")
    pack = load_json(pack_dir / "pack.json")
    files_root = pack_dir / "files"
    done = {}
    for r in pack["recorded"]:
        try:
            if r["kind"] == "not-yet":
                if r.get("values") or r.get("files") or r.get("evidence"):
                    problems.append(f"{r['id']}: a not-yet entry must carry no number and no evidence")
                done[r["id"]] = {}
                continue
            if r["kind"] == "derived":
                names = {a: done[ref.partition('#')[0]][ref.partition('#')[2]] for a, ref in r["inputs"].items()}
                if safe_eval(r["formula"], names) != r["values"]["value"]:
                    problems.append(f"{r['id']}: derived value does not recompute")
                done[r["id"]] = r["values"]
                continue
            for f in r["files"]:
                q = files_root / f["file"]
                if not q.is_file() or sha256_file(q) != f["sha256"]:
                    problems.append(f"{r['id']}: evidence file changed or missing: {f['file']}")
            doc, _ = collect_chain(r["evidence"], files_root)
            for name, ptr in r["record_rules"].items():
                if jptr(doc, ptr) != r["values"][name]:
                    problems.append(f"{r['id']}: {name} no longer matches {ptr} in its evidence")
            for ptr, want in r["require"].items():
                if jptr(doc, ptr) != want:
                    problems.append(f"{r['id']}: requirement {ptr} == {want!r} fails")
            if r.get("bit_exact"):
                check_bit_exact(r["values"])
            done[r["id"]] = r["values"]
        except (Refused, KeyError) as exc:
            problems.append(f"{r['id']}: {exc}")
    rep = leak_scan.scan([pack_dir], leak_scan.load_allow(allow_path if allow_path.exists() else None), root=pack_dir)
    if rep["findings"]:
        problems.append(f"leak scan: {rep['findings']} findings")
    return problems


# ----------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--claims", type=Path, default=FC_ROOT / "conformance" / "claims.json")
    b.add_argument("--out", type=Path, default=FC_ROOT / "pack")
    v = sub.add_parser("verify")
    v.add_argument("pack", type=Path, nargs="?", default=FC_ROOT / "pack")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        pack = build(a.claims, a.out)
        c = pack["counts"]
        print(f"pack: {a.out.name}/  files={pack['file_count']}  recorded={c['recorded']} "
              f"(bit-exact {c['bit_exact_recorded']})  not_recorded={c['not_recorded']}  "
              f"leak_findings={pack['leak_findings']}")
        print(f"manifest sha256: {pack['manifest_sha256']}")
        for n in pack["not_recorded"]:
            print(f"  not recorded: {n['id']}: {n['reason']}"
                  + (f" [claimed in {n['claimed_in']}]" if n.get("claimed_in") else ""))
        return 0
    problems = verify(a.pack)
    if problems:
        print("VERIFY FAILED")
        for p in problems:
            print("  " + p)
        return 1
    man = load_json(a.pack / "manifest.json")
    print(f"VERIFY OK: {man['count']} files, every hash and recorded value re-checked, leak scan 0 findings")
    print(f"manifest sha256: {sha256_file(a.pack / 'manifest.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
