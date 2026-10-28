# salpy

Ergonomic Python bindings for the SAL model checker in `../sal-3.3`.

`salpy` talks to SAL through a persistent `salenv --slave-mode` process. That
means Python can keep live references to SAL ASTs, contexts, modules, BDD FSMs,
paths, witnesses, and counterexamples instead of only scraping command output.

## Installation

Python 3.10+ and a working native SAL installation are required. The Python
package has no runtime dependencies and does not rebuild or modify SAL.

```sh
uv sync --locked
uv run python examples/run_all.py
```

`SAL()` discovers the sibling `../sal-3.3` installation. Elsewhere, pass
`SAL(sal_dir="/path/to/sal-3.3")` or set `SALENV_DIR`. Context search paths,
per-command timeouts, startup timeouts, and environment overrides are configurable:

```python
with SAL(context_path=["./models"], timeout=60, env={"MY_SETTING": "value"}) as sal:
    sal.configure(cse=True, simplifier=True, slicer=False)
```

For other projects, install the package with `uv add /path/to/salpy` or
`pip install /path/to/salpy`.

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
    print(expr.pp())  # 1 + 2
    print(expr.type().pp())  # nat

    result = sal.engines.smc("peterson!mutex")
    assert result.ok

    bad = sal.engines.smc("peterson!invalid")
    print(bad.status)  # counterexample
    print(bad.counterexample.length())  # e.g. 4
    print(bad.counterexample.state_expr(0).pp())
```

## Build a Model from Python

```python
from salpy import SAL

with SAL() as sal:
    ctx = sal.builder("toggle")
    ctx.module("main").output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
    ctx.theorem("safe", "main", "G(x = TRUE OR x = FALSE)")

    ctx.load(sal)
    print(sal.engines.smc("toggle!safe").status)
```

## Module Composition

Both live SAL modules and Python source builders support synchronous (`sync`)
and asynchronous/interleaving (`async_`) composition. Composition is left
associative, and SAL checks interface compatibility and shared-variable types.

Compose already-loaded modules, instantiate parameterized processes, rename
ports simultaneously, and check an anonymous system without declaring a theorem:

```python
with SAL() as sal:
    ctx = sal.load_context("../sal-3.3/examples/peterson/peterson.sal")
    left = ctx.module("process", False)
    right = ctx.module("process", True).rename(pc1="pc2", pc2="pc1", x1="x2", x2="x1")
    system = left.async_(right)
    result = system.check("G(NOT(pc1 = critical AND pc2 = critical))")
    assert result.proved
    print(system.fsm().num_reachable_states())  # 28
```

Use immutable `ModuleExpression` values to construct a context before loading it:

```python
from salpy import ContextBuilder, module_expr, sync, async_

ctx = ContextBuilder("composed")
worker = ctx.module("worker", params="i: [1..3]")
worker.output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
ctx.module("pair", worker.instantiate(1).async_(worker.instantiate(2).rename(x="y")))

# SAL's indexed composition and shared array wiring.
workers = (
    worker.instantiate("i")
    .rename(x="xs[i]")
    .forall("i", "[1..3]", asynchronous=True)
    .with_(outputs={"xs": "ARRAY [1..3] OF BOOLEAN"})
)
ctx.module("system", workers)
ctx.theorem("safe", "system", "G(xs[1] = TRUE OR xs[1] = FALSE)")

with SAL() as sal:
    loaded = ctx.load(sal)
    assert sal.engines.smc(loaded.assertion("safe")).proved
```

`sync(a, b, c)` and `async_(a, b, c)` compose source expressions or builders.
`module_expr("context!worker[1]")` refers to an existing module in source.
Both source expressions and live modules offer `hide(*ports)`, `output(*globals)`,
and `observe(observer)`. Observers must be definition-only SAL modules.

Array/record renaming targets, indexed composition, and `with_` declarations
belong to the source-expression API, where SAL can bind the index and shared
variables. Live `Module.rename` accepts identifier-to-identifier mappings.
`sal.module(expression)` also parses a standalone source expression.

`ctx.module(...)` and `ctx.assertion(...)` now return usable modules/assertions,
not their declarations. Use `ctx.module_decl(...)`, `ctx.assertion_decl(...)`,
`ctx.type_decl(...)`, or `ctx.constant(...)` to inspect declarations explicitly;
`declaration.definition()` retrieves their definitions.

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
uv run python examples/run_all.py
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

K-induction requires an invariant, `from_depth=0`, and a positive depth; invalid
combinations raise `ValueError`. Lemmas require `induction=True` and a named
assertion. They are strengthening assumptions, so establish the helper lemmas
independently before relying on a proof that uses them. The same controls are
available for finite-state `bmc`.

Inspect semantic results, not just process exit codes:

- `result.proved`: a proof (`proved` or `valid`).
- `result.bounded_safe`: no counterexample within the requested bounds, not a proof.
- `result.counterexample`: a reachable violation trace, when the engine provides one.
- `result.induction_counterexample`: a failed inductive-step trace, not necessarily reachable.
- `result.witness`: a CTL witness returned by WMC.
- `result.output`, `result.stderr`, `result.details`: diagnostics and search settings.

For compatibility, `result.ok` and `bool(result)` also accept bounded success.
Use `result.proved` when a proof is required. `ToolResult.ok` only reports a
CLI process's exit status, not whether a property was proved.

The explicit-state checker in this SAL build handles invariant-style properties
through `sal-esmc/verify`; SAL reports some liveness explicit-state paths as
not implemented.

## Object Lifetimes

Live terms, modules, BDDs, and paths belong to one SAL session. Do not mix them
across sessions. `release()`, `SAL.reset()`, session restarts, and closing SAL
invalidate the corresponding handles; misuse raises `SalObjectError` in Python.
Source expressions/builders are independent of sessions and can be reused.
Temporary model files remain available for the session and are cleaned on close.

Term operators accept other terms, expression strings, and Python scalar values.
Use `&`, `|`, `~`, and `.equals(...)` for symbolic expressions; implicit Python
truth testing of a `Term` raises `TypeError`.

SAL process errors preserve captured output. A protocol failure or timeout
terminates the session to prevent subsequent commands from consuming a partial
response; create a fresh `SAL()` after such an error. Backend failures raise
`SalEngineError`, and timeouts remain distinguishable as `SalTimeoutError`.
Raw Scheme `eval`, `define`, `slot`, and `call` remain available for trusted scripts.

## Development

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=salpy
uv build
```

The lockfile fixes development dependencies; Hatchling builds the wheel and
source distribution. CI runs linting, formatting, type checks, SAL-independent
unit tests, and builds on Python 3.10, 3.12, and 3.14. Integration tests are marked
`integration`, use the native SAL installation, and skip when SAL is unavailable:

```sh
uv run pytest -m "not integration"
uv run pytest -m integration
```

Solver integration tests additionally require SAL's configured Yices backend.
