"""Linear: estimates are points, and points are not time.

Without --points-as-hours every Linear estimate is refused, not converted.
With it, the output says the number rests on your assumption.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import Config
from ..model import Estimate, Task, parse_time
from .http import Cache, Client, SourceError, Transport

API = "https://api.linear.app/graphql"
QUERY = """
query Assigned($after: String) {
  viewer {
    assignedIssues(first: 25, after: $after, includeArchived: true) {
      nodes {
        identifier title url createdAt startedAt completedAt branchName estimate
        labels { nodes { name } }
        history(first: 50) { nodes { createdAt fromEstimate toEstimate } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fetch(section: dict, cfg: Config, cache: Cache | None = None, transport: Transport | None = None) -> list[Task]:
    token = cfg.token("linear")
    if not token:
        raise SourceError("linear: no API key — set LINEAR_API_KEY, or name another variable in linear.token_env")
    auth = token if token.startswith("lin_api_") else f"Bearer {token}"
    api = Client("linear", {"Authorization": auth}, cache, transport)
    url = section.get("url", API)
    tasks, after = [], None
    while True:
        issues = api.graphql(url, QUERY, {"after": after})["viewer"]["assignedIssues"]
        tasks += [_task(node) for node in issues["nodes"]]
        if not issues["pageInfo"]["hasNextPage"]:
            return tasks
        after = issues["pageInfo"]["endCursor"]


def _points(value: object, at: datetime | None, where: str) -> Estimate:
    n = float(value)  # type: ignore[arg-type]
    return Estimate(f"{n:g} points", "linear", at, ((n, "pt"),) if n > 0 else (), where)


def _task(node: dict) -> Task:
    created = parse_time(node.get("createdAt"))
    url = node.get("url") or ""
    events: list[tuple[datetime | None, object]] = []
    history = sorted((node.get("history") or {}).get("nodes") or [],
                     key=lambda h: parse_time(h.get("createdAt")) or EPOCH)
    for h in history:
        before, after = h.get("fromEstimate"), h.get("toEstimate")
        if before == after:
            continue
        if not events and before is not None:
            events.append((created, before))
        events.append((parse_time(h.get("createdAt")), after))
    if not events and node.get("estimate") is not None:
        events.append((created, node["estimate"]))
    labels = tuple(l.get("name", "") for l in (node.get("labels") or {}).get("nodes") or [])
    return Task(node["identifier"], "linear", node.get("title") or "", url, labels, "", created,
                parse_time(node.get("startedAt")), parse_time(node.get("completedAt")),
                [_points(v, at, url) for at, v in events if v is not None])
