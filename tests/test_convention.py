import unittest

from tests.helpers import T
from fibo.git import Commit
from fibo.sources.convention import find, from_commits, from_text


def commit(sha: str, email: str, when: str, message: str) -> Commit:
    subject, _, body = message.partition("\n\n")
    return Commit(sha * 40, ("p" * 40,), "x", email, T(when), T(when), subject, body)


class Find(unittest.TestCase):
    def test_every_form(self):
        cases = {
            "PROJ-1 fix\n\nEstimate: 2d\n": ["2d"], "Est: 4h": ["4h"], "/estimate 1w": ["1w"],
            "**Estimate:** 2d": ["2d"], "**Estimate**: 2d": ["2d"], "- est: 3d": ["3d"], "> Estimate: 1d": ["1d"],
            "estimate:2d": ["2d"],
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(find(text), want)

    def test_things_that_only_look_like_it(self):
        for text in ("Estimated: 2d", "the estimate is 2d", "Estimates: 2d", "reestimate: 2d", ""):
            with self.subTest(text=text):
                self.assertEqual(find(text), [])

    def test_order_is_kept(self):
        self.assertEqual(find("Estimate: 2d\nsomething\nEst: 3d"), ["2d", "3d"])

    def test_vague_values_are_kept_so_they_can_be_refused(self):
        self.assertEqual(find("Estimate: end of sprint"), ["end of sprint"])


class FromCommits(unittest.TestCase):
    me = {"me@example.com"}

    def test_oldest_first_whatever_the_order_given(self):
        newer = commit("b", "me@example.com", "2025-03-04 10:00 +03:00", "more\n\nEstimate: 3d")
        older = commit("a", "me@example.com", "2025-03-03 10:00 +03:00", "start\n\nEstimate: 2d")
        self.assertEqual([e.text for e in from_commits([newer, older], self.me)], ["2d", "3d"])

    def test_someone_elses_trailer_is_theirs(self):
        theirs = commit("a", "other@example.com", "2025-03-03 10:00 +03:00", "x\n\nEstimate: 2d")
        self.assertEqual(from_commits([theirs], self.me), [])

    def test_carries_where_and_when(self):
        e = from_commits([commit("c", "me@example.com", "2025-03-03 10:00 +03:00", "x\n\nEst: 4h")], self.me)[0]
        self.assertEqual((e.source, e.where, e.at, e.work_hours()), ("convention", "ccccccc",
                                                                     T("2025-03-03 10:00 +03:00"), 4))

    def test_pull_request_bodies(self):
        e = from_text("## Plan\n\nEstimate: 2d\n", T("2025-03-03 10:00 +03:00"), "https://x/pr/1", "github")[0]
        self.assertEqual((e.source, e.text, e.where), ("github", "2d", "https://x/pr/1"))


if __name__ == "__main__":
    unittest.main()
