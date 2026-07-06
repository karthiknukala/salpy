# salpy

Ergonomic Python bindings for the SAL model checker in `../sal-3.3`.

`salpy` talks to SAL through a persistent `salenv --slave-mode` process. That
means Python can keep live references to SAL ASTs, contexts, modules, BDD FSMs,
paths, witnesses, and counterexamples instead of only scraping command output.

## What SAL Exposes

The binding is built around SAL's exported Scheme API, especially:

- Parsing/typechecking: `sal/expr`, `sal/type`, `sal/module`, `sal/state-expr`,
  `sal/assertion-name`, `sal-env/import-context-from-file!`.
- AST transforms: `sal/simplify`, `sal/cse`, `make-flat-module`,
  `make-boolean-flat-module`, `make-flat-assertion`,
  `make-boolean-assertion`.
- Term construction: `make-sal-and`, `make-sal-or`, `make-sal-not`,
  `make-sal-equality`, `make-sal-application`.
- Symbolic model checking: `sal-flat-module->sal-bdd-fsm`,
  `sal-module-models/smc-invariant-core`, `sal-module-models/smc-accepting`.
- Bounded model checking: `sal-bmc/invariant`, `sal-bmc/liveness`,
  `sal-bmc/k-induction`, and the infinite-state variants in `sal-inf-bmc`.
- CTL witness/counterexample checking: `sal-wmc/ctl-check`.
- Explicit-state checking: `sal-esmc/verify`.
- Paths/simulation: `sal-path/length`, `sal-path/state-expr`,
  `sal-path/evaluate-expr-at`, BDD image/reachability helpers.

## Quick Start

```python
from salpy import SAL

with SAL() as sal:
    sal.load_context("../sal-3.3/examples/peterson/peterson.sal")

    expr = sal.expr("1 + 2")
    print(expr.pp())          # 1 + 2
    print(expr.type().pp())   # nat

    result = sal.engines.smc("peterson!mutex")
    assert result.ok

    bad = sal.engines.smc("peterson!invalid")
    print(bad.status)                         # counterexample
    print(bad.counterexample.length())        # e.g. 4
    print(bad.counterexample.state_expr(0).pp())
```

## Build a Model from Python

```python
from salpy import SAL

with SAL() as sal:
    ctx = sal.builder("toggle")
    ctx.module("main") \
        .output("x", "BOOLEAN") \
        .init("x = FALSE") \
        .transition("x' = NOT x")
    ctx.theorem("safe", "main", "G(x = TRUE OR x = FALSE)")

    ctx.load(sal)
    print(sal.engines.smc("toggle!safe").status)
```

## Simulation

```python
with SAL() as sal:
    sal.load_context("../sal-3.3/examples/peterson/peterson.sal")
    sim = sal.simulate("peterson!system")

    sim.step()
    sim.run_until("pc1 = critical")
    print(sim.display_trace())
```

## Examples

The [examples](examples) directory has runnable scripts for SAL's bundled
`short.sal`, `peterson.sal`, and `bakery.sal` models:

```sh
python examples/run_all.py
```

## Backend Notes

`salpy` exposes both direct API calls and command-line tool invocation:

```python
sal.engines.command("sal-smc", "../sal-3.3/examples/peterson/peterson.sal", "mutex")
```

SMC and WMC run in-process through SAL's API. BMC and infinite-state BMC still
need the external solver binaries configured in SAL, such as `yices2-sat`,
`yices`, `kissat`, or `minisat`; missing solvers are raised as
`SalEngineError` with SAL's diagnostic output attached.

Infinite-state BMC includes SAL's k-induction entry point:

```python
result = sal.engines.inf_bmc(
    "my_context!my_invariant",
    depth=20,
    solver="yices",
    induction=True,
    lemmas=["my_context!helper_lemma"],
)
```

The explicit-state checker in this SAL build handles invariant-style properties
through `sal-esmc/verify`; SAL reports some liveness explicit-state paths as
not implemented.
