"""Lint documents: every tok/s figure must say what kind of number it is.

Two checks:
  lint_paths()  For human-written docs (.md .txt .html .rst). Finds tok/s figures and
                reads the words around each one (measured / modelled / arithmetic /
                vendor claim ...), matches the figure against the registry, and reports:
                  MISLABELLED        called "measured" while the registry says otherwise -> ERROR
                  UNBACKED-MEASURED  called "measured" with no registry entry or run record -> ERROR
                  UNLABELLED         no label words near the figure -> ERROR
                  LABEL-DIFFERS      labelled, but differently from the registry -> WARN
                  UNREGISTERED       labelled but not in the registry -> WARN
                Negations ("NOT a measurement", "never ... measured") do not count as a label.
  check_tags()  For generated reports. Every line that carries a standalone number
                must carry a [MEASURED] / [MODELLED] / [VENDOR-CLAIM] / [NOT-YET] tag.
"""

from __future__ import annotations

import html
import os
import re

from . import labels as L

_NUM = r"(?P<num>(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?)"
_MULT = r"(?:\s?(?P<mult>[kKM])(?![A-Za-z]))?"
_GAP = r"(?:\s*[-\s]\s*|\s+(?:(?![\d,.]+\s)[\w.\-×]+\s+){0,3}?)"
_UNIT = r"(?P<unit>tok/s|tok/sec|tokens/s|tokens/sec|tokens per second|tokens a second)"
TOKPS_RX = re.compile(r"(?:~|≈|>|≥|over\s+|about\s+|roughly\s+)?" + _NUM + _MULT + _GAP + _UNIT, re.I)

CLASS_RX = {
    L.MEASURED: re.compile(r"\bmeasur(?:ed|ement|ements|ing)\b", re.I),
    L.MODELLED: re.compile(r"\b(?:modell?ed|arithmetic|projected|projection|derived|estimated?|calculated|computed|theoretical|paper\s+number)\b", re.I),
    L.VENDOR_CLAIM: re.compile(r"\b(?:vendor|claims?|claimed|according\s+to|marketing|advertised)\b", re.I),
    L.NOT_YET: re.compile(r"\b(?:not\s+yet|no\s+run\s+yet)\b", re.I),
}
NEG_RX = re.compile(r"\b(?:not|never|no|isn't|aren't|wasn't|non|without)\b[^.;:!?]*$", re.I)
DOC_EXTS = (".md", ".markdown", ".txt", ".html", ".htm", ".rst")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def strip_html(text: str) -> str:
    """Visible text with one line per block element. Source line breaks inside a block are joined."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|td|th|h[1-6]|section|pre|span)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


_BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#|\||>|<!--)")


def _logical_lines(lines: list) -> list:
    """Join wrapped Markdown/text lines into paragraphs, list items and table rows.
    Returns (first physical line index, text) pairs. Never crosses a blank line or the start of a new block."""
    out = []
    prev_blank = True
    for i, line in enumerate(lines):
        if not line.strip():
            prev_blank = True
            continue
        joinable = (out and not prev_blank and not _BLOCK_START.match(line)
                    and not out[-1][1].lstrip().startswith(("|", "#")))
        if joinable:
            out[-1] = (out[-1][0], out[-1][1] + " " + line.strip())
        else:
            out.append((i, line))
        prev_blank = False
    return out


def _parse_value(num: str, mult) -> float:
    v = float(num.replace(",", ""))
    return v * {"k": 1e3, "K": 1e3, "M": 1e6}.get(mult or "", 1.0)


def asserted_classes(context: str) -> set:
    found = set()
    for label, rx in CLASS_RX.items():
        for m in rx.finditer(context):
            before = context[max(0, m.start() - 40):m.start()]
            if NEG_RX.search(before):
                continue
            found.add(label)
    return found


_ABBREV = {"vs", "e.g", "i.e", "approx", "est", "etc", "cf", "fig", "no", "al", "inc", "corp", "ltd", "ca"}


def _sentence_spans(line: str) -> list:
    spans, start = [], 0
    for m in re.finditer(r"[.!?;](?=\s|$)", line):
        word = re.search(r"([A-Za-z.]+)$", line[start:m.start()])
        if m.group(0) == "." and word and word.group(1).lower().rstrip(".") in _ABBREV:
            continue
        spans.append((start, m.end()))
        start = m.end()
    if start < len(line):
        spans.append((start, len(line)))
    return spans


def _context(line: str, pos: int) -> str:
    """The sentence holding the figure, within its paragraph, list item or table row.
    If that sentence is very short, the next sentence of the same block is added.
    Never the previous one, so a label for an earlier figure does not leak forward,
    and never the next block."""
    spans = _sentence_spans(line) or [(0, len(line))]
    k = next((j for j, (a, b) in enumerate(spans) if a <= pos < b), len(spans) - 1)
    ctx = line[spans[k][0]:spans[k][1]]
    if len(ctx.strip()) < 40 and k + 1 < len(spans):
        ctx += " " + line[spans[k + 1][0]:spans[k + 1][1]]
    return ctx


def known_tokps(reg=None, res=None, runs=None) -> list:
    """(value, entry-id, label, aliases) for every registered tok/s number and every measured run value."""
    out = []
    if reg is not None:
        for nid in reg.order:
            n = reg.numbers[nid]
            if n.get("unit") != "tok/s" or n.get("label") == L.NOT_YET:
                continue
            try:
                v = res.value(nid) if res is not None else n.get("value")
            except Exception:
                v = n.get("value")
            if v is not None:
                out.append((float(v), nid, n["label"], [a.lower() for a in n.get("aliases", [])]))
    for rec in runs or []:
        if rec.get("_valid") and not rec.get("synthetic"):
            from .runs import derive
            for d in derive(rec):
                if d["unit"] == "tok/s" and d["label"] == L.MEASURED:
                    out.append((float(d["value"]), "run:" + rec["run_id"], L.MEASURED, []))
    return out


def _blank_code_fences(text: str) -> str:
    """Blank out fenced code blocks (commands, JSON templates) in Markdown, keeping line numbers."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def lint_text(text: str, name: str, known: list, is_html: bool = False) -> list:
    if is_html:
        text = strip_html(text)
    else:
        text = _blank_code_fences(text)
    out = []
    for i, line in _logical_lines(text.splitlines()):
        for m in TOKPS_RX.finditer(line):
            value = _parse_value(m.group("num"), m.group("mult"))
            if value == 0:
                continue  # "0 tok/s figures" is a count, not a throughput claim
            raw = m.group(0).strip()
            ctx = _context(line, m.start())
            classes = asserted_classes(ctx)
            match = None
            for v, nid, label, aliases in known:
                if (v and abs(value - v) / v <= 0.002) or raw.lower().split()[0] in aliases:
                    match = (nid, label)
                    break
            where = "%s:%d" % (name, i + 1)
            figure = raw[:m.start("unit") - m.start()].strip()
            out.append(_verdict(where, raw, figure, m.group("unit"), value, classes, match))
    return out


