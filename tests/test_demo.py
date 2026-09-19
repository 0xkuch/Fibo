import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import cli, tempdir
from fibo import config, demo, doctor, git
from fibo.analysis import analyze
from fibo.i18n import Lang
from fibo.render import Style


def build(path: Path):
    demo.build(path)
    return analyze(path, config.load(path, git.user_email(path)))


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(tempfile.mkdtemp(prefix="fibo-demo-test-"))
        cls.a = build(cls.path)

    @classmethod
    def tearDownClass(cls):
        demo._remove(cls.path)

    def test_it_has_something_to_say(self):
        self.assertGreaterEqual(len(self.a.counted), 100)
        self.assertTrue(2 < self.a.summary.multiplier < 6)
        self.assertGreaterEqual(len(self.a.kinds), 4)
        self.assertGreaterEqual(len(self.a.drift), 2)

    def test_every_refusal_shows_up(self):
        self.assertTrue({"after_start", "no_branch", "not_duration", "points"} <= set(self.a.excluded))

    def test_it_is_reproducible(self):
        again = build(tempdir(self))
        self.assertEqual(again.summary, self.a.summary)
        self.assertEqual((len(again.outcomes), len(again.counted)), (len(self.a.outcomes), len(self.a.counted)))

    def test_the_teammate_is_invisible(self):
        self.assertEqual(self.a.me, [demo.ME[1]])
        self.assertTrue(all(o.work is None or o.work.mine > 0 for o in self.a.outcomes))
        sam = [c for c in git.log(self.path).values() if c.email == demo.SAM[1]]
        self.assertTrue(sam)  # the teammate is in the history, just not in the numbers

    def test_the_ledger_is_intact_and_the_doctor_finds_the_planted_conflicts(self):
        found = doctor.check(self.a)
        self.assertEqual(found.chain, [])
        self.assertTrue(found.conflicts)

    def test_it_needs_no_config_and_no_global_identity(self):
        self.assertTrue((self.path / ".fibo.json").is_file())
        self.assertEqual(git.user_email(self.path), demo.ME[1])


class Run(unittest.TestCase):
    def args(self, path: Path):
        return argparse.Namespace(args=[str(path)], calendar=False, points_as_hours=None, verbose=False)

    def test_it_will_not_overwrite_a_real_directory(self):
        path = tempdir(self)
        (path / "precious.txt").write_text("mine", encoding="utf-8")
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(demo.run(self.args(path), Lang("en"), Style(False)), 2)
        self.assertTrue((path / "precious.txt").exists())

    def test_the_command_prints_the_report_and_says_it_is_a_demo(self):
        path = tempdir(self) / "demo"
        code, out, _ = cli("demo", str(path))
        self.assertEqual(code, 0)
        self.assertIn("your multiplier", out)
        self.assertIn("a demo is a demo", out)
        code, out, _ = cli("demo", str(path))  # a second run replaces its own demo
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
