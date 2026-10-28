from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from salpy import CheckResult, Engines, SalTimeoutError
from salpy.session import BEGIN_TEXT, END_TEXT, EvalResult


@pytest.fixture
def engines():
    session = Mock()
    session.sal_dir = Path("/sal")
    session.environment.return_value = {"SALENV_DIR": "/sal", "MY_SETTING": "value"}
    session.define.side_effect = [("assertion_ref", ""), ("path_ref", "")]
    session.capture_text.return_value = "true"
    session.eval.return_value = EvalResult(f"{BEGIN_TEXT}\nproved\n<primitive>\n{END_TEXT}", "")
    return Engines(SimpleNamespace(session=session, load_context=Mock()))


@pytest.mark.parametrize("engine,prefix", [("bmc", "sal-bmc"), ("inf_bmc", "sal-inf-bmc")])
def test_bounded_engines_call_the_correct_induction_api(engines, engine, prefix):
    result = getattr(engines, engine)(
        "model!safe", depth=5, induction=True, lemmas=["model!aux"], iterative=True
    )
    code = engines.session.eval.call_args.args[0]
    assert f"({prefix}/invariant assertion 0 5 #f #f 'yices)" in code
    assert f"({prefix}/k-induction assertion 5 #f lemma-exprs 'yices)" in code
    assert f"({prefix}/create-assertion-lemmas" in code
    assert result.proved
    assert result.details["induction"] is True


@pytest.mark.parametrize("engine", ["bmc", "inf_bmc"])
@pytest.mark.parametrize(
    "options",
    [
        {"depth": -1},
        {"depth": 1.5},
        {"depth": True},
        {"from_depth": 3, "to_depth": 2},
        {"induction": True, "from_depth": 1},
        {"induction": True, "depth": 0},
        {"lemmas": ["model!aux"]},
        {"induction": True, "lemmas": "model!aux"},
    ],
)
def test_invalid_search_options_do_not_reach_sal(engines, engine, options):
    with pytest.raises((ValueError, TypeError)):
        getattr(engines, engine)("model!safe", **options)
    engines.session.define.assert_not_called()


def test_liveness_induction_is_rejected(engines):
    engines.session.capture_text.return_value = "false"
    with pytest.raises(ValueError, match="safety"):
        engines.inf_bmc("model!live", induction=True)
    engines.session.eval.assert_not_called()


def test_induction_step_trace_is_not_a_reachable_counterexample(engines):
    engines.session.eval.return_value = EvalResult(
        f"{BEGIN_TEXT}\ninduction_failed\n<sal-path>\n{END_TEXT}", "diagnostic"
    )
    result = engines.inf_bmc("model!safe", induction=True)
    assert result.induction_counterexample is not None
    assert result.counterexample is None
    assert result.has_trace
    assert not result.proved
    assert result.stderr == "diagnostic"


def test_timeout_remains_distinguishable_from_solver_error(engines):
    engines.session.eval.side_effect = SalTimeoutError("timed out")
    with pytest.raises(SalTimeoutError):
        engines.inf_bmc("model!safe")


def test_no_counterexample_is_not_a_proof():
    result = CheckResult("inf_bmc", "no_counterexample")
    assert result.bounded_safe
    assert not result.proved


def test_cli_tools_share_session_configuration(engines, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "proved.", ""))
    monkeypatch.setattr(subprocess, "run", run)
    result = engines.command("sal-smc", "model.sal", "safe")
    assert result.ok
    assert run.call_args.args[0] == ["/sal/bin/sal-smc", "model.sal", "safe"]
    assert run.call_args.kwargs["env"]["MY_SETTING"] == "value"


def test_cli_timeouts_preserve_diagnostics(engines, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(
            side_effect=subprocess.TimeoutExpired(
                "sal-smc", 1, output=b"working", stderr=b"diagnostic"
            )
        ),
    )
    with pytest.raises(SalTimeoutError) as error:
        engines.command("sal-smc", timeout=1)
    assert error.value.stdout == "working"
    assert error.value.stderr == "diagnostic"
