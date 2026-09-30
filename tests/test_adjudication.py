"""端到端裁定规则测试。"""

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.accounts import Ledger, load_accounts
from src.adjudication import Adjudicator, VerificationError
from src.cases import CaseError, CaseRegistry
from src.enforcement import EnforcementService
from src.payments import BankGateway, PaymentService
from src.policies import load_policies, resolve_policy
from src.review import ReviewError, ReviewService
from src.timeutil import decision_deadline

ROOT = Path(__file__).resolve().parents[1]


def build():
    policies = load_policies(ROOT / "fixtures/policies.json")
    ledger = Ledger(load_accounts(ROOT / "fixtures/accounts.json"))
    registry = CaseRegistry()
    adjudicator = Adjudicator(policies, ledger, registry)
    payments = PaymentService(ledger, registry, BankGateway())
    enforcement = EnforcementService(ledger, registry, payments)
    review = ReviewService(policies, registry, payments)
    return policies, ledger, registry, adjudicator, payments, enforcement, review


def submission(**overrides):
    base = {
        "case_id": "C-2026-0001",
        "person_id": "P005",
        "account_id": "A005",
        "scenario": "renovation",
        "housing_city_code": "320199",
        "submitted_at": "2026-09-28",
        "request_amount": 130000,
        "voucher_id": "V-5001",
        "housing_id": "H-500",
        "channel": "window",
        "period": "2026",
    }
    base.update(overrides)
    return base


class PolicyVersionTest(unittest.TestCase):
    def test_version_pinned_at_acceptance_not_decision(self):
        """受理在 9/28 用 v1（装修额度10万），三天后决定时 10/1 政策已修订为 v2（8万），仍按 v1。"""
        policies, ledger, registry, adjudicator, *_ = build()
        before = resolve_policy(policies, "320199", "2026-09-28")
        after = resolve_policy(policies, "320199", "2026-10-01")
        self.assertEqual((before["version"], after["version"]), (1, 2))
        self.assertEqual(before["rules"]["renovation"]["annual_quota"], 100000)
        self.assertEqual(after["rules"]["renovation"]["annual_quota"], 80000)

        case = registry.submit(submission())
        decision = adjudicator.decide("C-2026-0001", "2026-10-01")
        self.assertEqual(decision["policy_version"], 1)
        self.assertEqual(decision["approved_amount"], 100000)
        self.assertEqual(decision["snapshot"]["resolved_at"], "2026-09-28")

    def test_city_chosen_by_housing_location(self):
        policies, *_ = build()
        yuecheng = resolve_policy(policies, "330199", "2026-09-28")
        self.assertEqual(yuecheng["rules"]["renovation"]["annual_quota"], 120000)


class ContributionAndVerificationTest(unittest.TestCase):
    def test_remote_contributions_recognized(self):
        # A005 本地仅 1 个月，外地 7 个月，互认后满 6 个月。
        _, ledger, registry, adjudicator, *_ = build()
        case = registry.submit(submission())
        snap = adjudicator.policy_snapshot(case)
        self.assertTrue(snap["mutual_recognition"])
        self.assertEqual(ledger.eligible_months("A005", True), 8)
        self.assertNotIn("contribution_months_insufficient", adjudicator.verify(case))

    def test_without_mutual_recognition_local_months_only(self):
        _, ledger, *_ = build()
        self.assertEqual(ledger.eligible_months("A005", mutual=False), 1)

    def test_family_auth_required_for_elevator(self):
        _, _, registry, adjudicator, *_ = build()
        # A001 有适老化授权，无加装电梯授权
        registry.submit(
            submission(
                case_id="C-E",
                person_id="P001",
                account_id="A001",
                scenario="elevator",
                voucher_id="V-1001",
            )
        )
        self.assertIn("family_auth_missing", adjudicator.verify(registry.get("C-E")))

    def test_voucher_scenario_mismatch(self):
        _, _, registry, adjudicator, *_ = build()
        registry.submit(
            submission(case_id="C-VM", person_id="P001", account_id="A001", voucher_id="V-1002")
        )
        # V-1002 是物业费凭证，用于装修申请
        self.assertIn("voucher_scenario_mismatch", adjudicator.verify(registry.get("C-VM")))

    def test_balance_and_history_occupation_cap_amount(self):
        # A001：凭证12万、额度10万、历史2024年装修（5年频次限制）应被拦截
        _, _, registry, adjudicator, *_ = build()
        registry.submit(
            submission(case_id="C-A1", person_id="P001", account_id="A001", voucher_id="V-1001")
        )
        decision = adjudicator.decide("C-A1", "2026-09-29")
        self.assertEqual(decision["result"], "rejected")
        self.assertIn("frequency_limit", decision["reasons"])


