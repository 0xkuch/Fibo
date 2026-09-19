"""The whole pass: trackers and history meeting on the same task."""

import json
import unittest
from unittest import mock

from tests.helpers import RepoBuilder, T, cli
from fibo import kinds
from fibo.model import Task, parse_estimate


def trackers(tasks=(), warnings=()):
    return mock.patch("fibo.analysis.fetch_trackers", return_value=(list(tasks), list(warnings)))


def ticket(key: str, said: str | None = "1d", closed: str | None = "2025-03-05 10:00 +03:00", **kw) -> Task:
    estimates = [parse_estimate(said, "jira", T("2025-03-01 10:00 +03:00"))] if said else []
    return Task(key, "jira", key.lower(), estimates=estimates, closed=T(closed) if closed else None, **kw)


JIRA = {"jira": {"url": "https://acme.atlassian.net"}}


class Linking(unittest.TestCase):
    def test_a_pull_request_body_lands_on_its_branch(self):
        b = RepoBuilder(self).branch("export", ("2025-03-03 09:00 +03:00", "add export"))
        b.merge("export", "2025-03-04 18:00 +03:00", subject="Merge pull request #7 from me/export")
        pr = Task("PR #7", "github", "add export", pr="7",
                  estimates=[parse_estimate("1d", "github", T("2025-03-03 08:00 +03:00"))])
        with trackers([pr]):
            a = b.analyze({"github": {"repo": "me/app"}})
        o = a.find("export")
        self.assertEqual((o.status, o.estimate.source), ("counted", "github"))
        self.assertEqual(len(a.outcomes), 1)

    def test_a_lowercase_branch_finds_its_ticket(self):
        b = RepoBuilder(self).branch("me/proj-412-fix-auth", ("2025-03-03 09:00 +03:00", "fix auth"))
        b.merge("me/proj-412-fix-auth", "2025-03-04 18:00 +03:00")
        with trackers([ticket("PROJ-412")]):
            a = b.analyze(JIRA)
        o = a.find("PROJ-412")
        self.assertEqual((o.status, o.start_from, o.end_from), ("counted", "commit", "merge"))
        self.assertEqual(len(a.outcomes), 1)

    def test_the_funnel_counts_what_the_tracker_knows(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00")
        tasks = [ticket("PROJ-1"), ticket("PROJ-2", said=None, closed=None), ticket("PROJ-3"),
                 ticket("PROJ-4", said=None)]
        with trackers(tasks):
            a = b.analyze(JIRA)
        self.assertEqual((len(a.outcomes), len(a.closed), len(a.estimated), len(a.counted)), (4, 3, 2, 1))
        self.assertEqual(dict(a.excluded), {"no_branch": 1})

    def test_a_tracker_failure_does_not_stop_the_report(self):
        b = RepoBuilder(self).branch("PROJ-1-x", ("2025-03-03 09:00 +03:00", "PROJ-1 x\n\nEstimate: 1d"))
        b.merge("PROJ-1-x", "2025-03-04 18:00 +03:00").write(".fibo.json", json.dumps(JIRA)).finish()
        with trackers(warnings=["jira: HTTP 401 from acme.atlassian.net/rest — check the token"]):
            code, out, err = cli("-C", str(b.path))
        self.assertEqual(code, 0)
        self.assertIn("1 counted", out)
        self.assertIn("! jira: HTTP 401", err)


class Kinds(unittest.TestCase):
    def test_labels_then_paths_then_titles(self):
        self.assertEqual(kinds.classify(("Bug",), "", [("migrations/0001.py", 100)], "add export"), "bugfix")
        self.assertEqual(kinds.classify((), "Story", [], "fix it"), "feature")
        self.assertEqual(kinds.classify((), "", [("db/migrations/0001.py", 90), ("app/models.py", 10)], "add export"),
                         "migration")
        self.assertEqual(kinds.classify((), "", [("src/client.py", 10)], "refactor the client"), "refactor")
        self.assertEqual(kinds.classify(), "other")

    def test_a_small_share_of_a_directory_is_not_the_kind(self):
        self.assertIsNone(kinds.from_paths([("tests/test_x.py", 4), ("src/x.py", 20)]))

    def test_a_kind_needs_five_tasks_and_a_breakdown_needs_two_kinds(self):
        b = RepoBuilder(self)
        for i in range(1, 10):
            title = "fix crash" if i <= 5 else "add export"
            b.branch(f"PROJ-{i}-x", (f"2025-03-{i + 2:02d} 09:00 +03:00", f"PROJ-{i} {title}\n\nEstimate: 1h"))
            b.merge(f"PROJ-{i}-x", f"2025-03-{i + 2:02d} 12:00 +03:00")
        a = b.analyze()
        self.assertEqual(len(a.counted), 9)
        self.assertEqual(a.kinds, [])  # features: only four

    def test_five_of_each_shows_the_breakdown(self):
        b = RepoBuilder(self)
        for i in range(1, 11):
            title, hours = ("fix crash", 11) if i <= 5 else ("add export", 13)
            b.branch(f"PROJ-{i}-x", (f"2025-03-{i + 2:02d} 09:00 +03:00", f"PROJ-{i} {title}\n\nEstimate: 1h"))
            b.merge(f"PROJ-{i}-x", f"2025-03-{i + 2:02d} {hours}:00 +03:00")
        a = b.analyze()
        self.assertEqual([k for k, _, _ in a.kinds], ["bugfix", "feature"])
        self.assertEqual([n for _, _, n in a.kinds], [5, 5])


if __name__ == "__main__":
    unittest.main()
