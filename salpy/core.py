"""Public high-level SAL facade."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from .builders import ContextBuilder
from .composition import ModuleExpression
from .engines import Engines
from .objects import Assertion, BddFsm, Context, Module, SalObject, Term, Type, wrap_object
from .session import SalSession
from .sexpr import scheme_call, scheme_literal
from .simulation import Simulation


class SAL:
    """High-level entry point for scripting SAL from Python."""

    def __init__(
        self,
        sal_dir: str | os.PathLike[str] | None = None,
        *,
        executable: str | os.PathLike[str] | None = None,
        context_path: Iterable[str | os.PathLike[str]] | None = None,
        timeout: float = 30.0,
        startup_timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> None:
        self.session = SalSession(
            sal_dir,
            executable=executable,
            context_path=context_path,
            timeout=timeout,
            startup_timeout=startup_timeout,
            env=env,
        )
        self.engines = Engines(self)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> SAL:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def eval(self, scheme: str, *, timeout: float | None = None) -> str:
        """Evaluate a raw Scheme/SALenv form and return printed output."""

        return self.session.eval(scheme, timeout=timeout).stdout

    def define(self, scheme_expr: str, *, kind: str | None = None) -> SalObject:
        ref, class_name = self.session.define(scheme_expr)
        return wrap_object(self.session, ref, class_name, kind=kind)

    def load_context(self, path_or_name: str | os.PathLike[str]) -> Context:
        """Load a context by file path or by SAL context name."""

        value = (
            Path(path_or_name) if isinstance(path_or_name, os.PathLike) else Path(str(path_or_name))
        )
        if value.exists():
            ref, class_name = self.session.define(
                scheme_call("salpy/load-context-file!", str(value.resolve()))
            )
            ctx = wrap_object(self.session, ref, class_name, kind="context")
            self._import_context_scope_if_simple(ctx)
            return ctx

        text = str(path_or_name)
        if Path(text).suffix in {".sal", ".lsal", ".xml"}:
            raise FileNotFoundError(text)

        ref, class_name = self.session.define(scheme_call("salpy/import-context!", text))
        ctx = wrap_object(self.session, ref, class_name, kind="context")
        self._import_context_scope_if_simple(ctx)
        return ctx

    def load_source(
        self,
        source: str,
        *,
        name: str | None = None,
        directory: str | os.PathLike[str] | None = None,
    ) -> Context:
        """Write SAL source to a temporary file, then import it."""

        if name is None:
            match = re.search(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\{|:)", source)
            if not match:
                raise ValueError("Could not infer the context name; pass name=...")
            name = match.group(1)
        return self.load_context(self.session.write_source(source, name, directory))

    def context(self, name: str) -> Context:
        ref, class_name = self.session.define(scheme_call("sal/context", name))
        return wrap_object(self.session, ref, class_name, kind="context")

    def import_(self, import_text: str) -> None:
        self.session.eval(f"(begin (sal/import {scheme_literal(import_text)}) #unspecified)")

    def _import_context_scope_if_simple(self, ctx: Context) -> None:
        has_params = self.session.capture_text(
            f'(if (null? (sal-context/params {ctx.ref})) "false" "true")'
        ).strip()
        if has_params == "false":
            self.import_(ctx.name())

    def expr(self, text: str) -> Term:
        ref, class_name = self.session.define(scheme_call("sal/expr", text))
        return wrap_object(self.session, ref, class_name, kind="term")

    term = expr

    def type(self, text: str) -> Type:
        ref, class_name = self.session.define(scheme_call("sal/type", text))
        return wrap_object(self.session, ref, class_name, kind="type")

    def assertion(self, text: str) -> Assertion:
        ref, class_name = self.session.define(scheme_call("sal/assertion-name", text))
        return wrap_object(self.session, ref, class_name, kind="assertion")

    def module(self, text: str | ModuleExpression) -> Module:
        ref, class_name = self.session.define(scheme_call("sal/module", str(text)))
        return wrap_object(self.session, ref, class_name, kind="module")

    def state_expr(self, text: str, module: str | Module) -> Term:
        module_obj = self.module(module) if isinstance(module, str) else module
        module_obj._sal_ref(session=self.session)
        return module_obj.state_expr(text)

    def flat_module(self, module: str | Module, *, skolemize: bool = False) -> Module:
        module_obj = self.module(module) if isinstance(module, str) else module
        module_obj._sal_ref(session=self.session)
        return module_obj.flat(skolemize=skolemize)

    def boolean_module(self, module: str | Module, *, skolemize: bool = False) -> Module:
        module_obj = self.module(module) if isinstance(module, str) else module
        module_obj._sal_ref(session=self.session)
        return module_obj.boolean(skolemize=skolemize)

    def fsm(self, module: str | Module) -> BddFsm:
        module_obj = self.module(module) if isinstance(module, str) else module
        module_obj._sal_ref(session=self.session)
        return module_obj.fsm()

    def simplify(self, obj: SalObject) -> SalObject:
        obj._sal_ref(session=self.session)
        return obj.call("sal/simplify")

    def cse(self, obj: SalObject) -> SalObject:
        obj._sal_ref(session=self.session)
        return obj.call("sal/cse")

    def reset(self) -> None:
        self.session.eval("(begin (sal/reset!) #unspecified)")
        self.session.generation += 1

    def configure(
        self,
        *,
        cse: bool | None = None,
        simplifier: bool | None = None,
        slicer: bool | None = None,
    ) -> None:
        forms = []
        if cse is not None:
            forms.append(f"(sal/enable-cse! {scheme_literal(cse)})")
        if simplifier is not None:
            forms.append(f"(sal/enable-simplifier! {scheme_literal(simplifier)})")
        if slicer is not None:
            forms.append(f"(sal/enable-slicer! {scheme_literal(slicer)})")
        if forms:
            self.session.eval("(begin " + " ".join(forms) + " #unspecified)")

    def use_sal_syntax(self) -> None:
        self.session.eval(
            "(begin (sal/set-sal-pp-proc! sal-ast->sal-doc) "
            "(sal/set-make-sal-string-reader-proc! make-sal-string-reader) #unspecified)"
        )

    def use_lsal_syntax(self) -> None:
        self.session.eval(
            "(begin (sal/set-sal-pp-proc! sal-ast->lsal-doc) "
            "(sal/set-make-sal-string-reader-proc! make-lsal-string-reader) #unspecified)"
        )

    def append_context_path(self, *paths: str | os.PathLike[str]) -> None:
        resolved = [str(Path(path).resolve()) for path in paths]
        items = scheme_literal(resolved)
        self.session.eval(
            f"(begin (sal-env/append-to-sal-context-path! *sal-env* {items}) #unspecified)"
        )
        self.session.context_path.extend(resolved)

    def set_context_path(self, *paths: str | os.PathLike[str]) -> None:
        resolved = [str(Path(path).resolve()) for path in paths]
        items = scheme_literal(resolved)
        self.session.eval(f"(begin (sal-env/set-sal-context-path! *sal-env* {items}) #unspecified)")
        self.session.context_path = resolved
        self.session._env_overrides["SALCONTEXTPATH"] = ""

    def help(self, prefix: str = "") -> str:
        return self.session.capture_text(
            f"(with-output-to-string (lambda () (api/show-entries {scheme_literal(prefix)})))"
        )

    def commands(self, prefix: str = "") -> str:
        return self.session.capture_text(
            f"(with-output-to-string (lambda () (api/show-entry-names {scheme_literal(prefix)})))"
        )

    def apropos(self, regex: str) -> str:
        return self.session.capture_text(
            f"(with-output-to-string (lambda () (api/apropos {scheme_literal(regex)})))"
        )

    def builder(self, name: str, *, params: str | None = None) -> ContextBuilder:
        return ContextBuilder(name=name, params=params)

    def simulate(self, module_or_fsm: str | Module | BddFsm) -> Simulation:
        return Simulation(self, module_or_fsm)


def connect(*args, **kwargs) -> SAL:
    return SAL(*args, **kwargs)
