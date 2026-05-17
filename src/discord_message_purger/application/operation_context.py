from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..domain.models import OperationState, Server


@dataclass
class OperationContext:

    pause_event: threading.Event = field(default_factory=threading.Event)
    resume_event: threading.Event = field(default_factory=threading.Event)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    state: OperationState = OperationState.IDLE
    server: Server | None = None
    authenticated_user_id: str | None = None

    def wait_if_paused(self) -> bool:

        if not self.pause_event.is_set():
            return True

        while self.pause_event.is_set():
            if self.cancel_event.is_set():
                return False
            if self.resume_event.wait(timeout=0.1):
                self.resume_event.clear()
                self.pause_event.clear()
                return True

        return True

    def check_cancelled(self) -> bool:

        return self.cancel_event.is_set()


__all__ = ["OperationContext"]
