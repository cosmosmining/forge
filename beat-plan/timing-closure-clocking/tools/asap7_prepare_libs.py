#!/usr/bin/env python3
"""asap7_prepare_libs.py -- stage ASAP7 RVT NLDM liberty files for the MODELLED 3 GHz track.

Forge Feature 5 (timing-closure / clocking pack). ASAP7 is a PREDICTIVE 7 nm PDK
(ASU / ARM research PDK); every timing number produced from these files is "modelled".

What it does, per corner (TT, SS):
  1. checks the SHA-256 of each source file against the pinned values below
     (source: The-OpenROAD-Project/OpenROAD-flow-scripts, flow/platforms/asap7/lib/NLDM,
     commit 8ba54e723175036fbe1a3541c7a1141cfc4f83b9);
  2. decompresses into <out>/;
  3. marks the cells that ORFS' asap7 config.mk lists in DONT_USE_CELLS
     (*x1p*_ASAP7*, *xp*_ASAP7*, SDF*, ICG*) with `dont_use : true;`, the way ORFS'
     markDontUse step does. (yosys 0.71 `abc -dont_use <glob>` made ABC fail on these
     libraries, so the attribute is set in the liberty instead.)

Usage: asap7_prepare_libs.py --src <ORFS asap7 lib/NLDM dir> --out build/asap7 [--corners TT SS]
"""
import argparse
import fnmatch
import gzip
import hashlib
import os
import re
import sys

PINNED = {
    "asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz":     "fe9f1c18e88ab129d63ad82adc256f3a85c7e38e47dabbe0a96749b41087dea1",
    "asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz": "8d6db2c2f83c3c162be54a5e102b2d379fcaaaef2db5f0b1d4152c395d01fea1",
    "asap7sc7p5t_OA_RVT_TT_nldm_211120.lib.gz":     "bbe6d904d58c7367de1ed7639e4eae386c65fa0a5af26ae62dc5e4e2ec52b08b",
    "asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz": "073ac4b6b08f272b6953b0ad54d1d9743767a7d15a0e2964ed86cf44c3dbe00e",
    "asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib":       "57a0b403485b99ebd676942af4673ac086b86c7c75fbdc3e5c0038501dd22ba3",
    "asap7sc7p5t_AO_RVT_SS_nldm_211120.lib.gz":     "9ac9c70139da3c4c72b2ed6113f011d8d96de2b30f9b261a237d2ed58ffa1ff5",
    "asap7sc7p5t_INVBUF_RVT_SS_nldm_220122.lib.gz": "339371d339fc0e3f4f50fa493ce82b984743af46d26823263dcca7a391e64408",
    "asap7sc7p5t_OA_RVT_SS_nldm_211120.lib.gz":     "6912520ffc1ae5bf69103d0286bcb7867fc90de80365dfc8ec0d6b55a9113f27",
    "asap7sc7p5t_SIMPLE_RVT_SS_nldm_211120.lib.gz": "71e55ce94cde9d10ad726cf7131e7356501aa1c380ae4e138f47c2f8ca7ca7db",
    "asap7sc7p5t_SEQ_RVT_SS_nldm_220123.lib":       "c6a6d9ad22bfb1bc9cf1c4ac66d09ce575ca18648ce4e50597d92174bc290d78",
}
DONT_USE = ["*x1p*_ASAP7*", "*xp*_ASAP7*", "SDF*", "ICG*"]
CELL_RE = re.compile(r'^(\s*cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{)\s*$')


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--corners", nargs="+", default=["TT", "SS"])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    bad = 0
    for name, digest in PINNED.items():
        corner = name.split("_")[3]
        if corner not in a.corners:
            continue
        src = os.path.join(a.src, name)
        if not os.path.exists(src):
            print(f"MISSING {src}")
            bad += 1
            continue
        got = sha256(src)
        if got != digest:
            print(f"HASH MISMATCH {name}: {got}")
            bad += 1
            continue
        dst = os.path.join(a.out, name[:-3] if name.endswith(".gz") else name)
        opener = gzip.open if name.endswith(".gz") else open
        marked = 0
        with opener(src, "rt") as fi, open(dst, "w") as fo:
            for line in fi:
                fo.write(line)
                m = CELL_RE.match(line.rstrip("\n"))
                if m and any(fnmatch.fnmatch(m.group(2), p) for p in DONT_USE):
                    fo.write("    dont_use : true ;\n")
                    marked += 1
        print(f"ok {os.path.basename(dst)} sha256-verified dont_use_marked={marked}")
    if bad:
        sys.exit(f"{bad} library file(s) missing or not matching the pinned SHA-256")
    for corner in a.corners:
        merge_comb(a.out, corner)


