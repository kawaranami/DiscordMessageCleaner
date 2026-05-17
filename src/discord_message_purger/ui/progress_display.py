from __future__ import annotations

from typing import Final

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discord_message_purger.domain.formatting import format_log_line
from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationLogEntry,
)


_PROCESSED_STATUSES: Final[frozenset[LogEntryStatus]] = frozenset(
    {
        LogEntryStatus.SUCCESS,
        LogEntryStatus.NOT_FOUND,
        LogEntryStatus.ERROR,
        LogEntryStatus.REJECTED,
    }
)

_BUTTON_SAVE_LOG: Final[str] = "Save log to file"

_FILE_DIALOG_TITLE: Final[str] = "Save operation log"
_FILE_DIALOG_FILTER: Final[str] = (
    "Text files (*.txt);;All files (*)"
)
_FILE_DIALOG_DEFAULT_NAME: Final[str] = "operation_log.txt"

_SAVE_ERROR_TITLE: Final[str] = "Failed to save log"
_SAVE_ERROR_TEMPLATE: Final[str] = (
    "Failed to write log to '{path}'.\nReason: {reason}"
)

_RATE_LIMIT_LABEL_TEMPLATE: Final[str] = (
    "Waiting for Discord API ({reason}): {seconds}s remaining"
)

_SUMMARY_TEMPLATE: Final[str] = (
    "Summary: success {success}, not found {not_found}, errors {errors}"
)

_NON_MESSAGE_LINE_TEMPLATE: Final[str] = (
    "-- {description} -- [{processed}/{total}]"
)


