"""Where estimates come from, in order of trust: the tracker, the text, the ledger.

Trackers are only asked when `.fibo.json` names them. With no config,
nothing leaves the machine.
"""

from __future__ import annotations

import importlib

from ..config import TRACKERS, Config
from ..model import Task
from .http import Cache, SourceError


def fetch(cfg: Config, *, offline: bool = False, refresh: bool = False) -> tuple[list[Task], list[str]]:
    tasks: list[Task] = []
    warnings: list[str] = []
    cache = Cache(cfg.root / ".fibo" / "cache", cfg.cache_ttl, refresh=refresh, offline=offline)
    for name in TRACKERS:
        section = cfg.trackers.get(name)
        if section is None:
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        try:
            tasks.extend(module.fetch(section, cfg, cache))
        except SourceError as exc:
            warnings.append(str(exc))
    return tasks, warnings


__all__ = ["Cache", "SourceError", "fetch"]
