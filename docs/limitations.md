# Known limitations

Stated rather than hidden. Each of these is a decision or a real gap, not a
to-do list.

- **Squash merges can double-count** in `git` mode if the squashed branch's own
  commits were captured on the same machine. A squash commit is
  indistinguishable from hand-written work — see
  [what the numbers mean](counting.md#merge-commits).
- **`git commit --amend` double-counts** in `git` mode: `post-commit` runs
  again and the amended commit's whole diff is read a second time. `claude`
  mode does filter it.
- **A client that commits without invoking git never fires the hook.** `git`
  mode hooks git's own `post-commit`, so a GUI built on libgit2 commits
  silently and the card stays flat.
- **The two capture modes are exclusive per machine.** Running both would count
  the same lines twice; `~/.claude/devcard/mode` is what keeps the git hook
  quiet on a Claude Code machine.
- **The serverless card is near-live, not live**: up to 15 minutes between
  publishes, then up to 5 minutes of `raw.githubusercontent.com` caching
  (`max-age=300`). These SVGs are not proxied through GitHub's image proxy — see
  [the serverless card](serverless.md#how-fresh-the-card-is). It publishes only
  when a hook fires, so the "updated" date and the heatmap's "today" do not move
  on days you do not code.
- **The serverless card has no per-language hover in a README.** It is one image
  per theme; the split card behind the hover needs the Worker.
- **Pinned repositories show no star count** on the serverless card — that
  would take a GitHub API call per pin at every publish.
- **Publishing force-pushes `devcard-data`**, so a ruleset that forbids
  force-pushes on that branch makes it fail.
- **Raw events are never deleted.** Deliberate, and measured — see
  [event retention](retention.md).
- **The repo count includes private repositories**, while the card's
  `N repos →` link goes to your public profile, so a visitor sees a shorter
  list than the number — see [privacy and security](privacy-and-security.md).
- **Legacy Worker: one card per Worker.** A deployment renders a single GitHub username;
  `?user=` only confirms it. devcard is deliberately not a multi-tenant service.
- **Legacy Worker: the last edits reach it up to about half a minute late** in
  `claude` mode. The syncer is throttled to one run per 20 seconds and makes a
  final pass when that window closes; a machine that sleeps or shuts down inside
  the window sends those events on its next sync instead.
- **Links inside the card don't click** when embedded via `<img>` — a browser
  limitation of anything loaded that way. Wrapping the image in a link makes
  the whole card clickable, if that is enough.
- **Legacy Worker: the hoverable bar's proportions are as fresh as the last weekly refresh.**
  The pixels are live; the widths and tooltip text live in your README — see
  [hover in a README](hover-in-a-readme.md).
