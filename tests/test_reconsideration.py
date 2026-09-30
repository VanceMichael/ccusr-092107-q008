import unittest
from datetime import datetime

from src.domain import AppStatus
from src.reconsideration import reconsider
from tests.support import make_adjudicator, make_app

ACCEPTED_UNDER_V1 = datetime(2026, 6, 28, 10, 0, 0)
AFTER_V2 = datetime(2026, 7, 2, 9, 0, 0)


class ReconsiderationTest(unittest.TestCase):
    def test_reconsideration_cites_original_policy_version(self):
        adj = make_adjudicator()
        adj.submit(
            make_app("app-1", "acct-001", accepted_at=ACCEPTED_UNDER_V1, amount=25000)
        )
        decision = adj.adjudicate("app-1", AFTER_V2)
        result = reconsider(adj, decision.decision_id, AFTER_V2)
        # 复议在 v2 生效后进行，但仍引用原裁定的 v1
        self.assertEqual(result.policy_version, 1)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 25000)  # 不受 v2 限额 20000 影响

    def test_reconsideration_uses_real_payment_record(self):
        adj = make_adjudicator()
        adj.submit(
            make_app("app-2", "acct-001", accepted_at=ACCEPTED_UNDER_V1, amount=20000)
        )
        decision = adj.adjudicate("app-2", AFTER_V2)
        adj.pay_approved(decision.decision_id, AFTER_V2)
        result = reconsider(adj, decision.decision_id, AFTER_V2)
        self.assertIsNotNone(result.payment)
        self.assertEqual(result.payment.amount, 20000)
        self.assertEqual(result.payment.decision_id, decision.decision_id)

    def test_unpaid_decision_has_no_payment_fact(self):
        adj = make_adjudicator()
        adj.submit(
            make_app("app-3", "acct-001", accepted_at=ACCEPTED_UNDER_V1, amount=20000)
        )
        decision = adj.adjudicate("app-3", AFTER_V2)
        result = reconsider(adj, decision.decision_id, AFTER_V2)
        self.assertIsNone(result.payment)

    def test_reconsideration_can_overturn_wrong_rejection(self):
        adj = make_adjudicator()
        # 物业费无需家庭授权，但申请按装修提交被拒后更正情形不在此列；
        # 这里验证：复议按原版本重新求值，结论与规则一致
        adj.submit(
            make_app(
                "app-4",
                "acct-002",
                accepted_at=ACCEPTED_UNDER_V1,
                amount=10000,
            )
        )
        decision = adj.adjudicate("app-4", AFTER_V2)
        self.assertEqual(decision.outcome, AppStatus.REJECTED)  # 冻结中
        # 冻结解除后复议：同一版本重新求值
        adj.accounts["acct-002"].frozen = 0
        result = reconsider(adj, decision.decision_id, AFTER_V2)
        self.assertEqual(result.policy_version, 1)
        self.assertEqual(result.outcome, AppStatus.APPROVED)
        self.assertEqual(result.amount, 10000)


if __name__ == "__main__":
    unittest.main()
