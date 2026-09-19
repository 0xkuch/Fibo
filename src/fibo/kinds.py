"""What kind of work it was: tracker labels first, then where the diff went, then the title."""

from __future__ import annotations

import re
from collections import Counter

KINDS = ("bugfix", "feature", "refactor", "migration", "tests", "docs", "perf", "infra", "chore", "other")

LABELS = {
    "bug": "bugfix", "bugfix": "bugfix", "bug fix": "bugfix", "defect": "bugfix", "fix": "bugfix",
    "hotfix": "bugfix", "incident": "bugfix", "regression": "bugfix", "type: bug": "bugfix", "kind/bug": "bugfix",
    "story": "feature", "feature": "feature", "new feature": "feature", "enhancement": "feature",
    "improvement": "feature", "epic": "feature", "type: feature": "feature", "kind/feature": "feature",
    "refactor": "refactor", "refactoring": "refactor", "tech debt": "refactor", "tech-debt": "refactor",
    "techdebt": "refactor", "technical debt": "refactor", "cleanup": "refactor", "debt": "refactor",
    "migration": "migration", "migrations": "migration", "data migration": "migration", "db migration": "migration",
    "test": "tests", "tests": "tests", "testing": "tests", "qa": "tests",
    "docs": "docs", "doc": "docs", "documentation": "docs",
    "performance": "perf", "perf": "perf", "optimization": "perf",
    "infra": "infra", "infrastructure": "infra", "devops": "infra", "ci": "infra", "ci/cd": "infra",
    "chore": "chore", "maintenance": "chore", "dependencies": "chore", "deps": "chore",
}

PATHS = {
    "migrations": "migration", "migration": "migration", "migrate": "migration", "alembic": "migration",
    "tests": "tests", "test": "tests", "spec": "tests", "specs": "tests", "__tests__": "tests", "e2e": "tests",
    "docs": "docs", "doc": "docs", "documentation": "docs",
    ".github": "infra", ".circleci": "infra", "infra": "infra", "deploy": "infra", "terraform": "infra",
    "k8s": "infra", "helm": "infra", "ansible": "infra",
}

WORDS = [
    ("migration", re.compile(r"\bmigrat")),
    ("refactor", re.compile(r"\b(refactor\w*|clean ?up|rewrite|restructure|extract|rename|simplify|tech debt)\b")),
    ("bugfix", re.compile(r"\b(fix\w*|bug\w*|hotfix|patch|regression|crash\w*|broken|repair)\b")),
    ("perf", re.compile(r"\b(perf|performance|optimi[sz]\w*|speed ?up|faster|latency|slow)\b")),
    ("tests", re.compile(r"\b(tests?|testing|coverage|flaky)\b")),
    ("docs", re.compile(r"\b(docs?|readme|documentation|changelog)\b")),
    ("infra", re.compile(r"\b(ci|pipeline|docker\w*|deploy\w*|terraform|k8s|helm|infra\w*)\b")),
    ("chore", re.compile(r"\b(chore|bump|upgrade|deps|dependenc\w*|lint\w*)\b")),
    ("feature", re.compile(r"\b(feat\w*|add\w*|implement\w*|introduc\w*|support|new|build|create|enable)\b")),
]


def from_labels(labels: tuple[str, ...] | list[str], issue_type: str = "") -> str | None:
    for raw in (*labels, issue_type):
        kind = LABELS.get(" ".join(str(raw).lower().split()))
        if kind:
            return kind
    return None


def from_paths(files: list[tuple[str, int]]) -> str | None:
    """The kind whose directories took more than half of the changed lines."""
    weights: Counter = Counter()
    total = 0
    for path, lines in files:
        total += lines
        for part in path.lower().split("/")[:-1]:
            if part in PATHS:
                weights[PATHS[part]] += lines
                break
    if not total or not weights:
        return None
    kind, weight = weights.most_common(1)[0]
    return kind if weight * 2 > total else None


def from_title(text: str) -> str | None:
    t = " ".join(re.split(r"[-_/\s]+", text.lower()))
    for kind, rx in WORDS:
        if rx.search(t):
            return kind
    return None


def classify(labels: tuple[str, ...] | list[str] = (), issue_type: str = "",
             files: list[tuple[str, int]] | None = None, title: str = "") -> str:
    return from_labels(labels, issue_type) or from_paths(files or []) or from_title(title) or "other"
