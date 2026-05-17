from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Union

import pytest

try:
    from freezegun import freeze_time as _freeze_time
except ImportError:
    _freeze_time = None  # type: ignore[assignment]


FreezeTarget = Union[str, datetime]


@pytest.fixture(scope="session")
def qapp_cls():

    from PySide6.QtWidgets import QApplication

    return QApplication


@pytest.fixture()
def qt_app(qapp):

    return qapp


@pytest.fixture()
def freeze_time() -> Callable[[FreezeTarget], "AbstractContextManager[None]"]:

    if _freeze_time is None:
        pytest.skip("freezegun не установлен — фикстура freeze_time недоступна")

    @contextmanager
    def _factory(target: FreezeTarget) -> Iterator[None]:
        with _freeze_time(target):
            yield

    return _factory
