"""骗提追缴：撤销裁定、追回已付资金、登记使用限制。"""

from .accounts import FRAUD_WITHDRAWAL_YEARS
from .timeutil import d


class EnforcementService:
    def __init__(self, ledger, registry, payments):
        self.ledger = ledger
        self.registry = registry
        self.payments = payments

    def clawback(self, case_id: str, found_at: str) -> dict:
        """认定骗提：以真实支付结果为准追回，未支付则只释放占用。"""
        case = self.registry.get(case_id)
        decision = case.get("decision")
        if not decision:
            raise ValueError("未裁定的案件不能追缴")

        real = self.payments.real_result(case_id)
        recovered = 0
        if real:
            account = self.ledger.get(case["account_id"])
            account["balance"] += real["amount"]
            recovered = real["amount"]
            self.ledger.clawback_usage(case_id)
        else:
            self.ledger.release_hold(case_id)
            self.ledger.release_occupation(case_id)

        self.ledger.add_restriction(
            case["account_id"], "fraudulent_withdrawal", found_at, FRAUD_WITHDRAWAL_YEARS
        )
        case["status"] = "clawed_back"
        case["decision"]["result"] = "revoked_fraud"
        return {
            "case_id": case_id,
            "recovered": recovered,
            "restriction_years": FRAUD_WITHDRAWAL_YEARS,
            "from_date": d(found_at).isoformat(),
        }
