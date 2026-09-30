import unittest
from datetime import date

from src.store import load_accounts, load_policy_book
from tests.support import FIXTURES


class StoreTest(unittest.TestCase):
    def test_policies_fixture_loads_with_versions(self):
        book = load_policy_book(FIXTURES / "policies.json")
        v1 = book.resolve("示例市", date(2026, 6, 30))
        v2 = book.resolve("示例市", date(2026, 7, 1))
        self.assertEqual((v1.version, v2.version), (1, 2))
        self.assertEqual(v1.scenarios["装修"].annual_limit, 30000)
        self.assertEqual(v2.scenarios["装修"].annual_limit, 20000)
        self.assertEqual(v1.restriction_years, {"违法提取": 3, "骗提骗贷": 5})
        self.assertEqual(book.resolve("邻市", date(2026, 9, 30)).version, 1)

    def test_accounts_fixture_loads_all_states(self):
        accounts = load_accounts(FIXTURES / "accounts.json")
        self.assertEqual(accounts["acct-001"].available, 80000)
        self.assertEqual(accounts["acct-002"].available, 0)
        self.assertEqual(len(accounts["acct-003"].withdrawals), 1)
        self.assertEqual(accounts["acct-004"].restrictions[0].kind, "违法提取")
        self.assertEqual(accounts["acct-005"].restrictions[0].kind, "骗提骗贷")


if __name__ == "__main__":
    unittest.main()
