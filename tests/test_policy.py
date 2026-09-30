import unittest
from datetime import date

from src.policy import PolicyBook, PolicyVersion, ScenarioRule

RULE = ScenarioRule(
    annual_limit=30000, requires_vouchers=True, requires_family_auth=True
)


def make_version(city="示例市", version=1, start="2025-01-01", end=None):
    return PolicyVersion(
        city=city,
        version=version,
        effective_from=date.fromisoformat(start),
        effective_to=date.fromisoformat(end) if end else None,
        scenarios={"装修": RULE},
        restriction_years={"违法提取": 3, "骗提骗贷": 5},
    )


class PolicyBookTest(unittest.TestCase):
    def test_resolve_picks_version_by_acceptance_day(self):
        book = PolicyBook()
        book.add(make_version(version=1, end="2026-07-01"))
        book.add(make_version(version=2, start="2026-07-01"))
        self.assertEqual(book.resolve("示例市", date(2026, 6, 30)).version, 1)
        self.assertEqual(book.resolve("示例市", date(2026, 7, 1)).version, 2)

    def test_effective_to_is_exclusive(self):
        book = PolicyBook()
        book.add(make_version(end="2026-07-01"))
        with self.assertRaises(LookupError):
            book.resolve("示例市", date(2026, 7, 1))

    def test_same_version_cannot_be_rewritten(self):
        book = PolicyBook()
        book.add(make_version())
        book.add(make_version())  # 内容一致的幂等重放
        changed = make_version()
        changed = PolicyVersion(
            city=changed.city,
            version=changed.version,
            effective_from=changed.effective_from,
            effective_to=changed.effective_to,
            scenarios={"装修": ScenarioRule(1, False, False)},
            restriction_years=changed.restriction_years,
        )
        with self.assertRaises(ValueError):
            book.add(changed)

    def test_overlapping_ranges_rejected(self):
        book = PolicyBook()
        book.add(make_version(version=1, end="2026-07-01"))
        with self.assertRaises(ValueError):
            book.add(make_version(version=2, start="2026-06-01"))

    def test_gap_raises_lookup(self):
        book = PolicyBook()
        book.add(make_version(version=1, end="2026-01-01"))
        book.add(make_version(version=2, start="2026-07-01"))
        with self.assertRaises(LookupError):
            book.resolve("示例市", date(2026, 3, 1))

    def test_get_returns_historical_version(self):
        book = PolicyBook()
        book.add(make_version(version=1, end="2026-07-01"))
        book.add(make_version(version=2, start="2026-07-01"))
        self.assertEqual(book.get("示例市", 1).version, 1)
        with self.assertRaises(LookupError):
            book.get("示例市", 9)


if __name__ == "__main__":
    unittest.main()
