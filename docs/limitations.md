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
- **`worker/wrangler.toml` is edited by `setup.py`** with your `database_id` and
  GitHub username. It is your fork's deployment config and belongs committed
  there, but it does mean `git status` is not clean after setup.
- **Raw events are never deleted.** Deliberate, and measured — see
  [event retention](retention.md).
- **The repo count includes private repositories**, while the card's
  `N repos →` link goes to your public profile, so a visitor sees a shorter
  list than the number — see [privacy and security](privacy-and-security.md).
- **Links inside the card don't click** when embedded via `<img>` — a browser
  limitation of anything loaded that way. Wrapping the image in a link makes
  the whole card clickable, if that is enough.
- **The hoverable bar's proportions are as fresh as the last weekly refresh.**
  The pixels are live; the widths and tooltip text live in your README — see
  [hover in a README](hover-in-a-readme.md).