TEMPLATE_RE = re.compile(r'^\s*(lu_table_template|power_lut_template|output_current_template)\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{')


def split_lib(path):
    """Split one liberty file into (header_lines, {template_name: lines}, [cell_blocks]).
    header = the `library (...) {` line plus every depth-1 item (attributes, templates,
    operating_conditions, ...) before the first cell. The closing brace is not kept."""
    header, cells, templates = [], [], {}
    depth, block, kind, name = 0, None, None, None
    with open(path) as f:
        for line in f:
            code = line.split("/*")[0]
            opens, closes = code.count("{"), code.count("}")
            if depth == 0:
                if opens:
                    header.append(line)          # library ( ... ) {
                depth += opens - closes
                continue
            if depth == 1 and block is None:
                m = CELL_RE.match(line.rstrip("\n"))
                t = TEMPLATE_RE.match(line)
                if m:
                    block, kind = [line], "cell"
                elif t:
                    block, kind, name = [line], "tmpl", t.group(2)
                elif opens > closes:
                    block, kind = [line], "other"
                else:
                    if closes > opens:            # closing brace of the library
                        depth += opens - closes
                        continue
                    if not cells:
                        header.append(line)       # plain attribute
                    depth += opens - closes
                    continue
                depth += opens - closes
                if depth == 1:                     # one-line group
                    pass
                else:
                    continue
            else:
                block.append(line)
                depth += opens - closes
                if depth != 1:
                    continue
            # a depth-1 group just closed
            if kind == "cell":
                cells.append(block)
            else:
                if kind == "tmpl":
                    templates[name] = block
                if not cells:
                    header.extend(block)
            block = None
    return header, templates, cells


def merge_comb(out, corner):
    """One combinational liberty per corner (ORFS mergeLib style): SIMPLE's header,
    plus templates only the other libraries define, plus every cell of INVBUF,
    SIMPLE, AO and OA. yosys 0.71 dropped the whole INVBUF library when it merged
    these files itself (ABC then had no buffer or inverter), so the merge is done here."""
    order = ["SIMPLE", "INVBUF", "AO", "OA"]
    files = {k: [os.path.join(out, x) for x in os.listdir(out)
                 if x.startswith(f"asap7sc7p5t_{k}_RVT_{corner}_") and x.endswith(".lib")][0] for k in order}
    base_header, base_tmpl, _ = split_lib(files["SIMPLE"])
    extra_tmpl, all_cells = [], []
    for k in order:
        _, tmpl, cells = split_lib(files[k])
        for name, lines in tmpl.items():
            if name not in base_tmpl:
                base_tmpl[name] = lines
                extra_tmpl.extend(lines)
        all_cells.extend(cells)
    dst = os.path.join(out, f"asap7sc7p5t_COMB_RVT_{corner}_merged.lib")
    with open(dst, "w") as fo:
        fo.write(f"/* merged by asap7_prepare_libs.py from {', '.join(os.path.basename(v) for v in files.values())} */\n")
        fo.writelines(base_header)
        fo.writelines(extra_tmpl)
        for c in all_cells:
            fo.writelines(c)
        fo.write("}\n")
    print(f"ok {os.path.basename(dst)} cells={len(all_cells)} extra_templates={len(extra_tmpl) and sum(1 for l in extra_tmpl if TEMPLATE_RE.match(l))}")


if __name__ == "__main__":
    main()
