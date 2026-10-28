from __future__ import annotations

import pytest

from salpy import ContextBuilder, ModuleExpression, async_, module_expr, sync


def test_composition_is_immutable_and_left_associative():
    a = module_expr("a")
    assert str(sync(a, "b", "c")) == "((a || b) || c)"
    assert str(async_(a, "b", "c")) == "((a [] b) [] c)"
    assert str(a) == "a"


def test_parameterized_indexed_array_composition():
    expression = (
        module_expr("worker")
        .instantiate("i", False)
        .rename(x="xs[i]")
        .forall("i", "[1..3]")
        .with_(outputs={"xs": "ARRAY [1..3] OF BOOLEAN"})
    )
    assert str(expression) == (
        "(WITH OUTPUT xs: ARRAY [1..3] OF BOOLEAN "
        "([] (i: [1..3]): (RENAME x TO xs[i] IN worker[i, FALSE])))"
    )


def test_organization_and_observer_syntax():
    assert str(module_expr("a").hide("x").observe("monitor")) == (
        "(OBSERVE (LOCAL x IN a) WITH monitor)"
    )
    assert str(module_expr("a").output("g")) == "(OUTPUT g IN a)"
    assert str(module_expr("a").forall("i", "[0..1]", asynchronous=False)) == (
        "(|| (i: [0..1]): a)"
    )


@pytest.mark.parametrize("compose", [sync, async_])
def test_empty_composition_is_rejected(compose):
    with pytest.raises(ValueError, match="at least one"):
        compose()


@pytest.mark.parametrize("name", ["bad name", "x; END", "../bad", "", "1worker"])
def test_invalid_identifiers_are_rejected(name):
    with pytest.raises(ValueError, match="identifier"):
        ContextBuilder(name)


def test_empty_expression_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        ModuleExpression("  ")


def test_builder_preserves_module_declaration_order():
    context = ContextBuilder("ordering")
    context.module("a")
    context.module("b", "a")
    context.module("c")
    context.module("d", "b [] c")
    text = context.source()
    assert text.index("a: MODULE") < text.index("b: MODULE") < text.index("c: MODULE")
    assert text.index("c: MODULE") < text.index("d: MODULE")
    with pytest.raises(ValueError, match="already defined"):
        context.module("b")


def test_multiple_definitions_are_separated_and_commands_cannot_be_lost():
    context = ContextBuilder("definitions")
    module = context.module("main").init("x = FALSE", "y = FALSE")
    assert "x = FALSE;\n" in module.source()
    module.transition("x' = NOT x").guarded("TRUE", "x' = FALSE")
    with pytest.raises(ValueError, match="either guarded"):
        module.source()