def _verdict(where, raw, figure, unit, value, classes, match) -> dict:
    row = {"where": where, "text": raw, "figure": figure, "unit": unit, "value": value, "asserted": sorted(classes),
           "registry": match[0] if match else None, "registry_label": match[1] if match else None}
    if match:
        nid, label = match
        if L.MEASURED in classes and label != L.MEASURED:
            row.update(level="ERROR", code="MISLABELLED",
                       message="called measured, but %s is %s" % (nid, label))
        elif label in classes:
            row.update(level="OK", code="LABELLED", message="matches %s (%s)" % (nid, label))
        elif classes:
            row.update(level="WARN", code="LABEL-DIFFERS",
                       message="labelled %s, registry says %s for %s" % ("/".join(sorted(classes)), label, nid))
        else:
            row.update(level="ERROR", code="UNLABELLED",
                       message="no label words near it; registry says %s (%s)" % (label, nid))
    else:
        if L.MEASURED in classes:
            row.update(level="ERROR", code="UNBACKED-MEASURED",
                       message="called measured, but no MEASURED registry entry or run record has this value")
        elif classes:
            row.update(level="WARN", code="UNREGISTERED",
                       message="labelled %s but not in data/claims.json; add it with source and method" % "/".join(sorted(classes)))
        else:
            row.update(level="ERROR", code="UNLABELLED",
                       message="no label (measured / modelled / vendor claim) and not in the registry")
    return row


def iter_docs(paths: list):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for f in sorted(files):
                    if f.lower().endswith(DOC_EXTS):
                        yield os.path.join(root, f)


def lint_paths(paths: list, known: list, display_root: str = None) -> list:
    out = []
    for p in iter_docs(paths):
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        name = os.path.relpath(p, display_root) if display_root else p
        out.extend(lint_text(text, name, known, is_html=p.lower().endswith((".html", ".htm"))))
    return out


# ----- generated-report tag check -------------------------------------------------

_TAG_RX = re.compile(r"\[(?:MEASURED|MODELLED|VENDOR-CLAIM|NOT-YET)\]")
_EXEMPT = [
    re.compile(r"`[^`]*`"),
    re.compile(r"https?://\S+"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?\b"),
    re.compile(r"\b[0-9a-f]{7,64}\b"),
    re.compile(r"\bv?\d+\.\d+\.\d+\b"),
]
_STANDALONE_NUM = re.compile(r"(?<![A-Za-z0-9_.])(?<![A-Za-z]-)\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_]|\.\d)")


def check_tags(text: str, name: str = "report") -> list:
    problems = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or _TAG_RX.search(line):
            continue
        stripped = line
        for rx in _EXEMPT:
            stripped = rx.sub(" ", stripped)
        m = _STANDALONE_NUM.search(stripped)
        if m:
            problems.append({"where": "%s:%d" % (name, i), "number": m.group(0), "line": line.strip()[:160]})
    return problems