class ProgressDisplay(QWidget):

    log_entry_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._entries: list[OperationLogEntry] = []
        self._processed_snapshots: list[int] = []
        self._processed: int = 0
        self._total: int = 0

        self._summary_text: str | None = None

        self._rl_active: bool = False
        self._rl_reason: str = ""
        self._rl_remaining_s: float = 0.0

        self._rl_timer = QTimer(self)
        self._rl_timer.setInterval(1000)
        self._rl_timer.timeout.connect(self._on_rate_limit_tick)

        self._build_ui()

        self.log_entry_signal.connect(
            self._on_log_entry_signal, Qt.ConnectionType.AutoConnection
        )


    def _build_ui(self) -> None:

        self._stats_header = QLabel("", self)
        self._stats_header.setObjectName("statsHeader")

        self._eta_label = QLabel("", self)
        self._eta_label.setObjectName("etaLabel")

        stats_row = QHBoxLayout()
        stats_row.addWidget(self._stats_header, stretch=1)
        stats_row.addWidget(self._eta_label)

        self._log_view = QPlainTextEdit(self)
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_view.setUndoRedoEnabled(False)

        self._rate_limit_label = QLabel("", self)
        self._rate_limit_label.setObjectName("rate_limit_label")
        self._rate_limit_label.setVisible(False)
        self._rate_limit_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._save_button = QPushButton(_BUTTON_SAVE_LOG, self)
        self._save_button.setAutoDefault(False)
        self._save_button.setDefault(False)
        self._save_button.clicked.connect(self.save_log_to_file)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self._rate_limit_label, stretch=1)
        bottom_row.addWidget(self._save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(stats_row)
        layout.addWidget(self._log_view, stretch=1)
        layout.addLayout(bottom_row)

        self.setLayout(layout)


    def append_log_entry(self, entry: OperationLogEntry) -> None:

        if entry.status in _PROCESSED_STATUSES:
            self._processed += 1

        self._entries.append(entry)
        self._processed_snapshots.append(self._processed)

        rendered = self._render_entry(entry, self._processed)
        self._append_line(rendered)

        self._update_stats_header()

    @Slot(object)
    def _on_log_entry_signal(self, entry: object) -> None:

        if isinstance(entry, OperationLogEntry):
            self.append_log_entry(entry)

    def update_total(self, new_total: int) -> None:

        if self._processed > new_total:
            raise AssertionError(
                "Invariant violation processed <= total: "
                f"attempted to set total={new_total} while "
                f"processed={self._processed}"
            )
        self._total = new_total
        self._rerender_all()

        self._update_stats_header()

    def show_rate_limit_wait(
        self, seconds_remaining: float, reason: str
    ) -> None:

        self._rl_active = True
        self._rl_reason = reason
        self._rl_remaining_s = max(0.0, float(seconds_remaining))

        self._refresh_rate_limit_label()
        self._rate_limit_label.setVisible(True)

        self._rl_timer.start()

    def hide_rate_limit_wait(self) -> None:

        self._rl_active = False
        self._rl_reason = ""
        self._rl_remaining_s = 0.0
        self._rl_timer.stop()
        self._rate_limit_label.clear()
        self._rate_limit_label.setVisible(False)

    def show_summary(
        self, success: int, not_found: int, errors: int
    ) -> None:

        self._summary_text = _SUMMARY_TEMPLATE.format(
            success=success,
            not_found=not_found,
            errors=errors,
        )
        self._append_line(self._summary_text)

    def save_log_to_file(self) -> None:

        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _FILE_DIALOG_TITLE,
            _FILE_DIALOG_DEFAULT_NAME,
            _FILE_DIALOG_FILTER,
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8", newline="") as fp:
                fp.write(self._journal_text())
        except OSError as exc:
            self._show_save_error(path, exc)


    @property
    def total(self) -> int:

        return self._total

    @property
    def processed(self) -> int:

        return self._processed

    @property
    def log_view(self) -> QPlainTextEdit:

        return self._log_view

    @property
    def rate_limit_label(self) -> QLabel:

        return self._rate_limit_label

    @property
    def save_button(self) -> QPushButton:

        return self._save_button


    def _format_eta(self, seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            m = s // 60
            sec = s % 60
            return f"{m}m {sec}s"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"

    def _update_stats_header(self) -> None:
        remaining = max(0, self._total - self._processed)

        if self._processed == 0 and self._total > 0:
            self._stats_header.setText(
                f"Scanning... Found {self._total} messages"
            )
            eta_seconds = self._total * 0.5
            self._eta_label.setText(
                f"Estimated deletion time: ~{self._format_eta(eta_seconds)}"
            )
        elif self._processed == 0 and self._total == 0:
            self._stats_header.setText("Waiting...")
            self._eta_label.setText("")
        else:
            self._stats_header.setText(
                f"Found: {self._total} | "
                f"Deleted: {self._processed} | "
                f"Remaining: {remaining}"
            )
            eta_seconds = remaining * 0.5
            if remaining > 0:
                self._eta_label.setText(
                    f"Estimated time: ~{self._format_eta(eta_seconds)}"
                )
            else:
                self._eta_label.setText("Done")

    def _render_entry(
        self, entry: OperationLogEntry, processed_snapshot: int
    ) -> str:

        if entry.message_timestamp is not None:
            return format_log_line(entry, processed_snapshot, self._total)
        return _NON_MESSAGE_LINE_TEMPLATE.format(
            description=entry.description,
            processed=processed_snapshot,
            total=self._total,
        )

    def _journal_text(self) -> str:

        lines: list[str] = []
        for entry, snapshot in zip(
            self._entries, self._processed_snapshots, strict=True
        ):
            lines.append(self._render_entry(entry, snapshot))
        return "\n".join(lines)

    def _rerender_all(self) -> None:

        text_lines: list[str] = []
        for entry, snapshot in zip(
            self._entries, self._processed_snapshots, strict=True
        ):
            text_lines.append(self._render_entry(entry, snapshot))
        if self._summary_text is not None:
            text_lines.append(self._summary_text)

        self._log_view.setPlainText("\n".join(text_lines))
        self._scroll_to_end()

    def _append_line(self, line: str) -> None:

        self._log_view.appendPlainText(line)
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:

        self._log_view.moveCursor(QTextCursor.MoveOperation.End)
        self._log_view.ensureCursorVisible()


    def _on_rate_limit_tick(self) -> None:

        if not self._rl_active:
            return

        self._rl_remaining_s = max(0.0, self._rl_remaining_s - 1.0)

        if self._rl_remaining_s <= 0.0:
            self._refresh_rate_limit_label()
            self.hide_rate_limit_wait()
            return

        self._refresh_rate_limit_label()

    def _refresh_rate_limit_label(self) -> None:

        seconds_int = int(self._rl_remaining_s) if (
            self._rl_remaining_s == int(self._rl_remaining_s)
        ) else int(self._rl_remaining_s) + 1
        self._rate_limit_label.setText(
            _RATE_LIMIT_LABEL_TEMPLATE.format(
                reason=self._rl_reason,
                seconds=seconds_int,
            )
        )

    def _show_save_error(self, path: str, exc: OSError) -> None:

        reason = exc.strerror if getattr(exc, "strerror", None) else str(exc)
        message = _SAVE_ERROR_TEMPLATE.format(path=path, reason=reason)
        QMessageBox.critical(self, _SAVE_ERROR_TITLE, message)


__all__ = ["ProgressDisplay"]
