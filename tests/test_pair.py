import unittest

from tests.helpers import ME, OTHER, RepoBuilder, T
from fibo.clock import Calendar, Zone
from fibo.model import Task, parse_estimate
from fibo.pair import Keys, branch_title, choose, collect, evaluate, parse_merge, work_for

CAL = Calendar()


class BranchKeys(unittest.TestCase):
    def test_naming_conventions(self):
        cases = {
            "PROJ-412-fix-auth": ["PROJ-412"], "feature/PROJ-412-fix-auth": ["PROJ-412"],
            "bugfix/PROJ-412": ["PROJ-412"], "PROJ-412": ["PROJ-412"], "users/me/ABC-7-x": ["ABC-7"],
            "PROJ-0412-x": ["PROJ-412"], "fix-login": [], "release/1.2": [], "feature/utf-8-support": [],
            "UTF-8": [], "ISO-8601-dates": [],
        }
        for branch, want in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(Keys().in_branch(branch), want)

    def test_lowercase_needs_a_known_key(self):
        self.assertEqual(Keys().in_branch("me/proj-412-fix"), [])
        self.assertEqual(Keys({"PROJ-412"}).in_branch("me/proj-412-fix"), ["PROJ-412"])
        self.assertEqual(Keys({"ENG-123"}).in_branch("eng_123_fix"), ["ENG-123"])

    def test_issue_numbers_github_style(self):
        keys = Keys({"#412"}, numeric=True)
        self.assertEqual(keys.in_branch("412-fix-login"), ["#412"])
        self.assertEqual(keys.in_branch("issue-412"), ["#412"])
        self.assertEqual(keys.in_branch("413-other"), [])
        self.assertEqual(Keys({"#412"}).in_branch("412-fix-login"), [])


class TextKeys(unittest.TestCase):
    def test_uppercase_keys(self):
        self.assertEqual(Keys().in_text("PROJ-412: fix auth"), ["PROJ-412"])
        self.assertEqual(Keys().in_text("ABC-1 and ABC-2"), ["ABC-1", "ABC-2"])

    def test_lookalikes_are_not_keys(self):
        self.assertEqual(Keys().in_text("switch to UTF-8, ISO-8601 and SHA-256 per RFC-2119"), [])

    def test_known_keys_in_lowercase(self):
        self.assertEqual(Keys({"ENG-5"}).in_text("fix eng-5 again"), ["ENG-5"])

    def test_closing_keywords_for_issue_numbers(self):
        self.assertEqual(Keys({"#45"}, numeric=True).in_text("closes #45"), ["#45"])

    def test_squash_suffix_is_a_pull_request_not_an_issue(self):
        self.assertEqual(Keys({"#45"}, numeric=True).in_text("Fix login (#45)"), [])


class MergeSubjects(unittest.TestCase):
    def test_every_host(self):
        cases = [
            ("Merge pull request #12 from me/PROJ-1-fix", ("PROJ-1-fix", "12")),
            ("Merge pull request #12 from me/feature/PROJ-1", ("feature/PROJ-1", "12")),
            ("Merge branch 'PROJ-1-fix' into 'main'", ("PROJ-1-fix", None)),
            ("Merge branch 'PROJ-1-fix'", ("PROJ-1-fix", None)),
            ("Merge remote-tracking branch 'origin/PROJ-1-fix'", ("PROJ-1-fix", None)),
            ("Merged in PROJ-1-fix (pull request #7)", ("PROJ-1-fix", "7")),
            ("Merged PR 88: fix things", (None, "88")),
            ("fix things", (None, None)),
        ]
        for subject, want in cases:
            with self.subTest(subject=subject):
                self.assertEqual(parse_merge(subject), want)

    def test_branch_title(self):
        self.assertEqual(branch_title("feature/PROJ-412-fix-auth-refresh"), "fix auth refresh")
        self.assertEqual(branch_title(None), "")


