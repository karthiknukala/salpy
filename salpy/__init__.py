"""Ergonomic Python bindings for the SAL model checker."""

from .builders import ContextBuilder, ModuleBuilder
from .core import SAL, connect
from .engines import CheckResult, Engines, ToolResult
from .exceptions import (
    SalEngineError,
    SalError,
    SalNotFoundError,
    SalProcessError,
    SalTimeoutError,
)
from .objects import Assertion, BddFsm, Context, Module, Path, SalObject, StateSet, Term, Type
from .session import SalSession, find_sal_dir
from .simulation import Simulation

__all__ = [
    "Assertion",
    "BddFsm",
    "CheckResult",
    "Context",
    "ContextBuilder",
    "Engines",
    "Module",
    "ModuleBuilder",
    "Path",
    "SAL",
    "SalEngineError",
    "SalError",
    "SalNotFoundError",
    "SalObject",
    "SalProcessError",
    "SalSession",
    "SalTimeoutError",
    "Simulation",
    "StateSet",
    "Term",
    "ToolResult",
    "Type",
    "connect",
    "find_sal_dir",
]

