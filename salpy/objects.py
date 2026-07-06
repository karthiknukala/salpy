"""Python wrappers around live SAL objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .sexpr import keyword, scheme_call, scheme_literal


def _sal_number_to_int(text: str) -> int:
    value = text.strip()
    try:
        return int(value)
    except ValueError:
        return int(float(value))


def wrap_object(session, ref: str, class_name: str = "", *, kind: str | None = None):
    cls = _class_for(class_name, kind)
    return cls(session, ref, class_name=class_name, kind=kind)


def _class_for(class_name: str, kind: str | None):
    if kind == "context":
        return Context
    if kind == "module":
        return Module
    if kind == "term":
        return Term
    if kind == "type":
        return Type
    if kind == "assertion":
        return Assertion
    if kind == "path":
        return Path
    if kind == "fsm":
        return BddFsm
    if kind == "states":
        return StateSet

    lowered = class_name.lower()
    if "sal-context" in lowered:
        return Context
    if "sal-bdd-fsm" in lowered:
        return BddFsm
    if "sal-module-models" in lowered or "assertion" in lowered:
        return Assertion
    if "path" in lowered:
        return Path
    if "module" in lowered:
        return Module
    if "type" in lowered or "subrange" in lowered:
        return Type
    if lowered.startswith("<sal-"):
        return Term
    return SalObject


@dataclass
class SalObject:
    session: Any
    ref: str
    class_name: str = ""
    kind: str | None = None

    def _sal_ref(self) -> str:
        return self.ref

    def __repr__(self) -> str:
        cls = self.class_name or "SAL object"
        return f"<{self.__class__.__name__} {self.ref} {cls}>"

    def refresh_class_name(self) -> str:
        self.class_name = self.session.capture_text(f"(salpy/class-name {self.ref})").strip()
        return self.class_name

    def pp(self) -> str:
        return self.session.capture_text(f"(salpy/pp-string {self.ref})")

    def detailed(self) -> str:
        return self.session.capture_text(f"(salpy/pp-detailed-string {self.ref})")

    def value_pp(self) -> str:
        return self.session.capture_text(f"(salpy/value-pp-string {self.ref})")

    def slot(self, name: str, *, kind: str | None = None):
        slot = keyword(name)
        ref, class_name = self.session.define(f"(slot-value {self.ref} {slot})")
        return wrap_object(self.session, ref, class_name, kind=kind)

    def set_slot(self, name: str, value: Any) -> None:
        slot = keyword(name)
        self.session.eval(
            f"(begin (set-slot-value! {self.ref} {slot} {scheme_literal(value)}) #unspecified)"
        )

    def call(self, function: str, *args: Any, kind: str | None = None):
        ref, class_name = self.session.define(scheme_call(function, self, *args))
        return wrap_object(self.session, ref, class_name, kind=kind)

    def release(self) -> None:
        self.session.eval(f"(begin (set! {self.ref} #unspecified) #unspecified)")

    def is_instance(self, class_name: str) -> bool:
        wanted = class_name if class_name.startswith("<") else f"<{class_name}>"
        text = self.session.capture_text(
            f'(if (instance-of? {self.ref} {wanted}) "true" "false")'
        )
        return text.strip() == "true"


class Term(SalObject):
    def type(self) -> "Type":
        ref, class_name = self.session.define(f"(sal-expr/type {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="type")

    def simplify(self) -> "Term":
        ref, class_name = self.session.define(f"(sal/simplify {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def cse(self) -> "Term":
        ref, class_name = self.session.define(f"(sal/cse {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def not_(self) -> "Term":
        ref, class_name = self.session.define(f"(make-sal-not {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def and_(self, *others: Any) -> "Term":
        args = " ".join(scheme_literal(arg) for arg in (self, *others))
        ref, class_name = self.session.define(f"(make-sal-and {args})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def or_(self, *others: Any) -> "Term":
        args = " ".join(scheme_literal(arg) for arg in (self, *others))
        ref, class_name = self.session.define(f"(make-sal-or {args})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def equals(self, other: Any) -> "Term":
        ref, class_name = self.session.define(
            f"(make-sal-equality {self.ref} {scheme_literal(other)})"
        )
        return wrap_object(self.session, ref, class_name, kind="term")

    def apply(self, *args: Any) -> "Term":
        arg_expr = "(make-application-argument " + " ".join(scheme_literal(arg) for arg in args) + ")"
        ref, class_name = self.session.define(f"(make-sal-application {self.ref} {arg_expr})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def __and__(self, other: Any) -> "Term":
        return self.and_(other)

    def __or__(self, other: Any) -> "Term":
        return self.or_(other)

    def __invert__(self) -> "Term":
        return self.not_()


class Type(SalObject):
    def is_finite(self) -> bool:
        return (
            self.session.capture_text(f'(if (sal-type/finite? {self.ref}) "true" "false")').strip()
            == "true"
        )

    def number_of_elements(self) -> int:
        text = self.session.capture_text(f"(salpy/string (sal-type/number-of-elements-as-integer {self.ref}))")
        return int(text.strip())


class Context(SalObject):
    def name(self) -> str:
        return self.session.capture_text(f"(salpy/string (sal-context/name {self.ref}))").strip()

    def declarations(self) -> list[str]:
        return self.session.capture_lines(f"(salpy/context-declaration-names {self.ref})")

    def module(self, name: str):
        return self._decl(name, "sal-context/module-declaration", "module-decl")

    def assertion(self, name: str):
        return self._decl(name, "sal-context/assertion-declaration", "assertion-decl")

    def type_decl(self, name: str):
        return self._decl(name, "sal-context/type-declaration", "type-decl")

    def constant(self, name: str):
        return self._decl(name, "sal-context/constant-declaration", "constant-decl")

    def _decl(self, name: str, function: str, kind: str):
        ref, class_name = self.session.define(scheme_call(function, self, name))
        return wrap_object(self.session, ref, class_name, kind=kind)


class Module(SalObject):
    def state_expr(self, expr: str) -> Term:
        ref, class_name = self.session.define(scheme_call("sal/state-expr", expr, self))
        return wrap_object(self.session, ref, class_name, kind="term")

    def flat(self, *, skolemize: bool = False):
        expr = f"(make-flat-module {self.ref} :skolemize? {scheme_literal(skolemize)})"
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="module")

    def boolean(self, *, skolemize: bool = False):
        expr = f"(make-boolean-flat-module {self.ref} :skolemize? {scheme_literal(skolemize)})"
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="module")

    def fsm(self):
        ref, class_name = self.session.define(f"(sal-flat-module->sal-bdd-fsm {self.boolean().ref})")
        return wrap_object(self.session, ref, class_name, kind="fsm")

    def state_variables(self) -> list[str]:
        return self.session.capture_lines(f"(salpy/module-state-variable-names {self.ref})")


class Assertion(SalObject):
    def flat(self, *, ltl: bool = False, skolemize: bool = False):
        expr = (
            f"(make-flat-assertion {self.ref} :ltl? {scheme_literal(ltl)} "
            f":skolemize? {scheme_literal(skolemize)})"
        )
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def boolean(self, *, ltl: bool = True, skolemize: bool = False):
        expr = (
            f"(make-boolean-assertion {self.ref} :ltl? {scheme_literal(ltl)} "
            f":skolemize? {scheme_literal(skolemize)})"
        )
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def module(self):
        return self.slot("module", kind="module")

    def body(self):
        return self.slot("expr", kind="term")

    def is_invariant(self) -> bool:
        return (
            self.session.capture_text(f'(if (sal-module-models/invariant? {self.ref}) "true" "false")').strip()
            == "true"
        )


class BddFsm(SalObject):
    def initial_states(self):
        ref, class_name = self.session.define(f"(slot-value {self.ref} :initial-states)")
        return wrap_object(self.session, ref, class_name, kind="states")

    def reachable_states(self):
        ref, class_name = self.session.define(f"(sal-bdd-fsm/reachable-states {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="states")

    def num_reachable_states(self) -> int:
        text = self.session.capture_text(f"(salpy/string (sal-bdd-fsm/num-reachable-states {self.ref}))")
        return _sal_number_to_int(text)

    def state_expr(self, expr: str):
        ref, class_name = self.session.define(scheme_call("make-state-expression-bdd", expr, self))
        return wrap_object(self.session, ref, class_name, kind="states")

    def display_states(self, states: Any | None = None, *, limit: int = 10) -> str:
        state_ref = scheme_literal(states) if states is not None else f"(slot-value {self.ref} :initial-states)"
        return self.session.capture_text(
            f'(with-output-to-string (lambda () (sal-bdd-fsm/display-states-without-choices {self.ref} {state_ref} {limit} #f)))'
        )


class StateSet(SalObject):
    def count(self, fsm: BddFsm) -> int:
        text = self.session.capture_text(f"(salpy/string (sal-bdd-fsm/num-states {fsm.ref} {self.ref}))")
        return _sal_number_to_int(text)

    def union(self, other: Any):
        ref, class_name = self.session.define(f"(bdd/or {self.ref} {scheme_literal(other)})")
        return wrap_object(self.session, ref, class_name, kind="states")

    def intersection(self, other: Any):
        ref, class_name = self.session.define(f"(bdd/and {self.ref} {scheme_literal(other)})")
        return wrap_object(self.session, ref, class_name, kind="states")

    def complement(self):
        ref, class_name = self.session.define(f"(bdd/not {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="states")


class Path(SalObject):
    def length(self) -> int | str:
        value = self.session.capture_text(f"(salpy/path-length-string {self.ref})").strip()
        try:
            return int(value)
        except ValueError:
            return value

    def state_expr(self, index: int, *, include_choices: bool = False) -> Term:
        ref, class_name = self.session.define(
            f"(sal-path/state-expr {self.ref} {index} {scheme_literal(include_choices)})"
        )
        return wrap_object(self.session, ref, class_name, kind="term")

    def evaluate(self, expr: str | Term, index: int):
        ref, class_name = self.session.define(
            f"(sal-path/evaluate-expr-at {self.ref} {scheme_literal(expr)} {index})"
        )
        return wrap_object(self.session, ref, class_name, kind="term")

    def states(self, limit: Optional[int] = None, *, include_choices: bool = False) -> list[str]:
        length = self.length()
        if isinstance(length, str):
            if limit is None:
                limit = 10
            count = limit
        else:
            count = min(length, limit) if limit is not None else length
        return [self.state_expr(i, include_choices=include_choices).pp() for i in range(count)]
