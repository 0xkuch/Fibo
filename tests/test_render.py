import io
import os
import unittest
from unittest import mock

from tests.helpers import RepoBuilder
from fibo.i18n import Lang, by, fmt, times
from fibo.render import SPARK, Style, color_enabled, detail, drift, report, sparkline


class Russian(unittest.TestCase):
    ru = Lang("ru")

    def test_plurals(self):
        cases = {1: "задача", 2: "задачи", 4: "задачи", 5: "задач", 11: "задач", 12: "задач", 14: "задач",
                 21: "задача", 22: "задачи", 25: "задач", 111: "задач", 1247: "задач"}
        for n, want in cases.items():
            with self.subTest(n=n):
                self.assertEqual(self.ru.word(n, "task"), want)

    def test_fractions_take_the_genitive(self):
        self.assertEqual(self.ru.word(4.5, "day"), "дня")

    def test_numbers(self):
        self.assertEqual(self.ru.int(1247), "1 247")
        self.assertEqual(Lang("en").int(1247), "1,247")

    def test_what_was_said(self):
        self.assertEqual(self.ru.said(((2.0, "d"),), "2d"), "2 дня")
        self.assertEqual(self.ru.said(((1.0, "w"),), "1w"), "неделя")
        self.assertEqual(self.ru.said(((1.0, "h"),), "1h"), "час")
        self.assertEqual(self.ru.said(((1.0, "d"), (4.0, "h")), "1d 4h"), "1d 4h")

    def test_ago(self):
        self.assertEqual(self.ru.ago(24), "два года назад")
        self.assertEqual(self.ru.ago(1), "месяц назад")
        self.assertEqual(self.ru.ago(0), "сейчас")


class English(unittest.TestCase):
    en = Lang("en")

    def test_plurals(self):
        self.assertEqual(self.en.count(1, "task"), "1 task")
        self.assertEqual(self.en.count(2, "task"), "2 tasks")

    def test_what_was_said(self):
        self.assertEqual(self.en.said(((2.0, "d"),), "2d"), "2 days")
        self.assertEqual(self.en.said(((1.0, "w"),), "1w"), "a week")
        self.assertEqual(self.en.said(((1.0, "h"),), "1h"), "an hour")

    def test_amounts_move_up_a_unit_when_long(self):
        self.assertEqual(self.en.amount(72, "d"), "9 days")
        self.assertEqual(self.en.amount(120, "w"), "3 weeks")
        self.assertEqual(self.en.amount(6, "h"), "6 hours")
        self.assertEqual(self.en.amount(30, "h"), "3.8 days")
        self.assertEqual(self.en.amount(160, "d"), "4 weeks")

    def test_ago(self):
        self.assertEqual(self.en.ago(24), "two years ago")
        self.assertEqual(self.en.ago(5), "five months ago")
        self.assertEqual(self.en.ago(12), "a year ago")


class Numbers(unittest.TestCase):
    def test_a_multiplier_keeps_its_decimal(self):
        self.assertEqual(times(3), "3.0×")
        self.assertEqual(times(3.84), "3.8×")
        self.assertEqual(by(4.5), "×4.5")
        self.assertEqual(times(250), "250×")

    def test_amounts_drop_a_useless_decimal(self):
        self.assertEqual((fmt(4.5), fmt(9.0), fmt(12.4)), ("4.5", "9", "12"))

    def test_sparkline(self):
        rising = sparkline([1.5, 2, 3, 4.5])
        self.assertEqual(len(rising), 4)
        self.assertTrue(set(rising) <= set(SPARK))
        self.assertLess(SPARK.index(rising[0]), SPARK.index(rising[-1]))
        flat = sparkline([3.0, 3.0, 3.0])
        self.assertEqual(len(set(flat)), 1)

    def test_a_wobble_stays_small(self):
        line = sparkline([3.6, 3.7, 3.65])
        self.assertLessEqual(SPARK.index(max(line)) - SPARK.index(min(line)), 4)


