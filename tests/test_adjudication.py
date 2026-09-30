import unittest
from datetime import datetime, timedelta

from src.domain import AppStatus, Channel, Scenario, SupplementRequest, Decision
from tests.support import make_adjudicator, make_app

# 示例市 v1 至 2026-07-01 前生效（装修限额 30000），v2 自 2026-07-01 起（限额 20000）
ACCEPTED_UNDER_V1 = datetime(2026, 6, 28, 10, 0, 0)
DECIDED_AFTER_V2 = datetime(2026, 7, 2, 9, 0, 0)


class TemporalAdjudicationTest(unittest.TestCase):
    """受理后政策修订，裁定仍适用受理时点的版本。"""

    def test_decision_uses_policy_at_acceptance_not_decision_day(self):
        adj = make_adjudicator()
        app = make_app("app-1", "acct-001", accepted_at=ACCEPTED_UNDER_V1)
        adj.submit(app)
        result = adj.adjudicate("app-1", DECIDED_AFTER_V2)
        self.assertIsInstance(result, Decision)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 25000)  # v1 限额 30000 下可全额
        self.assertEqual(result.policy_version, 1)

    def test_same_application_after_v2_would_be_capped(self):
        adj = make_adjudicator()
        app = make_app(
            "app-2", "acct-001", accepted_at=datetime(2026, 7, 2, 10, 0, 0)
        )
        adj.submit(app)
        result = adj.adjudicate("app-2", datetime(2026, 7, 3, 9, 0, 0))
        self.assertEqual(result.policy_version, 2)
        self.assertEqual(result.amount, 20000)  # v2 限额收紧

    def test_housing_city_governs_not_submission_channel(self):
        adj = make_adjudicator()
        app = make_app(
            "app-3",
            "acct-001",
            city="邻市",
            accepted_at=ACCEPTED_UNDER_V1,
            channel=Channel.ONLINE,
        )
        adj.submit(app)
        result = adj.adjudicate("app-3", DECIDED_AFTER_V2)
        self.assertEqual(result.policy_city, "邻市")
        self.assertEqual(result.amount, 15000)  # 邻市限额 15000


class DuplicateSubmissionTest(unittest.TestCase):
    def test_online_and_window_duplicates_share_one_case(self):
        adj = make_adjudicator()
        window_app = make_app(
            "app-w", "acct-001", accepted_at=ACCEPTED_UNDER_V1, channel=Channel.WINDOW
        )
        online_app = make_app(
            "app-o", "acct-001", accepted_at=ACCEPTED_UNDER_V1, channel=Channel.ONLINE
        )
        first_id, created = adj.submit(window_app)
        self.assertTrue(created)
        second_id, created = adj.submit(online_app)
        self.assertFalse(created)
        self.assertEqual(first_id, second_id)

    def test_resubmission_after_withdrawal_is_a_new_case(self):
        adj = make_adjudicator()
        adj.submit(make_app("app-w", "acct-001", accepted_at=ACCEPTED_UNDER_V1))
        adj.withdraw("app-w")
        new_app = make_app(
            "app-n", "acct-001", accepted_at=datetime(2026, 7, 2, 10, 0, 0)
        )
        new_id, created = adj.submit(new_app)
        self.assertTrue(created)
        self.assertEqual(new_id, "app-n")
        result = adj.adjudicate("app-n", datetime(2026, 7, 3, 9, 0, 0))
        self.assertEqual(result.policy_version, 2)  # 重提按新受理时间
        self.assertEqual(result.amount, 20000)


class BalanceAndFreezeTest(unittest.TestCase):
    def test_frozen_balance_during_transfer_is_unavailable(self):
        adj = make_adjudicator()
        app = make_app(
            "app-f", "acct-002", accepted_at=ACCEPTED_UNDER_V1, amount=10000
        )
        adj.submit(app)
        result = adj.adjudicate("app-f", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.REJECTED)
        self.assertIn("冻结", result.reasons[0])

    def test_partial_freeze_caps_approvable_amount(self):
        adj = make_adjudicator()
        adj.accounts["acct-002"].frozen = 40000  # 可用 10000
        app = make_app(
            "app-p", "acct-002", accepted_at=ACCEPTED_UNDER_V1, amount=25000
        )
        adj.submit(app)
        result = adj.adjudicate("app-p", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 10000)


