"""Real repositories for tests, built in milliseconds with one `git fast-import`."""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

from fibo import config, git
from fibo.__main__ import main
from fibo.analysis import Analysis, analyze
from fibo.demo import Stream, _remove
from fibo.model import parse_time

ME = ("Me", "me@example.com")
OTHER = ("Other", "other@example.com")


def T(text: str) -> datetime:
    """"2025-03-03 10:00 +03:00" -> an aware datetime."""
    value = parse_time(text)
    assert value is not None, text
    return value


def tempdir(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp(prefix="fibo-test-"))
    test.addCleanup(_remove, path)
    return path


class RepoBuilder:
    def __init__(self, test: unittest.TestCase, email: str = ME[1]):
        self.path = tempdir(test)
        git.run(["init", "-q"], self.path)
        git.run(["config", "user.email", email], self.path)
        git.run(["config", "user.name", "Me"], self.path)
        self.stream = Stream()
        self.main = self.stream.commit("refs/heads/main", ME, T("2025-01-01 09:00 +03:00"), "initial", [],
                                       {"README": "hello\n"})
        self.tips: dict[str, int] = {}
        self.deleted: list[str] = []
        self.files = 0
        self.prs = 0

    def _file(self) -> dict[str, str]:
        self.files += 1
        return {f"file{self.files}.txt": f"{self.files}\n"}

    def branch(self, name: str, *commits: tuple) -> "RepoBuilder":
        """commits: (when, message) or (when, message, who)."""
        tip = self.tips.get(name, self.main)
        for c in commits:
            who = c[2] if len(c) > 2 else ME
            tip = self.stream.commit(f"refs/heads/{name}", who, T(c[0]), c[1], [tip], self._file())
        self.tips[name] = tip
        return self

    def merge(self, name: str, when: str, subject: str | None = None, keep: bool = False) -> "RepoBuilder":
        self.prs += 1
        message = subject or f"Merge pull request #{self.prs} from me/{name}"
        self.main = self.stream.commit("refs/heads/main", ME, T(when), message, [self.main, self.tips[name]], {})
        if not keep:
            self.deleted.append(name)
        return self

    def sync(self, name: str, when: str) -> "RepoBuilder":
        """Merge main into a branch, the way people keep a long branch fresh."""
        self.tips[name] = self.stream.commit(f"refs/heads/{name}", ME, T(when), f"Merge branch 'main' into {name}",
                                             [self.tips[name], self.main], {})
        return self

    def direct(self, when: str, message: str, who: tuple = ME, landed: str | None = None) -> "RepoBuilder":
        self.main = self.stream.commit("refs/heads/main", who, T(when), message, [self.main], self._file(),
                                       T(landed) if landed else None)
        return self

    def write(self, name: str, text: str) -> "RepoBuilder":
        (self.path / name).parent.mkdir(parents=True, exist_ok=True)
        (self.path / name).write_text(text, encoding="utf-8")
        return self

    def finish(self) -> git.Repo:
        data = bytes(self.stream.out) + b"done\n"
        subprocess.run(["git", "fast-import", "--quiet", "--done"], cwd=self.path, input=data, check=True,
                       capture_output=True)
        if self.deleted:
            git.run(["update-ref", "--stdin"], self.path, stdin="".join(f"delete refs/heads/{b}\n" for b in self.deleted))
        git.run(["symbolic-ref", "HEAD", "refs/heads/main"], self.path)
        return git.open_repo(self.path)

    def analyze(self, data: dict | None = None, **kw) -> Analysis:
        self.finish()
        cfg = config.parse(data or {}, self.path, ME[1])
        return analyze(self.path, cfg, **kw)


def cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--no-color", "--lang", "en", *argv])
    return code, out.getvalue(), err.getvalue()
