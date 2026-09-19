"""The README shows only what exists, and quotes only real numbers."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


class Readme(unittest.TestCase):
    def test_every_picture_in_it_exists(self):
        refs = re.findall(r'src="(docs/[^"]+)"', README)
        self.assertGreaterEqual(len(refs), 10)
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertTrue((ROOT / ref).is_file(), ref)

    def test_the_test_count_it_quotes_is_the_real_one(self):
        count = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT)).countTestCases()
        quoted = {int(n) for n in re.findall(r"(\d+)(?: tests|%20%E2%9C%93)", README)}
        self.assertEqual(quoted, {count})


if __name__ == "__main__":
    unittest.main()
