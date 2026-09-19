import unittest
from datetime import timedelta, timezone

from tests import helpers  # noqa: F401  (puts src on the path)
from fibo.model import from_seconds, parse_estimate, parse_time


def hours(text: str) -> float | None:
    return parse_estimate(text, "test").work_hours()


class ParseEstimate(unittest.TestCase):
    def test_hours_days_weeks(self):
        self.assertEqual(hours("4h"), 4)
        self.assertEqual(hours("2d"), 16)
        self.assertEqual(hours("1w"), 40)

    def test_decimal_point_and_comma(self):
        self.assertEqual(hours("1.5d"), 12)
        self.assertEqual(hours("1,5d"), 12)

    def test_compound(self):
        self.assertEqual(hours("1d 4h"), 12)
        self.assertEqual(hours("1w 2d"), 56)

    def test_words(self):
        self.assertEqual(hours("2 days"), 16)
        self.assertEqual(hours("3 hours"), 3)
        self.assertEqual(hours("1 week"), 40)

    def test_minutes(self):
        self.assertEqual(hours("30m"), 0.5)
        self.assertEqual(hours("90 min"), 1.5)

    def test_tilde_is_tolerated(self):
        self.assertEqual(hours("~2d"), 16)

    def test_not_a_duration(self):
        for text in ["soon", "end of sprint", "2", "quick", "2d?", "two days", "0d", "", "asap"]:
            with self.subTest(text=text):
                e = parse_estimate(text, "test")
                self.assertFalse(e.is_duration)
                self.assertIsNone(e.work_hours())

    def test_points_are_not_time(self):
        for text in ["3 points", "5sp", "2 pts", "1 point", "8 story points"]:
            with self.subTest(text=text):
                e = parse_estimate(text, "test")
                self.assertTrue(e.is_points)
                self.assertFalse(e.is_duration)
                self.assertIsNone(e.work_hours())

    def test_points_convert_only_on_request(self):
        e = parse_estimate("3 points", "test")
        self.assertEqual(e.work_hours(points_as_hours=4), 12)

    def test_calendar_hours_take_words_literally(self):
        self.assertEqual(parse_estimate("2d", "t").calendar_hours(), 48)
        self.assertEqual(parse_estimate("1w", "t").calendar_hours(), 168)
        self.assertEqual(parse_estimate("4h", "t").calendar_hours(), 4)

    def test_unit_is_the_largest(self):
        self.assertEqual(parse_estimate("1w 2d", "t").unit, "w")
        self.assertEqual(parse_estimate("3 points", "t").unit, "pt")
        self.assertIsNone(parse_estimate("soon", "t").unit)

    def test_custom_day_length(self):
        self.assertEqual(parse_estimate("2d", "t").work_hours(hours_per_day=6), 12)

    def test_same_value(self):
        self.assertTrue(parse_estimate("2d", "t").same_value(parse_estimate("16h", "t")))
        self.assertFalse(parse_estimate("2d", "t").same_value(parse_estimate("3d", "t")))
        self.assertTrue(parse_estimate("soon", "t").same_value(parse_estimate("Soon", "t")))

    def test_keeps_what_was_said(self):
        self.assertEqual(parse_estimate("  2d ", "t").text, "2d")


class FromSeconds(unittest.TestCase):
    def test_back_to_what_was_typed(self):
        self.assertEqual(from_seconds(28800, "jira").text, "1d")
        self.assertEqual(from_seconds(57600, "jira").text, "2d")
        self.assertEqual(from_seconds(144000, "jira").text, "1w")
        self.assertEqual(from_seconds(43200, "jira").text, "1d 4h")
        self.assertEqual(from_seconds(5400, "jira").text, "1.5h")

    def test_tracker_day_length_is_respected(self):
        e = from_seconds(21600, "jira", hours_per_day=6)  # Jira set to 6-hour days: 21600s is "1d"
        self.assertEqual(e.text, "1d")
        self.assertEqual(e.work_hours(), 8)  # a day on your calendar

    def test_nothing_is_not_a_duration(self):
        for value in (0, None, "abc", -60):
            with self.subTest(value=value):
                self.assertFalse(from_seconds(value, "jira").is_duration)


class ParseTime(unittest.TestCase):
    def test_jira_style(self):
        t = parse_time("2024-03-05T14:02:11.123+0300")
        self.assertEqual(t.utcoffset(), timedelta(hours=3))
        self.assertEqual(t.microsecond, 123000)

    def test_zulu_and_colon_offsets_agree(self):
        self.assertEqual(parse_time("2024-03-05T11:02:11Z"), parse_time("2024-03-05T14:02:11+03:00"))

    def test_naive_means_utc(self):
        self.assertEqual(parse_time("2024-03-05 14:02").tzinfo, timezone.utc)

    def test_garbage(self):
        for value in (None, "", "yesterday", "2024-13"):
            with self.subTest(value=value):
                self.assertIsNone(parse_time(value))


if __name__ == "__main__":
    unittest.main()
