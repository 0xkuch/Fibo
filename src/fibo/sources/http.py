"""Read-only HTTP with a disposable cache.

GET for REST. POST only for GraphQL, and only for queries: a mutation is
refused before it leaves the process. The cache holds API responses and
nothing else; deleting it loses nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .. import __version__


class SourceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Cache:
    def __init__(self, directory: Path | None, ttl: int = 3600, refresh: bool = False, offline: bool = False):
        self.dir, self.ttl, self.refresh, self.offline = directory, ttl, refresh, offline

    def get(self, key: str) -> Any:
        if self.dir is None or (self.refresh and not self.offline):
            return None
        path = self.dir / f"{key}.json"
        try:
            if not self.offline and time.time() - path.stat().st_mtime > self.ttl:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: Any) -> None:
        if self.dir is None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        ignore = self.dir.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("cache/\n", encoding="utf-8")
        tmp = self.dir / f"{key}.tmp"
        tmp.write_text(json.dumps(value), encoding="utf-8")
        tmp.replace(self.dir / f"{key}.json")


Transport = Callable[[str, "bytes | None", dict], Any]
_MUTATION = re.compile(r"^\s*mutation\b|\bmutation\s*[({]", re.IGNORECASE)


class Client:
    def __init__(self, name: str, headers: dict[str, str], cache: Cache | None = None,
                 transport: Transport | None = None, timeout: float = 30):
        self.name, self.headers, self.cache, self.timeout = name, headers, cache, timeout
        self.transport = transport or self._urlopen

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        return self._request(url, None)

    def graphql(self, url: str, query: str, variables: dict[str, Any] | None = None) -> Any:
        if _MUTATION.search(query):
            raise SourceError(f"{self.name}: refusing to send a mutation — fibo only reads")
        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        data = self._request(url, body)
        if isinstance(data, dict) and data.get("errors"):
            first = data["errors"][0]
            raise SourceError(f"{self.name}: {first.get('message', first) if isinstance(first, dict) else first}")
        return data.get("data") if isinstance(data, dict) else data

    def _request(self, url: str, body: bytes | None) -> Any:
        key = hashlib.sha256(b"\n".join([self.name.encode(), url.encode(), body or b""])).hexdigest()[:40]
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
            if self.cache.offline:
                raise SourceError(f"{self.name}: --offline, and {_short(url)} is not in the cache")
        value = self.transport(url, body, self.headers)
        if self.cache is not None:
            self.cache.put(key, value)
        return value

    def _urlopen(self, url: str, body: bytes | None, headers: dict) -> Any:
        head = {"Accept": "application/json", "User-Agent": f"fibo/{__version__}", **headers}
        if body is not None:
            head["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=head, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            hint = {401: "check the token", 403: "the token cannot read this", 404: "not found",
                    410: "gone", 429: "rate limited, try again later"}.get(exc.code, exc.reason)
            raise SourceError(f"{self.name}: HTTP {exc.code} from {_short(url)} — {hint}", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise SourceError(f"{self.name}: cannot reach {urllib.parse.urlsplit(url).netloc}: {reason}") from None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SourceError(f"{self.name}: {_short(url)} did not answer with JSON") from None


def _short(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.netloc}{parts.path}"
