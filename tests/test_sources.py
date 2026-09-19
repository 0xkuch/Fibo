import base64
import json
import os
import re
import unittest
import urllib.parse
from unittest import mock

from tests.helpers import T, tempdir
from fibo import config
from fibo.sources import github, gitlab, jira, linear
from fibo.sources.http import SourceError


class FakeAPI:
    """Routes a request by its URL path; remembers every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict, bytes | None, dict]] = []

    def __call__(self, url, body, headers):
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.path, query, body, dict(headers)))
        for pattern, answer in self.routes.items():
            if re.fullmatch(pattern, parts.path):
                return answer(query, body) if callable(answer) else answer
        raise SourceError(f"no route for {parts.path}", 404)


def cfg(test, data):
    return config.parse(data, tempdir(test))


def seconds(days: float) -> str:
    return str(int(days * 8 * 3600))


def jira_issue(histories, estimate=None, total=None):
    return {"key": "PROJ-1", "fields": {
        "summary": "fix auth", "created": "2025-03-01T10:00:00.000+0300",
        "resolutiondate": "2025-03-06T18:00:00.000+0300", "timeoriginalestimate": estimate,
        "issuetype": {"name": "Bug"}, "labels": ["backend"]},
        "changelog": {"total": total if total is not None else len(histories), "histories": histories}}


EDITS = [
    {"created": "2025-03-01T11:00:00.000+0300",
     "items": [{"field": "timeoriginalestimate", "fieldId": "timeoriginalestimate", "from": None, "to": seconds(2)}]},
    {"created": "2025-03-03T09:30:00.000+0300", "items": [{"field": "status", "toString": "In Progress"}]},
    {"created": "2025-03-05T12:00:00.000+0300",
     "items": [{"field": "timeoriginalestimate", "from": seconds(2), "to": seconds(5)}]},
]
TT = {"workingHoursPerDay": 8, "workingDaysPerWeek": 5}


class Jira(unittest.TestCase):
    def fetch(self, routes, **section):
        c = cfg(self, {"jira": {"url": "https://acme.atlassian.net", "email": "me@acme.com", "token": "t", **section}})
        api = FakeAPI({"/rest/api/3/configuration/timetracking/options": TT, **routes})
        return jira.fetch(c.trackers["jira"], c, None, api), api

    def test_estimate_history_status_and_closing(self):
        tasks, api = self.fetch({"/rest/api/3/search/jql": {"issues": [jira_issue(EDITS, seconds(5))], "isLast": True}})
        t = tasks[0]
        self.assertEqual((t.key, t.title, t.kind_hint, t.labels), ("PROJ-1", "fix auth", "Bug", ("backend",)))
        self.assertEqual([e.text for e in t.estimates], ["2d", "1w"])
        self.assertEqual(t.estimates[0].at, T("2025-03-01 11:00 +03:00"))
        self.assertEqual(t.started, T("2025-03-03 09:30 +03:00"))
        self.assertEqual(t.closed, T("2025-03-06 18:00 +03:00"))
        self.assertEqual(t.url, "https://acme.atlassian.net/browse/PROJ-1")

    def test_asks_only_for_your_issues(self):
        _, api = self.fetch({"/rest/api/3/search/jql": {"issues": [], "isLast": True}}, jql="project = PROJ")
        search = next(q for path, q, _, _ in api.calls if path.endswith("/search/jql"))
        self.assertTrue(search["jql"].startswith("assignee = currentUser() AND (project = PROJ)"))
        self.assertTrue(all(body is None for _, _, body, _ in api.calls))  # nothing but GETs

    def test_basic_auth_for_cloud(self):
        _, api = self.fetch({"/rest/api/3/search/jql": {"issues": [], "isLast": True}})
        expected = "Basic " + base64.b64encode(b"me@acme.com:t").decode()
        self.assertEqual(api.calls[0][3]["Authorization"], expected)

    def test_created_with_an_estimate_already_set(self):
        history = [{"created": "2025-03-02T10:00:00.000+0300",
                    "items": [{"field": "timeoriginalestimate", "from": seconds(1), "to": seconds(2)}]}]
        tasks, _ = self.fetch({"/rest/api/3/search/jql": {"issues": [jira_issue(history, seconds(2))]}})
        self.assertEqual([(e.text, e.at) for e in tasks[0].estimates],
                         [("1d", T("2025-03-01 10:00 +03:00")), ("2d", T("2025-03-02 10:00 +03:00"))])

    def test_no_history_means_it_was_set_at_creation(self):
        tasks, _ = self.fetch({"/rest/api/3/search/jql": {"issues": [jira_issue([], seconds(1))]}})
        self.assertEqual([(e.text, e.at) for e in tasks[0].estimates], [("1d", T("2025-03-01 10:00 +03:00"))])

    def test_server_falls_back_to_the_classic_search(self):
        tasks, _ = self.fetch({"/rest/api/2/search": {"issues": [jira_issue(EDITS)], "total": 1}})
        self.assertEqual(len(tasks), 1)

    def test_a_long_changelog_is_read_in_full(self):
        issue = jira_issue(EDITS[:1], total=3)
        tasks, _ = self.fetch({"/rest/api/3/search/jql": {"issues": [issue]},
                               "/rest/api/3/issue/PROJ-1/changelog": {"values": EDITS, "isLast": True}})
        self.assertEqual(len(tasks[0].estimates), 2)
        self.assertIsNotNone(tasks[0].started)

    def test_a_six_hour_day_in_jira_is_still_a_day(self):
        c = cfg(self, {"jira": {"url": "https://x", "token": "t"}})
        history = [{"created": "2025-03-01T11:00:00.000+0300",
                    "items": [{"field": "timeoriginalestimate", "from": None, "to": str(6 * 3600)}]}]
        api = FakeAPI({"/rest/api/3/configuration/timetracking/options": {"workingHoursPerDay": 6},
                       "/rest/api/3/search/jql": {"issues": [jira_issue(history)]}})
        self.assertEqual(jira.fetch(c.trackers["jira"], c, None, api)[0].estimates[0].text, "1d")

    def test_bearer_token_without_an_email(self):
        c = cfg(self, {"jira": {"url": "https://x", "token": "pat"}})
        api = FakeAPI({"/rest/api/3/search/jql": {"issues": []}})
        jira.fetch(c.trackers["jira"], c, None, api)
        self.assertEqual(api.calls[-1][3]["Authorization"], "Bearer pat")

    def test_no_token_is_a_clear_error(self):
        c = cfg(self, {"jira": {"url": "https://x", "token_env": "SURELY_NOT_SET_12345"}})
        with self.assertRaises(SourceError):
            jira.fetch(c.trackers["jira"], c, None, FakeAPI({}))


LINEAR_NODE = {
    "identifier": "ENG-5", "title": "add export", "url": "https://linear.app/x/issue/ENG-5",
    "createdAt": "2025-03-01T10:00:00.000Z", "startedAt": "2025-03-03T08:00:00.000Z",
    "completedAt": "2025-03-06T15:00:00.000Z", "branchName": "me/eng-5-add-export", "estimate": 3,
    "labels": {"nodes": [{"name": "Feature"}]},
    "history": {"nodes": [
        {"createdAt": "2025-03-04T10:00:00.000Z", "fromEstimate": 2, "toEstimate": 3},
        {"createdAt": "2025-03-01T10:05:00.000Z", "fromEstimate": None, "toEstimate": 2},
        {"createdAt": "2025-03-02T10:00:00.000Z", "fromEstimate": None, "toEstimate": None}]},
}


class Linear(unittest.TestCase):
    def test_points_with_their_history(self):
        c = cfg(self, {"linear": {"token": "lin_api_x"}})
        page = {"data": {"viewer": {"assignedIssues": {"nodes": [LINEAR_NODE],
                                                       "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
        api = FakeAPI({"/graphql": page})
        t = linear.fetch(c.trackers["linear"], c, None, api)[0]
        self.assertEqual([e.points for e in t.estimates], [2, 3])
        self.assertTrue(all(e.is_points and not e.is_duration for e in t.estimates))
        self.assertEqual(t.estimates[0].at, T("2025-03-01 10:05 +00:00"))
        self.assertEqual((t.key, t.labels, t.started, t.closed),
                         ("ENG-5", ("Feature",), T("2025-03-03 08:00 +00:00"), T("2025-03-06 15:00 +00:00")))
        path, _, body, headers = api.calls[0]
        self.assertEqual(headers["Authorization"], "lin_api_x")
        self.assertIn("assignedIssues", json.loads(body)["query"])
        self.assertNotIn("mutation", json.loads(body)["query"])


class GitHub(unittest.TestCase):
    ROUTES = {
        "/user": {"login": "me"},
        "/repos/acme/app/issues": [
            {"number": 5, "title": "fix login", "html_url": "https://github.com/acme/app/issues/5",
             "labels": [{"name": "est: 2d"}, {"name": "bug"}], "created_at": "2025-03-01T08:00:00Z",
             "closed_at": "2025-03-06T15:00:00Z"},
            {"number": 6, "title": "a pull request", "pull_request": {}, "labels": []}],
        "/repos/acme/app/issues/5/events": [
            {"event": "labeled", "label": {"name": "bug"}, "created_at": "2025-03-01T08:00:00Z"},
            {"event": "labeled", "label": {"name": "est: 1d"}, "created_at": "2025-03-01T09:00:00Z"},
            {"event": "unlabeled", "label": {"name": "est: 1d"}, "created_at": "2025-03-04T09:00:00Z"},
            {"event": "labeled", "label": {"name": "est: 2d"}, "created_at": "2025-03-04T09:00:00Z"}],
        "/search/issues": {"items": [{"number": 7, "title": "export", "html_url": "https://github.com/acme/app/pull/7",
                                      "body": "Adds export.\n\nEstimate: 4h", "created_at": "2025-03-02T08:00:00Z"}]},
    }

    def test_labels_pull_requests_and_history(self):
        c = cfg(self, {"github": {"repo": "acme/app", "token": "ghp_x"}})
        api = FakeAPI(self.ROUTES)
        tasks = {t.key: t for t in github.fetch(c.trackers["github"], c, None, api)}
        self.assertEqual(set(tasks), {"#5", "PR #7"})
        issue = tasks["#5"]
        self.assertEqual([(e.text, e.at) for e in issue.estimates],
                         [("1d", T("2025-03-01 09:00 +00:00")), ("2d", T("2025-03-04 09:00 +00:00"))])
        self.assertEqual(issue.labels, ("bug",))
        self.assertEqual((tasks["PR #7"].pr, tasks["PR #7"].estimates[0].text), ("7", "4h"))
        search = next(q for p, q, _, _ in api.calls if p == "/search/issues")
        self.assertEqual(search["q"], "repo:acme/app is:pr author:me")

    def test_repository_comes_from_origin_when_not_configured(self):
        c = cfg(self, {"github": {"token": "ghp_x"}})
        with mock.patch("fibo.git.remote_url", return_value="git@github.com:acme/app.git"):
            self.assertEqual(github.slug(c.trackers["github"], c), "acme/app")


class GitLab(unittest.TestCase):
    def routes(self, notes):
        return {
            "/api/v4/user": {"id": 42},
            "/api/v4/projects/acme%2Fapp/issues": [
                {"iid": 3, "title": "fix", "web_url": "https://gitlab.com/acme/app/-/issues/3",
                 "created_at": "2025-03-01T08:00:00Z", "closed_at": "2025-03-06T15:00:00Z", "labels": ["bug"],
                 "time_stats": {"time_estimate": 57600}, "issue_type": "issue"}],
            "/api/v4/projects/acme%2Fapp/issues/3/notes": notes,
        }

    def fetch(self, notes):
        c = cfg(self, {"gitlab": {"project": "acme/app", "token": "glpat"}})
        api = FakeAPI(self.routes(notes))
        return gitlab.fetch(c.trackers["gitlab"], c, None, api), api

    def test_the_system_note_dates_the_estimate(self):
        tasks, api = self.fetch([
            {"system": True, "body": "changed time estimate to 2d", "created_at": "2025-03-01T10:00:00Z"},
            {"system": False, "body": "changed time estimate to 9d", "created_at": "2025-03-02T10:00:00Z"}])
        t = tasks[0]
        self.assertEqual((t.key, t.labels), ("#3", ("bug",)))
        self.assertEqual([(e.text, e.at) for e in t.estimates], [("2d", T("2025-03-01 10:00 +00:00"))])
        self.assertEqual(api.calls[0][3]["PRIVATE-TOKEN"], "glpat")

    def test_without_notes_it_was_set_at_creation(self):
        tasks, _ = self.fetch([])
        self.assertEqual([(e.text, e.at) for e in tasks[0].estimates], [("2d", T("2025-03-01 08:00 +00:00"))])


class Environment(unittest.TestCase):
    def test_trackers_are_never_asked_without_config(self):
        from fibo.sources import fetch

        with mock.patch.dict(os.environ, {"JIRA_API_TOKEN": "x", "GITHUB_TOKEN": "y", "LINEAR_API_KEY": "z"}):
            self.assertEqual(fetch(config.parse({}, tempdir(self))), ([], []))


if __name__ == "__main__":
    unittest.main()
