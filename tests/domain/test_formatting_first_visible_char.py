from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.formatting import first_visible_char


# Feature: discord-message-purger, Property 32: first_visible_char correctness
@pytest.mark.property
@given(content=st.text())
@settings(max_examples=100)
def test_first_visible_char_property(content: str) -> None:
    result = first_visible_char(content)

    assert isinstance(result, str), (
        "Результат first_visible_char должен быть строкой, "
        f"получено: {type(result).__name__}"
    )
    assert len(result) == 1, (
        "Результат first_visible_char должен иметь длину ровно 1 символ, "
        f"получено: {result!r} (длина {len(result)})"
    )

    if content.strip() != "":
        expected = content.lstrip()[0]
        assert result == expected, (
            "Для непустой по содержанию строки first_visible_char должна "
            f"вернуть первый символ content.lstrip(), ожидалось {expected!r}, "
            f"получено {result!r} (вход: {content!r})"
        )
    else:
        assert result == "·", (
            'Для пустой или whitespace-only строки first_visible_char '
            f'должна вернуть "·", получено {result!r} (вход: {content!r})'
        )