class MaterialCheckTest(unittest.TestCase):
    def test_missing_family_auth_and_vouchers_trigger_supplement(self):
        adj = make_adjudicator()
        app = make_app(
            "app-m",
            "acct-001",
            accepted_at=ACCEPTED_UNDER_V1,
            family_auth=False,
            vouchers=(),
        )
        adj.submit(app)
        result = adj.adjudicate("app-m", ACCEPTED_UNDER_V1 + timedelta(hours=4))
        self.assertIsInstance(result, SupplementRequest)
        self.assertEqual(set(result.missing), {"家庭授权", "消费凭证"})
        self.assertEqual(adj.status["app-m"], AppStatus.SUPPLEMENT)

    def test_supplement_resumes_and_keeps_original_policy_version(self):
        adj = make_adjudicator()
        app = make_app(
            "app-s",
            "acct-001",
            accepted_at=ACCEPTED_UNDER_V1,
            family_auth=False,
        )
        adj.submit(app)
        adj.adjudicate("app-s", ACCEPTED_UNDER_V1 + timedelta(hours=2))
        adj.supplement(
            "app-s", DECIDED_AFTER_V2, family_auth=True  # 补件时 v2 已生效
        )
        result = adj.adjudicate("app-s", DECIDED_AFTER_V2 + timedelta(hours=1))
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.policy_version, 1)  # 仍按受理时点
        self.assertEqual(result.amount, 25000)

    def test_suspension_time_is_deducted_from_three_day_limit(self):
        adj = make_adjudicator()
        app = make_app(
            "app-d",
            "acct-001",
            accepted_at=ACCEPTED_UNDER_V1,
            family_auth=False,
        )
        adj.submit(app)
        adj.adjudicate("app-d", ACCEPTED_UNDER_V1 + timedelta(hours=6))
        adj.supplement("app-d", ACCEPTED_UNDER_V1 + timedelta(days=10))
        # 自然经过 10 天，但中止 9 天 18 小时，耗用仅 6 小时
        remaining = adj.processing_remaining(
            "app-d", ACCEPTED_UNDER_V1 + timedelta(days=10)
        )
        self.assertEqual(remaining, timedelta(days=3) - timedelta(hours=6))


class OccupancyAndRestrictionTest(unittest.TestCase):
    def test_historical_withdrawals_reduce_annual_quota(self):
        adj = make_adjudicator()
        # acct-003 本年已在 house-01 装修提取 10000
        app = make_app(
            "app-h", "acct-003", accepted_at=ACCEPTED_UNDER_V1, amount=25000
        )
        adj.submit(app)
        result = adj.adjudicate("app-h", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 20000)  # 30000 - 10000

    def test_illegal_withdrawal_restricts_three_years(self):
        adj = make_adjudicator()
        # acct-004 于 2024-08-01 记 违法提取，限制 3 年
        app = make_app("app-r3", "acct-004", accepted_at=ACCEPTED_UNDER_V1)
        adj.submit(app)
        result = adj.adjudicate("app-r3", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.REJECTED)
        self.assertIn("违法提取", result.reasons[0])

    def test_fraud_restricts_five_years(self):
        adj = make_adjudicator()
        # acct-005 于 2023-01-15 记 骗提骗贷，限制 5 年
        app = make_app("app-r5", "acct-005", accepted_at=ACCEPTED_UNDER_V1)
        adj.submit(app)
        result = adj.adjudicate("app-r5", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.REJECTED)
        self.assertIn("骗提骗贷", result.reasons[0])

    def test_three_year_record_would_have_expired(self):
        adj = make_adjudicator()
        # 同一记录日期若按 3 年计已满期：换用 违法提取 类型验证期限差异
        adj.accounts["acct-005"].restrictions.clear()
        from src.domain import RestrictionRecord

        adj.accounts["acct-005"].restrictions.append(
            RestrictionRecord("违法提取", datetime(2023, 1, 15))
        )
        app = make_app("app-ok", "acct-005", accepted_at=ACCEPTED_UNDER_V1)
        adj.submit(app)
        result = adj.adjudicate("app-ok", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.APPROVED)


class OtherScenariosTest(unittest.TestCase):
    def test_property_fee_needs_no_family_auth(self):
        adj = make_adjudicator()
        app = make_app(
            "app-fee",
            "acct-001",
            accepted_at=ACCEPTED_UNDER_V1,
            scenario=Scenario.PROPERTY_FEE,
            amount=5000,
            family_auth=False,
        )
        adj.submit(app)
        result = adj.adjudicate("app-fee", DECIDED_AFTER_V2)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 5000)

    def test_elevator_and_aging_renovation_rules_apply(self):
        adj = make_adjudicator()
        for app_id, scenario, amount in (
            ("app-el", Scenario.ELEVATOR, 50000),
            ("app-ag", Scenario.AGING_RENOVATION, 20000),
        ):
            app = make_app(
                app_id,
                "acct-001",
                accepted_at=ACCEPTED_UNDER_V1,
                scenario=scenario,
                amount=amount,
                house_id=f"house-{app_id}",
            )
            adj.submit(app)
            result = adj.adjudicate(app_id, DECIDED_AFTER_V2)
            self.assertEqual(result.outcome, AppStatus.APPROVED)
            self.assertEqual(result.amount, amount)


if __name__ == "__main__":
    unittest.main()
