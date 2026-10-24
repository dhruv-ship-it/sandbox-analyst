import pytest

from sandbox_analyst.llm.limiter import RateLimiter


def test_first_call_never_sleeps():
    sleeps: list[float] = []
    clock = iter([100.0])
    RateLimiter(rpm=60, sleep=sleeps.append, now=lambda: next(clock)).wait()
    assert sleeps == []


def test_second_call_sleeps_for_the_remaining_interval():
    sleeps: list[float] = []
    clock = iter([100.0, 100.4])
    limiter = RateLimiter(rpm=60, sleep=sleeps.append, now=lambda: next(clock))
    limiter.wait()
    limiter.wait()
    assert sleeps == pytest.approx([0.6])  # 60/60 = 1.0s interval; 0.4s elapsed, 0.6s remaining


def test_no_sleep_once_enough_time_has_already_passed():
    sleeps: list[float] = []
    clock = iter([100.0, 102.0])
    limiter = RateLimiter(rpm=60, sleep=sleeps.append, now=lambda: next(clock))
    limiter.wait()
    limiter.wait()
    assert sleeps == []


def test_lower_rpm_means_a_longer_minimum_interval():
    sleeps: list[float] = []
    clock = iter([100.0, 100.5])
    limiter = RateLimiter(rpm=30, sleep=sleeps.append, now=lambda: next(clock))
    limiter.wait()
    limiter.wait()
    assert sleeps == [1.5]  # 60/30 = 2.0s interval; 0.5s elapsed, 1.5s remaining
