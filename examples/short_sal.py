from __future__ import annotations

import bootstrap  # noqa: F401
from common import sal_example, section, show_lines, show_result, title

from salpy import SAL


def main() -> None:
    title("short.sal")

    with SAL(timeout=60) as sal:
        source = sal_example(sal, "short", "short.sal")
        ctx = sal.load_context(source)
        print(f"loaded context: {ctx.name()}")
        print(f"declarations: {', '.join(ctx.declarations())}")

        main_module = sal.module("short!main")
        print(f"state variables: {', '.join(main_module.state_variables())}")

        fsm = sal.fsm(main_module)
        print(f"reachable states: {fsm.num_reachable_states()}")

        section("Assertions")
        for assertion in ("short!th1", "short!th2", "short!th3"):
            print(assertion)
            show_result(sal.engines.smc(assertion))
            show_result(sal.engines.wmc(assertion))

        section("Simulation")
        sim = sal.simulate(main_module)
        sim.step()
        found = sim.run_until("state = busy")
        print(f"found busy state: {found}")
        show_lines(sim.display_trace().splitlines(), limit=18)


if __name__ == "__main__":
    main()
