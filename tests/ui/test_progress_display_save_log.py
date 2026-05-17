from __future__ import annotations

import builtins
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationLogEntry,
)
from discord_message_purger.ui import progress_display as progress_display_module
from discord_message_purger.ui.progress_display import ProgressDisplay


class _FakeQFileDialog:

    return_value: tuple[str, str] = ("", "")
    calls: list[tuple[Any, ...]] = []

    @staticmethod
    def getSaveFileName(
        parent: Any,
        caption: str,
        directory: str,
        filter_: str,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[str, str]:
        _FakeQFileDialog.calls.append((parent, caption, directory, filter_))
        return _FakeQFileDialog.return_value


class _FakeQMessageBox:

    calls: list[dict[str, Any]] = []

    @staticmethod
    def critical(
        parent: Any,
        title: str,
        message: str,
        *args: Any,
        **kwargs: Any,
    ) -> int:
        _FakeQMessageBox.calls.append(
            {"parent": parent, "title": title, "message": message}
        )
        return 0


def _make_log_entry(first_char: str = "A", minute: int = 4) -> OperationLogEntry:

    return OperationLogEntry(
        timestamp_local=datetime(2024, 1, 2, 3, minute, 0),
        status=LogEntryStatus.SUCCESS,
        channel_id="100",
        message_id=f"200{minute}",
        first_visible_char=first_char,
        message_timestamp=datetime(2024, 1, 2, 3, minute, 0),
        http_status=204,
        error_type=None,
        description="успешно удалено",
    )


@pytest.fixture()
def widget(qtbot):

    w = ProgressDisplay()
    qtbot.addWidget(w)

    w.update_total(2)
    w.append_log_entry(_make_log_entry("A", minute=4))
    w.append_log_entry(_make_log_entry("Б", minute=5))
    return w


@pytest.fixture(autouse=True)
def _reset_fakes():

    _FakeQFileDialog.return_value = ("", "")
    _FakeQFileDialog.calls = []
    _FakeQMessageBox.calls = []
    yield
    _FakeQFileDialog.return_value = ("", "")
    _FakeQFileDialog.calls = []
    _FakeQMessageBox.calls = []


def _patch_qt_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(progress_display_module, "QFileDialog", _FakeQFileDialog)
    monkeypatch.setattr(progress_display_module, "QMessageBox", _FakeQMessageBox)


def test_save_log_cancellation_does_not_write_file_or_show_error(
    widget: ProgressDisplay,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:

    _FakeQFileDialog.return_value = ("", "")
    _patch_qt_dialogs(monkeypatch)

    open_calls: list[Any] = []
    real_open = builtins.open

    def tracking_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        mode = ""
        if args:
            mode = str(args[0])
        else:
            mode = str(kwargs.get("mode", ""))
        if "w" in mode or "a" in mode or "x" in mode:
            open_calls.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    entries_before = list(widget._entries)
    snapshots_before = list(widget._processed_snapshots)
    processed_before = widget.processed
    total_before = widget.total
    log_text_before = widget._log_view.toPlainText()

    widget.save_log_to_file()

    assert len(_FakeQFileDialog.calls) == 1
    _, caption, _directory, file_filter = _FakeQFileDialog.calls[0]
    assert caption == "Сохранить журнал операции"
    assert "*.txt" in file_filter

    assert open_calls == []
    assert list(tmp_path.iterdir()) == []

    assert _FakeQMessageBox.calls == []

    assert widget._entries == entries_before
    assert widget._processed_snapshots == snapshots_before
    assert widget.processed == processed_before
    assert widget.total == total_before
    assert widget._log_view.toPlainText() == log_text_before


def test_save_log_successful_save_writes_journal_text(
    widget: ProgressDisplay,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:

    target = tmp_path / "operation_log.txt"

    _FakeQFileDialog.return_value = (str(target), "Текстовые файлы (*.txt)")
    _patch_qt_dialogs(monkeypatch)

    expected_text = widget._journal_text()
    assert expected_text != ""

    widget.save_log_to_file()

    assert target.exists()
    actual_text = target.read_text(encoding="utf-8")
    assert actual_text == expected_text

    assert _FakeQMessageBox.calls == []
    assert len(_FakeQFileDialog.calls) == 1


def test_save_log_oserror_shows_critical_with_path_and_reason(
    widget: ProgressDisplay,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:

    target = tmp_path / "subdir_with_no_access" / "operation_log.txt"

    _FakeQFileDialog.return_value = (str(target), "Текстовые файлы (*.txt)")
    _patch_qt_dialogs(monkeypatch)

    expected_reason = "Отказано в доступе для теста"
    real_open = builtins.open

    def raising_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path) == str(target):
            raise PermissionError(13, expected_reason)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", raising_open)

    entries_before = list(widget._entries)
    snapshots_before = list(widget._processed_snapshots)
    log_text_before = widget._log_view.toPlainText()

    widget.save_log_to_file()

    assert not target.exists()

    assert len(_FakeQMessageBox.calls) == 1
    call = _FakeQMessageBox.calls[0]
    assert call["title"] == "Не удалось сохранить журнал"
    assert str(target) in call["message"]
    assert expected_reason in call["message"]
    assert call["parent"] is widget

    assert widget._entries == entries_before
    assert widget._processed_snapshots == snapshots_before
    assert widget._log_view.toPlainText() == log_text_before
