"""Python wrappers around live SAL objects."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, overload

from .composition import identifier
from .exceptions import SalObjectError
from .sexpr import keyword, scheme_call, scheme_literal, sym

if TYPE_CHECKING:
    from .engines import CheckResult
    from .session import SalSession


def _sal_number_to_int(text: str) -> int:
    value = text.strip()
    try:
        return int(value)
    except ValueError:
        number = Decimal(value)
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError(f"SAL returned a non-integral state count: {text!r}") from None
        return int(number)


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["context"]
) -> Context: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["module"]
) -> Module: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["term"]
) -> Term: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["type"]
) -> Type: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["assertion"]
) -> Assertion: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["path"]
) -> Path: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["fsm"]
) -> BddFsm: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: Literal["states"]
) -> StateSet: ...


@overload
def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: str | None = None
) -> SalObject: ...


def wrap_object(
    session: SalSession, ref: str, class_name: str = "", *, kind: str | None = None
) -> SalObject:
    cls = _class_for(class_name, kind)
    return cls(session, ref, class_name=class_name, kind=kind)


def _class_for(class_name: str, kind: str | None) -> type[SalObject]:
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
    if lowered.endswith("-decl>") or kind and kind.endswith("-decl"):
        return Declaration
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


class SalObject:
    def __init__(
        self, session: SalSession, ref: str, class_name: str = "", kind: str | None = None
    ) -> None:
        self.session = session
        self._ref = ref
        self.class_name = class_name
        self.kind = kind
        self._generation = session.generation
        self._released = False

    @property
    def ref(self) -> str:
        if self._released:
            raise SalObjectError("This SAL object has been released.")
        if not self.session.is_running or self._generation != self.session.generation:
            raise SalObjectError("This SAL object belongs to a closed or reset session.")
        return self._ref

    def _sal_ref(self, *, session: SalSession | None = None) -> str:
        if session is not None and session is not self.session:
            raise SalObjectError("SAL objects from different sessions cannot be combined.")
        return self.ref

    def __repr__(self) -> str:
        cls = self.class_name or "SAL object"
        return f"<{self.__class__.__name__} {self._ref} {cls}>"

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
            f"(begin (set-slot-value! {self.ref} {slot} {scheme_literal(value, session=self.session)}) #unspecified)"
        )

    def call(self, function: str, *args: Any, kind: str | None = None):
        ref, class_name = self.session.define(
            scheme_call(function, self, *args, session=self.session)
        )
        return wrap_object(self.session, ref, class_name, kind=kind)

    def release(self) -> None:
        if self._released:
            return
        self.session.eval(f"(begin (set! {self.ref} #unspecified) #unspecified)")
        self._released = True

    def is_instance(self, class_name: str) -> bool:
        wanted = class_name if class_name.startswith("<") else f"<{class_name}>"
        sym(wanted)
        text = self.session.capture_text(f'(if (instance-of? {self.ref} {wanted}) "true" "false")')
        return text.strip() == "true"


class Term(SalObject):
    def _operand(self, value: Any) -> str:
        if isinstance(value, Term):
            return value._sal_ref(session=self.session)
        if isinstance(value, (str, bool, int, float)):
            scheme_literal(value)
            text = str(value).upper() if isinstance(value, bool) else str(value)
            return scheme_call("sal/expr", text)
        raise TypeError("Term operands must be SAL terms, expression strings, or Python scalars.")

    def __bool__(self) -> bool:
        raise TypeError("SAL terms are symbolic. Use &, |, and ~ instead of Python and/or/not.")

    def type(self) -> Type:
        ref, class_name = self.session.define(f"(sal-expr/type {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="type")

    def simplify(self) -> Term:
        ref, class_name = self.session.define(f"(sal/simplify {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def cse(self) -> Term:
        ref, class_name = self.session.define(f"(sal/cse {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def not_(self) -> Term:
        ref, class_name = self.session.define(f"(make-sal-not {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def and_(self, *others: Any) -> Term:
        args = " ".join(self._operand(arg) for arg in (self, *others))
        ref, class_name = self.session.define(f"(make-sal-and {args})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def or_(self, *others: Any) -> Term:
        args = " ".join(self._operand(arg) for arg in (self, *others))
        ref, class_name = self.session.define(f"(make-sal-or {args})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def equals(self, other: Any) -> Term:
        ref, class_name = self.session.define(
            f"(make-sal-equality {self.ref} {self._operand(other)})"
        )
        return wrap_object(self.session, ref, class_name, kind="term")

    def apply(self, *args: Any) -> Term:
        arg_expr = (
            "(make-application-argument " + " ".join(self._operand(arg) for arg in args) + ")"
        )
        ref, class_name = self.session.define(f"(make-sal-application {self.ref} {arg_expr})")
        return wrap_object(self.session, ref, class_name, kind="term")

    def __and__(self, other: Any) -> Term:
        return self.and_(other)

    def __or__(self, other: Any) -> Term:
        return self.or_(other)

    def __invert__(self) -> Term:
        return self.not_()


class Type(SalObject):
    def is_finite(self) -> bool:
        return (
            self.session.capture_text(f'(if (sal-type/finite? {self.ref}) "true" "false")').strip()
            == "true"
        )

    def number_of_elements(self) -> int:
        text = self.session.capture_text(
            f"(salpy/string (sal-type/number-of-elements-as-integer {self.ref}))"
        )
        return int(text.strip())


class Declaration(SalObject):
    """A declaration, distinct from the module, type, or expression it defines."""

    def definition(self) -> SalObject:
        if self.is_instance("sal-module-decl"):
            return self.slot("parametric-module").slot("module", kind="module")
        if self.is_instance("sal-assertion-decl"):
            return self.slot("assertion-expr", kind="assertion")
        if self.is_instance("sal-type-decl"):
            return self.slot("type", kind="type")
        return self.slot("value", kind="term")


class Context(SalObject):
    def name(self) -> str:
        return self.session.capture_text(f"(salpy/string (sal-context/name {self.ref}))").strip()

    def declarations(self) -> list[str]:
        return self.session.capture_lines(f"(salpy/context-declaration-names {self.ref})")

    def module(self, name: str, *actuals: str | int | bool) -> Module:
        from .composition import module_expr

        text = module_expr(f"{self.name()}!{identifier(name)}").instantiate(*actuals)
        ref, class_name = self.session.define(scheme_call("sal/module", str(text)))
        return wrap_object(self.session, ref, class_name, kind="module")

    def assertion(self, name: str) -> Assertion:
        ref, class_name = self.session.define(
            scheme_call("sal/assertion-name", f"{self.name()}!{identifier(name)}")
        )
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def module_decl(self, name: str) -> Declaration:
        return self._decl(name, "sal-context/module-declaration", "module-decl")

    def assertion_decl(self, name: str) -> Declaration:
        return self._decl(name, "sal-context/assertion-declaration", "assertion-decl")

    def type_decl(self, name: str) -> Declaration:
        return self._decl(name, "sal-context/type-declaration", "type-decl")

    def constant(self, name: str) -> Declaration:
        return self._decl(name, "sal-context/constant-declaration", "constant-decl")

    def _decl(self, name: str, function: str, kind: str) -> Declaration:
        ref, class_name = self.session.define(scheme_call(function, self, sym(identifier(name))))
        if class_name == "<primitive>":
            raise KeyError(name)
        return Declaration(self.session, ref, class_name, kind=kind)


class Module(SalObject):
    def sync(self, *others: Module) -> Module:
        """Compose live modules in lockstep using SAL's native AST constructors."""
        return self._compose("<sal-synch-composition>", others)

    def async_(self, *others: Module) -> Module:
        """Interleave live modules; one component takes each transition."""
        return self._compose("<sal-asynch-composition>", others)

    def observe(self, observer: Module) -> Module:
        """Attach a definition-only observer on the right."""
        return self._compose("<sal-observer>", (observer,))

    def _compose(self, class_name: str, others: tuple[Module, ...]) -> Module:
        if not others:
            return self
        expression = self.ref
        for other in others:
            if not isinstance(other, Module):
                raise TypeError(
                    "Live composition requires Module objects; use sal.module(...) first."
                )
            expression = (
                f"(salpy/module-compose {class_name} {expression} "
                f"{other._sal_ref(session=self.session)})"
            )
        ref, class_name = self.session.define(f"(salpy/checked-module {expression})")
        return wrap_object(self.session, ref, class_name, kind="module")

    def rename(self, names: Mapping[str, str] | None = None, **renames: str) -> Module:
        """Simultaneously rename state variables to new identifiers.

        For array/record targets and indexed composition, use ModuleExpression
        while building a context, so SAL can resolve the index and shared types.
        """
        pairs = {**(names or {}), **renames}
        if not pairs:
            return self
        values = [[identifier(old), identifier(new)] for old, new in pairs.items()]
        return self.call("salpy/module-rename", values, kind="module")

    def hide(self, *names: str) -> Module:
        """Hide output/global variables from the interface."""
        return self._organize("<sal-hiding>", names)

    def output(self, *names: str) -> Module:
        """Turn global variables into outputs."""
        return self._organize("<sal-new-output>", names)

    def _organize(self, class_name: str, names: tuple[str, ...]) -> Module:
        if not names:
            return self
        values = scheme_literal([identifier(name) for name in names])
        ref, cls = self.session.define(f"(salpy/module-organize {class_name} {self.ref} {values})")
        return wrap_object(self.session, ref, cls, kind="module")

    def assertion(self, formula: str) -> Assertion:
        """Build a typechecked temporal assertion over this (possibly anonymous) module."""
        name = self.session.unique_name("salpy_property")
        assertion_ref, _ = self.session.define(
            f"(make-ast-instance <sal-module-models> {self.ref} :module {self.ref} "
            f":expr (sal/state-expr {scheme_literal(formula)} {self.ref}))"
        )
        assertion_source = self.session.capture_text(f"(salpy/lsal-source {assertion_ref})")
        source = f"(context {name} () () (theorem property {assertion_source}))"
        path = self.session.write_source(source, name, suffix=".lsal")
        self.session.define(scheme_call("salpy/load-context-file!", path))
        ref, class_name = self.session.define(scheme_call("sal/assertion-name", f"{name}!property"))
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def check(self, formula: str, *, engine: str = "smc", **options: Any) -> CheckResult:
        """Check a property without adding a named theorem to a context."""
        from .engines import Engines

        if engine not in {"smc", "wmc", "bmc", "inf_bmc", "emc"}:
            raise ValueError(f"Unknown model checker: {engine!r}")
        return getattr(Engines(self.session), engine)(self.assertion(formula), **options)

    def state_expr(self, expr: str) -> Term:
        ref, class_name = self.session.define(scheme_call("sal/state-expr", expr, self))
        return wrap_object(self.session, ref, class_name, kind="term")

    def flat(self, *, skolemize: bool = False) -> Module:
        expr = f"(make-flat-module {self.ref} :skolemize? {scheme_literal(skolemize)})"
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="module")

    def boolean(self, *, skolemize: bool = False) -> Module:
        expr = f"(make-boolean-flat-module {self.ref} :skolemize? {scheme_literal(skolemize)})"
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="module")

    def fsm(self) -> BddFsm:
        ref, class_name = self.session.define(
            f"(sal-flat-module->sal-bdd-fsm {self.boolean().ref})"
        )
        return wrap_object(self.session, ref, class_name, kind="fsm")

    def state_variables(self) -> list[str]:
        return self.session.capture_lines(f"(salpy/module-state-variable-names {self.ref})")


