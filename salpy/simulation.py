"""BDD-based simulation helpers."""

from __future__ import annotations

from typing import Any

from .objects import BddFsm, Module, Path, StateSet, wrap_object
from .sexpr import scheme_literal


class Simulation:
    """A small stateful wrapper around SAL's BDD simulation primitives."""

    def __init__(self, sal, module_or_fsm: str | Module | BddFsm) -> None:
        self.sal = sal
        self.session = sal.session
        if isinstance(module_or_fsm, BddFsm):
            self.fsm = module_or_fsm
        elif isinstance(module_or_fsm, Module):
            self.fsm = module_or_fsm.fsm()
        else:
            ref, class_name = self.session.define(f"(make-bdd-fsm {scheme_literal(module_or_fsm)})")
            self.fsm = wrap_object(self.session, ref, class_name, kind="fsm")

        self.current_ref, current_class = self.session.define(f"(slot-value {self.fsm.ref} :initial-states)")
        self.trace_ref, _ = self.session.define(f"(list {self.current_ref})")
        self.visited_ref, _ = self.session.define(self.current_ref)
        self.current = wrap_object(self.session, self.current_ref, current_class, kind="states")
        self.visited = wrap_object(self.session, self.visited_ref, current_class, kind="states")

    def step(self) -> StateSet:
        self.session.eval(
            f"""
(begin
  (set! {self.current_ref} (sal-bdd-fsm/image {self.fsm.ref} {self.current_ref}))
  (set! {self.trace_ref} (cons {self.current_ref} {self.trace_ref}))
  (set! {self.visited_ref} (bdd/or {self.current_ref} {self.visited_ref}))
  #unspecified)
"""
        )
        return self.current

    def backtrack(self) -> StateSet:
        self.session.eval(
            f"""
(begin
  (when (null? (cdr {self.trace_ref}))
    (sign-error "Cannot backtrack: the simulation is at the initial frontier."))
  (set! {self.trace_ref} (cdr {self.trace_ref}))
  (set! {self.current_ref} (car {self.trace_ref}))
  #unspecified)
"""
        )
        return self.current

    def filter(self, goal: str | StateSet) -> StateSet:
        goal_expr = self._state_set_expr(goal)
        self.session.eval(
            f"""
(begin
  (set! {self.current_ref} (bdd/and {self.current_ref} {goal_expr}))
  (set! {self.trace_ref} (cons {self.current_ref} (cdr {self.trace_ref})))
  #unspecified)
"""
        )
        return self.current

    def restart(self, start: str | StateSet | None = None) -> StateSet:
        start_expr = f"(slot-value {self.fsm.ref} :initial-states)" if start is None else self._state_set_expr(start)
        self.session.eval(
            f"""
(begin
  (set! {self.current_ref} {start_expr})
  (set! {self.trace_ref} (list {self.current_ref}))
  (set! {self.visited_ref} {self.current_ref})
  #unspecified)
"""
        )
        return self.current

    def run_until(self, goal: str | StateSet) -> bool:
        goal_expr = self._state_set_expr(goal)
        text = self.session.capture_text(
            f"""
(let* ((goal-bdd {goal_expr})
       (trace (sal-bdd-fsm/make-trace-from-to {self.fsm.ref} {self.current_ref} goal-bdd)))
  (cond
    ((and trace (not (null? trace)))
     (for-each (lambda (bdd)
                 (set! {self.trace_ref} (cons bdd {self.trace_ref}))
                 (set! {self.current_ref} bdd)
                 (set! {self.visited_ref} (bdd/or bdd {self.visited_ref})))
               (cdr (reverse trace)))
     "true")
    (else "false")))
"""
        )
        return text.strip() == "true"

    def display_current(self, *, limit: int = 10) -> str:
        return self.fsm.display_states(self.current, limit=limit)

    def display_trace(self) -> str:
        return self.session.capture_text(
            f"""
(with-output-to-string
  (lambda ()
    (let* ((bool-flat-module (slot-value {self.fsm.ref} :flat-module))
           (flat-module (sal-derived-flat-module/original-flat-module bool-flat-module))
           (bool-step-list (sal-bdd-fsm/trace->step-list {self.fsm.ref} {self.trace_ref} #t))
           (step-list (sal-bool-step-list->step-list bool-step-list bool-flat-module)))
      (sal-step-list/recover-executed-transition-info! step-list flat-module)
      (sal-step-list/display step-list flat-module #t #f #t #f 0))))
"""
        )

    def path(self) -> Path:
        ref, class_name = self.session.define(
            f"(sal-derived-path->original-path (sal-bdd-fsm/make-path {self.fsm.ref} {self.trace_ref} #t))"
        )
        return wrap_object(self.session, ref, class_name, kind="path")

    def _state_set_expr(self, value: str | StateSet) -> str:
        if isinstance(value, str):
            return f"(make-state-expression-bdd {scheme_literal(value)} {self.fsm.ref})"
        return scheme_literal(value)

