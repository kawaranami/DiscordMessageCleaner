from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import TokenManager
from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.models import Message, OperationLogEntry
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter
from discord_message_purger.ui.main_window import MainWindow


def _setup_logging() -> Path:

    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent.parent.parent

    log_path = base_dir / "discord_purger.log"

    handlers: list[logging.Handler] = []
    try:
        handlers.append(
            logging.FileHandler(log_path, mode="w", encoding="utf-8")
        )
    except Exception:
        import tempfile
        log_path = Path(tempfile.gettempdir()) / "discord_purger.log"
        try:
            handlers.append(
                logging.FileHandler(log_path, mode="w", encoding="utf-8")
            )
        except Exception:
            pass

    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return log_path


class _LazyDeleter:

    def __init__(
        self,
        http: DiscordHttpClient,
        operation_log: OperationLog,
        session: Session,
        rate_limiter: RateLimiter,
    ) -> None:
        self._http = http
        self._operation_log = operation_log
        self._session = session
        self._rate_limiter = rate_limiter
        self._deleter: MessageDeleter | None = None

    def delete(self, message: Message) -> OperationLogEntry:
        if self._deleter is None:
            self._deleter = MessageDeleter(
                http=self._http,
                operation_log=self._operation_log,
                authenticated_user_id=self._session.authenticated_user_id or "",
                rate_limiter=self._rate_limiter,
            )
        return self._deleter.delete(message)


def main() -> None:

    log_path = _setup_logging()
    logger = logging.getLogger("discord_message_purger")
    logger.info("=== Starting Discord Message Purger ===")
    logger.info("Log file: %s", log_path)

    app = QApplication(sys.argv)

    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    session = Session()

    rate_limiter = RateLimiter()
    http_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
    )

    operation_log = OperationLog()
    scanner = MessageScanner(http_client, operation_log)

    deleter = _LazyDeleter(
        http=http_client,
        operation_log=operation_log,
        session=session,
        rate_limiter=rate_limiter,
    )

    token_manager = TokenManager(http_client, session)
    controller = OperationController(
        scanner=scanner,
        deleter=deleter,  # type: ignore[arg-type]  # LazyDeleter implements DeleterProtocol
        operation_log=operation_log,
        session=session,
    )

    window = MainWindow(
        controller=controller,
        session=session,
        token_manager=token_manager,
        http_client=http_client,
    )

    app.aboutToQuit.connect(session.clear_token)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import tempfile
        import traceback as _tb
        from pathlib import Path as _Path

        if getattr(sys, "frozen", False):
            _crash_dir = _Path(sys.executable).parent
        else:
            _crash_dir = _Path.cwd()
        _crash_path = _crash_dir / "discord_purger_crash.log"
        try:
            _crash_path.write_text(_tb.format_exc(), encoding="utf-8")
        except Exception:
            _Path(tempfile.gettempdir(), "discord_purger_crash.log").write_text(
                _tb.format_exc(), encoding="utf-8"
            )
        raise
