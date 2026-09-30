"""复议：只能引用原裁定版本与真实支付结果，禁止按新政策重算。"""

from .policies import resolve_policy


class ReviewError(Exception):
    pass


class ReviewService:
    def __init__(self, policies: dict, registry, payments):
        self.policies = policies
        self.registry = registry
        self.payments = payments

    def apply(self, case_id: str, at: str, claim: str = "") -> dict:
        case = self.registry.get(case_id)
        original = case.get("decision")
        if not original:
            raise ReviewError("原裁定不存在，不能复议")

        # 只引用原裁定留存的版本快照，不按当前政策重新取版。
        snapshot = original["snapshot"]
        current = resolve_policy(self.policies, case["housing_city_code"], at)

        real_payment = self.payments.real_result(case_id)
        recorded_payment = case.get("payment")

        result = {
            "case_id": case_id,
            "reviewed_at": at,
            "original_policy_version": original["policy_version"],
            "current_policy_version": current["version"],
            "applied_policy_version": original["policy_version"],
            "original_snapshot": snapshot,
            "claim": claim,
            "payment": real_payment,
        }

        if current["version"] != original["policy_version"]:
            result["note"] = "政策已修订，复议仍按原裁定版本审查"

        # 复议结论以真实支付结果为准，不认账面以外的支付主张。
        if original["result"] == "approved":
            if real_payment and recorded_payment and real_payment["bank_serial"] == recorded_payment.get("bank_serial"):
                result["outcome"] = "upheld"
            elif not real_payment:
                result["outcome"] = "approved_not_paid"
            else:
                result["outcome"] = "payment_mismatch"
        else:
            result["outcome"] = "recheck_rejection"
        return result
