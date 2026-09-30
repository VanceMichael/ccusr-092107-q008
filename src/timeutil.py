"""日期与办理期限工具。"""

from datetime import date, timedelta


def d(value: str | date) -> date:
    """把 ISO 字符串转为日期。"""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def iso(value: date) -> str:
    return value.isoformat()


DECISION_DAYS = 3


def decision_deadline(accepted_at: str | date, suspensions: list[dict]) -> date:
    """受理日加三日，扣除已结束的补件中止时段。

    尚未结束的中止时段不能扣除，调用方应先阻止作出决定。
    """
    deadline = d(accepted_at) + timedelta(days=DECISION_DAYS)
    for interval in suspensions:
        if interval.get("end") is None:
            continue
        deadline += d(interval["end"]) - d(interval["start"])
    return deadline


def suspension_open(suspensions: list[dict]) -> bool:
    return any(interval.get("end") is None for interval in suspensions)
