"""Reading history. One `git log` for the whole graph; everything else happens in memory."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .model import parse_time


class GitError(RuntimeError):
    pass


_FORMAT = "%x1e%H%x1f%P%x1f%aN%x1f%aE%x1f%aI%x1f%cI%x1f%s%x1f%b"


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author: str
    email: str  # lowercased, .mailmap applied
    at: datetime  # author date: when it was written
    landed: datetime  # committer date: when it took its final place
    subject: str
    body: str = ""

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def message(self) -> str:
        return f"{self.subject}\n\n{self.body}".strip()

    @property
    def short(self) -> str:
        return self.sha[:7]


def run(args: list[str], cwd: Path | str, stdin: str | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", GIT_OPTIONAL_LOCKS="0")
    cmd = ["git", "-c", "core.quotepath=off", "-c", "log.showSignature=false",
           "-c", "i18n.logOutputEncoding=UTF-8", *args]
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), input=stdin.encode() if stdin is not None else None,
                              capture_output=True, env=env)
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH") from None
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return proc.stdout.decode("utf-8", "replace")


def toplevel(path: Path | str) -> Path:
    return Path(run(["rev-parse", "--show-toplevel"], path).strip())


def user_email(root: Path) -> str | None:
    try:
        return run(["config", "user.email"], root).strip().lower() or None
    except GitError:
        return None


def remote_url(root: Path, name: str = "origin") -> str | None:
    try:
        return run(["remote", "get-url", name], root).strip() or None
    except GitError:
        return None


def remotes(root: Path) -> list[str]:
    try:
        return run(["remote"], root).split()
    except GitError:
        return []


def refs(root: Path) -> dict[str, str]:
    """Branch name -> sha, local and remote-tracking, symbolic refs skipped."""
    out = run(["for-each-ref", "--format=%(refname)%1f%(objectname)%1f%(symref)",
               "refs/heads", "refs/remotes"], root)
    found: dict[str, str] = {}
    for line in out.splitlines():
        name, sha, symref = (line.split("\x1f") + ["", ""])[:3]
        if symref:
            continue
        for prefix in ("refs/heads/", "refs/remotes/"):
            if name.startswith(prefix):
                found[name[len(prefix):]] = sha
    return found


def main_branch(root: Path, all_refs: dict[str, str], configured: str | None = None) -> str | None:
    if configured:
        for name in (configured, f"origin/{configured}"):
            if name in all_refs:
                return name
        raise GitError(f"main branch '{configured}' not found")
    try:
        head = run(["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], root).strip()
    except GitError:
        head = ""
    if head in all_refs:
        return head
    for name in ("main", "master", "trunk", "develop"):
        for candidate in (name, f"origin/{name}"):
            if candidate in all_refs:
                return candidate
    return None


def log(root: Path) -> dict[str, Commit]:
    """Every commit reachable from a branch or tag, keyed by sha."""
    try:
        out = run(["log", "--branches", "--remotes", "--tags", f"--format={_FORMAT}"], root)
    except GitError as exc:
        if "does not have any commits" in str(exc) or "bad default revision" in str(exc):
            return {}
        raise
    commits: dict[str, Commit] = {}
    for record in out.split("\x1e"):
        fields = record.split("\x1f", 7)
        if len(fields) < 8:
            continue
        sha, parents, name, email, at, landed, subject, body = fields
        a, c = parse_time(at.strip()), parse_time(landed.strip())
        if a is None or c is None:
            continue
        commits[sha.strip()] = Commit(sha.strip(), tuple(parents.split()), name.strip(),
                                      email.strip().lower(), a, c, subject.strip(), body.strip())
    return commits


def mainline(commits: dict[str, Commit], tip: str | None) -> list[str]:
    """First-parent chain of the main branch, oldest first."""
    chain: list[str] = []
    seen: set[str] = set()
    sha = tip
    while sha and sha in commits and sha not in seen:
        seen.add(sha)
        chain.append(sha)
        parents = commits[sha].parents
        sha = parents[0] if parents else None
    chain.reverse()
    return chain


def numstat(root: Path, shas: list[str]) -> dict[str, list[tuple[str, int]]]:
    """sha -> [(path, lines changed)] for exactly these commits, in one call."""
    if not shas:
        return {}
    out = run(["log", "--no-walk=unsorted", "--stdin", "--numstat", "--no-renames", "--format=%x1e%H"],
              root, stdin="\n".join(shas) + "\n")
    result: dict[str, list[tuple[str, int]]] = {}
    for record in out.split("\x1e"):
        lines = record.strip().splitlines()
        if not lines:
            continue
        files = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) == 3:
                added, deleted, path = parts
                files.append((path, (int(added) if added.isdigit() else 1) + (int(deleted) if deleted.isdigit() else 1)))
        result[lines[0].strip()] = files
    return result


@dataclass
class Repo:
    root: Path
    commits: dict[str, Commit]
    refs: dict[str, str]
    main: str | None
    tip: str | None


def open_repo(path: Path | str, main: str | None = None) -> Repo:
    root = toplevel(path)
    all_refs = refs(root)
    name = main_branch(root, all_refs, main)
    return Repo(root, log(root), all_refs, name, all_refs.get(name) if name else None)
