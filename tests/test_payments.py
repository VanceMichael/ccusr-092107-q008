import threading
import unittest
from datetime import datetime

from src.domain import AppStatus
from tests.support import make_adjudicator, make_app

ACCEPTED = datetime(2026, 6, 28, 10, 0, 0)
NOW = datetime(2026, 6, 29, 9, 0, 0)


def approved_decision(adj, app_id="app-pay", applicant="acct-001", amount=20000):
    adj.submit(make_app(app_id, applicant, accepted_at=ACCEPTED, amount=amount))
    return adj.adjudicate(app_id, NOW)


class PaymentTest(unittest.TestCase):
    def test_double_pay_returns_first_record_and_debits_once(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        first = adj.pay_approved(decision.decision_id, NOW)
        second = adj.pay_approved(decision.decision_id, NOW)
        self.assertIs(first, second)
        self.assertEqual(adj.accounts["acct-001"].balance, 80000 - 20000)

    def test_concurrent_bank_requests_pay_only_once(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        results = []

        def pay():
            results.append(adj.pay_approved(decision.decision_id, NOW))

        threads = [threading.Thread(target=pay) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({id(r) for r in results}), 1)
        self.assertEqual(adj.accounts["acct-001"].balance, 80000 - 20000)
        self.assertEqual(len(adj.accounts["acct-001"].withdrawals), 1)

    def test_rejected_decision_cannot_be_paid(self):
        adj = make_adjudicator()
        adj.submit(
            make_app("app-x", "acct-002", accepted_at=ACCEPTED, amount=10000)
        )
        decision = adj.adjudicate("app-x", NOW)
        self.assertEqual(decision.outcome, AppStatus.REJECTED)
        with self.assertRaises(ValueError):
            adj.pay_approved(decision.decision_id, NOW)

    def test_payment_feeds_historical_occupancy(self):
        adj = make_adjudicator()
        decision = approved_decision(adj, amount=20000)
        adj.pay_approved(decision.decision_id, NOW)
        # 同一住房同一场景再次申请：额度 30000 - 20000 = 10000
        later = datetime(2026, 6, 30, 10, 0, 0)
        adj.submit(
            make_app("app-next", "acct-001", accepted_at=later, amount=25000)
        )
        result = adj.adjudicate("app-next", later)
        self.assertEqual(result.amount, 10000)


class FraudRecoveryTest(unittest.TestCase):
    def test_recovery_restores_balance_and_adds_restriction(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        adj.pay_approved(decision.decision_id, NOW)
        adj.recover_fraud(decision.decision_id, NOW)
        account = adj.accounts["acct-001"]
        self.assertEqual(account.balance, 80000)
        self.assertEqual(account.restrictions[-1].kind, "骗提骗贷")

    def test_recovered_applicant_is_restricted_five_years(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        adj.pay_approved(decision.decision_id, NOW)
        adj.recover_fraud(decision.decision_id, NOW)
        adj.submit(
            make_app(
                "app-again",
                "acct-001",
                accepted_at=ACCEPTED,
                house_id="house-02",
            )
        )
        result = adj.adjudicate("app-again", NOW)
        self.assertEqual(result.outcome, AppStatus.REJECTED)
        self.assertIn("骗提骗贷", result.reasons[0])

    def test_recovery_is_idempotent(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        adj.pay_approved(decision.decision_id, NOW)
        first = adj.recover_fraud(decision.decision_id, NOW)
        second = adj.recover_fraud(decision.decision_id, NOW)
        self.assertIs(first, second)
        self.assertEqual(adj.accounts["acct-001"].balance, 80000)
        self.assertEqual(len(adj.accounts["acct-001"].restrictions), 1)

    def test_recovery_without_payment_fails(self):
        adj = make_adjudicator()
        decision = approved_decision(adj)
        with self.assertRaises(ValueError):
            adj.recover_fraud(decision.decision_id, NOW)


if __name__ == "__main__":
    unittest.main()
