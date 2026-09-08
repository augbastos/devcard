#!/usr/bin/env python3
"""Rewrite the hoverable card block in a README from live data.

The card's language bar is served as one image per language so that each can
carry its own `title` — that is the only way a GitHub README gets a tooltip for
a single language, because a README renders the card through an `<img>` and no
pointer event reaches inside an SVG loaded that way.

The catch is that a `title` is an HTML attribute, so the tooltip text and the
slice widths live in the README rather than in the image. They cannot follow the
data on their own; this script is what moves them. The pixels are always live —
every slice is fetched from the Worker on each view — so a stale block shows the
right colours in slightly wrong proportions, never a broken bar.

Usage:
    python scripts/refresh_readme.py [--readme README.md] [--url https://...]

The Worker's origin is taken from --url, then $DEVCARD_URL, then whatever the
README already points at. Writes only when the block actually changed, and exits
0 either way; --check exits 1 when it would have changed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

START = "<!-- devcard:start -->"
END = "<!-- devcard:end -->"

# Any devcard image already in the file tells us where the Worker lives.
ORIGIN_RE = re.compile(r'src="(https?://[^"/]+)/svg\?')


def find_origin(readme: str) -> str | None:
    match = ORIGIN_RE.search(readme)
    return match.group(1) if match else None


def fetch_block(origin: str, user: str | None, timeout: float) -> str:
    url = f"{origin}/embed"
    if user:
        url += f"?user={urllib.parse.quote(user)}"
    request = urllib.request.Request(url, headers={"User-Agent": "devcard-refresh"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read().decode("utf-8").strip()


def replace_block(readme: str, block: str) -> str:
    start = readme.find(START)
    end = readme.find(END)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(
            f"markers not found: the README needs {START} and {END} around the card"
        )
    # Whatever the file already uses. Joining with "\n" regardless would rewrite
    # a CRLF README's two inserted lines as LF, leaving the file with mixed
    # endings and a diff noisier than the change.
    newline = "\r\n" if "\r\n" in readme else "\n"
    return readme[: start + len(START)] + newline + block + newline + readme[end:]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--url", default=os.environ.get("DEVCARD_URL"))
    parser.add_argument("--user", default=os.environ.get("DEVCARD_USER"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the block is out of date, without writing",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    # newline="" keeps the file's own line endings intact through the round trip.
    with open(args.readme, encoding="utf-8", newline="") as handle:
        readme = handle.read()

    origin = args.url or find_origin(readme)
    if not origin:
        print("no Worker URL: pass --url or set DEVCARD_URL", file=sys.stderr)
        return 2

    try:
        block = fetch_block(origin.rstrip("/"), args.user, args.timeout)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        # A card that is briefly unreachable must not rewrite the README with
        # nothing, and must not fail a scheduled run loudly enough to page
        # anyone. Leave the last good block in place and say why.
        print(f"card unreachable, leaving the README alone: {exc}", file=sys.stderr)
        return 0

    if "<img" not in block:
        print(f"unexpected response from {origin}/embed, leaving it alone", file=sys.stderr)
        return 0

    updated = replace_block(readme, block)
    if updated == readme:
        print("already current")
        return 0
    if args.check:
        print("out of date")
        return 1

    with open(args.readme, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    print(f"refreshed {args.readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
