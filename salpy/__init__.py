"""Ergonomic Python bindings for the SAL model checker."""

from .builders import ContextBuilder, ModuleBuilder
from .composition import ModuleExpression, async_, module_expr, sync
from .core import SAL, connect
from .engines import CheckResult, Engines, ToolResult
from .exceptions import (
    SalEngineError,
    SalError,
    SalNotFoundError,
    SalObjectError,
    SalProcessError,
    SalTimeoutError,
)
from .objects import (
    Assertion,
    BddFsm,
    Context,
    Declaration,
    Module,
    Path,
    SalObject,
    StateSet,
    Term,
    Type,
)
from .session import SalSession, find_sal_dir
from .simulation import Simulation

__all__ = [
    "Assertion",
    "BddFsm",
    "CheckResult",
    "Context",
    "ContextBuilder",
    "Declaration",
    "Engines",
    "Module",
    "ModuleBuilder",
    "ModuleExpression",
    "Path",
    "SAL",
    "SalEngineError",
    "SalError",
    "SalNotFoundError",
    "SalObject",
    "SalObjectError",
    "SalProcessError",
    "SalSession",
    "SalTimeoutError",
    "Simulation",
    "StateSet",
    "Term",
    "ToolResult",
    "Type",
    "connect",
    "async_",
    "module_expr",
    "sync",
    "find_sal_dir",
]
