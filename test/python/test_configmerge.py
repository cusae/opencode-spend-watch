import io
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import configmerge


class MergeTests(unittest.TestCase):
    def test_keeps_existing_values_and_appends_missing_options(self):
        example = '# Template\nA=1\nB="two"\n# C=9\nD=\n'
        current = "# Mine\nA=42\nE=keep\n"
        merged, added = configmerge.merge(example, current)
        self.assertEqual(added, ["B", "D"])
        self.assertTrue(merged.startswith(current))
        self.assertIn("A=42", merged)
        self.assertIn("E=keep", merged)
        self.assertIn('B="two"', merged)
        self.assertIn("D=", merged)
        self.assertNotIn("C=9", merged)

    def test_reports_nothing_when_all_options_exist(self):
        example = "A=1\nB=2\n"
        current = "A=9\nB=8\n"
        merged, added = configmerge.merge(example, current)
        self.assertEqual(merged, current)
        self.assertEqual(added, [])

    def test_adds_a_newline_to_a_file_without_one(self):
        merged, _ = configmerge.merge("B=2\n", "A=1")
        self.assertIn("A=1\n", merged)

    def test_duplicate_names_in_the_example_are_added_once(self):
        merged, added = configmerge.merge("A=1\nA=2\n", "")
        self.assertEqual(added, ["A"])
        self.assertEqual(merged.count("A=1"), 1)
        self.assertNotIn("A=2", merged)


class CommandTests(unittest.TestCase):
    def test_writes_a_backup_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            example = directory / "example.env"
            target = directory / "config.env"
            example.write_text("A=1\nB=2\n", encoding="utf-8")
            target.write_text("A=42\n", encoding="utf-8")
            target.chmod(0o600)

            with redirect_stdout(io.StringIO()) as output:
                code = configmerge.main([str(example), str(target)])

            self.assertEqual(code, 0)
            self.assertIn("A=42", target.read_text())
            self.assertIn("B=2", target.read_text())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            backups = list(directory.glob("config.env.bak.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "A=42\n")
            self.assertIn("backup:", output.getvalue())

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            example = directory / "example.env"
            target = directory / "config.env"
            example.write_text("A=1\nB=2\n", encoding="utf-8")
            target.write_text("A=42\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()) as output:
                code = configmerge.main(["--dry-run", str(example), str(target)])

            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(), "A=42\n")
            self.assertEqual(list(directory.glob("config.env.bak.*")), [])
            self.assertIn("nothing written", output.getvalue())

    def test_creates_a_missing_target_with_mode_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            example = directory / "example.env"
            target = directory / "config.env"
            example.write_text("A=1\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                code = configmerge.main([str(example), str(target)])

            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(), "A=1\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_reports_when_nothing_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            example = directory / "example.env"
            target = directory / "config.env"
            example.write_text("A=1\n", encoding="utf-8")
            target.write_text("A=2\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(configmerge.main([str(example), str(target)]), 0)
            self.assertIn("no missing options", output.getvalue())

    def test_default_paths_exist_in_a_checkout(self):
        self.assertTrue(configmerge.default_example().exists())
        self.assertTrue(configmerge.default_target().exists())

    def test_missing_example_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = configmerge.main(
                    [str(Path(tmp) / "absent.env"), str(Path(tmp) / "config.env")]
                )
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
