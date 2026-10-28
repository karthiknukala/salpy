# salpy Examples

These examples exercise SAL's bundled models through the Python bindings:

- `short_sal.py` loads `short.sal`, checks all three assertions with SMC/WMC,
  builds a BDD FSM, and simulates a path to `state = busy`.
- `peterson_sal.py` loads `peterson.sal`, proves mutual exclusion, gets a
  counterexample for the intentionally invalid assertion, runs WMC, and simulates
  a path to a critical section. It also reconstructs the system using live module
  instantiation, simultaneous renaming, and asynchronous composition.
- `bakery_sal.py` loads parameterized `bakery.sal`, instantiates
  `bakery{3,4}`, checks parameterized assertions, and prints a counterexample
  for its invalid theorem.
- `composition_sal.py` constructs a new context from Python, compares synchronous
  and asynchronous semantics, and composes three workers using indexed array wiring.

Run one example:

```sh
uv run python examples/peterson_sal.py
```

Run all examples:

```sh
uv run python examples/run_all.py
```

