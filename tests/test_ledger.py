import hashlib
import unittest

from tests.helpers import T, tempdir
from fibo.sources import ledger


class Ledger(unittest.TestCase):
    def setUp(self):
        self.root = tempdir(self)
        self.path = self.root / ledger.PATH

    def fill(self, n: int = 3) -> list[str]:
        for i in range(1, n + 1):
            ledger.append(self.root, f"PROJ-{i}", f"{i}d", "me@example.com", T(f"2025-03-0{i} 10:00 +03:00"))
        return self.path.read_text(encoding="utf-8").splitlines()

    def rewrite(self, lines: list[str]) -> None:
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_every_line_hashes_the_one_before(self):
        lines = self.fill()
        entries, problems = ledger.read(self.root)
        self.assertEqual(problems, [])
        self.assertEqual(entries[0]["prev"], ledger.GENESIS)
        self.assertEqual(entries[1]["prev"], hashlib.sha256(lines[0].encode()).hexdigest())

    def test_editing_a_line_breaks_the_chain_after_it(self):
        lines = self.fill()
        lines[1] = lines[1].replace('"2d"', '"5d"')
        self.rewrite(lines)
        self.assertEqual([n for n, _ in ledger.read(self.root)[1]], [3])

    def test_deleting_a_line_breaks_the_chain(self):
        lines = self.fill()
        self.rewrite([lines[0], lines[2]])
        self.assertEqual([n for n, _ in ledger.read(self.root)[1]], [2])

    def test_reordering_breaks_the_chain(self):
        lines = self.fill()
        self.rewrite([lines[1], lines[0], lines[2]])
        self.assertTrue(ledger.read(self.root)[1])

    def test_editing_the_last_line_is_caught_by_the_head(self):
        lines = self.fill()
        lines[2] = lines[2].replace('"3d"', '"1d"')
        self.rewrite(lines)
        self.assertEqual([n for n, _ in ledger.read(self.root)[1]], [3])

    def test_appending_by_hand_is_caught_by_the_head(self):
        lines = self.fill(1)
        forged = lines[0].replace("PROJ-1", "PROJ-9")
        self.rewrite(lines + [forged])
        self.assertTrue(ledger.read(self.root)[1])

    def test_a_line_that_is_not_an_entry(self):
        lines = self.fill(1)
        self.rewrite(lines + ["not json"])
        self.assertIn("not a ledger entry", [p for _, p in ledger.read(self.root)[1]])

    def test_estimates_by_key(self):
        ledger.append(self.root, "PROJ-1", "2d", "me@example.com", T("2025-03-01 10:00 +03:00"))
        said = ledger.estimates(self.root)
        e = said["PROJ-1"][0]
        self.assertEqual((e.source, e.text, e.work_hours(), e.where), ("ledger", "2d", 16, "ledger:1"))
        self.assertEqual(e.at, T("2025-03-01 10:00 +03:00"))

    def test_no_ledger_is_empty_not_an_error(self):
        self.assertEqual(ledger.read(self.root), ([], []))
        self.assertEqual(ledger.estimates(self.root), {})


if __name__ == "__main__":
    unittest.main()