class DeadlineTest(unittest.TestCase):
    def test_three_day_deadline(self):
        self.assertEqual(decision_deadline("2026-09-28", []).isoformat(), "2026-10-01")

    def test_supplement_days_excluded(self):
        _, _, registry, adjudicator, *_ = build()
        registry.submit(submission())
        # 9/29 中止补件，10/01 恢复，中止 2 天，期限顺延 2 天。
        registry.suspend_for_supplement("C-2026-0001", "2026-09-29")
        registry.resume_from_supplement("C-2026-0001", "2026-10-01")
        self.assertEqual(registry.deadline("C-2026-0001").isoformat(), "2026-10-03")

        # 中止未结束时不能决定
        registry.suspend_for_supplement("C-2026-0001", "2026-10-02")
        with self.assertRaises(VerificationError) as ctx:
            adjudicator.decide("C-2026-0001", "2026-10-02")
        self.assertEqual(ctx.exception.code, "supplement_open")

    def test_overdue_decision_rejected(self):
        _, _, registry, adjudicator, *_ = build()
        registry.submit(submission())
        with self.assertRaises(VerificationError) as ctx:
            adjudicator.decide("C-2026-0001", "2026-10-02")
        self.assertEqual(ctx.exception.code, "deadline_exceeded")


class DuplicateAndWithdrawTest(unittest.TestCase):
    def test_online_and_window_submissions_merge(self):
        _, _, registry, *_ = build()
        first = registry.submit(submission(channel="window"))
        second = registry.submit(submission(channel="online"))
        self.assertIs(first, second)
        self.assertEqual(second["channels"], ["window", "online"])
        self.assertEqual(len(registry.cases), 1)

    def test_withdraw_and_resubmit_keeps_acceptance_time(self):
        _, _, registry, adjudicator, *_ = build()
        registry.submit(submission())
        registry.withdraw("C-2026-0001", "2026-09-29")
        renewed = registry.resubmit("C-2026-0001", "2026-09-30", "window")
        self.assertEqual(renewed["accepted_at"], "2026-09-28")
        self.assertEqual(renewed["origin_case_id"], "C-2026-0001")
        decision = adjudicator.decide(renewed["case_id"], "2026-10-01")
        self.assertEqual(decision["policy_version"], 1)

    def test_resubmitting_withdrawn_case_as_new_is_rejected(self):
        _, _, registry, *_ = build()
        registry.submit(submission())
        registry.withdraw("C-2026-0001", "2026-09-29")
        with self.assertRaises(CaseError):
            registry.submit(submission(channel="online"))


class TransferFreezeTest(unittest.TestCase):
    def test_transfer_frozen_balance_unavailable(self):
        _, ledger, registry, adjudicator, *_ = build()
        registry.submit(
            submission(case_id="C-A4", person_id="P004", account_id="A004",
                       scenario="property_fee", voucher_id="V-4001", request_amount=3000)
        )
        self.assertTrue(ledger.transfer_frozen("A004"))
        self.assertEqual(ledger.available_balance("A004"), 0)
        decision = adjudicator.decide("C-A4", "2026-09-29")
        self.assertEqual(decision["result"], "rejected")
        self.assertIn("transfer_frozen", decision["reasons"])

    def test_approved_after_transfer_release(self):
        _, ledger, registry, adjudicator, payments, *_ = build()
        ledger.release_transfer("A004", "2026-10-05")
        registry.submit(
            submission(case_id="C-A4", person_id="P004", account_id="A004",
                       scenario="property_fee", voucher_id="V-4001", request_amount=3000,
                       submitted_at="2026-10-06")
        )
        decision = adjudicator.decide("C-A4", "2026-10-07")
        self.assertEqual(decision["result"], "approved")
        result = payments.pay("C-A4")
        self.assertEqual(result["status"], "paid")


