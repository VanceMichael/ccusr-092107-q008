import unittest
from datetime import datetime, timedelta

from src import deadline
from src.domain import Suspension

ACCEPTED = datetime(2026, 9, 28, 9, 0, 0)


class DeadlineTest(unittest.TestCase):
    def test_no_suspension_counts_full_elapsed(self):
        now = ACCEPTED + timedelta(days=2)
        self.assertEqual(deadline.consumed(ACCEPTED, [], now), timedelta(days=2))
        self.assertEqual(deadline.remaining(ACCEPTED, [], now), timedelta(days=1))

    def test_suspension_is_deducted(self):
        susp = [
            Suspension(
                start=ACCEPTED + timedelta(days=1),
                end=ACCEPTED + timedelta(days=4),
            )
        ]
        now = ACCEPTED + timedelta(days=5)
        # 经过 5 天，中止 3 天，耗用 2 天
        self.assertEqual(
            deadline.consumed(ACCEPTED, susp, now), timedelta(days=2)
        )
        self.assertFalse(deadline.is_overdue(ACCEPTED, susp, now))

    def test_open_suspension_counts_until_now(self):
        susp = [Suspension(start=ACCEPTED + timedelta(hours=2))]
        now = ACCEPTED + timedelta(days=10)
        self.assertEqual(
            deadline.consumed(ACCEPTED, susp, now), timedelta(hours=2)
        )

    def test_overdue_without_suspension(self):
        now = ACCEPTED + timedelta(days=3, seconds=1)
        self.assertTrue(deadline.is_overdue(ACCEPTED, [], now))


if __name__ == "__main__":
    unittest.main()
