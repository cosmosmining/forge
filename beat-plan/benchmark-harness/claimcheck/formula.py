"""Safe arithmetic evaluator for MODELLED derivations.

A formula is plain arithmetic over named inputs, e.g. "cycles * period_ns * 1e-6".
Allowed syntax: numbers, names, + - * / **, unary minus or plus, parentheses, and
min(), max(), abs(). Everything else (attributes, subscripts, other calls,
comprehensions, lambdas, and so on) is rejected, so a registry file can never
run code.
"""

from __future__ import annotations

import ast
import operator

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"min": min, "max": max, "abs": abs}


class FormulaError(ValueError):
    """Raised for disallowed syntax, unknown inputs or arithmetic errors."""


def names_in(expr: str) -> list:
    """Input names a formula uses (function names excluded), in first-seen order."""
    tree = _parse(expr)
    seen = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _FUNCS and node.id not in seen:
            seen.append(node.id)
    return seen


def evaluate(expr: str, env: dict) -> float:
    """Evaluate a formula with the given input values and return a float."""
    tree = _parse(expr)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FormulaError("only numeric constants are allowed")
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise FormulaError("unknown input %r" % node.id)
            val = env[node.id]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise FormulaError("input %r is not a number" % node.id)
            return val
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 64:
                raise FormulaError("exponent too large")
            try:
                return _BINOPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise FormulaError("division by zero")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
            and node.args
        ):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise FormulaError("disallowed syntax: %s" % type(node).__name__)

    return float(ev(tree))


def _parse(expr: str):
    if not isinstance(expr, str) or not expr.strip():
        raise FormulaError("empty formula")
    if len(expr) > 500:
        raise FormulaError("formula too long")
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError("syntax error: %s" % exc.msg)
