"""Small Scheme-expression helpers for talking to SALenv."""

from __future__ import annotations

import math
import re
from os import PathLike
from typing import Any


class Symbol(str):
    """A Scheme symbol that should be emitted without string quotes."""

    def __new__(cls, value: str):
        if not value or re.search(r"[\s()\[\]{}\"';`,|\\]", value):
            raise ValueError(f"Invalid Scheme symbol: {value!r}")
        return super().__new__(cls, value)


def sym(value: str) -> Symbol:
    return Symbol(value)


def _quote_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def scheme_literal(value: Any, *, session=None) -> str:
    """Convert a small Python value into a Scheme literal."""

    if hasattr(value, "_sal_ref"):
        return value._sal_ref(session=session)
    if isinstance(value, Symbol):
        if value.startswith(":"):
            return str(value)
        return "'" + str(value)
    if value is True:
        return "#t"
    if value is False or value is None:
        return "#f"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Scheme literals must be finite numbers.")
        return repr(value)
    if isinstance(value, PathLike):
        return _quote_string(str(value))
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, (list, tuple)):
        return "(list " + " ".join(scheme_literal(item, session=session) for item in value) + ")"
    raise TypeError(f"cannot convert {type(value).__name__} to a Scheme literal")


def scheme_call(name: str, *args: Any, session=None) -> str:
    Symbol(name)
    return "(" + " ".join([name, *(scheme_literal(arg, session=session) for arg in args)]) + ")"


def keyword(name: str) -> Symbol:
    if name.startswith(":"):
        return sym(name)
    return sym(":" + name)