class Assertion(SalObject):
    def definition(self) -> Assertion:
        """Resolve a qualified theorem name, including its context parameters."""
        if not self.is_instance("sal-qualified-assertion-name"):
            return self
        return self.call("sal-assertion-name/definition", kind="assertion")

    def flat(self, *, ltl: bool = False, skolemize: bool = False) -> Assertion:
        expr = (
            f"(make-flat-assertion {self.ref} :ltl? {scheme_literal(ltl)} "
            f":skolemize? {scheme_literal(skolemize)})"
        )
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def boolean(self, *, ltl: bool = True, skolemize: bool = False) -> Assertion:
        expr = (
            f"(make-boolean-assertion {self.ref} :ltl? {scheme_literal(ltl)} "
            f":skolemize? {scheme_literal(skolemize)})"
        )
        ref, class_name = self.session.define(expr)
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def module(self) -> Module:
        return self.definition().slot("module", kind="module")

    def body(self) -> Term:
        return self.definition().slot("expr", kind="term")

    def is_invariant(self) -> bool:
        assertion = self.definition()
        return (
            self.session.capture_text(
                f'(if (sal-module-models/invariant? {assertion.ref}) "true" "false")'
            ).strip()
            == "true"
        )


class BddFsm(SalObject):
    def initial_states(self) -> StateSet:
        ref, class_name = self.session.define(f"(slot-value {self.ref} :initial-states)")
        return wrap_object(self.session, ref, class_name, kind="states")

    def reachable_states(self) -> StateSet:
        ref, class_name = self.session.define(f"(sal-bdd-fsm/reachable-states {self.ref})")
        return wrap_object(self.session, ref, class_name, kind="states")

    def num_reachable_states(self) -> int:
        text = self.session.capture_text(
            f"(salpy/string (sal-bdd-fsm/num-reachable-states {self.ref}))"
        )
        return _sal_number_to_int(text)

    def state_expr(self, expr: str) -> StateSet:
        ref, class_name = self.session.define(scheme_call("make-state-expression-bdd", expr, self))
        return wrap_object(self.session, ref, class_name, kind="states")

    def display_states(self, states: Any | None = None, *, limit: int = 10) -> str:
        state_ref = (
            scheme_literal(states, session=self.session)
            if states is not None
            else f"(slot-value {self.ref} :initial-states)"
        )
        return self.session.capture_text(
            f"(with-output-to-string (lambda () (sal-bdd-fsm/display-states-without-choices {self.ref} {state_ref} {limit} #f)))"
        )


