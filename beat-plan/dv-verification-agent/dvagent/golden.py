"""Load and run golden models, and measure which golden-model lines ran.

A golden model is a plain Python function named in the manifest as
"path/to/file.py:function".
  style = "map":    f(beat: dict) -> dict          one output beat per input beat
  style = "stream": f(beats: list[dict]) -> list   whole input stream -> output beats
Input values arrive as ints in each port's signedness. Output values may be
signed ints or raw bit patterns; anything that does not fit the port is an
error in the model or the manifest, and the run becomes INCOMPLETE instead of
being silently truncated.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
from dataclasses import dataclass, field

from . import gm


class GoldenError(Exception):
    pass


def load_callable(spec: str, base_dir: str):
    if ":" not in spec:
        raise GoldenError(f"golden model {spec!r} must look like file.py:function")
    file_part, func = spec.rsplit(":", 1)
    path = file_part if os.path.isabs(file_part) else os.path.join(base_dir, file_part)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise GoldenError(f"golden model file not found: {path}")
    mod_name = "dvagent_golden_" + str(abs(hash(path)))
    sp = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(sp)
    # make `from dvagent import gm` work from the golden file
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)
    sp.loader.exec_module(mod)
    fn = getattr(mod, func, None)
    if fn is None or not callable(fn):
        raise GoldenError(f"{path} has no function {func}")
    return fn, path


@dataclass
class GoldenCoverage:
    file: str
    covered: list = field(default_factory=list)
    uncovered: list = field(default_factory=list)
    functions_called: list = field(default_factory=list)
    functions_never_called: list = field(default_factory=list)

    @property
    def ratio(self) -> float:
        n = len(self.covered) + len(self.uncovered)
        return len(self.covered) / n if n else 1.0


def _coverable_lines(path: str) -> dict:
    """{function_name: set(statement line numbers)} for top-level functions."""
    with open(path) as f:
        tree = ast.parse(f.read(), path)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines = set()
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]  # docstring
            for stmt in body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.stmt):
                        lines.add(sub.lineno)
            out[node.name] = lines
    return out


def _normalise(value, port, where):
    w = port.width
    if not isinstance(value, int):
        raise GoldenError(f"{where}: {port.name} = {value!r} is not an int")
    if port.signed:
        if gm.smin(w) <= value <= gm.smax(w):
            return value
        if 0 <= value <= gm.mask(w):
            return gm.to_signed(value, w)
    else:
        if 0 <= value <= gm.mask(w):
            return value
    raise GoldenError(f"{where}: {port.name} = {value} does not fit a "
                      f"{'signed' if port.signed else 'unsigned'} {w}-bit port")


def run(fn, path: str, style: str, beats: list, out_ports: list, trace: bool = True):
    """Return (expected_output_beats, GoldenCoverage|None)."""
    executed = set()
    called = set()
    target = os.path.abspath(path)

    def tracer(frame, event, arg):
        if os.path.abspath(frame.f_code.co_filename) != target:
            return None
        if event == "call":
            called.add(frame.f_code.co_name)
        if event == "line":
            executed.add(frame.f_lineno)
        return tracer

    old = sys.gettrace()
    if trace:
        sys.settrace(tracer)
    try:
        if style == "map":
            raw = [fn(dict(b)) for b in beats]
        else:
            raw = fn([dict(b) for b in beats])
    except GoldenError:
        raise
    except Exception as e:  # the model itself crashed
        raise GoldenError(f"golden model raised {type(e).__name__}: {e}") from e
    finally:
        if trace:
            sys.settrace(old)

    if not isinstance(raw, list):
        raise GoldenError("golden model must return a list (stream style) or dicts (map style)")
    expected = []
    names = [p.name for p in out_ports]
    for i, beat in enumerate(raw):
        if not isinstance(beat, dict):
            raise GoldenError(f"output beat {i} is not a dict: {beat!r}")
        missing = [n for n in names if n not in beat]
        if missing:
            raise GoldenError(f"output beat {i} lacks {missing}")
        expected.append({p.name: _normalise(beat[p.name], p, f"output beat {i}") for p in out_ports})

    cov = None
    if trace:
        lines_by_fn = _coverable_lines(target)
        cov = GoldenCoverage(file=target)
        for name, lines in sorted(lines_by_fn.items()):
            if name in called:
                cov.functions_called.append(name)
                cov.covered += sorted(lines & executed)
                cov.uncovered += sorted(lines - executed)
            else:
                cov.functions_never_called.append(name)
    return expected, cov
