from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.infrastructure.rate_limiter import RateLimiter


class _FakeClock:

    def __init__(self) -> None:
        self._t: float = 1_000.0

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds < 0.0:
            raise ValueError(f"sleep_fn получил отрицательную длительность: {seconds!r}")
        self._t += seconds

    def advance(self, seconds: float) -> None:
        if seconds < 0.0:
            raise ValueError(
                f"advance ожидает неотрицательное значение, получено: {seconds!r}"
            )
        self._t += seconds


_MIN_INTERVAL_SECONDS: float = 0.25


# Feature: discord-message-purger, Property 27: Minimum 250 ms between consecutive deletes
@pytest.mark.property
@given(
    work_intervals=st.lists(
        st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=2,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_min_delete_interval_at_least_250_ms(work_intervals: list[float]) -> None:
    clock = _FakeClock()
    limiter = RateLimiter(
        time_source=clock.now,
        sleep_fn=clock.sleep,
    )

    send_timestamps: list[float] = []

    for work_interval in work_intervals:
        clock.advance(work_interval)

        limiter.enforce_min_delete_interval()

        send_timestamps.append(clock.now())

    assert len(send_timestamps) == len(work_intervals), (
        "Количество записанных моментов отправки должно совпадать "
        "с числом вызовов enforce_min_delete_interval"
    )

    for i in range(1, len(send_timestamps)):
        t1 = send_timestamps[i - 1]
        t2 = send_timestamps[i]
        delta = t2 - t1
        assert delta >= _MIN_INTERVAL_SECONDS, (
            "Интервал между последовательными DELETE должен быть "
            f">= {_MIN_INTERVAL_SECONDS} с, получено {delta!r} "
            f"(пара #{i - 1}->{i}, work_intervals={work_intervals!r}, "
            f"timestamps={send_timestamps!r})"
        )
