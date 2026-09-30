"""支付台账：同一裁定只支付一次，银行并发请求返回首次结果。"""

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PaymentRecord:
    """真实支付结果；复议只引用台账中的记录。"""

    decision_id: str
    amount: int
    paid_at: datetime


@dataclass(frozen=True)
class RecoveryRecord:
    """骗提追缴记录。"""

    decision_id: str
    amount: int
    recovered_at: datetime


class PaymentLedger:
    """按裁定编号幂等记账，重复与并发调用不会重复付款。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payments: dict[str, PaymentRecord] = {}
        self._recoveries: dict[str, RecoveryRecord] = {}

    def pay(self, decision_id: str, amount: int, paid_at: datetime) -> PaymentRecord:
        with self._lock:
            existing = self._payments.get(decision_id)
            if existing is not None:
                return existing
            record = PaymentRecord(decision_id, amount, paid_at)
            self._payments[decision_id] = record
            return record

    def find(self, decision_id: str) -> PaymentRecord | None:
        return self._payments.get(decision_id)

    def recover(
        self, decision_id: str, amount: int, recovered_at: datetime
    ) -> RecoveryRecord:
        with self._lock:
            existing = self._recoveries.get(decision_id)
            if existing is not None:
                return existing
            record = RecoveryRecord(decision_id, amount, recovered_at)
            self._recoveries[decision_id] = record
            return record

    def is_recovered(self, decision_id: str) -> bool:
        return decision_id in self._recoveries
