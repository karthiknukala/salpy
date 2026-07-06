from __future__ import annotations

from pathlib import Path
from typing import Iterable

from salpy import CheckResult, SAL


def sal_example(sal: SAL, *parts: str) -> Path:
    return sal.session.sal_dir / "examples" / Path(*parts)


def title(text: str) -> None:
    print()
    print("=" * len(text))
    print(text)
    print("=" * len(text))


def section(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def show_result(result: CheckResult) -> None:
    marker = "ok" if result.ok else "not ok"
    print(f"{result.engine}: {result.status} ({marker})")


def show_lines(lines: Iterable[str], *, limit: int = 12) -> None:
    for idx, line in enumerate(lines):
        if idx >= limit:
            print("...")
            return
        print(line)


def show_counterexample(result: CheckResult, *, states: int = 3) -> None:
    if not result.counterexample:
        print("no counterexample object")
        return
    print(f"counterexample length: {result.counterexample.length()}")
    for idx, state in enumerate(result.counterexample.states(limit=states)):
        print()
        print(f"state {idx}:")
        show_lines(state.splitlines(), limit=10)

