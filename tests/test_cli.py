"""The refusals, the one subject, and every command, through the real entry point."""

import json
import unittest
from pathlib import Path

from tests.helpers import OTHER, RepoBuilder, cli, tempdir
from fibo.__main__ import build_parser
from fibo.sources import ledger


def repo(test: unittest.TestCase, *extra) -> RepoBuilder:
    b = RepoBuilder(test)
    b.branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d"))
    b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
    b.branch("PROJ-2-wip", ("2025-03-05 09:00 +03:00", "PROJ-2 wip"))
    for name, message in extra:
        b.branch(name, ("2025-03-06 09:00 +03:00", message)).merge(name, "2025-03-07 12:00 +03:00")
    b.finish()
    return b


class Say(unittest.TestCase):
    def setUp(self):
        self.path = str(repo(self).path)

    def say(self, *args):
        return cli("-C", self.path, "say", *args)

    def test_soon_is_not_a_duration(self):
        code, out, err = self.say("PROJ-9", "soon")
        self.assertEqual(code, 2)
        self.assertIn("is not a duration", err)
        self.assertEqual(ledger.read(Path(self.path))[0], [])

    def test_points_are_not_time(self):
        code, _, err = self.say("PROJ-9", "3", "points")
        self.assertEqual(code, 2)
        self.assertIn("points are not time", err)

    def test_after_the_work_began(self):
        code, _, err = self.say("PROJ-2", "2d")
        self.assertEqual(code, 2)
        self.assertIn("written after the work began", err)

    def test_a_closed_task_cannot_be_re_estimated(self):
        code, _, err = self.say("PROJ-1", "2d")
        self.assertEqual(code, 2)
        self.assertIn("already done", err)

    def test_before_starting_it_is_written_down(self):
        code, out, _ = self.say("proj-9", "2d")
        self.assertEqual(code, 0)
        self.assertIn("PROJ-9", out)
        entries, problems = ledger.read(Path(self.path))
        self.assertEqual([(e["key"], e["said"], e["email"]) for e in entries], [("PROJ-9", "2d", "me@example.com")])
        self.assertEqual(problems, [])

    def test_saying_it_twice_is_refused(self):
        self.say("PROJ-9", "2d")
        code, _, err = self.say("PROJ-9", "1d")
        self.assertEqual(code, 2)
        self.assertIn("already has an estimate", err)

    def test_every_refusal_wears_the_refuse_face(self):
        _, _, err = self.say("PROJ-9", "soon")
        self.assertTrue(err.startswith("(ò,ó)  ✗"), err)

    def test_saying_prints_the_new_link_in_the_chain(self):
        _, out, _ = self.say("PROJ-9", "2d")
        entry = ledger.read(Path(self.path))[0][0]
        self.assertIn(f"+1 line · {ledger.head(Path(self.path))[:6]} ← {entry['prev'][:6]}", out)

    def test_the_said_flag(self):
        self.assertEqual(self.say("PROJ-9", "--said", "4h")[0], 0)

    def test_usage(self):
        self.assertEqual(self.say("PROJ-9")[0], 2)


class OneSubject(unittest.TestCase):
    def test_someone_else_fails_loudly_not_emptily(self):
        b = repo(self)
        code, out, err = cli("-C", str(b.path), "--whose", "someone@else.com")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("one subject", err)

    def test_your_own_alias_is_you(self):
        b = repo(self).write(".fibo.json", json.dumps({"emails": ["me@work.com"]}))
        code, out, _ = cli("-C", str(b.path), "--whose", "Me@Work.com")
        self.assertEqual(code, 0)
        self.assertIn("your multiplier", out)

    def test_no_export_no_team_no_everyone(self):
        options = {s for action in build_parser()._actions for s in action.option_strings}
        for forbidden in ("--export", "--all", "--team", "--authors", "--everyone", "--json", "--csv", "--output"):
            self.assertNotIn(forbidden, options)
        path = str(repo(self).path)
        for verb, words in (("export", "exports nothing"), ("predict", "predicts nothing"),
                            ("team", "aggregates nobody")):
            with self.subTest(verb=verb):
                code, out, err = cli("-C", path, verb)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(words, err)

    def test_a_task_that_happens_to_be_named_like_a_verb_is_still_shown(self):
        b = repo(self, ("export", "add export\n\nEstimate: 1d"))
        code, out, _ = cli("-C", str(b.path), "export")
        self.assertEqual(code, 0)
        self.assertIn("add export", out)

    def test_the_report_names_its_subject(self):
        self.assertIn("one subject: you — me@example.com", cli("-C", str(repo(self).path))[1])

    def test_other_peoples_work_is_not_counted_at_all(self):
        b = RepoBuilder(self).branch("PROJ-5-x", ("2025-03-03 09:00 +03:00", "PROJ-5 x\n\nEstimate: 1d", OTHER))
        b.merge("PROJ-5-x", "2025-03-04 18:00 +03:00").finish()
        out = cli("-C", str(b.path))[1]
        self.assertIn("0 tasks", out)
        self.assertNotIn("PROJ-5", out)


