from __future__ import annotations

import queue
from unittest.mock import Mock

import pytest

from salpy import SalProcessError, SalSession, SalTimeoutError
from salpy.session import BEGIN_TEXT, END_TEXT, extract_text_block


def test_text_block_preserves_contents():
    assert extract_text_block(f"noise\n{BEGIN_TEXT}\nhello\nworld\n{END_TEXT}\n") == "hello\nworld"


@pytest.mark.parametrize("output", ["", BEGIN_TEXT, END_TEXT, f"{END_TEXT}\n{BEGIN_TEXT}"])
def test_missing_response_frames_are_errors(output):
    with pytest.raises(SalProcessError):
        extract_text_block(output)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_nonpositive_and_nonfinite_timeouts_are_rejected(value):
    with pytest.raises(ValueError, match="positive"):
        SalSession._validate_timeout(value)


def test_collector_ignores_stderr_as_a_protocol_channel():
    session = object.__new__(SalSession)
    session._proc = Mock()
    session._proc.poll.return_value = None
    session._events = queue.Queue()
    session._events.put(("stderr", "diagnostic\n"))
    session._events.put(("stdout", "reply\n"))
    session._events.put(("stdout", "@@@END_OF_CMD@@@\n"))
    result = session._collect(1)
    assert result.stdout == "reply\n"
    assert result.stderr == "diagnostic\n"


def test_collecting_timeout_terminates_the_process():
    session = object.__new__(SalSession)
    session._proc = Mock()
    session._proc.poll.return_value = None
    session._events = queue.Queue()
    session.terminate = Mock()
    with pytest.raises(SalTimeoutError):
        session._collect(0.01)
    session.terminate.assert_called_once()


def test_hard_error_cannot_be_mistaken_for_success():
    session = object.__new__(SalSession)
    session._proc = Mock()
    session._proc.poll.return_value = None
    session._events = queue.Queue()
    session._events.put(("stderr", "*** ERROR: bad input\n"))
    session._events.put(("stdout", "@@@END_OF_CMD@@@\n"))
    with pytest.raises(SalProcessError) as error:
        session._collect(1)
    assert "bad input" in error.value.stderr
