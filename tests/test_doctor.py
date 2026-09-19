import unittest

from tests.helpers import ME, RepoBuilder, T, tempdir
from fibo import config, doctor
from fibo.analysis import Analysis
from fibo.clock import Calendar, Zone
from fibo.i18n import Lang
from fibo.model import Task, parse_estimate
from fibo.pair import Keys, collect, evaluate, work_for
from fibo.render import Style
from fibo.sources import ledger

CAL = Calendar()


class Doctor(unittest.TestCase):
    def outcome(self, estimates, extra=()):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        units = collect(b.finish(), Keys({"PROJ-1"}))
        work = work_for("PROJ-1", units["PROJ-1"], {ME[1]}, CAL, Zone())
        task = Task("PROJ-1", "jira", "x", estimates=list(estimates), closed=T("2025-03-05 18:00 +03:00"))
        o = evaluate("PROJ-1", task, work, list(extra), CAL, Zone())
        a = Analysis(b.path, config.parse({}, b.path, ME[1]), "work", [ME[1]], "main", [o])
        return a, o

    def test_an_estimate_edited_after_the_start_is_caught(self):
        before = parse_estimate("2d", "jira", T("2025-03-01 10:00 +03:00"))
        after = parse_estimate("5d", "jira", T("2025-03-04 10:00 +03:00"))
        a, o = self.outcome([before, after])
        self.assertEqual(o.status, "counted")
        self.assertIs(o.estimate, before)  # the edit does not count...
        found = doctor.check(a)
        self.assertEqual(found.edited, [(o, after)])  # ...but it is reported
        self.assertEqual(found.problems, 1)
        text = doctor.render(a, found, Lang("en"), Style(False))
        self.assertIn("estimates edited after the work began", text)
        self.assertIn("2d → 5d", text)

    def test_an_edit_before_the_start_is_just_grooming(self):
        a, _ = self.outcome([parse_estimate("1d", "jira", T("2025-03-01 10:00 +03:00")),
                             parse_estimate("2d", "jira", T("2025-03-02 10:00 +03:00"))])
        self.assertEqual(doctor.check(a).problems, 0)

    def test_tracker_and_trailer_disagree(self):
        a, o = self.outcome([parse_estimate("2d", "jira", T("2025-03-01 10:00 +03:00"))],
                            [parse_estimate("3d", "convention", T("2025-03-03 09:00 +03:00"))])
        found = doctor.check(a)
        self.assertEqual([e.text for _, e in found.conflicts], ["3d"])

    def test_conflicting_trailers_in_one_branch(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 2d"),
                                     ("2025-03-04 09:00 +03:00", "hm\n\nEstimate: 4d"))
        a = b.merge("PROJ-1-x", "2025-03-05 18:00 +03:00").analyze()
        found = doctor.check(a)
        self.assertEqual([(o.key, o.estimate.text, e.text) for o, e in found.conflicts], [("PROJ-1", "2d", "4d")])
        self.assertEqual(a.find("PROJ-1").status, "counted")  # the first one written counts

    def test_a_broken_ledger_chain(self):
        b = RepoBuilder(self)
        for key in ("PROJ-8", "PROJ-9"):
            ledger.append(b.path, key, "1d", ME[1], T("2025-03-01 10:00 +03:00"))
        path = b.path / ledger.PATH
        path.write_text(path.read_text(encoding="utf-8").replace("PROJ-8", "PROJ-7"), encoding="utf-8")
        found = doctor.check(b.analyze())
        self.assertTrue(found.ledger_present)
        self.assertEqual([n for n, _ in found.chain], [2])

    def test_late_estimates_are_listed_but_are_not_problems(self):
        a, o = self.outcome([parse_estimate("2d", "jira", T("2025-03-03 12:00 +03:00"))])
        found = doctor.check(a)
        self.assertEqual((found.late, found.problems), ([o], 0))

    def test_a_clean_history(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 2d"))
        a = b.merge("PROJ-1-x", "2025-03-05 18:00 +03:00").analyze()
        found = doctor.check(a)
        self.assertEqual(found.problems, 0)
        self.assertFalse(found.ledger_present)
        text = doctor.render(a, found, Lang("en"), Style(False))
        self.assertIn("nothing to report", text)
        self.assertTrue(text.startswith("  (o,O)   fibo · "))  # through the monocle


if __name__ == "__main__":
    unittest.main()
