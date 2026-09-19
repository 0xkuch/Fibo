import unittest
from datetime import timedelta

from tests.helpers import T
from fibo.clock import Calendar, Zone, calendar_hours

CAL = Calendar()
H = timedelta(hours=1)
PLUS3 = Zone.fixed(3 * H)


def work(a: str, b: str, zone: Zone = PLUS3, cal: Calendar = CAL) -> float:
    return cal.work_hours(T(a), T(b), zone)


class WorkHours(unittest.TestCase):
    def test_a_full_day_is_eight_hours(self):
        self.assertAlmostEqual(work("2025-03-03 09:00 +03:00", "2025-03-03 18:00 +03:00"), 8)

    def test_outside_the_window_does_not_count(self):
        self.assertEqual(work("2025-03-03 07:00 +03:00", "2025-03-03 09:00 +03:00"), 0)
        self.assertEqual(work("2025-03-03 18:00 +03:00", "2025-03-03 23:30 +03:00"), 0)

    def test_part_of_a_day_is_scaled(self):
        self.assertAlmostEqual(work("2025-03-03 09:00 +03:00", "2025-03-03 13:30 +03:00"), 4)

    def test_across_the_weekend(self):
        # Friday 17-18 and Monday 9-10: two hours of window.
        self.assertAlmostEqual(work("2025-03-07 17:00 +03:00", "2025-03-10 10:00 +03:00"), 2 * 8 / 9)

    def test_a_weekend_is_zero(self):
        self.assertEqual(work("2025-03-08 10:00 +03:00", "2025-03-09 18:00 +03:00"), 0)

    def test_a_week_is_forty(self):
        self.assertAlmostEqual(work("2025-03-03 09:00 +03:00", "2025-03-10 09:00 +03:00"), 40)

    def test_reversed_or_missing_is_zero(self):
        self.assertEqual(work("2025-03-04 10:00 +03:00", "2025-03-03 10:00 +03:00"), 0)
        self.assertEqual(CAL.work_hours(None, T("2025-03-03 10:00 +03:00")), 0)

    def test_the_author_offset_decides_the_day(self):
        a, b = "2025-03-03 06:00 +00:00", "2025-03-03 15:00 +00:00"
        self.assertAlmostEqual(work(a, b, PLUS3), 8)  # 09:00-18:00 in Moscow
        self.assertAlmostEqual(work(a, b, Zone.fixed(0 * H)), 6 * 8 / 9)  # 09:00-15:00 in London

    def test_timezone_change_mid_span(self):
        zone = Zone([(T("2025-03-01 12:00 +03:00"), 3 * H), (T("2025-03-05 12:00 +01:00"), 1 * H)])
        # Mon 09:00 → Wed 14:00 at +03 is 9+9+5 window hours; Wed 12:00 → Fri 18:00 at +01 is 6+9+9.
        got = work("2025-03-03 09:00 +03:00", "2025-03-07 18:00 +01:00", zone)
        self.assertAlmostEqual(got, 47 * 8 / 9)
        self.assertAlmostEqual(work("2025-03-03 09:00 +03:00", "2025-03-07 18:00 +01:00", PLUS3), 40)

    def test_custom_calendar(self):
        cal = Calendar(frozenset({0, 1, 2, 3, 4, 5}), 10, 16, 6)
        self.assertAlmostEqual(work("2025-03-08 10:00 +03:00", "2025-03-08 16:00 +03:00", cal=cal), 6)
        self.assertEqual(cal.unit_hours("d"), 6)
        self.assertEqual(cal.unit_hours("w"), 36)

    def test_advance_is_the_inverse(self):
        start = T("2025-03-04 11:20 +03:00")
        for hours in (0.5, 3, 8, 13, 40, 77.5):
            with self.subTest(hours=hours):
                end = CAL.advance(start, hours, 3 * H)
                self.assertAlmostEqual(CAL.work_hours(start, end, PLUS3), hours, places=6)

    def test_advance_skips_the_weekend(self):
        # Two working hours are 2.25 window hours: Friday 17-18, then Monday from 9:00.
        self.assertEqual(CAL.advance(T("2025-03-07 17:00 +03:00"), 2, 3 * H), T("2025-03-10 10:15 +03:00"))


class Zones(unittest.TestCase):
    def test_a_single_stray_commit_is_not_a_move(self):
        samples = [(T(f"2025-03-0{d} 12:00 +03:00"), 3 * H) for d in (1, 2, 4, 5)]
        samples.append((T("2025-03-03 12:00 +00:00"), 0 * H))  # a web-UI edit
        self.assertEqual(Zone(samples).offsets, [3 * H])

    def test_a_real_move_is_kept(self):
        samples = [(T("2025-03-01 12:00 +03:00"), 3 * H), (T("2025-03-02 12:00 +03:00"), 3 * H),
                   (T("2025-03-10 12:00 +01:00"), 1 * H), (T("2025-03-11 12:00 +01:00"), 1 * H)]
        zone = Zone(samples)
        self.assertEqual(zone.offsets, [3 * H, 1 * H])
        self.assertEqual(zone.at(T("2025-03-05 12:00 +00:00")), 3 * H)
        self.assertEqual(zone.at(T("2025-03-12 12:00 +00:00")), 1 * H)

    def test_before_the_first_sample_the_first_offset_holds(self):
        zone = Zone([(T("2025-03-01 12:00 +03:00"), 3 * H)])
        self.assertEqual(zone.at(T("2020-01-01 00:00 +00:00")), 3 * H)

    def test_empty_zone_uses_the_instant_own_offset(self):
        self.assertEqual(Zone().at(T("2025-03-01 12:00 +05:00")), 5 * H)


class CalendarHours(unittest.TestCase):
    def test_raw_hours(self):
        self.assertEqual(calendar_hours(T("2025-03-07 17:00 +03:00"), T("2025-03-10 10:00 +03:00")), 65)

    def test_never_negative(self):
        self.assertEqual(calendar_hours(T("2025-03-10 10:00 +03:00"), T("2025-03-07 17:00 +03:00")), 0)
        self.assertEqual(calendar_hours(None, None), 0)


if __name__ == "__main__":
    unittest.main()
