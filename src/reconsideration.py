"""复议：只能引用原裁定的政策版本和台账中的真实支付结果。"""

from dataclasses import dataclass
from datetime import datetime

from .adjudication import Adjudicator
from .domain import AppStatus
from .payments import PaymentRecord


@dataclass(frozen=True)
class ReconsiderationResult:
    """复议结论；政策版本与原裁定一致，支付事实来自台账。"""

    decision_id: str
    outcome: AppStatus
    amount: int
    policy_city: str
    policy_version: int
    payment: PaymentRecord | None
    reasons: tuple[str, ...]
    decided_at: datetime


def reconsider(
    adjudicator: Adjudicator, decision_id: str, now: datetime
) -> ReconsiderationResult:
    """对原裁定复议。

    不重新解析当前政策：按原裁定记录的城市与版本号取回历史版本，
    即使该版本此后已被修订。支付事实只取自支付台账。
    """
    original = adjudicator.decision_by_id(decision_id)
    policy = adjudicator.book.get(original.policy_city, original.policy_version)
    app = adjudicator.apps[original.app_id]
    account = adjudicator.accounts[app.applicant_id]
    kind, amount, reasons = adjudicator.evaluate(app, policy, account)
    if kind == "supplement":
        # 复议阶段不再中止补件；材料不齐视为不成立
        kind, amount = "reject", 0
        reasons = [f"材料不齐：{'、'.join(reasons)}"]
    outcome = AppStatus.APPROVED if kind == "approve" else AppStatus.REJECTED
    payment = adjudicator.ledger.find(decision_id)
    return ReconsiderationResult(
        decision_id=decision_id,
        outcome=outcome,
        amount=amount,
        policy_city=policy.city,
        policy_version=policy.version,
        payment=payment,
        reasons=tuple(reasons),
        decided_at=now,
    )
