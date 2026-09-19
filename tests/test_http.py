import unittest

from tests.helpers import tempdir
from fibo.sources.http import Cache, Client, SourceError


class Fake:
    def __init__(self, value=None):
        self.value = value if value is not None else {"ok": True}
        self.calls: list[tuple] = []

    def __call__(self, url, body, headers):
        self.calls.append((url, body, dict(headers)))
        return self.value


class ReadOnly(unittest.TestCase):
    def test_rest_is_a_plain_get(self):
        fake = Fake()
        Client("x", {}, None, fake).get("https://x/api", {"a": 1, "skip": None})
        url, body, _ = fake.calls[0]
        self.assertEqual(url, "https://x/api?a=1")
        self.assertIsNone(body)

    def test_a_mutation_never_leaves_the_process(self):
        fake = Fake()
        client = Client("x", {}, None, fake)
        for query in ("mutation { issueDelete(id: 1) { success } }",
                      "  mutation Delete($id: String!) { issueDelete(id: $id) { success } }",
                      "query { viewer { id } } mutation { x }"):
            with self.subTest(query=query), self.assertRaises(SourceError):
                client.graphql("https://x/graphql", query)
        self.assertEqual(fake.calls, [])

    def test_a_field_named_like_it_is_fine(self):
        fake = Fake({"data": {"mutationLog": []}})
        self.assertEqual(Client("x", {}, None, fake).graphql("https://x/graphql", "query { mutationLog { id } }"),
                         {"mutationLog": []})

    def test_graphql_errors_are_raised(self):
        with self.assertRaises(SourceError) as ctx:
            Client("x", {}, None, Fake({"errors": [{"message": "bad token"}]})).graphql("https://x/g", "query { a }")
        self.assertIn("bad token", str(ctx.exception))


class Caching(unittest.TestCase):
    def setUp(self):
        self.dir = tempdir(self) / ".fibo" / "cache"

    def test_second_call_comes_from_the_cache(self):
        fake = Fake()
        client = Client("x", {"Authorization": "Bearer SECRET"}, Cache(self.dir, 3600), fake)
        self.assertEqual(client.get("https://x/a"), client.get("https://x/a"))
        self.assertEqual(len(fake.calls), 1)

    def test_the_cache_holds_responses_not_secrets(self):
        Client("x", {"Authorization": "Bearer SECRET"}, Cache(self.dir, 3600), Fake()).get("https://x/a")
        files = list(self.dir.iterdir())
        self.assertTrue(files)
        self.assertTrue(all("SECRET" not in f.read_text(encoding="utf-8") for f in files))
        self.assertEqual((self.dir.parent / ".gitignore").read_text(encoding="utf-8"), "cache/\n")

    def test_expired_entries_are_fetched_again(self):
        fake = Fake()
        client = Client("x", {}, Cache(self.dir, ttl=-1), fake)
        client.get("https://x/a")
        client.get("https://x/a")
        self.assertEqual(len(fake.calls), 2)

    def test_refresh_ignores_the_cache(self):
        Client("x", {}, Cache(self.dir, 3600), Fake()).get("https://x/a")
        fake = Fake()
        Client("x", {}, Cache(self.dir, 3600, refresh=True), fake).get("https://x/a")
        self.assertEqual(len(fake.calls), 1)

    def test_offline_uses_only_the_cache(self):
        Client("x", {}, Cache(self.dir, 3600), Fake({"v": 1})).get("https://x/a")
        fake = Fake()
        offline = Client("x", {}, Cache(self.dir, ttl=-1, offline=True), fake)
        self.assertEqual(offline.get("https://x/a"), {"v": 1})
        with self.assertRaises(SourceError):
            offline.get("https://x/never-fetched")
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
