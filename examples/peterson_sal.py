from __future__ import annotations

import bootstrap  # noqa: F401

from salpy import SAL

from common import sal_example, section, show_counterexample, show_lines, show_result, title


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

        section("Simulation")
        sim = sal.simulate(system)
        sim.run_until("pc1 = critical")
        show_lines(sim.display_trace().splitlines(), limit=22)


if __name__ == "__main__":
    main()
