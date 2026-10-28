from __future__ import annotations

import pytest

from salpy import SAL, SalNotFoundError, find_sal_dir


@pytest.fixture
def sal_dir():
    try:
        return find_sal_dir()
    except SalNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def sal(sal_dir):
    with SAL(sal_dir, timeout=20) as instance:
        yield instance
