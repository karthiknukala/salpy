"""Model-checker and backend invocation helpers."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import SalEngineError, SalProcessError, SalTimeoutError
from .objects import SalObject, wrap_object
from .session import BEGIN_TEXT, END_TEXT, SalSession, extract_text_block
from .sexpr import scheme_literal, sym


@dataclass
class CheckResult:
    engine: str
    status: str
    counterexample: SalObject | None = None
    witness: SalObject | None = None
    induction_counterexample: SalObject | None = None
    assertion: Any = None
    output: str = ""
    stderr: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"proved", "valid", "no_counterexample"}

    @property
    def has_trace(self) -> bool:
        return any(
            item is not None
            for item in (self.counterexample, self.witness, self.induction_counterexample)
        )

    @property
    def proved(self) -> bool:
        """True only for a proof, never for a bounded absence of counterexamples."""
        return self.status in {"proved", "valid"}

    @property
    def bounded_safe(self) -> bool:
        return self.status == "no_counterexample"

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class ToolResult:
    tool: str
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def check(self) -> ToolResult:
        if not self.ok:
            raise SalEngineError(
                f"{self.tool} exited with code {self.returncode}",
                stdout=self.stdout,
                stderr=self.stderr,
            )
        return self


class Engines:
    def __init__(self, sal) -> None:
        self.sal = sal

    @property
    def session(self) -> SalSession:
        return self.sal if isinstance(self.sal, SalSession) else self.sal.session

    def smc(
        self,
        assertion: str | SalObject,
        *,
        context: str | os.PathLike[str] | None = None,
        counterexamples: bool = True,
        forward: bool = True,
        prioritized: bool = False,
        strategy: str = "greedy",
        threshold: int = 10000,
        timeout: float | None = None,
    ) -> CheckResult:
        """Run SAL's BDD symbolic model checker."""

        self._load_context(context)
        path_ref, _ = self.session.define("#unspecified")
        assertion_expr = scheme_literal(assertion, session=self.session)
        code = f"""
(begin
  (sal-smc/enable-counter-examples! {scheme_literal(counterexamples)})
  (sal-smc/enable-prioritized-traversal! {scheme_literal(prioritized)})
  (sal-smc/set-prioritized-traversal-strategy! {scheme_literal(sym(strategy))})
  (sal-smc/set-prioritized-traversal-threshold! {threshold})
  (let* ((assertion (make-boolean-assertion {assertion_expr} :ltl? #t))
         (flat-module (slot-value assertion :module))
         (fsm (sal-flat-module->sal-bdd-fsm flat-module)))
    (multiple-value-bind
        (valid? ce)
        (cond
          ((sal-module-models/invariant? assertion)
           (sal-module-models/smc-invariant-core assertion fsm {scheme_literal(forward)}))
          ((sal-module-models/accepting? assertion)
           (sal-module-models/smc-accepting assertion fsm))
          (else
           (sign-error "sal-smc supports invariant and LTL/accepting assertions.")))
      (set! {path_ref} (if (eq? ce #unspecified) #unspecified (sal-derived-path->original-path ce)))
      (print {scheme_literal(BEGIN_TEXT)})
      (print (cond
        (valid? "proved")
        ((eq? ce #unspecified) "invalid")
        (else "counterexample")))
      (print (salpy/class-name {path_ref}))
      (print {scheme_literal(END_TEXT)})))
  #unspecified)
"""
        return self._result_from_eval("smc", code, path_ref, assertion, timeout=timeout)

    def bmc(
        self,
        assertion: str | SalObject,
        *,
        context: str | os.PathLike[str] | None = None,
        depth: int = 10,
        from_depth: int = 0,
        to_depth: int | None = None,
        solver: str = "yices",
        acyclic: bool = False,
        iterative: bool = False,
        induction: bool = False,
        lemmas: list[str] | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Run SAL's bounded model checker."""

        return self._bounded(
            "bmc",
            assertion,
            context=context,
            depth=depth,
            from_depth=from_depth,
            to_depth=to_depth,
            solver=solver,
            acyclic=acyclic,
            iterative=iterative,
            induction=induction,
            lemmas=lemmas,
            timeout=timeout,
        )

    def inf_bmc(
        self,
        assertion: str | SalObject,
        *,
        context: str | os.PathLike[str] | None = None,
        depth: int = 10,
        from_depth: int = 0,
        to_depth: int | None = None,
        solver: str = "yices",
        acyclic: bool = False,
        iterative: bool = False,
        induction: bool = False,
        lemmas: list[str] | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Run SAL's infinite-state BMC entry points.

        Set ``induction=True`` to run SAL's ``sal-inf-bmc/k-induction`` after
        the bounded safety search succeeds.
        """

        return self._bounded(
            "inf_bmc",
            assertion,
            context=context,
            depth=depth,
            from_depth=from_depth,
            to_depth=to_depth,
            solver=solver,
            acyclic=acyclic,
            iterative=iterative,
            induction=induction,
            lemmas=lemmas,
            timeout=timeout,
        )

    def _bounded(
        self,
        engine: str,
        assertion: str | SalObject,
        *,
        context,
        depth: int,
        from_depth: int,
        to_depth: int | None,
        solver: str,
        acyclic: bool,
        iterative: bool,
        induction: bool,
        lemmas: list[str] | None,
        timeout: float | None,
    ) -> CheckResult:
        upper = depth if to_depth is None else to_depth
        if (
            any(
                isinstance(n, bool) or not isinstance(n, int) or n < 0
                for n in (depth, from_depth, upper)
            )
            or from_depth > upper
        ):
            raise ValueError("BMC requires integer depths with 0 <= from_depth <= to_depth.")
        if induction and (from_depth != 0 or upper == 0):
            raise ValueError("K-induction requires from_depth=0 and a positive depth.")
        if lemmas and not induction:
            raise ValueError("Lemmas require induction=True.")
        if lemmas and (not isinstance(assertion, str) or isinstance(lemmas, str)):
            raise ValueError("Lemmas require a named assertion and a list of assertion names.")
        if lemmas and any(not isinstance(lemma, str) for lemma in lemmas):
            raise TypeError("Lemma names must be strings.")
        solver_expr = scheme_literal(sym(solver))
        assertion_expr = scheme_literal(assertion, session=self.session)
        self._load_context(context)
        prefix = "sal-inf-bmc" if engine == "inf_bmc" else "sal-bmc"
        make_assertion = "make-flat-assertion" if engine == "inf_bmc" else "make-boolean-assertion"
        try:
            assertion_ref, _ = self.session.define(
                f"({make_assertion} {assertion_expr} :ltl? #t)", timeout=timeout
            )
            if induction:
                invariant = (
                    self.session.capture_text(
                        f'(if (sal-module-models/invariant? {assertion_ref}) "true" "false")',
                        timeout=timeout,
                    ).strip()
                    == "true"
                )
                if not invariant:
                    raise ValueError(
                        "K-induction is only supported for invariant (safety) properties."
                    )
            path_ref, _ = self.session.define("#unspecified", timeout=timeout)
        except SalTimeoutError:
            raise
        except SalProcessError as exc:
            raise SalEngineError(
                f"{engine} failed: {exc}", stdout=exc.stdout, stderr=exc.stderr
            ) from exc
        single_step = not iterative
        lemma_expr = "'()"
        if lemmas:
            lemma_expr = (
                f"({prefix}/create-assertion-lemmas {scheme_literal(lemmas)} "
                f"(sal/assertion-name {scheme_literal(assertion)}) assertion)"
            )
        code = f"""
(begin
  (let* ((assertion {assertion_ref})
         (lemma-exprs {lemma_expr}))
    (multiple-value-bind
        (valid? ce)
        (cond
          ((sal-module-models/invariant? assertion)
           ({prefix}/invariant assertion {from_depth} {upper} {scheme_literal(acyclic)} {scheme_literal(single_step)} {solver_expr}))
          (else
           ({prefix}/liveness assertion {upper} {scheme_literal(single_step)} {solver_expr})))
      (cond
        ((and valid? {scheme_literal(induction)} (sal-module-models/invariant? assertion))
         (multiple-value-bind
             (proved? induction-ce)
             ({prefix}/k-induction assertion {upper} {scheme_literal(acyclic)} lemma-exprs {solver_expr})
           (set! {path_ref} (if (eq? induction-ce #unspecified) #unspecified (sal-derived-path->original-path induction-ce)))
           (print {scheme_literal(BEGIN_TEXT)})
           (print (if proved? "proved" "induction_failed"))
           (print (salpy/class-name {path_ref}))
           (print {scheme_literal(END_TEXT)})))
        (else
         (set! {path_ref} (if (eq? ce #unspecified) #unspecified (sal-derived-path->original-path ce)))
         (print {scheme_literal(BEGIN_TEXT)})
         (print (cond
           (valid? "no_counterexample")
           ((eq? ce #unspecified) "invalid")
           (else "counterexample")))
         (print (salpy/class-name {path_ref}))
         (print {scheme_literal(END_TEXT)})))))
  #unspecified)
"""
        return self._result_from_eval(
            engine,
            code,
            path_ref,
            assertion,
            timeout=timeout,
            details={
                "from_depth": from_depth,
                "to_depth": upper,
                "solver": solver,
                "induction": induction,
                "iterative": iterative,
                "acyclic": acyclic,
            },
        )

    def wmc(
        self,
        assertion: str | SalObject,
        *,
        context: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Run SAL's CTL witness/counterexample symbolic checker."""

        self._load_context(context)
        evidence_ref, _ = self.session.define("#unspecified")
        assertion_expr = scheme_literal(assertion, session=self.session)
        code = f"""
(begin
  (let* ((assertion0 (make-boolean-assertion {assertion_expr}))
         (assertion (if (sal-module-models/ctl-property? assertion0)
                      assertion0
                      (let* ((property (slot-value assertion0 :expr))
                             (ctl-property (ltl->ctl property)))
                        (copy-instance assertion0 :expr ctl-property))))
         (flat-module (slot-value assertion :module))
         (fsm (sal-flat-module->sal-bdd-fsm flat-module))
         (evidence (sal-wmc/ctl-check fsm (slot-value assertion :expr))))
    (set! {evidence_ref} evidence)
    (print {scheme_literal(BEGIN_TEXT)})
    (print (if (instance-of? evidence <wmc-witness>) "proved" "counterexample"))
    (print (salpy/class-name {evidence_ref}))
    (print {scheme_literal(END_TEXT)}))
  #unspecified)
"""
        result = self._result_from_eval("wmc", code, evidence_ref, assertion, timeout=timeout)
        if result.status == "proved":
            result.witness = result.counterexample
            result.counterexample = None
        return result

    def emc(
        self,
        assertion: str | SalObject,
        *,
        context: str | os.PathLike[str] | None = None,
        strategy: str = "dfs",
        max_depth: int | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Run SAL's explicit-state model checker."""

        self._load_context(context)
        path_ref, _ = self.session.define("#unspecified")
        assertion_expr = scheme_literal(assertion, session=self.session)
        depth_expr = "#f" if max_depth is None else str(max_depth)
        code = f"""
(begin
  (sal-esmc/set-traversal-strategy! {scheme_literal(sym(strategy))})
  (sal-esm/set-max-search-depth! {depth_expr})
  (let ((result (sal-esmc/verify {assertion_expr})))
    (print {scheme_literal(BEGIN_TEXT)})
    (cond
      ((eq? result 'valid)
       (set! {path_ref} #unspecified)
       (print "proved"))
      ((eq? result 'unknown)
       (set! {path_ref} #unspecified)
       (print "unknown"))
      ((eq? result 'invalid)
       (set! {path_ref} #unspecified)
       (print "invalid"))
      ((pair? result)
       (set! {path_ref} (cdr result))
       (print (symbol->string (car result))))
      (else
       (set! {path_ref} #unspecified)
       (print "unknown")))
    (print (salpy/class-name {path_ref}))
    (print {scheme_literal(END_TEXT)}))
  #unspecified)
"""
        return self._result_from_eval(
            "emc",
            code,
            path_ref,
            assertion,
            timeout=timeout,
            details={"strategy": strategy, "max_depth": max_depth},
        )

    def command(
        self, tool: str, *args: str | os.PathLike[str], timeout: float | None = None
    ) -> ToolResult:
        """Run one of SAL's command-line tools and return captured output."""

        tool_path = Path(tool)
        if not tool_path.is_absolute():
            tool_path = self.session.sal_dir / "bin" / tool
        try:
            completed = subprocess.run(
                [str(tool_path), *(str(arg) for arg in args)],
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=self.session.environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise SalTimeoutError(
                f"{tool} timed out after {exc.timeout:g} seconds",
                stdout=_output_text(exc.stdout),
                stderr=_output_text(exc.stderr),
            ) from exc
        except OSError as exc:
            raise SalEngineError(f"Could not run {tool_path}: {exc}") from exc
        return ToolResult(
            tool=str(tool_path),
            args=tuple(str(arg) for arg in args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _load_context(self, context: str | os.PathLike[str] | None) -> None:
        if context is not None:
            if isinstance(self.sal, SalSession):
                raise ValueError("Load contexts through SAL.load_context() before Module.check().")
            self.sal.load_context(context)

    def _result_from_eval(
        self,
        engine: str,
        code: str,
        object_ref: str,
        assertion: Any,
        *,
        timeout: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> CheckResult:
        try:
            eval_result = self.session.eval(code, timeout=timeout)
        except SalTimeoutError:
            raise
        except SalProcessError as exc:
            raise SalEngineError(
                f"{engine} failed: {exc}", stdout=exc.stdout, stderr=exc.stderr
            ) from exc

        block = extract_text_block(eval_result.stdout).splitlines()
        status = block[0].strip() if block else "unknown"
        class_name = block[1].strip() if len(block) > 1 else ""
        trace = None
        if class_name and class_name != "<primitive>" and engine == "wmc":
            trace = wrap_object(self.session, object_ref, class_name)
        elif (
            class_name
            and class_name != "<primitive>"
            and status not in {"proved", "valid", "no_counterexample", "unknown"}
        ):
            trace = wrap_object(self.session, object_ref, class_name, kind="path")
        return CheckResult(
            engine=engine,
            status=status,
            counterexample=trace if status != "induction_failed" else None,
            induction_counterexample=trace if status == "induction_failed" else None,
            assertion=assertion,
            output=eval_result.stdout,
            stderr=eval_result.stderr,
            details=dict(details or {}),
        )


def _output_text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
