"""Convenience builders that emit ordinary SAL source."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


def _ensure_semicolon(line: str) -> str:
    stripped = line.rstrip()
    if stripped.endswith(";"):
        return stripped
    return stripped + ";"


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in text.splitlines())


@dataclass
class GuardedCommand:
    label: str | None
    guard: str
    assignments: list[str]

    def source(self, *, indent: int = 8) -> str:
        label = f"{self.label}: " if self.label else ""
        assignment_text = "; ".join(self.assignments)
        return _indent(f"{label}{self.guard} --> {assignment_text}", indent)


@dataclass
class ModuleBuilder:
    name: str
    params: str | None = None
    inputs: list[tuple[str, str]] = field(default_factory=list)
    outputs: list[tuple[str, str]] = field(default_factory=list)
    locals: list[tuple[str, str]] = field(default_factory=list)
    globals: list[tuple[str, str]] = field(default_factory=list)
    initializations: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    commands: list[GuardedCommand] = field(default_factory=list)
    raw_sections: list[str] = field(default_factory=list)

    def input(self, name: str, type_: str) -> "ModuleBuilder":
        self.inputs.append((name, type_))
        return self

    def output(self, name: str, type_: str) -> "ModuleBuilder":
        self.outputs.append((name, type_))
        return self

    def local(self, name: str, type_: str) -> "ModuleBuilder":
        self.locals.append((name, type_))
        return self

    def global_(self, name: str, type_: str) -> "ModuleBuilder":
        self.globals.append((name, type_))
        return self

    def init(self, *lines: str) -> "ModuleBuilder":
        self.initializations.extend(lines)
        return self

    def definition(self, *lines: str) -> "ModuleBuilder":
        self.definitions.extend(lines)
        return self

    def transition(self, *lines: str) -> "ModuleBuilder":
        self.transitions.extend(lines)
        return self

    def guarded(self, guard: str, *assignments: str, label: str | None = None) -> "ModuleBuilder":
        self.commands.append(GuardedCommand(label, guard, list(assignments)))
        return self

    def raw(self, text: str) -> "ModuleBuilder":
        self.raw_sections.append(text)
        return self

    def source(self, *, indent: int = 2) -> str:
        name = self.name if self.params is None else f"{self.name} [{self.params}]"
        lines = [" " * indent + f"{name}: MODULE =", " " * (indent + 2) + "BEGIN"]
        for title, decls in (
            ("INPUT", self.inputs),
            ("OUTPUT", self.outputs),
            ("LOCAL", self.locals),
            ("GLOBAL", self.globals),
        ):
            for var_name, type_ in decls:
                lines.append(" " * (indent + 4) + f"{title} {var_name} : {type_}")
        if self.initializations:
            lines.append(" " * (indent + 4) + "INITIALIZATION")
            lines.extend(_indent(line, indent + 6) for line in self.initializations)
        if self.definitions:
            lines.append(" " * (indent + 4) + "DEFINITION")
            lines.extend(_indent(_ensure_semicolon(line), indent + 6) for line in self.definitions)
        if self.commands:
            lines.append(" " * (indent + 4) + "TRANSITION")
            lines.append(" " * (indent + 6) + "[")
            for idx, command in enumerate(self.commands):
                if idx:
                    lines.append(" " * (indent + 7) + "[]")
                lines.append(command.source(indent=indent + 7))
            lines.append(" " * (indent + 6) + "]")
        elif self.transitions:
            lines.append(" " * (indent + 4) + "TRANSITION")
            lines.extend(_indent(line, indent + 6) for line in self.transitions)
        for section in self.raw_sections:
            lines.append(_indent(section, indent + 4))
        lines.append(" " * (indent + 2) + "END;")
        return "\n".join(lines)


@dataclass
class ContextBuilder:
    name: str
    params: str | None = None
    imports: list[str] = field(default_factory=list)
    types: list[tuple[str, str]] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    modules: list[ModuleBuilder] = field(default_factory=list)
    theorems: list[tuple[str, str, str, str]] = field(default_factory=list)
    raw_declarations: list[str] = field(default_factory=list)

    def import_(self, text: str) -> "ContextBuilder":
        self.imports.append(text)
        return self

    def type(self, name: str, definition: str) -> "ContextBuilder":
        self.types.append((name, definition))
        return self

    def constant(self, declaration: str) -> "ContextBuilder":
        self.constants.append(declaration)
        return self

    def module(self, name: str, *, params: str | None = None) -> ModuleBuilder:
        module = ModuleBuilder(name=name, params=params)
        self.modules.append(module)
        return module

    def theorem(
        self,
        name: str,
        module: str,
        formula: str,
        *,
        kind: str = "THEOREM",
    ) -> "ContextBuilder":
        self.theorems.append((name, kind, module, formula))
        return self

    def raw(self, declaration: str) -> "ContextBuilder":
        self.raw_declarations.append(declaration)
        return self

    def source(self) -> str:
        name = self.name if self.params is None else f"{self.name} {{{self.params}}}"
        lines = [f"{name}: CONTEXT =", "BEGIN"]
        for import_text in self.imports:
            lines.append(_indent(_ensure_semicolon(f"IMPORTING {import_text}"), 2))
        for type_name, definition in self.types:
            lines.append(_indent(f"{type_name}: TYPE = {definition};", 2))
        for declaration in self.constants:
            lines.append(_indent(_ensure_semicolon(declaration), 2))
        for declaration in self.raw_declarations:
            lines.append(_indent(_ensure_semicolon(declaration), 2))
        for module in self.modules:
            lines.append("")
            lines.append(module.source(indent=2))
        for theorem_name, kind, module_name, formula in self.theorems:
            lines.append("")
            lines.append(_indent(f"{theorem_name}: {kind} {module_name} |- {formula};", 2))
        lines.append("END")
        return "\n".join(lines)

    def write(self, directory: str | Path | None = None) -> Path:
        if directory is None:
            directory = tempfile.mkdtemp(prefix="salpy-")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.file_stem()}.sal"
        path.write_text(self.source(), encoding="utf-8")
        return path

    def load(self, sal, directory: str | Path | None = None):
        return sal.load_context(self.write(directory))

    def file_stem(self) -> str:
        stem = re.split(r"[\s{]", self.name, maxsplit=1)[0]
        return stem