class StateSet(SalObject):
    def count(self, fsm: BddFsm) -> int:
        fsm._sal_ref(session=self.session)
        text = self.session.capture_text(
            f"(salpy/string (sal-bdd-fsm/num-states {fsm.ref} {self.ref}))"
        )
        return _sal_number_to_int(text)

    def union(self, other: StateSet) -> StateSet:
        ref, class_name = self.session.define(
            f"(bdd/or {self.ref} {scheme_literal(other, session=self.session)})"
        )
        return wrap_object(self.session, ref, class_name, kind="states")

    def intersection(self, other: StateSet) -> StateSet:
        ref, class_name = self.session.define(
            f"(bdd/and {self.ref} {scheme_literal(other, session=self.session)})"
        )
        return wrap_object(self.session, ref, class_name, kind="states")

    def complement(self) -> StateSet:
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

    def evaluate(self, expr: str | Term, index: int) -> Term:
        ref, class_name = self.session.define(
            f"(sal-path/evaluate-expr-at {self.ref} {scheme_literal(expr, session=self.session)} {index})"
        )
        return wrap_object(self.session, ref, class_name, kind="term")

    def states(self, limit: int | None = None, *, include_choices: bool = False) -> list[str]:
        length = self.length()
        if isinstance(length, str):
            if limit is None:
                limit = 10
            count = limit
        else:
            count = min(length, limit) if limit is not None else length
        return [self.state_expr(i, include_choices=include_choices).pp() for i in range(count)]
