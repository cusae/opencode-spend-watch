import json
import re
import unittest
from pathlib import Path

import watch

ROOT = Path(__file__).resolve().parents[2]


class MetadataTests(unittest.TestCase):
    def test_version_is_consistent_everywhere(self):
        metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
        spec = (ROOT / "packaging/rpm/opencode-spend-watch.spec").read_text(encoding="utf-8")
        changelog = (ROOT / "debian/changelog").read_text(encoding="utf-8")

        self.assertEqual(metadata["version"], watch.VERSION)
        self.assertEqual(
            re.search(r"^Version:\s+(\S+)$", spec, re.MULTILINE).group(1),
            watch.VERSION,
        )
        self.assertEqual(
            re.search(r"^opencode-spend-watch \(([^)]+)\)", changelog).group(1),
            watch.VERSION,
        )

    def test_metadata_lists_the_supported_platforms(self):
        metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
        names = {entry["operatingsystem"] for entry in metadata["operatingsystem_support"]}
        self.assertEqual(names, {"Debian", "Ubuntu", "CentOS", "FreeBSD", "Darwin"})

    def test_metadata_lists_python_as_a_dependency(self):
        metadata = json.loads((ROOT / "metadata.json").read_text(encoding="utf-8"))
        self.assertIn("python3", [dependency["name"] for dependency in metadata["dependencies"]])


if __name__ == "__main__":
    unittest.main()
