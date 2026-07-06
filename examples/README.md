# salpy Examples

These examples exercise SAL's bundled models through the Python bindings:

- `short_sal.py` loads `short.sal`, checks all three assertions with SMC/WMC,
  builds a BDD FSM, and simulates a path to `state = busy`.
- `peterson_sal.py` loads `peterson.sal`, proves mutual exclusion, gets a
  counterexample for the intentionally invalid assertion, runs WMC, and simulates
  a path to a critical section.
- `bakery_sal.py` loads parameterized `bakery.sal`, instantiates
  `bakery{3,4}`, checks parameterized assertions, and prints a counterexample
  for its invalid theorem.

Run one example:

```sh
python examples/peterson_sal.py
```

Run all examples:

```sh
python examples/run_all.py
```