class History(unittest.TestCase):
    def work(self, b: RepoBuilder, key: str, known=()):
        units = collect(b.finish(), Keys(known))
        self.assertIn(key, units)
        return units, work_for(key, units[key], {ME[1]}, CAL, Zone())

    def test_a_merged_branch_is_one_task(self):
        b = RepoBuilder(self).branch("PROJ-1-fix-auth", ("2025-03-03 10:00 +03:00", "PROJ-1 fix auth"),
                                     ("2025-03-04 12:00 +03:00", "tests"))
        b.merge("PROJ-1-fix-auth", "2025-03-05 15:00 +03:00")
        units, w = self.work(b, "PROJ-1")
        self.assertEqual(list(units), ["PROJ-1"])
        self.assertEqual((w.start, w.end), (T("2025-03-03 10:00 +03:00"), T("2025-03-05 15:00 +03:00")))
        self.assertEqual((len(w.commits), w.mine, w.branch, w.pr), (2, 2, "PROJ-1-fix-auth", "1"))

    def test_key_only_in_commit_messages(self):
        b = RepoBuilder(self).branch("fix-login", ("2025-03-03 10:00 +03:00", "PROJ-2 fix login"),
                                     ("2025-03-03 12:00 +03:00", "more"))
        b.merge("fix-login", "2025-03-04 10:00 +03:00")
        _, w = self.work(b, "PROJ-2")
        self.assertEqual(len(w.commits), 2)

    def test_no_key_at_all_uses_the_branch_name(self):
        b = RepoBuilder(self).branch("cleanup-imports", ("2025-03-03 10:00 +03:00", "tidy"))
        b.merge("cleanup-imports", "2025-03-03 12:00 +03:00")
        self.work(b, "cleanup-imports")

    def test_squash_on_main_cannot_say_when_work_began(self):
        b = RepoBuilder(self).direct("2025-03-05 15:00 +03:00", "PROJ-3 fix typo (#9)")
        units, w = self.work(b, "PROJ-3")
        self.assertTrue(units["PROJ-3"][0].squashed)
        self.assertIsNone(w.start)
        self.assertEqual(w.end, T("2025-03-05 15:00 +03:00"))
        self.assertEqual(w.pr, "9")

    def test_rebased_commits_keep_their_author_dates(self):
        b = RepoBuilder(self)
        b.direct("2025-03-03 10:00 +03:00", "PROJ-4 part one", landed="2025-03-05 15:00 +03:00")
        b.direct("2025-03-04 10:00 +03:00", "PROJ-4 part two", landed="2025-03-05 15:00 +03:00")
        units, w = self.work(b, "PROJ-4")
        self.assertEqual(len(units["PROJ-4"]), 1)
        self.assertEqual((w.start, w.end), (T("2025-03-03 10:00 +03:00"), T("2025-03-05 15:00 +03:00")))

    def test_an_unmerged_branch_is_unfinished_work(self):
        b = RepoBuilder(self).branch("PROJ-5-wip", ("2025-03-03 10:00 +03:00", "PROJ-5 start"))
        units, w = self.work(b, "PROJ-5")
        self.assertEqual(units["PROJ-5"][0].how, "branch")
        self.assertIsNone(w.end)

    def test_the_branch_left_behind_by_a_squash_gives_the_start(self):
        b = RepoBuilder(self).branch("PROJ-6-x", ("2025-03-03 10:00 +03:00", "PROJ-6 x"),
                                     ("2025-03-04 10:00 +03:00", "more"))
        b.direct("2025-03-06 12:00 +03:00", "PROJ-6 x (#3)")
        _, w = self.work(b, "PROJ-6")
        self.assertEqual((w.start, w.end), (T("2025-03-03 10:00 +03:00"), T("2025-03-06 12:00 +03:00")))

    def test_a_follow_up_months_later_is_new_work(self):
        b = RepoBuilder(self).branch("PROJ-7-a", ("2025-03-03 10:00 +03:00", "PROJ-7 a"))
        b.merge("PROJ-7-a", "2025-03-05 15:00 +03:00")
        b.branch("PROJ-7-again", ("2025-06-02 10:00 +03:00", "PROJ-7 again")).merge("PROJ-7-again", "2025-06-03 15:00 +03:00")
        _, w = self.work(b, "PROJ-7")
        self.assertEqual(w.end, T("2025-03-05 15:00 +03:00"))
        self.assertEqual(len(w.units), 1)

    def test_a_follow_up_next_day_is_the_same_task(self):
        b = RepoBuilder(self).branch("PROJ-8-a", ("2025-03-03 10:00 +03:00", "PROJ-8 a"))
        b.merge("PROJ-8-a", "2025-03-05 15:00 +03:00")
        b.branch("PROJ-8-b", ("2025-03-06 10:00 +03:00", "PROJ-8 b")).merge("PROJ-8-b", "2025-03-06 16:00 +03:00")
        _, w = self.work(b, "PROJ-8")
        self.assertEqual(w.end, T("2025-03-06 16:00 +03:00"))
        self.assertEqual(len(w.commits), 2)

    def test_mostly_someone_elses_branch_is_not_yours(self):
        b = RepoBuilder(self).branch("PROJ-9-x", ("2025-03-03 10:00 +03:00", "PROJ-9 x", OTHER),
                                     ("2025-03-03 11:00 +03:00", "a", OTHER), ("2025-03-03 12:00 +03:00", "b", OTHER),
                                     ("2025-03-03 13:00 +03:00", "review fix"))
        b.merge("PROJ-9-x", "2025-03-04 10:00 +03:00")
        _, w = self.work(b, "PROJ-9")
        self.assertEqual(w.mine, 1)
        self.assertFalse(w.is_mine)

    def test_merging_main_into_a_branch_does_not_leak_other_work(self):
        b = RepoBuilder(self).branch("PROJ-10-a", ("2025-03-03 10:00 +03:00", "PROJ-10 a"))
        b.branch("PROJ-11-b", ("2025-03-03 11:00 +03:00", "PROJ-11 b"))
        b.merge("PROJ-10-a", "2025-03-04 10:00 +03:00")
        b.sync("PROJ-11-b", "2025-03-04 11:00 +03:00").branch("PROJ-11-b", ("2025-03-04 12:00 +03:00", "more"))
        b.merge("PROJ-11-b", "2025-03-05 10:00 +03:00")
        units, w = self.work(b, "PROJ-11")
        self.assertEqual([c.subject for c in w.commits], ["PROJ-11 b", "more"])
        self.assertEqual(len(units["PROJ-10"][0].commits), 1)


