"""核验与裁定：按受理时固定的政策版本作出决定并留存快照。"""

from .accounts import Ledger
from .cases import CaseRegistry
from .policies import mutual_recognition_active, resolve_policy, rule_for
from .timeutil import d, suspension_open


class VerificationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Adjudicator:
    def __init__(self, policies: dict, ledger: Ledger, registry: CaseRegistry):
        self.policies = policies
        self.ledger = ledger
        self.registry = registry

    def policy_snapshot(self, case: dict) -> dict:
        """受理时点版本；已固定的快照直接复用，保证修订不溯及。"""
        if case["policy_snapshot"]:
            return case["policy_snapshot"]
        policy = resolve_policy(self.policies, case["housing_city_code"], case["accepted_at"])
        snapshot = {
            "city_code": policy["city_code"],
            "city_name": policy["city_name"],
            "version": policy["version"],
            "effective_from": policy["effective_from"],
            "effective_to": policy.get("effective_to"),
            "resolved_at": case["accepted_at"],
            "rule": rule_for(policy, case["scenario"]),
            "mutual_recognition": mutual_recognition_active(policy, case["accepted_at"]),
        }
        case["policy_snapshot"] = snapshot
        return snapshot

    def verify(self, case: dict) -> list[str]:
        """返回问题代码列表；为空即核验通过。"""
        snapshot = self.policy_snapshot(case)
        rule = snapshot["rule"]
        account_id = case["account_id"]
        accepted = d(case["accepted_at"])
        problems: list[str] = []

        if self.ledger.restriction_active(account_id, accepted):
            problems.append("restriction_active")

        if self.ledger.transfer_frozen(account_id):
            problems.append("transfer_frozen")

        if self.ledger.eligible_months(account_id, snapshot["mutual_recognition"]) < rule["required_months"]:
            problems.append("contribution_months_insufficient")

        if rule["needs_family_auth"] and not self.ledger.has_family_auth(account_id, case["scenario"], accepted):
            problems.append("family_auth_missing")

        if rule["needs_voucher"]:
            voucher = self.ledger.voucher(account_id, case["voucher_id"]) if case.get("voucher_id") else None
            if not voucher or not voucher["valid"]:
                problems.append("voucher_invalid")
            elif voucher["scenario"] != case["scenario"]:
                problems.append("voucher_scenario_mismatch")

        years = rule.get("frequency_years")
        if years:
            last = self.ledger.last_paid_usage(account_id, case["scenario"])
            if last is not None and accepted.year - last.year < years:
                problems.append("frequency_limit")

        return problems

    def quota_remaining(self, case: dict, snapshot: dict) -> int | None:
        quota = snapshot["rule"]["annual_quota"]
        if quota is None:
            return None
        year = d(case["accepted_at"]).year
        return quota - self.ledger.paid_usage(case["account_id"], case["scenario"], year) - self.ledger.occupied(
            case["account_id"], case["scenario"], year
        )

    def decide(self, case_id: str, decided_at: str) -> dict:
        case = self.registry.get(case_id)
        if case["status"] in ("decided", "withdrawn"):
            raise VerificationError("case_not_open", f"案件 {case_id} 当前状态为 {case['status']}，不能裁定")
        if suspension_open(case["suspensions"]):
            raise VerificationError("supplement_open", "补件中止尚未结束，不能作出决定")
        if d(decided_at) > self.registry.deadline(case_id):
            raise VerificationError("deadline_exceeded", "已超过扣除补件中止后的三日办理期限")

        snapshot = self.policy_snapshot(case)
        problems = self.verify(case)
        decision = {
            "case_id": case_id,
            "decided_at": decided_at,
            "policy_version": snapshot["version"],
            "policy_resolved_at": snapshot["resolved_at"],
            "snapshot": snapshot,
        }

        if problems:
            decision.update({"result": "rejected", "reasons": problems, "approved_amount": 0})
        else:
            amount = case["request_amount"]
            voucher = self.ledger.voucher(case["account_id"], case["voucher_id"])
            amount = min(amount, voucher["amount"])
            remaining = self.quota_remaining(case, snapshot)
            if remaining is not None and remaining <= 0:
                decision.update(
                    {"result": "rejected", "reasons": ["annual_quota_exhausted"], "approved_amount": 0}
                )
                case["decision"] = decision
                case["status"] = "decided"
                return decision
            if remaining is not None:
                amount = min(amount, remaining)
            amount = min(amount, self.ledger.available_balance(case["account_id"]))
            decision.update({"result": "approved", "reasons": [], "approved_amount": amount})
            if amount > 0:
                year = d(case["accepted_at"]).year
                self.ledger.occupy(case_id, case["account_id"], case["scenario"], year, amount)
                self.ledger.hold(case_id, case["account_id"], amount)

        case["decision"] = decision
        case["status"] = "decided"
        return decision
