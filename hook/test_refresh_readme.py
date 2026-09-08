"""Tests for the README refresher.

This script runs unattended on a schedule and rewrites a public README, so the
failure modes that matter are the quiet ones: emptying the block when the card
is briefly unreachable, or rewriting every line of the file because the line
endings did not survive the round trip.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
)

import refresh_readme as refresher

ORIGIN = "https://card.example"
BLOCK = '<p><img src="https://card.example/svg?user=x&amp;part=body" width="100%"></p>'


def readme(newline: str, block: str = "<p>old</p>") -> str:
    return newline.join(
        [
            "# devcard",
            "",
            refresher.START,
            block,
            refresher.END,
            "",
            "Some prose.",
            "",
        ]
    )


class TestReplaceBlock(unittest.TestCase):
    def test_swaps_only_the_block(self):
        out = refresher.replace_block(readme("\n"), BLOCK)
        self.assertIn(BLOCK, out)
        self.assertNotIn("<p>old</p>", out)
        self.assertIn("# devcard", out)
        self.assertIn("Some prose.", out)

    def test_keeps_crlf_endings(self):
        """A CRLF file must stay CRLF.

        Joining with "\\n" regardless left two LF lines in an otherwise CRLF
        file, which reads as the whole file having changed.
        """
        out = refresher.replace_block(readme("\r\n"), BLOCK)
        self.assertEqual(out.count("\n"), out.count("\r\n"))

    def test_keeps_lf_endings(self):
        out = refresher.replace_block(readme("\n"), BLOCK)
        self.assertEqual(out.count("\r"), 0)

    def test_is_idempotent(self):
        once = refresher.replace_block(readme("\r\n"), BLOCK)
        twice = refresher.replace_block(once, BLOCK)
        self.assertEqual(once, twice)

    def test_refuses_a_file_without_markers(self):
        with self.assertRaises(SystemExit):
            refresher.replace_block("# devcard\n\nno markers here\n", BLOCK)


class TestFindOrigin(unittest.TestCase):
    def test_reads_the_worker_url_from_the_existing_block(self):
        text = readme("\n", '<img src="https://card.example/svg?user=x&amp;part=body">')
        self.assertEqual(refresher.find_origin(text), "https://card.example")

    def test_returns_none_when_there_is_nothing_to_read(self):
        self.assertIsNone(refresher.find_origin("# devcard\n"))


class TestMain(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".md")
        os.close(handle)
        with open(self.path, "w", encoding="utf-8", newline="") as out:
            out.write(readme("\r\n"))
        self.addCleanup(os.unlink, self.path)

    def read(self) -> str:
        with open(self.path, encoding="utf-8", newline="") as handle:
            return handle.read()

    def test_writes_the_new_block(self):
        with mock.patch.object(refresher, "fetch_block", return_value=BLOCK):
            self.assertEqual(refresher.main(["--readme", self.path, "--url", ORIGIN]), 0)
        self.assertIn(BLOCK, self.read())

    def test_leaves_the_file_alone_when_the_card_is_unreachable(self):
        """A card that is down for a minute must not empty someone's README."""
        before = self.read()
        with mock.patch.object(refresher, "fetch_block", side_effect=OSError("timed out")):
            self.assertEqual(refresher.main(["--readme", self.path, "--url", ORIGIN]), 0)
        self.assertEqual(self.read(), before)

    def test_leaves_the_file_alone_on_a_response_that_is_not_a_card(self):
        before = self.read()
        with mock.patch.object(refresher, "fetch_block", return_value="<html>error</html>"):
            self.assertEqual(refresher.main(["--readme", self.path, "--url", ORIGIN]), 0)
        self.assertEqual(self.read(), before)

    def test_check_reports_without_writing(self):
        before = self.read()
        with mock.patch.object(refresher, "fetch_block", return_value=BLOCK):
            self.assertEqual(refresher.main(["--readme", self.path, "--url", ORIGIN, "--check"]), 1)
        self.assertEqual(self.read(), before)

    def test_check_is_quiet_when_already_current(self):
        with mock.patch.object(refresher, "fetch_block", return_value=BLOCK):
            refresher.main(["--readme", self.path, "--url", ORIGIN])
            self.assertEqual(refresher.main(["--readme", self.path, "--url", ORIGIN, "--check"]), 0)

    def test_stops_when_it_cannot_tell_which_worker_to_ask(self):
        """No --url, no $DEVCARD_URL, and a block with no card in it yet."""
        before = self.read()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(refresher.main(["--readme", self.path]), 2)
        self.assertEqual(self.read(), before)

    def test_second_run_changes_nothing(self):
        with mock.patch.object(refresher, "fetch_block", return_value=BLOCK):
            refresher.main(["--readme", self.path, "--url", ORIGIN])
            once = self.read()
            refresher.main(["--readme", self.path, "--url", ORIGIN])
        self.assertEqual(self.read(), once)


if __name__ == "__main__":
    unittest.main()
