"""Build and compare composed systems, including an indexed worker array."""

from __future__ import annotations

import bootstrap  # noqa: F401
from common import section, show_result, title

from salpy import SAL


def main() -> None:
    title("Module Composition")
    with SAL() as sal:
        context = sal.builder("composition_example")
        worker = context.module("worker", params="i: [1..3]")
        worker.output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
        left = worker.instantiate(1)
        right = worker.instantiate(2).rename(x="y")
        context.module("lockstep", left.sync(right))
        context.module("interleaved", left.async_(right))
        context.module(
            "workers",
            worker.instantiate("i")
            .rename(x="xs[i]")
            .forall("i", "[1..3]")
            .with_(outputs={"xs": "ARRAY [1..3] OF BOOLEAN"}),
        )
        loaded = context.load(sal)
        section("Lockstep Versus Interleaving")
        for name in ("lockstep", "interleaved"):
            module = loaded.module(name)
            print(f"{name}: {module.fsm().num_reachable_states()} reachable states")
            show_result(module.check("G(x = y)"))
        section("Indexed Composition")
        print(
            f"three workers: {loaded.module('workers').fsm().num_reachable_states()} reachable states"
        )


if __name__ == "__main__":
    main()
