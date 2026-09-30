"""三日办理期限：补件依法中止的时间从期限中扣除。"""

from datetime import datetime, timedelta

from .domain import Suspension

LIMIT = timedelta(days=3)


def _overlap(start: datetime, end: datetime, susp: Suspension) -> timedelta:
    s = max(start, susp.start)
    e = min(end, susp.end) if susp.end is not None else end
    return max(timedelta(0), e - s)


def consumed(
    accepted_at: datetime, suspensions: list[Suspension], now: datetime
) -> timedelta:
    """已耗用的办理时间：经过时间减去中止区间。"""
    elapsed = now - accepted_at
    paused = sum(
        (_overlap(accepted_at, now, s) for s in suspensions), timedelta(0)
    )
    return elapsed - paused


def remaining(
    accepted_at: datetime, suspensions: list[Suspension], now: datetime
) -> timedelta:
    """剩余办理时间；为负表示已超期。"""
    return LIMIT - consumed(accepted_at, suspensions, now)


def is_overdue(
    accepted_at: datetime, suspensions: list[Suspension], now: datetime
) -> bool:
    return remaining(accepted_at, suspensions, now) < timedelta(0)
