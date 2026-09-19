import math
import unittest
from datetime import timedelta

from tests.helpers import T
from fibo.stats import by_quarter, geomean, mean, median, multiplier, quantile, rolling, summarize


class Basics(unittest.TestCase):
    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)

    def test_quantile_type_7(self):
        xs = list(range(1, 11))
        self.assertAlmostEqual(quantile(xs, 0.9), 9.1)
        self.assertEqual(quantile(xs, 0), 1)
        self.assertEqual(quantile(xs, 1), 10)
        self.assertEqual(quantile([5], 0.9), 5)

    def test_mean(self):
        self.assertEqual(mean([1, 2, 3, 6]), 3)

    def test_nothing_is_an_error(self):
        for fn in (median, mean):
            with self.assertRaises(ValueError):
                fn([])
        with self.assertRaises(ValueError):
            quantile([], 0.5)


class Multiplier(unittest.TestCase):
    def test_median_in_log_space(self):
        self.assertAlmostEqual(multiplier([1, 4, 16]), 4)

    def test_even_count_is_geometric_between_the_middles(self):
        self.assertAlmostEqual(multiplier([2, 8]), 4)

    def test_one_disaster_does_not_move_it(self):
        self.assertAlmostEqual(multiplier([2, 2, 2, 40]), 2)
        self.assertGreater(sum([2, 2, 2, 40]) / 4, 11)  # what an arithmetic mean would have said

    def test_under_and_over_are_symmetric(self):
        self.assertAlmostEqual(multiplier([0.25, 4]), 1)

    def test_geometric_mean(self):
        self.assertAlmostEqual(geomean([2, 8]), 4)
        self.assertAlmostEqual(geomean([1, 10, 100]), 10)

    def test_non_positive_ratios_are_ignored(self):
        self.assertAlmostEqual(multiplier([0, -1, 3]), 3)

    def test_nothing_gives_none(self):
        self.assertIsNone(multiplier([]))
        self.assertIsNone(geomean([]))
        self.assertIsNone(summarize([]))


class Summary(unittest.TestCase):
    def test_all_fields_on_a_known_set(self):
        s = summarize([0.5, 1, 2, 4, 8])
        self.assertEqual(s.n, 5)
        self.assertAlmostEqual(s.multiplier, 2)
        self.assertAlmostEqual(s.geomean, 2)
        self.assertAlmostEqual(s.p90, 4 * 2 ** 0.6)
        self.assertAlmostEqual(s.under, 3 / 5)

    def test_exactly_on_time_is_not_underestimated(self):
        self.assertEqual(summarize([1, 1, 1]).under, 0)


class Drift(unittest.TestCase):
    def points(self, days: int, ratio) -> list:
        start = T("2024-01-01 12:00 +00:00")
        return [(start + timedelta(days=d), ratio(d) if callable(ratio) else ratio) for d in range(days)]

    def test_needs_a_full_window(self):
        self.assertEqual(rolling(self.points(60, 3.0)), [])

    def test_a_constant_ratio_draws_a_flat_line(self):
        out = rolling(self.points(365, 3.0))
        self.assertGreaterEqual(len(out), 2)
        self.assertLessEqual(len(out), 12)
        for _, m, n in out:
            self.assertAlmostEqual(m, 3.0)
            self.assertGreaterEqual(n, 3)

    def test_the_window_follows_a_change(self):
        out = rolling(self.points(400, lambda d: 2.0 if d < 200 else 8.0))
        self.assertAlmostEqual(out[0][1], 2.0)
        self.assertAlmostEqual(out[-1][1], 8.0)

    def test_quarters(self):
        rows = by_quarter([(T("2025-01-15 12:00 +00:00"), 2), (T("2025-02-15 12:00 +00:00"), 8),
                           (T("2025-04-02 12:00 +00:00"), 3)])
        self.assertEqual([(y, q, n) for y, q, _, n in rows], [(2025, 1, 2), (2025, 2, 1)])
        self.assertAlmostEqual(rows[0][2], 4)
        self.assertTrue(all(math.isfinite(m) for _, _, m, _ in rows))


if __name__ == "__main__":
    unittest.main()
