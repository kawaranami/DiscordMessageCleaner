from __future__ import annotations

from typing import Callable

from .formatting import format_log_line
from .models import (
    LogEntryStatus,
    OperationLogEntry,
    OperationSummary,
)

_PROCESSED_STATUSES: frozenset[LogEntryStatus] = frozenset(
    {
        LogEntryStatus.SUCCESS,
        LogEntryStatus.NOT_FOUND,
        LogEntryStatus.ERROR,
        LogEntryStatus.REJECTED,
    }
)


class OperationLog:

    __slots__ = (
        "entries",
        "scanned_messages",
        "found_total",
        "processed",
        "skipped_other_authors",
        "channels_skipped",
        "on_total_changed",
        "_processed_snapshots",
    )

    def __init__(self) -> None:
        self.entries: list[OperationLogEntry] = []

        self.scanned_messages: int = 0
        self.found_total: int = 0
        self.processed: int = 0
        self.skipped_other_authors: int = 0
        self.channels_skipped: int = 0

        self.on_total_changed: Callable[[int], None] | None = None

        self._processed_snapshots: list[int] = []


    def add(self, entry: OperationLogEntry) -> None:
        if entry.status in _PROCESSED_STATUSES:
            new_processed = self.processed + 1
            if new_processed > self.found_total:
                raise AssertionError(
                    "Invariant violation processed <= found_total: "
                    f"attempted to set processed={new_processed} "
                    f"while found_total={self.found_total}"
                )
            self.processed = new_processed
        elif entry.status is LogEntryStatus.CHANNEL_SKIPPED:
            self.channels_skipped += 1

        self.entries.append(entry)
        self._processed_snapshots.append(self.processed)

    def update_total(self, new: int) -> None:
        if self.processed > new:
            raise AssertionError(
                "Invariant violation processed <= found_total: "
                f"attempted to set found_total={new} while "
                f"processed={self.processed}"
            )
        self.found_total = new

        if self.on_total_changed is not None:
            self.on_total_changed(new)


    def summary(self) -> OperationSummary:
        success = 0
        not_found = 0
        errors = 0
        for entry in self.entries:
            status = entry.status
            if status is LogEntryStatus.SUCCESS:
                success += 1
            elif status is LogEntryStatus.NOT_FOUND:
                not_found += 1
            elif status is LogEntryStatus.ERROR:
                errors += 1

        return OperationSummary(
            success=success,
            not_found=not_found,
            errors=errors,
            rejected_other_author=self.skipped_other_authors,
            channels_skipped=self.channels_skipped,
            scanned_messages=self.scanned_messages,
            found_for_user=self.found_total,
        )

    def export_text(self) -> str:
        current_total = self.found_total

        lines: list[str] = []
        for entry, processed_snapshot in zip(
            self.entries, self._processed_snapshots, strict=True
        ):
            if entry.message_timestamp is not None:
                lines.append(
                    format_log_line(entry, processed_snapshot, current_total)
                )
            else:
                lines.append(
                    f"-- {entry.description} -- "
                    f"[{processed_snapshot}/{current_total}]"
                )

        return "\n".join(lines)


__all__ = ["OperationLog"]
