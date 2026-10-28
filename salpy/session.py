"""Persistent SALenv process management."""

from __future__ import annotations

import math
import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .exceptions import SalNotFoundError, SalProcessError, SalTimeoutError
from .sexpr import scheme_literal

BEGIN_TEXT = "@@@SALPY_BEGIN_TEXT@@@"
END_TEXT = "@@@SALPY_END_TEXT@@@"


@dataclass
class EvalResult:
    stdout: str
    stderr: str


def find_sal_dir(start: Path | None = None) -> Path:
    """Find a nearby SAL installation directory."""

    env_dir = os.environ.get("SALENV_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))

    here = Path(__file__).resolve()
    roots = [Path.cwd(), *Path.cwd().parents, here.parents[1], *here.parents]
    if start is not None:
        roots.insert(0, Path(start).resolve())

    for root in roots:
        candidates.extend(
            [
                root / "sal-3.3",
                root / "../sal-3.3",
                root,
            ]
        )

    seen = set()
    for candidate in candidates:
        path = candidate.resolve()
        if path in seen:
            continue
        seen.add(path)
        if (path / "bin" / "salenv").exists():
            return path
    raise SalNotFoundError(
        "Could not find SAL. Pass sal_dir=... or set SALENV_DIR to the SAL installation."
    )


class SalSession:
    """A live SALenv slave-mode process.

    The session keeps SAL objects alive and lets Python refer to them through
    generated Scheme variable names.
    """

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
        self.sal_dir = Path(sal_dir).resolve() if sal_dir else find_sal_dir()
        self.executable = (
            Path(executable).resolve() if executable else self.sal_dir / "bin" / "salenv"
        )
        if not self.executable.exists():
            raise SalNotFoundError(f"SAL executable not found: {self.executable}")
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self._validate_timeout(timeout)
        self._validate_timeout(startup_timeout)
        self.context_path = [str(Path(p).resolve()) for p in context_path or []]
        self._env_overrides = dict(env or {})
        self._proc: subprocess.Popen[str] | None = None
        self._events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._counter = 0
        self.generation = 0
        self._readers: list[threading.Thread] = []
        self._sources: list[tempfile.TemporaryDirectory] = []
        self._lock = threading.RLock()
        self.start()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def environment(self) -> dict[str, str]:
        """Build the same configured environment for SALenv and CLI backends."""
        env = os.environ.copy()
        env.update(self._env_overrides)
        env["SALENV_DIR"] = str(self.sal_dir)
        env["PATH"] = env.get("PATH", "") + os.pathsep + str(self.sal_dir / "bin")
        if self.context_path:
            current = env.get("SALCONTEXTPATH")
            pieces = [*self.context_path]
            if current:
                pieces.append(current)
            env["SALCONTEXTPATH"] = os.pathsep.join(pieces)
        return env

    def start(self) -> None:
        if self.is_running:
            return
        self.generation += 1

        self._proc = subprocess.Popen(
            [str(self.executable), "--slave-mode"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.environment(),
        )
        self._events = queue.Queue()
        self._start_reader("stdout", self._proc.stdout)
        self._start_reader("stderr", self._proc.stderr)
        try:
            self._wait_for_startup()
            self._install_helpers()
        except BaseException:
            self.terminate()
            raise

    def _start_reader(self, source: str, pipe) -> None:
        events = self._events

        def read_loop() -> None:
            try:
                for line in iter(pipe.readline, ""):
                    events.put((source, line))
            finally:
                events.put((source, ""))

        thread = threading.Thread(target=read_loop, name=f"salpy-{source}", daemon=True)
        thread.start()
        self._readers.append(thread)

    def _wait_for_startup(self) -> None:
        deadline = time.monotonic() + self.startup_timeout
        stdout: list[str] = []
        stderr: list[str] = []
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                raise SalProcessError(
                    f"SALenv exited during startup with code {self._proc.returncode}",
                    stdout="".join(stdout),
                    stderr="".join(stderr),
                )
            try:
                source, line = self._events.get(timeout=0.05)
            except queue.Empty:
                continue
            if source == "stderr":
                stderr.append(line)
            else:
                stdout.append(line)
                if "@@@STARTED@@@" in line:
                    return
        self.terminate()
        raise SalTimeoutError("Timed out waiting for SALenv to start")

    def _install_helpers(self) -> None:
        helpers = files("salpy").joinpath("_bridge.scm").read_text(encoding="utf-8")
        self.eval(helpers, timeout=self.startup_timeout)

    def _drain_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def eval(self, code: str, *, timeout: float | None = None) -> EvalResult:
        """Evaluate one Scheme form and return SAL's printed output."""

        effective_timeout = self.timeout if timeout is None else timeout
        self._validate_timeout(effective_timeout)
        with self._lock:
            if not self.is_running:
                raise SalProcessError("SALenv is not running")
            assert self._proc is not None and self._proc.stdin is not None
            self._drain_events()
            try:
                self._proc.stdin.write(code.rstrip() + "\n")
                self._proc.stdin.flush()
                return self._collect(effective_timeout)
            except OSError as exc:
                self.terminate()
                raise SalProcessError(f"Could not communicate with SALenv: {exc}") from exc
            except BaseException:
                # A partially consumed protocol reply must never reach the next call.
                self.terminate()
                raise

    @staticmethod
    def _validate_timeout(value: float) -> None:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Timeout must be a positive, finite number.")

    def _collect(self, timeout: float) -> EvalResult:
        deadline = time.monotonic() + timeout
        stdout: list[str] = []
        stderr: list[str] = []
        error_lines: list[str] = []
        in_error = False
        saw_hard_error = False
        last_output = time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                captured_stdout = "".join(stdout)
                captured_stderr = "".join(stderr)
                self.terminate()
                raise SalTimeoutError(
                    f"SAL command timed out after {timeout:g} seconds",
                    stdout=captured_stdout,
                    stderr=captured_stderr,
                )
            if self._proc and self._proc.poll() is not None:
                raise SalProcessError(
                    f"SALenv exited with code {self._proc.returncode}",
                    stdout="".join(stdout),
                    stderr="".join(stderr),
                )
            try:
                source, line = self._events.get(timeout=min(0.05, remaining))
            except queue.Empty:
                if saw_hard_error and time.monotonic() - last_output > 0.5:
                    captured_stdout = "".join(stdout)
                    captured_stderr = "".join(stderr)
                    self.terminate()
                    message = (captured_stderr or captured_stdout).strip()
                    raise SalProcessError(
                        message, stdout=captured_stdout, stderr=captured_stderr
                    ) from None
                continue
            if line == "":
                continue
            last_output = time.monotonic()
            if source == "stderr":
                stderr.append(line)
                if "*** ERROR:" in line:
                    saw_hard_error = True
                continue

            if "*** ERROR:" in line:
                saw_hard_error = True
            marker = line.rstrip("\r\n")
            if marker == "@@@BEGIN_ERROR_MSG@@@":
                in_error = True
                continue
            if marker == "@@@END_ERROR_MSG@@@":
                message = "".join(error_lines).strip() or "".join(stdout).strip()
                raise SalProcessError(message, stdout="".join(stdout), stderr="".join(stderr))
            if marker == "@@@INTERRUPTED@@@":
                raise SalProcessError(
                    "SAL command was interrupted", stdout="".join(stdout), stderr="".join(stderr)
                )
            if marker == "@@@PP_ERROR@@@":
                raise SalProcessError(
                    "SAL could not print the result", stdout="".join(stdout), stderr="".join(stderr)
                )
            if marker == "@@@END_OF_CMD@@@":
                if saw_hard_error or in_error:
                    raise SalProcessError(
                        "SAL reported an error", stdout="".join(stdout), stderr="".join(stderr)
                    )
                return EvalResult(stdout="".join(stdout), stderr="".join(stderr))

            if in_error:
                error_lines.append(line)
            else:
                stdout.append(line)

    def terminate(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        self._close_proc_streams(proc)
        self._join_readers()
        self._proc = None

    def close(self) -> None:
        for source in self._sources:
            source.cleanup()
        self._sources.clear()
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write("(exit)\n")
                proc.stdin.flush()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.terminate()
                return
        self._close_proc_streams(proc)
        self._join_readers()
        self._proc = None

    def _join_readers(self) -> None:
        for reader in self._readers:
            reader.join(timeout=2)
        self._readers.clear()

    def write_source(
        self,
        source: str,
        name: str,
        directory: str | os.PathLike[str] | None = None,
        *,
        suffix: str = ".sal",
    ) -> Path:
        from .composition import identifier

        identifier(name)
        if suffix not in {".sal", ".lsal"}:
            raise ValueError("Source files must use .sal or .lsal syntax.")
        if directory is None:
            temporary = tempfile.TemporaryDirectory(prefix="salpy-")
            self._sources.append(temporary)
            directory = temporary.name
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"{name}{suffix}"
        target.write_text(source, encoding="utf-8")
        return target

    def unique_name(self, prefix: str = "__salpy") -> str:
        with self._lock:
            self._counter += 1
            return f"{prefix}_{self._counter}"

    @staticmethod
    def _close_proc_streams(proc: subprocess.Popen[str]) -> None:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> SalSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def capture_text(self, string_expr: str, *, timeout: float | None = None) -> str:
        code = f"""
(begin
  (print {scheme_literal(BEGIN_TEXT)})
  (display {string_expr})
  (print "")
  (print {scheme_literal(END_TEXT)})
  #unspecified)
"""
        result = self.eval(code, timeout=timeout)
        return extract_text_block(result.stdout)

    def capture_lines(self, list_expr: str, *, timeout: float | None = None) -> list[str]:
        code = f"""
(begin
  (print {scheme_literal(BEGIN_TEXT)})
  (for-each print {list_expr})
  (print {scheme_literal(END_TEXT)})
  #unspecified)
"""
        text = self.eval(code, timeout=timeout).stdout
        return [line for line in extract_text_block(text).splitlines()]

    def define(self, expr: str, *, timeout: float | None = None) -> tuple[str, str]:
        name = self.unique_name()
        code = f"""
(begin
  (define {name} {expr})
  (print {scheme_literal(BEGIN_TEXT)})
  (print (salpy/class-name {name}))
  (print {scheme_literal(END_TEXT)})
  #unspecified)
"""
        result = self.eval(code, timeout=timeout)
        class_name = extract_text_block(result.stdout).strip()
        return name, class_name

    def set_var(self, name: str, expr: str, *, timeout: float | None = None) -> str:
        code = f"""
(begin
  (set! {name} {expr})
  (print {scheme_literal(BEGIN_TEXT)})
  (print (salpy/class-name {name}))
  (print {scheme_literal(END_TEXT)})
  #unspecified)
"""
        return extract_text_block(self.eval(code, timeout=timeout).stdout).strip()


def extract_text_block(output: str) -> str:
    lines = output.splitlines(keepends=True)
    for start, line in enumerate(lines):
        if line.rstrip("\r\n") != BEGIN_TEXT:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end].rstrip("\r\n") == END_TEXT:
                text = "".join(lines[start + 1 : end])
                return text.removesuffix("\n").removesuffix("\r")
    raise SalProcessError("SAL response did not contain a salpy text block", stdout=output)
