"""Composable SAL module expressions, checked by SAL when loaded.

These immutable expressions contain SAL source, not live session handles. They
can reference parameters and indexed variables that only exist in the model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


def identifier(value: str) -> str:
    """Validate an unqualified SAL identifier (SAL checks reserved words)."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_?]*", value):
        raise ValueError(f"Invalid SAL identifier: {value!r}")
    return value


class ModuleSource(Protocol):
    def expression(self) -> ModuleExpression: ...


@dataclass(frozen=True)
class ModuleExpression:
    """A module expression in ordinary SAL syntax.

    Use ``sync`` for lockstep steps and ``async_`` for interleaving steps.
    Renaming is simultaneous, so swapping names is supported.
    """

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("A module expression cannot be empty.")

    def __str__(self) -> str:
        return self.text

    def expression(self) -> ModuleExpression:
        return self

    def sync(self, *others: str | ModuleSource) -> ModuleExpression:
        return sync(self, *others)

    def async_(self, *others: str | ModuleSource) -> ModuleExpression:
        return async_(self, *others)

    def instantiate(self, *actuals: str | int | bool) -> ModuleExpression:
        if not actuals:
            return self
        values = (
            str(value).upper() if isinstance(value, bool) else str(value) for value in actuals
        )
        return ModuleExpression(f"{self.text}[{', '.join(values)}]")

    def rename(self, names: Mapping[str, str] | None = None, **renames: str) -> ModuleExpression:
        pairs = {**(names or {}), **renames}
        if not pairs:
            return self
        clauses = ", ".join(f"{identifier(old)} TO {new}" for old, new in pairs.items())
        return ModuleExpression(f"(RENAME {clauses} IN {self.text})")

    def hide(self, *names: str) -> ModuleExpression:
        if not names:
            return self
        return ModuleExpression(f"(LOCAL {', '.join(map(identifier, names))} IN {self.text})")

    def output(self, *names: str) -> ModuleExpression:
        """Turn global variables into outputs using SAL's OUTPUT operator."""
        if not names:
            return self
        return ModuleExpression(f"(OUTPUT {', '.join(map(identifier, names))} IN {self.text})")

    def observe(self, observer: str | ModuleSource) -> ModuleExpression:
        """Attach a definition-only observer as the right-hand operand."""
        return ModuleExpression(f"(OBSERVE {self.text} WITH {module_expr(observer)})")

    def forall(self, index: str, type_: str, *, asynchronous: bool = True) -> ModuleExpression:
        """Indexed composition, e.g. ``([] (i: [1..3]): worker[i])``."""
        operator = "[]" if asynchronous else "||"
        return ModuleExpression(f"({operator} ({identifier(index)}: {type_}): {self.text})")

    def with_(
        self,
        *,
        inputs: Mapping[str, str] | None = None,
        outputs: Mapping[str, str] | None = None,
        locals: Mapping[str, str] | None = None,
        globals: Mapping[str, str] | None = None,
    ) -> ModuleExpression:
        """Declare shared variables, including array targets for indexed renames."""
        declarations = [
            f"{kind} {identifier(name)}: {type_}"
            for kind, variables in (
                ("INPUT", inputs),
                ("OUTPUT", outputs),
                ("LOCAL", locals),
                ("GLOBAL", globals),
            )
            for name, type_ in (variables or {}).items()
        ]
        if not declarations:
            return self
        return ModuleExpression(f"(WITH {'; '.join(declarations)} {self.text})")


def module_expr(value: str | ModuleSource) -> ModuleExpression:
    """Refer to a named/parameterized module or an existing builder expression."""
    return ModuleExpression(value) if isinstance(value, str) else value.expression()


def _compose(operator: str, modules: tuple[str | ModuleSource, ...]) -> ModuleExpression:
    if not modules:
        raise ValueError("Composition needs at least one module.")
    result = module_expr(modules[0])
    for module in modules[1:]:
        result = ModuleExpression(f"({result} {operator} {module_expr(module)})")
    return result


def sync(*modules: str | ModuleSource) -> ModuleExpression:
    """Compose module expressions synchronously, left to right."""
    return _compose("||", modules)


def async_(*modules: str | ModuleSource) -> ModuleExpression:
    """Compose module expressions asynchronously, left to right."""
    return _compose("[]", modules)