class Color(unittest.TestCase):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    def test_no_color_is_respected(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(color_enabled(self.Tty()))

    def test_force_color(self):
        env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
        with mock.patch.dict(os.environ, {**env, "FORCE_COLOR": "1"}, clear=True):
            self.assertTrue(color_enabled(io.StringIO()))

    def test_a_pipe_gets_no_color(self):
        env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "FORCE_COLOR")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(color_enabled(io.StringIO()))
            self.assertTrue(color_enabled(self.Tty()) or os.environ.get("TERM") == "dumb")

    def test_style(self):
        self.assertEqual(Style(False).bold("x"), "x")
        self.assertEqual(Style(True).bold("x"), "\x1b[1mx\x1b[0m")


class Report(unittest.TestCase):
    def build(self, *tasks):
        b = RepoBuilder(self)
        for i, (message, hours_later) in enumerate(tasks, 1):
            b.branch(f"PROJ-{i}-x", (f"2025-03-{i + 2:02d} 09:00 +03:00", f"PROJ-{i} x\n\n{message}"))
            b.merge(f"PROJ-{i}-x", f"2025-03-{i + 2:02d} {9 + hours_later:02d}:00 +03:00")
        return b.analyze()

    def test_the_numbers_on_a_small_history(self):
        a = self.build(("Estimate: 1h", 2), ("Estimate: 1h", 3), ("Estimate: 1h", 4), ("Estimate: soon", 1),
                       ("nothing", 1))
        text = report(a, Lang("en"), Style(False))
        self.assertIn("5 tasks · 5 closed · 4 estimated · 3 counted", text)
        self.assertIn('said "an hour"', text)
        self.assertIn("your multiplier", text)
        self.assertIn("excluded: 1 task (not a duration: 1)", text)
        self.assertIn("too few to mean much", text)
        self.assertTrue(text.startswith("  (o,o)   fibo · "))
        self.assertEqual(text.splitlines()[1:3], ["  /)_)", '   ""'])

    def test_a_quarter_of_one_task_gets_no_bar(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-01-13 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1h"))
        b.merge("PROJ-1-x", "2025-01-13 12:00 +03:00")
        for i in (2, 3, 4):
            b.branch(f"PROJ-{i}-x", (f"2025-04-0{i} 09:00 +03:00", f"PROJ-{i} x\n\nEstimate: 1h"))
            b.merge(f"PROJ-{i}-x", f"2025-04-0{i} 13:00 +03:00")
        lines = drift(b.analyze(), Lang("en"), Style(False)).splitlines()
        q1 = next(l for l in lines if "2025 Q1" in l)
        q2 = next(l for l in lines if "2025 Q2" in l)
        self.assertIn("·", q1)
        self.assertNotIn("█", q1)
        self.assertIn("█", q2)
        self.assertIn("n=3", q2)

    def test_a_long_pause_is_named_and_clipped(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d"),
                                     ("2025-03-17 10:00 +03:00", "back at it"))
        a = b.merge("PROJ-1-x", "2025-03-17 12:00 +03:00").analyze()
        o = a.find("PROJ-1")
        self.assertLess(o.active_h, o.span_h)
        # two weeks of silence count as three days; the last two hours count as they are
        self.assertAlmostEqual(o.active_h, 24 + 2 * 8 / 9, places=6)
        text = detail(a, o, Lang("en"), Style(False))
        self.assertIn("longest pause", text)
        self.assertIn("clipped to 3 days in active", text)

    def test_nothing_to_divide(self):
        a = self.build(("nothing", 1))
        text = report(a, Lang("en"), Style(False))
        self.assertIn("(-,-)", text)
        self.assertIn("nothing to divide yet", text)
        self.assertIn("fibo demo", text)
        self.assertTrue(text.endswith("none of it written here"))


if __name__ == "__main__":
    unittest.main()