class Choose(unittest.TestCase):
    start = T("2025-03-03 10:00 +03:00")

    def test_the_value_standing_at_the_start_counts(self):
        e1 = parse_estimate("1d", "jira", T("2025-03-01 10:00 +03:00"))
        e2 = parse_estimate("2d", "jira", T("2025-03-02 10:00 +03:00"))
        e3 = parse_estimate("5d", "jira", T("2025-03-10 10:00 +03:00"))
        chosen, later, conflicts = choose([e3, e1, e2], self.start)
        self.assertEqual(chosen.text, "2d")
        self.assertEqual(later, [e3])
        self.assertEqual(conflicts, [])

    def test_when_everything_is_late_the_first_written_is_kept(self):
        late = parse_estimate("2d", "jira", T("2025-03-04 10:00 +03:00"))
        self.assertIs(choose([late], self.start)[0], late)

    def test_tracker_outranks_text_and_ledger(self):
        at = T("2025-03-01 10:00 +03:00")
        conv, jira, led = (parse_estimate("3d", "convention", at), parse_estimate("2d", "jira", at),
                           parse_estimate("1d", "ledger", at))
        chosen, _, conflicts = choose([conv, led, jira], self.start)
        self.assertIs(chosen, jira)
        self.assertEqual(conflicts, [conv, led])

    def test_agreeing_sources_are_not_conflicts(self):
        at = T("2025-03-01 10:00 +03:00")
        chosen, _, conflicts = choose([parse_estimate("2d", "jira", at), parse_estimate("16h", "convention", at)],
                                      self.start)
        self.assertEqual(chosen.source, "jira")
        self.assertEqual(conflicts, [])

    def test_nothing(self):
        self.assertEqual(choose([], self.start), (None, [], []))


