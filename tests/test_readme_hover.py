"""README language hover: pure markup, consent gates, and real local git only."""
import contextlib
from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from devcard import cli, config, data, publish, readme, render
from devcard.svg import NEUTRAL_LANGUAGE_COLOR
from devcard.themes import theme_pair

from .helpers import Home, TempDirTest, edit, git
from .test_cli import init
from .test_optin_golden import fixture as optin_card
from .test_publish import NOW, cfg_for, run


def card(languages=None):
    agg = {"format": 1, "language_percentages": languages or {"Python": 80, "Rust": 20}}
    return data.card_data(data.merge([agg], now=NOW), "octo-cat", NOW, tz="UTC")


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class BlockTest(unittest.TestCase):
    def test_titles_sources_urls_and_exact_width_sum(self):
        block = readme.build_block("octo-cat/cards", card())
        tags = Tags(block).tags
        images = [attrs for tag, attrs in tags if tag == "img"]
        sources = [attrs for tag, attrs in tags if tag == "source"]
        self.assertEqual(len(images), 5)  # body, two caps, two languages
        self.assertEqual([img["src"].rsplit("/", 1)[1] for img in images],
                         ["body.svg", "cap-left.svg", "0.svg", "1.svg", "cap-right.svg"])
        self.assertEqual(images[0]["width"], "100%")
        self.assertIn("devcard", images[0]["alt"])
        self.assertNotIn("card.svg", block)
        self.assertEqual(block.count("<p>"), 1)
        self.assertTrue(block.startswith("<p><picture>"))
        self.assertTrue(block.endswith("</picture></p>"))
        self.assertEqual(len(sources), len(images))
        self.assertEqual([img["title"] for img in images if "title" in img], ["Python 80.0%", "Rust 20.0%"])
        self.assertEqual(sum(Decimal(img["width"][:-1]) for img in images[1:]), 100)
        for source in sources:
            self.assertEqual(source["media"], "(prefers-color-scheme: dark)")
            self.assertTrue(source["srcset"].endswith("-dark.svg"))
        for img in images:
            self.assertTrue(img["src"].startswith("https://raw.githubusercontent.com/octo-cat/cards/devcard-data/"))
        for img in images:
            self.assertEqual(img["align"], "top")
        row = block.split("<p>")[1]
        self.assertNotIn("\n", row)
        self.assertNotIn("</picture> <picture>", row)
        self.assertIsNone(re.search(r">\s+<", block))

    def test_unsupported_layouts_and_missing_languages_use_normal_embed(self):
        for layout, c in [(layout, card()) for layout in ("banner", "half", "vertical", "unknown")] + [
                ("full", data.card_data({}, "octo-cat", NOW))]:
            with self.subTest(layout=layout, sections=c.sections):
                self.assertEqual(readme.build_block("octo-cat/cards", c, layout=layout),
                                 config.embed_html("octo-cat/cards"))
                self.assertEqual(render.render(c, layout=layout, split=True), render.render(c, layout=layout))

    def test_body_closes_bar_gap_and_keeps_content_with_flat_frame(self):
        complete = replace(optin_card(), show_agents=True, show_usage=True,
                           languages=card().languages, total_lines=100,
                           badges=[{"kind": "badge", "label": "Builder"}],
                           pins=[{"repo": "example", "note": "A pinned repository", "stars": 12}])
        for c in (complete, card(), card({"Python": 100}), replace(complete, languages=[], total_lines=0)):
            for layout in ("full", "wide"):
                for theme in theme_pair("default"):
                    with self.subTest(layout=layout, sections=c.sections, theme=theme):
                        full = ET.fromstring(render.render(c, theme, layout=layout, now=NOW, static=True))
                        raw = render.render(c, theme, layout=layout, now=NOW, static=True, split=True)
                        body = ET.fromstring(raw)
                        self.assertEqual(body.get("width"), "840")
                        self.assertEqual(body.get("viewBox"), f'0 0 840 {body.get("height")}')
                        ns = {"s": "http://www.w3.org/2000/svg"}
                        frame = body.find("s:rect[@class='bg brd']", ns)
                        # Bottom corners and stroke lie below the viewBox, as in the Worker.
                        self.assertGreaterEqual(float(frame.get("height")) - 14, float(body.get("height")))
                        self.assertEqual(frame.get("width"), "839")
                        self.assertEqual(frame.get("rx"), str(readme.CORNER))
                        self.assertIsNone(body.find(".//s:rect[@class='track']", ns))
                        self.assertIsNone(body.find(".//s:rect[@class='hit']", ns))
                        self.assertIsNone(body.find(".//s:clipPath[@id='barclip']", ns))
                        self.assertIsNone(body.find(".//s:clipPath[@id='wbar']", ns))
                        # Legend/heatmap/footer/optional lines survive; only the bar's tooltip text goes.
                        self.assertEqual([n.text for n in body.findall(".//s:text", ns)],
                                         [n.text for n in full.findall(".//s:text", ns)
                                          if n.get("class") != "tiptx"])
                        self.assertLess(float(body.get("height")), float(full.get("height")))

    def test_render_files_adds_body_pair_without_changing_normal_cards(self):
        agg = {"format": 1, "language_percentages": {"Python": 80, "Rust": 20}}
        for layout in render.LAYOUTS:
            cfg = cfg_for("local", layout=layout)
            full = publish.render_files(cfg, [agg], NOW)
            hover = publish.render_files({**cfg, "readme_hover": True}, [agg], NOW)
            with self.subTest(layout=layout):
                self.assertEqual(full, {k: hover[k] for k in full})
                if layout in ("full", "wide"):
                    self.assertIn("lang/body.svg", hover)
                    self.assertIn("lang/body-dark.svg", hover)
                    self.assertIn(b"#ffffff", hover["lang/body.svg"])
                    self.assertIn(b"#0f1117", hover["lang/body-dark.svg"])
                else:
                    self.assertEqual(full, hover)

    def test_other_group_titles_are_localized_and_html_escaped(self):
        languages = {f"Lang{i}": 10 - i for i in range(9)}
        languages["Python"] = 100
        c = card(languages)
        # Aggregates reject such names; exercise HTML escaping independently.
        c.languages[0].language = 'A"<&'
        block = readme.build_block("octo-cat/cards", c, "pt")
        titles = [attrs["title"] for tag, attrs in Tags(block).tags if tag == "img" and "title" in attrs]
        self.assertEqual(len(titles), 7)
        self.assertTrue(titles[-1].startswith("outras:"))
        self.assertIn('A&quot;&lt;&amp;', block)
        self.assertIn("Lang5", titles[-1])

    def test_empty_and_tiny_slices_still_tile_exactly(self):
        for c in (data.card_data({}, "octo-cat", NOW), card({"Python": 100, "Rust": 0.00000001})):
            with self.subTest(languages=c.languages):
                left, slots, right = readme.strip_layout(c)
                self.assertEqual(left + right + sum(units for _, units, _ in slots), 1_000_000)
                self.assertTrue(all(units > 0 for _, units, _ in slots))

    def test_slice_files_match_layout_colours_and_theme_without_private_fields(self):
        c = card({f"Lang{i}": i + 1 for i in range(10)})
        files = readme.slice_files(c, *theme_pair("default"))
        _, slots, _ = readme.strip_layout(c)
        for i, (_s, units, _share) in enumerate(slots):
            for suffix, bg in (("", "#ffffff"), ("-dark", "#0f1117")):
                raw = files[f"lang/{i}{suffix}.svg"]
                svg = ET.fromstring(raw)
                self.assertAlmostEqual(float(svg.get("width")), 840 * units / 1_000_000, places=6)
                self.assertIn(bg.encode(), raw)
                self.assertNotIn(b"prefers-color-scheme", raw)
                for private in (b"project", b"email", b"source_id"):
                    self.assertNotIn(private, raw)
        self.assertIn(NEUTRAL_LANGUAGE_COLOR.encode(), files["lang/6.svg"])
        for raw in files.values():
            ET.fromstring(raw)

    def test_replace_block_preserves_every_newline_and_surrounding_bytes(self):
        for nl in ("\n", "\r\n"):
            original = f"before{nl}{readme.START}{nl}old{nl}{readme.END}{nl}after{nl}"
            updated = readme.replace_block(original, "one\ntwo")
            self.assertEqual(updated, original.replace("old", f"one{nl}two"))
            self.assertEqual(readme.replace_block(updated, "one\r\ntwo"), updated)
        for original in ("no markers", readme.START, readme.END + readme.START):
            with self.assertRaises(ValueError):
                readme.replace_block(original, "one")


class HoverPublishTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.remote = self.bare_remote()

    def seed_default(self, content=None, mode="100644"):
        repo = publish._Repo(os.path.join(self.tmp, "default-builder.git"), self.remote)
        repo.ensure()
        files = {"keep.txt": b"unrelated\x00bytes\n"}
        if content is not None:
            files["README.md"] = content
        tree = repo.write_tree(files)
        if mode != "100644":
            env = {"GIT_INDEX_FILE": os.path.join(repo.path, "fixture-index")}
            blob = repo.out("rev-parse", f"{tree}:README.md")
            repo.git("read-tree", tree, env=env)
            repo.git("update-index", "--cacheinfo", mode, blob, "README.md", env=env)
            tree = repo.out("write-tree", env=env)
        head = repo.commit(tree, NOW - 60)
        repo.git("push", "-q", "origin", f"{head}:refs/heads/trunk")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/trunk")
        return head

    def marked(self, nl="\n"):
        return f"# Profile{nl}{readme.START}{nl}old{nl}{readme.END}{nl}Tail{nl}".encode()

    def head(self):
        return git(self.remote, "rev-parse", "trunk")

    def body(self):
        repo = publish._Repo(self.remote, self.remote)
        return repo.git("show", "trunk:README.md").stdout

    def test_end_to_end_preserves_history_crlf_and_files_and_publishes_both_themes(self):
        parent = self.seed_default(self.marked("\r\n"))
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 80), edit(NOW - 50, "Rust", 20)])
            cfg = cfg_for(self.remote, readme_hover=True)
            self.assertEqual(run(cfg, force=True), "published")
            state = publish._read_json(config.state_path())
            self.assertEqual(state["last_readme_push"], NOW)
            current = self.head()
            self.assertNotEqual(current, parent)
            self.assertEqual(git(self.remote, "log", "-1", "--format=%P", "trunk"), parent)
            self.assertEqual(git(self.remote, "log", "-1", "--format=%s", "trunk"), "devcard: refresh language bar")
            self.assertEqual(git(self.remote, "show", "trunk:keep.txt"), "unrelated\x00bytes")
            body = self.body()
            self.assertTrue(body.startswith(b"# Profile\r\n" + readme.START.encode() + b"\r\n"))
            self.assertTrue(body.endswith(readme.END.encode() + b"\r\nTail\r\n"))
            self.assertNotIn(b"\n", body.replace(b"\r\n", b""))
            titles = [a["title"] for t, a in Tags(body.decode()).tags if t == "img" and "title" in a]
            self.assertEqual(titles, ["Python 80.0%", "Rust 20.0%"])
            for filename in ("lang/body.svg", "lang/body-dark.svg", "lang/0.svg", "lang/0-dark.svg",
                             "lang/1.svg", "lang/1-dark.svg"):
                ET.fromstring(git(self.remote, "show", f"{publish.BRANCH}:{filename}"))
            self.assertEqual(git(self.remote, "rev-list", "--count", publish.BRANCH), "1")
            self.assertEqual(run(cfg, now=NOW + 86401, force=True), "unchanged")
            self.assertEqual(self.head(), current)  # unchanged README makes no daily commit

    def test_disabled_or_unconsented_never_reads_default_branch_or_writes_slices(self):
        for cfg in (cfg_for(self.remote), cfg_for(self.remote, readme_hover="true"),
                    cfg_for(self.remote, readme_hover=True, consent={"totals": True})):
            with self.subTest(cfg=cfg), Home(self.tmp, "a") as home, \
                    mock.patch.object(publish._Repo, "default_head") as default:
                home.add_events([edit(NOW - 60)])
                run(cfg, force=True)
                default.assert_not_called()
                files = git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH)
                self.assertNotIn("lang/", files)

    def test_missing_markers_or_readme_skip_and_hint_only_once(self):
        parent = self.seed_default(b"# No markers\n")
        with Home(self.tmp, "a") as home, mock.patch.object(publish.lib, "log_error") as log:
            home.add_events([edit(NOW - 60)])
            cfg = cfg_for(self.remote, readme_hover=True)
            run(cfg, force=True)
            run(cfg, now=NOW + 1000, force=True)
            self.assertEqual(self.head(), parent)
            log.assert_called_once()
            self.assertIn(readme.START, log.call_args.args[0])
            self.assertNotIn("last_readme_push", publish._read_json(config.state_path()))

    def test_saved_disable_wins_over_a_stale_publish_configuration(self):
        with Home(self.tmp, "a"), mock.patch.object(publish._Repo, "default_head") as default:
            cfg = cfg_for(self.remote, readme_hover=True)
            config.save({**cfg, "readme_hover": False})
            run(cfg, force=True)
            default.assert_not_called()
            self.assertNotIn("lang/", git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH))

    def test_missing_default_branch_or_readme_is_safe(self):
        for seeded in (False, True):
            with self.subTest(seeded=seeded), Home(self.tmp, "a"), mock.patch.object(publish.lib, "log_error"):
                if seeded:
                    parent = self.seed_default()
                run(cfg_for(self.remote, readme_hover=True), force=True)
                if seeded:
                    self.assertEqual(self.head(), parent)

    def test_daily_limit_applies_even_with_force_and_refreshes_after_24h(self):
        self.seed_default(self.marked())
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 80), edit(NOW - 50, "Rust", 20)])
            cfg = cfg_for(self.remote, readme_hover=True)
            run(cfg, force=True)
            first = self.head()
            home.add_events([edit(NOW + 10, "Rust", 100)])
            for elapsed in (20, 86400):
                run(cfg, now=NOW + elapsed, force=True)
                self.assertEqual(self.head(), first)
                self.assertEqual(publish._read_json(config.state_path())["last_readme_push"], NOW)
            # Card tree can be unchanged while the README update is now due.
            self.assertEqual(run(cfg, now=NOW + 86401, force=True), "unchanged")
            self.assertNotEqual(self.head(), first)
            self.assertIn(b"Rust 60.0%", self.body())
            self.assertEqual(publish._read_json(config.state_path())["last_readme_push"], NOW + 86401)

    def test_stale_slices_removed_on_shrink_disable_and_revoke(self):
        with Home(self.tmp, "a") as home, mock.patch.object(publish.lib, "log_error"):
            home.add_events([edit(NOW - 60, "Python", 80), edit(NOW - 50, "Rust", 20)])
            cfg = cfg_for(self.remote, readme_hover=True)
            run(cfg, force=True)
            self.assertIn("lang/1.svg", git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH))
            conn = publish.lib.init_db()
            try:
                conn.execute("DELETE FROM events WHERE language = 'Rust'")
                conn.commit()
            finally:
                conn.close()
            run(cfg, now=NOW + 60, force=True)
            files = git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH)
            self.assertIn("lang/0.svg", files)
            self.assertNotIn("lang/1", files)
            for change in ({"readme_hover": False}, {"consent": {"totals": True}}):
                run({**cfg, **change}, now=NOW + 120, force=True)
                self.assertNotIn("lang/", git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH))

    def test_competing_default_branch_edit_is_preserved_on_next_daily_retry(self):
        self.seed_default(self.marked())
        original = publish._Repo.push_readme
        attempts = []

        def race(repo, commit, ref):
            if not attempts:
                attempts.append(True)
                head = self.head()
                tree = repo.write_tree({"README.md": self.marked(), "keep.txt": b"concurrent edit"})
                other = repo.out("commit-tree", tree, "-p", head, "-m", "concurrent", env=publish.AUTHOR_ENV)
                repo.git("push", "-q", "origin", f"{other}:{ref}")
            return original(repo, commit, ref)

        with Home(self.tmp, "a"), mock.patch.object(publish._Repo, "push_readme", race):
            cfg = cfg_for(self.remote, readme_hover=True)
            self.assertEqual(run(cfg, force=True), "published")
            self.assertEqual(git(self.remote, "rev-list", "--count", "trunk"), "2")
            self.assertEqual(run(cfg, now=NOW + 86401, force=True), "unchanged")
        self.assertEqual(git(self.remote, "show", "trunk:keep.txt"), "concurrent edit")
        self.assertEqual(git(self.remote, "rev-list", "--count", "trunk"), "3")

    def test_rejected_readme_push_preserves_card_success_and_backs_off_for_24h(self):
        self.seed_default(self.marked())
        with Home(self.tmp, "a") as home, mock.patch.object(publish.lib, "log_error") as log, \
                mock.patch.object(publish._Repo, "push_readme", return_value=(False, "remote details")) as push:
            cfg = cfg_for(self.remote, readme_hover=True)
            self.assertEqual(run(cfg, force=True), "published")
            push.assert_called_once()
            state = publish._read_json(config.state_path())
            self.assertEqual(state["last_push"], NOW)  # data branch succeeded
            self.assertEqual(state["last_readme_attempt"], NOW)
            self.assertEqual(state["readme_failure_reason"], "default branch rejected the update (protected?)")
            self.assertNotIn("last_readme_push", state)
            self.assertNotIn("remote details", str(state))
            log.assert_called_once_with("README hover: octo-cat/octo-cat default branch rejected the update (protected?); retrying in 24 h")
            with mock.patch.object(publish._Repo, "default_head") as default:
                home.add_events([edit(NOW + 10)])
                self.assertEqual(run(cfg, now=NOW + 20, force=True), "published")
                self.assertEqual(run(cfg, now=NOW + 86400, force=True), "unchanged")
                default.assert_not_called()
                push.assert_called_once()
                log.assert_called_once()
            with mock.patch.object(publish._Repo, "push_readme", return_value=(True, "")) as retry:
                self.assertEqual(run(cfg, now=NOW + 86401, force=True), "unchanged")
                retry.assert_called_once()
            state = publish._read_json(config.state_path())
            self.assertEqual(state["last_readme_push"], NOW + 86401)
            self.assertNotIn("readme_failure_reason", state)

    def test_readme_git_failure_does_not_fail_card_publication(self):
        with Home(self.tmp, "a"), mock.patch.object(publish.lib, "log_error") as log, \
                mock.patch.object(publish._Repo, "default_head", side_effect=publish.PublishError("unavailable")) as default:
            cfg = cfg_for(self.remote, readme_hover=True)
            self.assertEqual(run(cfg, force=True), "published")
            self.assertEqual(run(cfg, now=NOW + 1000, force=True), "unchanged")
            default.assert_called_once()
            log.assert_called_once_with("README hover: octo-cat/octo-cat README update failed; retrying in 24 h")
            state = publish._read_json(config.state_path())
            self.assertEqual(state["last_readme_attempt"], NOW)
            self.assertEqual(state["readme_failure_reason"], "README git operation failed")

    def test_invalid_utf8_symlink_and_executable_readmes_have_a_distinct_hint(self):
        cases = (("utf8", b"\xff" + self.marked(), "100644"),
                 ("symlink", b"target.md", "120000"),
                 ("executable", self.marked(), "100755"))
        for name, content, mode in cases:
            with self.subTest(name=name):
                self.remote = self.bare_remote(f"{name}.git")
                parent = self.seed_default(content, mode)
                with Home(self.tmp, name), mock.patch.object(publish.lib, "log_error") as log, \
                        mock.patch.object(publish._Repo, "push_readme") as push:
                    cfg = cfg_for(self.remote, readme_hover=True)
                    self.assertEqual(run(cfg, force=True), "published")
                    self.assertEqual(run(cfg, now=NOW + 1000, force=True), "unchanged")
                    log.assert_called_once_with("README.md is not a regular UTF-8 file; hover skipped")
                    push.assert_not_called()
                    self.assertEqual(self.head(), parent)
                    state = publish._read_json(config.state_path())
                    self.assertNotIn("readme_marker_hint", state)
                    self.assertNotIn("last_readme_push", state)