class Refusals(unittest.TestCase):
    def test_no_estimate_is_not_guessed(self):
        b = repo(self, ("PROJ-3-x", "PROJ-3 x"))
        code, out, _ = cli("-C", str(b.path), "PROJ-3")
        self.assertEqual(code, 0)
        self.assertIn("no estimate — not counted, not guessed", out)

    def test_points_without_a_rate_are_excluded(self):
        b = repo(self, ("PROJ-3-x", "PROJ-3 x\n\nEstimate: 2 points"))
        self.assertIn("points, not time: 1", cli("-C", str(b.path))[1])

    def test_points_with_a_rate_say_whose_assumption_it_is(self):
        b = repo(self, ("PROJ-3-x", "PROJ-3 x\n\nEstimate: 2 points"))
        self.assertIn("your assumption, not a measurement", cli("-C", str(b.path), "--points-as-hours", "4")[1])

    def test_late_and_vague_estimates_are_named_in_the_exclusions(self):
        b = RepoBuilder(self)
        b.branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x"), ("2025-03-03 12:00 +03:00", "y\n\nEst: 1d"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        b.branch("PROJ-2-x", ("2025-03-05 09:00 +03:00", "PROJ-2 x\n\nEstimate: soon"))
        b.merge("PROJ-2-x", "2025-03-06 18:00 +03:00").finish()
        out = cli("-C", str(b.path))[1]
        self.assertIn("excluded: 2 tasks", out)
        self.assertIn("estimate after start: 1", out)
        self.assertIn("not a duration: 1", out)


class Commands(unittest.TestCase):
    def test_the_last_line_is_the_disclaimer(self):
        code, out, _ = cli("-C", str(repo(self).path))
        self.assertEqual(code, 0)
        self.assertEqual(out.rstrip().splitlines()[-1], "all of it computed from your history, none of it written here")

    def test_one_task(self):
        code, out, _ = cli("-C", str(repo(self).path), "proj-1")
        self.assertEqual(code, 0)
        self.assertIn("PROJ-1", out)
        self.assertIn("counted", out)

    def test_drift_and_doctor(self):
        path = str(repo(self).path)
        self.assertEqual(cli("-C", path, "drift")[0], 0)
        code, out, _ = cli("-C", path, "doctor")
        self.assertEqual(code, 0)
        self.assertIn("nothing to report", out)

    def test_doctor_fails_on_a_broken_ledger(self):
        b = repo(self)
        cli("-C", str(b.path), "say", "PROJ-9", "2d")
        cli("-C", str(b.path), "say", "PROJ-10", "1d")
        path = b.path / ledger.PATH
        path.write_text(path.read_text(encoding="utf-8").replace('"2d"', '"1d"'), encoding="utf-8")
        code, out, _ = cli("-C", str(b.path), "doctor")
        self.assertEqual(code, 1)
        self.assertIn("chain broken", out)

    def test_not_a_repository(self):
        code, _, err = cli("-C", str(tempdir(self)))
        self.assertEqual(code, 2)
        self.assertIn("not a git repository", err)

    def test_calendar_mode(self):
        self.assertIn("calendar time", cli("-C", str(repo(self).path), "--calendar")[1])

    def test_verbose_shows_the_geometric_mean(self):
        self.assertIn("geometric mean", cli("-C", str(repo(self).path), "-v")[1])

    def test_russian(self):
        out = cli("-C", str(repo(self).path), "--lang", "ru")[1]
        self.assertIn("твой множитель", out)
        self.assertTrue(out.rstrip().endswith("всё посчитано из твоей истории, не написано здесь"))

    def test_a_broken_config_is_a_clear_error(self):
        b = repo(self).write(".fibo.json", "{nope")
        code, _, err = cli("-C", str(b.path))
        self.assertEqual(code, 2)
        self.assertIn(".fibo.json", err)


if __name__ == "__main__":
    unittest.main()
