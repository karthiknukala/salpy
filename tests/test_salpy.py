from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from salpy import SalObject, SalObjectError
from salpy.objects import _sal_number_to_int
from salpy.sexpr import keyword, scheme_call, scheme_literal, sym


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "#t"),
        (False, "#f"),
        (None, "#f"),
        (42, "42"),
        (1.5, "1.5"),
        ('a"b\n', '"a\\"b\\n"'),
        ([1, True], "(list 1 #t)"),
        (sym("yices2"), "'yices2"),
        (keyword("ltl?"), ":ltl?"),
    ],
)
def test_scheme_literals(value, expected):
    assert scheme_literal(value) == expected


@pytest.mark.parametrize("value", ["two words", "x)(exit", "", "'quoted"])
def test_symbols_cannot_inject_forms(value):
    with pytest.raises(ValueError):
        sym(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_scheme_numbers_are_rejected(value):
    with pytest.raises(ValueError):
        scheme_literal(value)


def test_unsupported_literals_are_rejected():
    with pytest.raises(TypeError):
        scheme_literal({"x": 1})


def test_function_calls_validate_names():
    assert scheme_call("some/function", True, "text") == '(some/function #t "text")'
    with pytest.raises(ValueError):
        scheme_call("foo) (exit")


def test_state_counts_preserve_large_integer_precision():
    assert _sal_number_to_int("9007199254740993.0") == 9007199254740993
    assert _sal_number_to_int("89.0") == 89
    with pytest.raises(ValueError):
        _sal_number_to_int("1.5")


def test_cross_session_and_stale_object_references_are_rejected():
    session = SimpleNamespace(generation=1, is_running=True, eval=Mock(), capture_text=Mock())
    obj = SalObject(session, "ref")
    assert scheme_literal(obj, session=session) == "ref"
    with pytest.raises(SalObjectError, match="different sessions"):
        scheme_literal([obj], session=SimpleNamespace())
    session.generation += 1
    with pytest.raises(SalObjectError, match="reset"):
        obj.pp()
    session.eval.assert_not_called()
    session.capture_text.assert_not_called()