class HoverCommandTest(TempDirTest):
    def test_toggle_is_local_and_does_not_grant_language_consent(self):
        with Home(self.tmp, "a"), mock.patch.object(cli, "publish") as send:
            config.save(cfg_for("local", consent={}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["readme", "--enable"]), 0)
                self.assertTrue(config.load()["readme_hover"])
                self.assertFalse(config.consents(config.load())["languages"])
                self.assertEqual(cli.main(["readme", "--disable"]), 0)
                self.assertFalse(config.load()["readme_hover"])
            send.assert_not_called()

    def test_init_default_no_and_explicit_flag_and_interactive_yes(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), Home(self.tmp, "a"), mock.patch.object(cli, "publish"):
                argv = ["--yes", "--mode", "git", "--user", "octo-cat", "--repo", "octo-cat/cards", "--remote", "local"]
                init([*argv, *(["--readme-hover"] if enabled else [])])
                self.assertEqual(config.load()["readme_hover"], enabled)
        with Home(self.tmp, "b"), mock.patch.object(cli, "publish"):
            init(["--mode", "claude", "--user", "octo-cat", "--repo", "octo-cat/cards", "--remote", "local"],
                 answers=[*["n"] * len(config.CONSENT_CATEGORIES), "y"])
            self.assertTrue(config.load()["readme_hover"])


if __name__ == "__main__":
    unittest.main()
