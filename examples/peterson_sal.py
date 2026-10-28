from __future__ import annotations

import bootstrap  # noqa: F401
from common import sal_example, section, show_counterexample, show_lines, show_result, title

from salpy import SAL


def main() -> None:
    title("peterson.sal")

    with SAL(timeout=60) as sal:
        source = sal_example(sal, "peterson", "peterson.sal")
        ctx = sal.load_context(source)
        print(f"loaded context: {ctx.name()}")
        print(f"declarations: {', '.join(ctx.declarations())}")

        system = sal.module("peterson!system")
        print(f"system variables: {', '.join(system.state_variables())}")

        fsm = sal.fsm(system)
        print(f"reachable states: {fsm.num_reachable_states()}")

        section("Safety")
        mutex = sal.engines.smc("peterson!mutex")
        print("peterson!mutex")
        show_result(mutex)

        invalid = sal.engines.smc("peterson!invalid")
        print()
        print("peterson!invalid")
        show_result(invalid)
        show_counterexample(invalid)

        section("CTL Witness Checker")
        ctl = sal.engines.wmc("peterson!mutex_ctl")
        print("peterson!mutex_ctl")
        show_result(ctl)
        if ctl.witness:
            print(f"witness object: {ctl.witness.class_name}")

        section("Rebuild the Composition")
        left = ctx.module("process", False)
        right = ctx.module("process", True).rename(pc1="pc2", pc2="pc1", x1="x2", x2="x1")
        rebuilt = left.async_(right)
        show_result(rebuilt.check("G(NOT(pc1 = critical AND pc2 = critical))"))

        section("Simulation")
        sim = sal.simulate(system)
        sim.run_until("pc1 = critical")
        show_lines(sim.display_trace().splitlines(), limit=22)


if __name__ == "__main__":
    main()
