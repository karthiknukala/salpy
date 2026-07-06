"""Persistent SALenv process management."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .exceptions import SalNotFoundError, SalProcessError, SalTimeoutError
from .sexpr import scheme_literal


BEGIN_TEXT = "@@@SALPY_BEGIN_TEXT@@@"
END_TEXT = "@@@SALPY_END_TEXT@@@"


@dataclass
class EvalResult:
    stdout: str
    stderr: str


def find_sal_dir(start: Optional[Path] = None) -> Path:
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
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.sal_dir = Path(sal_dir).resolve() if sal_dir else find_sal_dir()
        self.executable = Path(executable).resolve() if executable else self.sal_dir / "bin" / "salenv"
        if not self.executable.exists():
            raise SalNotFoundError(f"SAL executable not found: {self.executable}")
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.context_path = [str(Path(p)) for p in context_path or []]
        self._env_overrides = dict(env or {})
        self._proc: subprocess.Popen[str] | None = None
        self._events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._counter = 0
        self._lock = threading.RLock()
        self.start()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.is_running:
            return
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

        self._proc = subprocess.Popen(
            [str(self.executable), "--slave-mode"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._events = queue.Queue()
        self._start_reader("stdout", self._proc.stdout)
        self._start_reader("stderr", self._proc.stderr)
        self._wait_for_startup()
        self._install_helpers()

    def _start_reader(self, source: str, pipe) -> None:
        def read_loop() -> None:
            try:
                for line in iter(pipe.readline, ""):
                    self._events.put((source, line))
            finally:
                self._events.put((source, ""))

        thread = threading.Thread(target=read_loop, name=f"salpy-{source}", daemon=True)
        thread.start()

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
        helpers = r"""
(begin
  (define (salpy/pp-string obj)
    (with-output-to-string (lambda () (sal/pp obj))))
  (define (salpy/pp-detailed-string obj)
    (with-output-to-string (lambda () (sal/pp-detailed obj))))
  (define (salpy/value-pp-string obj)
    (with-output-to-string (lambda () (sal-value/pp obj))))
  (define (salpy/class-name obj)
    (symbol->string (class-name-of (class-of obj))))
  (define (salpy/string obj)
    (cond
      ((string? obj) obj)
      ((symbol? obj) (symbol->string obj))
      (else (with-output-to-string (lambda () (display obj))))))
  (define (salpy/load-context-file! path)
    (sal-env/import-context-from-file! *sal-env* path)
    (sal/context (file-name->sal-context-name path)))
  (define (salpy/import-context! name)
    (sal-env/import-context! *sal-env* name)
    (sal/context name))
  (define (salpy/declaration-names decls)
    (map (lambda (decl) (symbol->string (sal-decl/name decl))) decls))
  (define (salpy/context-declaration-names ctx)
    (salpy/declaration-names (sal-context/declarations ctx)))
  (define (salpy/module-state-variable-names module)
    (salpy/declaration-names (sal-module/state-variables module)))
  (define (salpy/path-length-string path)
    (salpy/string (sal-path/length path)))
  #unspecified)
"""
        self.eval(helpers, timeout=self.startup_timeout)

    def _drain_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def eval(self, code: str, *, timeout: float | None = None) -> EvalResult:
        """Evaluate one Scheme form and return SAL's printed output."""

        with self._lock:
            if not self.is_running:
                raise SalProcessError("SALenv is not running")
            assert self._proc is not None and self._proc.stdin is not None
            self._drain_events()
            self._proc.stdin.write(code.rstrip() + "\n")
            self._proc.stdin.flush()
            return self._collect(timeout or self.timeout)

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
                    raise SalProcessError(message, stdout=captured_stdout, stderr=captured_stderr)
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
            if "@@@BEGIN_ERROR_MSG@@@" in line:
                in_error = True
                continue
            if "@@@END_ERROR_MSG@@@" in line:
                message = "".join(error_lines).strip() or "".join(stdout).strip()
                raise SalProcessError(message, stdout="".join(stdout), stderr="".join(stderr))
            if "@@@INTERRUPTED@@@" in line:
                raise SalProcessError("SAL command was interrupted", stdout="".join(stdout), stderr="".join(stderr))
            if "@@@END_OF_CMD@@@" in line:
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
        self._proc = None

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write("(exit)\n")
                proc.stdin.flush()
                proc.wait(timeout=3)
            except Exception:
                self.terminate()
                return
        self._close_proc_streams(proc)
        self._proc = None

    @staticmethod
    def _close_proc_streams(proc: subprocess.Popen[str]) -> None:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> "SalSession":
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
        self._counter += 1
        name = f"__salpy_{self._counter}"
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
    start = output.find(BEGIN_TEXT)
    end = output.find(END_TEXT)
    if start < 0 or end < 0 or end < start:
        raise SalProcessError("SAL response did not contain a salpy text block", stdout=output)
    text = output[start + len(BEGIN_TEXT) : end]
    if text.startswith("\n"):
        text = text[1:]
    if text.endswith("\n"):
        text = text[:-1]
    return text
