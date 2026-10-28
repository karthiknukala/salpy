from __future__ import annotations

import pytest

from salpy import Declaration, Module, SalObjectError, SalProcessError, module_expr

pytestmark = pytest.mark.integration


def test_parsing_terms_and_types(sal):
    expression = sal.expr("1 + 2")
    assert expression.pp().strip() == "1 + 2"
    assert expression.type().pp().strip() == "nat"
    assert sal.expr("TRUE").and_(False).type().pp().strip() == "bool"
    assert sal.expr("1").equals(1).type().pp().strip() == "bool"
    assert sal.expr("LAMBDA (x: INTEGER): x + 1").apply(2).type().pp().strip() == "int"
    with pytest.raises(TypeError, match="symbolic"):
        bool(expression)


def test_builder_checks_named_assertions(sal):
    context = sal.builder("builder_test")
    context.module("main").output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
    context.theorem("safe", "main", "G(x = TRUE OR x = FALSE)")
    loaded = context.load(sal)
    assert sal.engines.smc(loaded.assertion("safe")).proved
    assertion = loaded.assertion("safe")
    assert assertion.is_invariant()
    assert assertion.module().state_variables() == ["x"]
    assert "G" in assertion.body().pp()
    with pytest.raises(KeyError):
        loaded.module_decl("missing")


def toggler(sal):
    return sal.module("BEGIN OUTPUT x: BOOLEAN INITIALIZATION x = FALSE TRANSITION x' = NOT x END")


def test_live_sync_and_async_have_different_semantics(sal):
    a = toggler(sal)
    b = a.rename(x="y")
    synchronous = a.sync(b)
    asynchronous = a.async_(b)
    assert synchronous.fsm().num_reachable_states() == 2
    assert asynchronous.fsm().num_reachable_states() == 4
    assert synchronous.check("G(x = y)").proved
    failure = asynchronous.check("G(x = y)")
    assert failure.status == "counterexample"
    assert failure.counterexample is not None
    assert failure.counterexample.length() > 0


def test_native_composition_checks_interface_conflicts(sal):
    a = toggler(sal)
    with pytest.raises(SalProcessError, match="output variable"):
        a.sync(a)


def test_native_composition_checks_shared_variable_types(sal):
    a = toggler(sal)
    b = sal.module("BEGIN INPUT x: [0..2] END")
    with pytest.raises(SalProcessError, match="[Tt]ype"):
        a.sync(b)


def test_hiding_and_observers(sal):
    a = toggler(sal)
    monitor = sal.module("BEGIN INPUT x: BOOLEAN OUTPUT same: BOOLEAN DEFINITION same = x END")
    watched = a.observe(monitor)
    assert watched.check("G(same = x)").proved
    hidden = watched.hide("x")
    assert hidden.fsm().num_reachable_states() == 2
    assert "LOCAL x" in hidden.pp()


def test_live_global_output_conversion(sal):
    shared = sal.module(
        "BEGIN GLOBAL g: BOOLEAN INITIALIZATION g = FALSE TRANSITION g' = NOT g END"
    )
    assert shared.output("g").fsm().num_reachable_states() == 2
    assert "GLOBAL" in shared.pp()


@pytest.mark.parametrize("asynchronous,expected", [(True, 8), (False, 2)])
def test_indexed_composition_with_array_renaming(sal, asynchronous, expected):
    context = sal.builder("indexed_test")
    worker = context.module("worker", params="i: [1..3]")
    worker.output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
    system = (
        worker.instantiate("i")
        .rename(x="xs[i]")
        .forall("i", "[1..3]", asynchronous=asynchronous)
        .with_(outputs={"xs": "ARRAY [1..3] OF BOOLEAN"})
    )
    context.module("system", system)
    loaded = context.load(sal)
    assert loaded.module("system").fsm().num_reachable_states() == expected
    assert loaded.module("worker", 1).state_variables() == ["x"]
    declaration = loaded.module_decl("worker")
    assert isinstance(declaration, Declaration)
    assert isinstance(declaration.definition(), Module)


def test_recompose_peterson_from_its_parameterized_processes(sal):
    context = sal.load_context(sal.session.sal_dir / "examples/peterson/peterson.sal")
    p1 = context.module("process", False)
    p2 = context.module("process", True).rename(pc1="pc2", pc2="pc1", x1="x2", x2="x1")
    system = p1.async_(p2)
    assert (
        system.fsm().num_reachable_states() == context.module("system").fsm().num_reachable_states()
    )
    assert system.check("G(NOT(pc1 = critical AND pc2 = critical))").proved


def test_session_lifetimes_and_reset(sal):
    term = sal.expr("TRUE")
    term.release()
    term.release()
    with pytest.raises(SalObjectError, match="released"):
        term.pp()
    stale = sal.expr("TRUE")
    sal.reset()
    with pytest.raises(SalObjectError, match="reset"):
        stale.pp()
    assert sal.expr("TRUE").type().pp().strip() == "bool"


def test_source_files_are_retained_until_close_then_cleaned(sal):
    context = sal.builder("temporary_model")
    context.module("main").output("x", "BOOLEAN").init("x = FALSE")
    context.load(sal)
    temporary = sal.session._sources[0].name
    from pathlib import Path

    assert Path(temporary).exists()
    sal.close()
    assert not Path(temporary).exists()


def test_inf_bmc_proves_unbounded_counter_with_induction(sal):
    context = sal.builder("unbounded_counter")
    context.module("main").output("x", "INTEGER").init("x = 0").transition("x' = x + 1")
    context.theorem("nonnegative", "main", "G(x >= 0)")
    context.load(sal)
    result = sal.engines.inf_bmc("unbounded_counter!nonnegative", depth=2, induction=True)
    assert result.proved
    assert result.counterexample is None


def test_composed_module_can_be_loaded_from_expression(sal):
    context = sal.builder("expression_test")
    context.module("a").output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
    context.load(sal)
    expression = module_expr("expression_test!a").async_(
        module_expr("expression_test!a").rename(x="y")
    )
    assert sal.module(expression).fsm().num_reachable_states() == 4


def test_simulation_and_state_sets(sal):
    context = sal.load_context(sal.session.sal_dir / "examples/short/short.sal")
    module = context.module("main")
    fsm = module.fsm()
    initial = fsm.initial_states()
    reachable = fsm.reachable_states()
    assert reachable.count(fsm) == 4
    assert initial.union(initial.complement()).count(fsm) == 4
    assert initial.intersection(reachable).count(fsm) == initial.count(fsm)
    simulation = sal.simulate(fsm)
    simulation.step()
    simulation.backtrack()
    simulation.filter("state = ready")
    simulation.restart()
    assert simulation.run_until("state = busy")
    assert "busy" in simulation.display_current()
    assert "Step" in simulation.display_trace()
    assert simulation.path().length() >= 1
    assert sal.engines.wmc(context.assertion("th1")).proved


def test_induction_failure_is_inconclusive_not_a_reachable_violation(sal):
    sal.load_context(sal.session.sal_dir / "examples/peterson/peterson.sal")
    result = sal.engines.inf_bmc("peterson!mutex", depth=1, induction=True)
    assert result.status == "induction_failed"
    assert not result.proved
    assert result.counterexample is None