class Statuses(unittest.TestCase):
    def outcome(self, b: RepoBuilder, key: str, **kw):
        a = b.analyze(**kw)
        o = a.find(key)
        self.assertIsNotNone(o, f"{key} not found in {[x.key for x in a.outcomes]}")
        return a, o

    def test_counted_with_the_right_numbers(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        _, o = self.outcome(b, "PROJ-1")
        self.assertEqual(o.status, "counted")
        self.assertAlmostEqual(o.span_h, 16)
        self.assertAlmostEqual(o.ratio(), 2.0)
        self.assertAlmostEqual(o.cal_h, 33)
        self.assertAlmostEqual(o.ratio("calendar"), 33 / 24)

    def test_an_estimate_written_after_the_first_commit(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x"),
                                     ("2025-03-03 15:00 +03:00", "oh right\n\nEstimate: 1d"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        self.assertEqual(self.outcome(b, "PROJ-1")[1].status, "after_start")

    def test_not_a_duration(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: soon"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        self.assertEqual(self.outcome(b, "PROJ-1")[1].status, "not_duration")

    def test_points_are_refused_without_a_rate(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 3 points"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        a, o = self.outcome(b, "PROJ-1")
        self.assertEqual(o.status, "points")
        self.assertFalse(a.assumed_points)

    def test_points_with_a_rate_are_counted_and_flagged(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 2 points"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        a, o = self.outcome(b, "PROJ-1", points_as_hours=4)
        self.assertEqual(o.status, "counted")
        self.assertAlmostEqual(o.ratio(), 2.0)
        self.assertTrue(a.assumed_points)

    def test_no_estimate_is_not_guessed(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        a, o = self.outcome(b, "PROJ-1")
        self.assertEqual(o.status, "unestimated")
        self.assertIsNone(o.said_h)
        self.assertEqual((len(a.closed), len(a.estimated), len(a.counted)), (1, 0, 0))

    def test_unfinished_work_is_open(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d"))
        self.assertEqual(self.outcome(b, "PROJ-1")[1].status, "open")

    def test_a_squash_with_nothing_else_has_no_branch(self):
        b = RepoBuilder(self).direct("2025-03-04 18:00 +03:00", "PROJ-1 x (#4)\n\nEstimate: 1h")
        self.assertEqual(self.outcome(b, "PROJ-1")[1].status, "no_branch")

    def test_weekend_work_is_not_zero(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-08 10:00 +03:00", "PROJ-1 x\n\nEstimate: 4h"))
        b.merge("PROJ-1-x", "2025-03-08 14:00 +03:00")
        _, o = self.outcome(b, "PROJ-1")
        self.assertEqual(o.status, "counted")
        self.assertAlmostEqual(o.ratio(), 1.0)

    def test_someone_elses_trailer_is_not_your_estimate(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d", OTHER),
                                     ("2025-03-03 10:00 +03:00", "mine"), ("2025-03-03 11:00 +03:00", "mine too"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        self.assertEqual(self.outcome(b, "PROJ-1")[1].status, "unestimated")

    def test_other_peoples_tasks_are_not_in_the_count_at_all(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d", OTHER))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        a = b.analyze()
        self.assertEqual(a.outcomes, [])


class TrackerTasks(unittest.TestCase):
    def task(self, estimate_at: str = "2025-03-01 10:00 +03:00", **kw) -> Task:
        return Task("PROJ-1", "jira", "x", estimates=[parse_estimate("2d", "jira", T(estimate_at))],
                    closed=T("2025-03-05 18:00 +03:00"), **kw)

    def work(self, who=ME):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x", who))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        units = collect(b.finish(), Keys({"PROJ-1"}))
        return work_for("PROJ-1", units["PROJ-1"], {ME[1]}, CAL, Zone())

    def test_counted_from_the_tracker(self):
        o = evaluate("PROJ-1", self.task(), self.work(), [], CAL, Zone())
        self.assertEqual((o.status, o.start_from, o.end_from), ("counted", "commit", "merge"))

    def test_git_beats_the_tracker_for_the_end(self):
        o = evaluate("PROJ-1", self.task(), self.work(), [], CAL, Zone())
        self.assertEqual(o.end, T("2025-03-04 18:00 +03:00"))

    def test_nobody_elses_commits(self):
        o = evaluate("PROJ-1", self.task(), self.work(OTHER), [], CAL, Zone())
        self.assertEqual(o.status, "not_yours")

    def test_closed_in_the_tracker_but_no_branch(self):
        o = evaluate("PROJ-1", self.task(), None, [], CAL, Zone())
        self.assertEqual(o.status, "no_branch")
        self.assertTrue(o.closed)

    def test_estimate_set_after_the_first_commit(self):
        o = evaluate("PROJ-1", self.task("2025-03-03 12:00 +03:00"), self.work(), [], CAL, Zone())
        self.assertEqual(o.status, "after_start")

    def test_tracker_start_is_used_when_history_cannot_say(self):
        b = RepoBuilder(self).direct("2025-03-04 18:00 +03:00", "PROJ-1 x (#2)")
        units = collect(b.finish(), Keys({"PROJ-1"}))
        work = work_for("PROJ-1", units["PROJ-1"], {ME[1]}, CAL, Zone())
        o = evaluate("PROJ-1", self.task(started=T("2025-03-03 09:00 +03:00")), work, [], CAL, Zone())
        self.assertEqual((o.status, o.start_from), ("counted", "tracker"))


if __name__ == "__main__":
    unittest.main()
