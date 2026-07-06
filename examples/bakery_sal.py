from __future__ import annotations

import bootstrap  # noqa: F401

from salpy import SAL

from common import sal_example, section, show_counterexample, show_result, title


INSTANCE = "bakery{3,4}"


def main() -> None:
    title("bakery.sal")

    with SAL(timeout=120) as sal:
        source = sal_example(sal, "bakery", "bakery.sal")
        ctx = sal.load_context(source)
        print(f"loaded parameterized context: {ctx.name()}")
        print(f"instance: {INSTANCE}")

        system = sal.module(f"{INSTANCE}!system")
        print(f"system variables: {', '.join(system.state_variables())}")

        fsm = sal.fsm(system)
        print(f"reachable states: {fsm.num_reachable_states()}")

        section("Parameterized Assertions")
        for assertion in (f"{INSTANCE}!mutex", f"{INSTANCE}!aux"):
            print(assertion)
            show_result(sal.engines.smc(assertion, timeout=90))

        section("Counterexample")
        invalid = sal.engines.smc(f"{INSTANCE}!invalid", timeout=90)
        print(f"{INSTANCE}!invalid")
        show_result(invalid)
        show_counterexample(invalid, states=2)


if __name__ == "__main__":
    main()
