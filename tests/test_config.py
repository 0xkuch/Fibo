import builtins
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import tempdir
from fibo.config import ConfigError, load, parse


class Config(unittest.TestCase):
    def setUp(self):
        self.root = tempdir(self)

    def write(self, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / ".fibo.json").write_text(text, encoding="utf-8")

    def test_no_file_means_defaults_and_no_network(self):
        cfg = load(self.root, "Me@Example.com")
        self.assertEqual(cfg.emails, ["me@example.com"])
        self.assertEqual(cfg.trackers, {})
        self.assertEqual((cfg.calendar.day_start, cfg.calendar.day_end, cfg.calendar.hours_per_day), (9, 18, 8))
        self.assertIsNone(cfg.path)

    def test_emails_are_merged_and_lowercased(self):
        self.write({"emails": ["Me@Work.com", "me@example.com"]})
        self.assertEqual(load(self.root, "me@example.com").emails, ["me@example.com", "me@work.com"])

    def test_calendar(self):
        self.write({"calendar": {"workdays": ["mon", "tue", "wed", "thu"], "start": "10:00", "end": "19:30",
                                 "hours_per_day": 7}})
        cal = load(self.root).calendar
        self.assertEqual(cal.workdays, frozenset({0, 1, 2, 3}))
        self.assertEqual((cal.day_start, cal.day_end, cal.hours_per_day), (10, 19.5, 7))

    def test_bad_values_are_refused(self):
        bad = [{"emails": ["nobody"]}, {"calendar": {"start": 18, "end": 9}},
               {"calendar": {"hours_per_day": 12}}, {"calendar": {"workdays": ["someday"]}},
               {"points_as_hours": -1}, {"cache_ttl": "soon"}, {"main_branch": 5}, {"jira": "yes"},
               {"in_progress": "doing"}]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ConfigError):
                parse(data, self.root)
        for text in ("{not json", "[1, 2]"):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.write(text)
                load(self.root)

    def test_unknown_keys_are_reported_not_fatal(self):
        self.write({"colour": "blue"})
        self.assertTrue(any("colour" in w for w in load(self.root).warnings))

    def test_a_private_key_in_the_file_is_refused(self):
        self.write({"jira": {"token": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."}})
        with self.assertRaises(ConfigError):
            load(self.root)

    def read_files(self) -> set[str]:
        """Load the config and return the names of every file that was opened."""
        opened: list[str] = []
        real_open, real_read = builtins.open, Path.read_text

        def spy_open(file, *a, **k):
            opened.append(str(file))
            return real_open(file, *a, **k)

        def spy_read(path, *a, **k):
            opened.append(str(path))
            return real_read(path, *a, **k)

        with mock.patch("builtins.open", spy_open), mock.patch.object(Path, "read_text", spy_read):
            self.cfg = load(self.root)
        return {Path(p).name for p in opened}

    def test_only_the_config_file_is_read(self):
        self.write({"emails": ["me@example.com"], "jira": {"url": "https://x.atlassian.net"}})
        self.assertEqual(self.read_files(), {".fibo.json"})

    def test_a_key_file_is_never_opened(self):
        key = self.root / "id_rsa"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n", encoding="utf-8")
        self.write({"jira": {"url": "https://x", "token_file": str(key), "private_key": str(key),
                             "ssh_key": str(key)}})
        self.assertEqual(self.read_files(), {".fibo.json"})
        self.assertEqual(set(self.cfg.trackers["jira"]), {"url"})
        self.assertEqual(sum("ignored" in w for w in self.cfg.warnings), 3)

    def test_tokens_come_from_the_environment(self):
        self.write({"jira": {"url": "https://x", "token_env": "MY_JIRA"}, "github": {}})
        with mock.patch.dict(os.environ, {"MY_JIRA": "s3cret", "GITHUB_TOKEN": "ghp_x"}, clear=False):
            cfg = load(self.root)
            self.assertEqual(cfg.token("jira"), "s3cret")
            self.assertEqual(cfg.token("github"), "ghp_x")

    def test_a_token_in_the_file_works_too(self):
        self.write({"linear": {"token": "lin_api_x"}})
        self.assertEqual(load(self.root).token("linear"), "lin_api_x")

    def test_no_token_is_none(self):
        self.write({"gitlab": {"token_env": "SURELY_NOT_SET_12345"}})
        self.assertIsNone(load(self.root).token("gitlab"))


if __name__ == "__main__":
    unittest.main()
