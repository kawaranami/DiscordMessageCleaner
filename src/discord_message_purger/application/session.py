from __future__ import annotations

from dataclasses import dataclass, field


_TOKEN_MASK = "***"


@dataclass(repr=False)
class Session:

    consent_granted: bool = False

    token: str | None = field(default=None)

    authenticated_user_id: str | None = field(default=None)

    def clear_token(self) -> None:

        if self.token is not None:
            self.token = "\x00" * len(self.token)
        self.token = None
        self.authenticated_user_id = None

    def __repr__(self) -> str:

        token_repr = _TOKEN_MASK if self.token is not None else "None"
        return (
            f"Session(consent_granted={self.consent_granted!r}, "
            f"token={token_repr}, "
            f"authenticated_user_id={self.authenticated_user_id!r})"
        )
