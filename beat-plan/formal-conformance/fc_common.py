"""Shared helpers for the Forge formal + conformance tools.

Standard library only, so the tools run with any Python >= 3.9 (the laptop's or this
container's). Every path that goes into an evidence file is relative to FC_ROOT or
replaced by a placeholder, so evidence never carries a home directory, user name or
scratch path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

FC_ROOT = Path(__file__).resolve().parent          # beat-plan/formal-conformance
VERDICTS = ("PASS", "FAIL", "INCOMPLETE")           # Forge gate semantics: only PASS counts


# ---------------------------------------------------------------- hashing / json
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rel_to_root(path: Path, root: Path = FC_ROOT) -> str:
    """Path relative to root, POSIX style. Refuses paths outside root (they would leak)."""
    p = Path(path).resolve()
    try:
        return p.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"path {p.name!r} is outside {root.name}/; evidence must live inside it") from exc


# ---------------------------------------------------------------- sanitizing
_HOME_PATTERNS = [
    re.compile(r"/home/[A-Za-z0-9._-]+"),
    re.compile(r"/Users/[A-Za-z0-9._-]+"),
    re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"),
    re.compile(r"/root(?=/|\b)"),
]
# compiler paths inside version banners, e.g. "Clang /some/build/dir/bin/clang++ 22.1.0"
_COMPILER_PATH = re.compile(r"((?:Clang|clang|GCC|gcc|g\+\+)\s+)(/\S+)")


class Sanitizer:
    """Replace absolute prefixes with stable placeholders.

    Longest prefix first, so a work dir inside FC_ROOT becomes <work> and not <fc>/... .
    """

    def __init__(self, roots: dict[str, Path] | None = None):
        roots = dict(roots or {})
        roots.setdefault("<fc>", FC_ROOT)
        pairs = []
        for tag, p in roots.items():
            for variant in {str(Path(p)), str(Path(p).resolve())}:
                pairs.append((variant, tag))
        self.pairs = sorted(pairs, key=lambda x: -len(x[0]))

    def __call__(self, text: str) -> str:
        for prefix, tag in self.pairs:
            text = text.replace(prefix, tag)
        text = _COMPILER_PATH.sub(lambda m: m.group(1) + "<path>", text)
        for pat in _HOME_PATTERNS:
            text = pat.sub("<home>", text)
        return text


def clean_version(text: str) -> str:
    """One-line tool version without build-machine paths."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else "unknown"
    return _COMPILER_PATH.sub(lambda m: m.group(1) + "<path>", line)


# ---------------------------------------------------------------- tool discovery
def _which(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def find_tools() -> dict:
    """Resolve the EDA tools.

    sby must drive the yosys it shipped with, so tools come in matched sets:
      * native set (OSS CAD Suite): sby + yosys + yosys-smtbmc + yosys-witness
      * YoWASP set (PyPI yowasp-yosys): yowasp-sby + yowasp-yosys + yowasp-yosys-smtbmc + ...
    The native set wins when a native sby is on PATH. Env overrides, per tool:
    FORGE_SBY, FORGE_YOSYS, FORGE_SMTBMC, FORGE_WITNESS, FORGE_SOLVER (default z3).
    """
    env = os.environ.get
    sby = env("FORGE_SBY") or _which(["sby"]) or _which(["yowasp-sby"])
    prefix = "yowasp-" if sby and Path(sby).name.startswith("yowasp-") else ""
    return {
        "sby": sby,
        "yosys": env("FORGE_YOSYS") or _which([prefix + "yosys"]),
        "smtbmc": env("FORGE_SMTBMC") or _which([prefix + "yosys-smtbmc"]),
        "witness": env("FORGE_WITNESS") or _which([prefix + "yosys-witness"]),
        "solver": env("FORGE_SOLVER") or "z3",
    }


def sby_env(tools: dict) -> dict:
    env = dict(os.environ)
    if tools.get("yosys"):
        env["YOSYS"] = tools["yosys"]
    if tools.get("smtbmc"):
        env["SMTBMC"] = tools["smtbmc"]
    if tools.get("witness"):
        env["WITNESS"] = tools["witness"]
    return env


def tool_versions(tools: dict) -> dict:
    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return (r.stdout or r.stderr)
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            return f"unavailable ({type(exc).__name__})"

    out = {}
    if tools.get("yosys"):
        out["yosys"] = clean_version(run([tools["yosys"], "-V"]))
    if tools.get("sby"):
        v = clean_version(run([tools["sby"], "--version"]))
        if "unknown" in v.lower() and "yowasp" in Path(tools["sby"]).name:
            v = "SymbiYosys bundled with YoWASP yosys (" + out.get("yosys", "?") + ")"
        out["sby"] = v
    if tools.get("solver"):
        out["solver"] = clean_version(run([tools["solver"], "--version"]))
    out["engine"] = f"smtbmc {tools.get('solver')}"
    return out