class PaymentConcurrencyTest(unittest.TestCase):
    def test_concurrent_bank_calls_settle_once(self):
        _, ledger, registry, adjudicator, payments, *_ = build()
        registry.submit(submission())
        adjudicator.decide("C-2026-0001", "2026-09-30")
        before = ledger.get("A005")["balance"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: payments.pay("C-2026-0001"), range(8)))
        serials = {r["bank_serial"] for r in results}
        self.assertEqual(len(serials), 1)
        self.assertEqual(ledger.get("A005")["balance"], before - 100000)
        # 八个并发请求都看到同一笔支付，余额只被扣一次
        self.assertTrue(all(r["status"] == "paid" and r["amount"] == 100000 for r in results))


class RestrictionAndClawbackTest(unittest.TestCase):
    def test_fraudulent_withdrawal_restriction_three_years(self):
        _, _, registry, adjudicator, *_ = build()
        registry.submit(
            submission(case_id="C-A2", person_id="P002", account_id="A002", voucher_id="V-2001")
        )
        decision = adjudicator.decide("C-A2", "2026-09-29")
        self.assertIn("restriction_active", decision["reasons"])

    def test_loan_fraud_restriction_five_years(self):
        _, ledger, *_ = build()
        # 2024-06-01 起 5 年，2029-06 前受限
        self.assertIsNotNone(ledger.restriction_active("A003", "2029-05-31"))
        self.assertIsNone(ledger.restriction_active("A003", "2029-06-01"))

    def test_clawback_recovers_real_payment_and_imposes_restriction(self):
        _, ledger, registry, adjudicator, payments, enforcement, _ = build()
        registry.submit(submission())
        adjudicator.decide("C-2026-0001", "2026-09-30")
        paid = payments.pay("C-2026-0001")
        balance_after_payment = ledger.get("A005")["balance"]

        outcome = enforcement.clawback("C-2026-0001", "2026-11-10")
        self.assertEqual(outcome["recovered"], paid["amount"])
        self.assertEqual(outcome["restriction_years"], 3)
        self.assertEqual(ledger.get("A005")["balance"], balance_after_payment + paid["amount"])
        self.assertIsNotNone(ledger.restriction_active("A005", "2027-01-01"))

    def test_clawback_without_payment_only_releases_occupation(self):
        _, ledger, registry, adjudicator, payments, enforcement, _ = build()
        registry.submit(submission())
        adjudicator.decide("C-2026-0001", "2026-09-30")
        occupied_before = ledger.occupied("A005", "renovation", 2026)
        self.assertEqual(occupied_before, 100000)
        outcome = enforcement.clawback("C-2026-0001", "2026-11-10")
        self.assertEqual(outcome["recovered"], 0)
        self.assertEqual(ledger.occupied("A005", "renovation", 2026), 0)


class ReviewTest(unittest.TestCase):
    def test_review_uses_original_version_after_revision(self):
        *_, adjudicator, payments, _, review = build()
        registry = adjudicator.registry
        registry.submit(submission())
        adjudicator.decide("C-2026-0001", "2026-10-01")
        payments.pay("C-2026-0001")
        result = review.apply("C-2026-0001", "2026-10-05")
        self.assertEqual(result["applied_policy_version"], 1)
        self.assertEqual(result["current_policy_version"], 2)
        self.assertEqual(result["outcome"], "upheld")
        self.assertIsNotNone(result["payment"])

    def test_review_requires_real_payment(self):
        *_, adjudicator, payments, _, review = build()
        registry = adjudicator.registry
        registry.submit(submission())
        adjudicator.decide("C-2026-0001", "2026-09-30")
        # 未支付即复议
        result = review.apply("C-2026-0001", "2026-10-02")
        self.assertEqual(result["payment"], None)
        self.assertEqual(result["outcome"], "approved_not_paid")

    def test_review_without_decision_fails(self):
        *_, registry, _, _, _, review = build()
        registry.submit(submission())
        with self.assertRaises(ReviewError):
            review.apply("C-2026-0001", "2026-10-02")


if __name__ == "__main__":
    unittest.main()
