"""Exceptions raised by salpy."""


class SalError(RuntimeError):
    """Base class for salpy errors."""


class SalNotFoundError(SalError):
    """Raised when a SAL installation or executable cannot be found."""


class SalProcessError(SalError):
    """Raised when SAL reports an evaluation or process error."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class SalTimeoutError(SalProcessError):
    """Raised when a SAL command does not finish before its timeout."""


class SalEngineError(SalProcessError):
    """Raised when a model-checking backend fails."""

