"""The parallel runner must report failures without dropping other modules."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import run_tests


class RunnerTest(unittest.TestCase):
    def test_discovery_runs_both_suites_and_propagates_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("hook", "tests"):
                (root / folder).mkdir()
                (root / folder / "__init__.py").touch()
            (root / "hook" / "test_pass.py").write_text(
                "import unittest\nclass Test(unittest.TestCase):\n"
                "    def test_pass(self): self.assertTrue(True)\n", encoding="utf-8")
            broken = root / "tests" / "test_fail.py"
            for source in (
                "import unittest\nclass Test(unittest.TestCase):\n"
                "    def test_fail(self): self.fail('failure sentinel')\n",
                "raise RuntimeError('import sentinel')\n",
                "import unittest\nclass Test(unittest.TestCase):\n"
                "    def test_pass(self): self.assertTrue(True)\n",
            ):
                with self.subTest(source=source):
                    broken.write_text(source, encoding="utf-8")
                    output = io.StringIO()
                    with mock.patch.object(run_tests, "ROOT", root), \
                            contextlib.redirect_stdout(output):
                        code = run_tests.main(["--jobs", "2"])
                    self.assertEqual(code, int("sentinel" in source))
                    self.assertIn("test_pass.py:", output.getvalue())
                    self.assertIn("test_fail.py:", output.getvalue())
                    self.assertIn("2 modules in", output.getvalue())

    def test_launch_error_fails_without_abandoning_other_modules(self):
        with mock.patch.object(run_tests, "run_module", side_effect=OSError("launch failed")) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests.main(["--jobs", "2"]), 1)
        self.assertGreater(run.call_count, 1)

    def test_invalid_worker_count_and_empty_discovery_fail(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(run_tests, "ROOT", Path(tmp)), \
                contextlib.redirect_stderr(io.StringIO()):
            for args in (["--jobs", "0"], ["--jobs", "-1"], []):
                with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                    run_tests.main(args)
                self.assertEqual(error.exception.code, 2)
