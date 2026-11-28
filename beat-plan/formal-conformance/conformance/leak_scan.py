#!/usr/bin/env python3
"""leak_scan: refuse to ship a pack that carries secrets or private details.

Scans text files for credentials (private keys, cloud and API tokens, password
assignments), personal or machine details (e-mail addresses, home-directory and
session scratch paths, session links, private IP addresses), and binary or very
large files (model weights do not belong in a conformance pack).

Findings are reported with file, line, column and a REDACTED excerpt: the scanner
never prints what it found. Exit status 1 if there is any finding.

An allowlist entry suppresses one exact, documented case (rule + literal text at
the match position); suppressed matches are still listed in the report.

    python3 conformance/leak_scan.py <file-or-dir>... [--report out.json] [--allow allow.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
SKIP_DIRS = {".git", "__pycache__", "work", ".pytest_cache"}

# Patterns are assembled from pieces so this file never contains a literal that
# would itself look like a credential to another scanner.
_B = "-----BEGIN "
RULES = [
    ("private_key_block", re.compile(_B + r"(?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\b(?:AK" + r"IA|AS" + r"IA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr])_[A-Za-z0-9]{36,}\b|\bgithub_" + r"pat_[A-Za-z0-9_]{40,}")),
    ("anthropic_api_key", re.compile(r"\bsk-" + r"ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_style_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("slack_token", re.compile(r"\bxo" + r"x[abposr]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAI" + r"za[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("secret_assignment", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
        r"[\"']?\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']")),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("home_path", re.compile(r"/home/[A-Za-z0-9._-]+/|/Users/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\|/ro" + r"ot/")),
    ("tilde_user_path", re.compile(r"~/(?:Desktop|Documents|Downloads|Library)/")),
    ("session_scratch_path", re.compile(r"/tmp/cl" + r"aude-")),
    ("session_link", re.compile(r"claude\.ai/(?:code/)?session_[A-Za-z0-9]+")),
    ("private_ipv4", re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
]


def redact(s: str) -> str:
    return f"{s[:2]}… (len {len(s)})"


def iter_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS):
                    yield f


def scan(paths, allow=None, deny_terms=None, root: Path | None = None) -> dict:
    allow = allow or []
    rules = list(RULES)
    for term in deny_terms or []:
        rules.append(("denylist_term", re.compile(re.escape(term), re.I)))
    findings, suppressed, files = [], [], 0
    for f in iter_files(paths):
        files += 1
        fr = f.resolve()
        shown = (fr.relative_to(root.resolve()).as_posix()
                 if root and fr.is_relative_to(root.resolve()) else f.name)   # never an absolute path
        data = f.read_bytes()
        if len(data) > MAX_BYTES:
            findings.append({"rule": "large_file", "file": shown, "line": 0, "col": 0,
                             "excerpt": f"{len(data)} bytes > {MAX_BYTES}"})
            continue
        if b"\x00" in data:
            findings.append({"rule": "binary_file", "file": shown, "line": 0, "col": 0,
                             "excerpt": "contains NUL bytes"})
            continue
        text = data.decode("utf-8", errors="replace")
        for ln, line in enumerate(text.splitlines(), 1):
            for name, rx in rules:
                for m in rx.finditer(line):
                    item = {"rule": name, "file": shown, "line": ln, "col": m.start() + 1,
                            "excerpt": redact(m.group(0))}
                    why = next((a["why"] for a in allow if a["rule"] == name
                                and line[m.start():].startswith(a["text"])), None)
                    if why:
                        item["allowed_because"] = why
                        suppressed.append(item)
                    else:
                        findings.append(item)
    return {"schema": "forge.leakscan/v1", "files_scanned": files,
            "rules": [r[0] for r in rules] + ["binary_file", "large_file"],
            "findings": len(findings), "items": findings,
            "suppressed": len(suppressed), "suppressed_items": suppressed}


def load_allow(path):
    return json.loads(Path(path).read_text()) if path else []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--allow", type=Path, help="JSON list of {rule, text, why}")
    ap.add_argument("--deny-file", type=Path, help="extra case-insensitive terms, one per line")
    a = ap.parse_args(argv)
    deny = [t.strip() for t in a.deny_file.read_text().splitlines() if t.strip()] if a.deny_file else []
    rep = scan(a.paths, load_allow(a.allow), deny, root=Path.cwd())
    if a.report:
        a.report.write_text(json.dumps(rep, indent=2) + "\n")
    print(f"leak scan: {rep['files_scanned']} files, {rep['findings']} findings, "
          f"{rep['suppressed']} allowlisted")
    for it in rep["items"]:
        print(f"  {it['rule']}: {it['file']}:{it['line']}:{it['col']} {it['excerpt']}")
    return 1 if rep["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
