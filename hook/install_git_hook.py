#!/usr/bin/env python3
"""Install (or remove) the devcard post-commit hook in git repositories.

Usage:
    python install_git_hook.py <path> [<path> ...]
    python install_git_hook.py --uninstall <path> [<path> ...]

Each <path> may be a repository or a folder containing repositories (scanned
one level deep, plus the folder itself). Paths containing spaces are fine —
each one is a separate argument.

The hook line is APPENDED to an existing post-commit hook, so husky and friends
keep working, and running the installer twice is a no-op. A hook that is not a
POSIX shell script is never modified: the installer reports it and prints the
line to add by hand, because appending `sh` to a Python or Ruby hook would
break the hook that is already there.

Where the hook goes is asked of git rather than assumed. `.git/hooks/` is wrong
for a worktree (`.git` is a file there), for a submodule, and for any repo that
sets `core.hooksPath` — `git rev-parse --git-path hooks/post-commit` is right
for all of them.
"""
import os
import stat
import subprocess
import sys

HOOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devcard_git_hook.py")
MARKER = "# devcard-hook"
SHELL_SHEBANGS = ("sh", "bash", "dash", "zsh", "ksh", "ash")


def _git(cwd, *args):
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, errors="replace"
        )
    except OSError:
        return None


def hook_line():
    """The line appended to a post-commit hook.

    Backgrounded (`&`) and silenced so a commit never waits on, or is disturbed
    by, devcard. `-S` skips `site` import, which is most of a cold Python start.
    """
    python = sys.executable.replace("\\", "/")
    script = HOOK_SCRIPT.replace("\\", "/")
    return f'"{python}" -S "{script}" >/dev/null 2>&1 &  {MARKER}\n'


def repo_root(path):
    """Absolute root of the repository or worktree AT `path`, else None.

    Deliberately strict: a subdirectory of a repository is not itself a repo,
    and treating it as one is how a scan of a project's parent folder ends up
    "finding" the same repository several times.
    """
    result = _git(path, "rev-parse", "--show-toplevel")
    if result is None or result.returncode != 0:
        return None
    top = result.stdout.strip()
    if not top:
        return None
    try:
        if os.path.realpath(top) != os.path.realpath(path):
            return None
    except OSError:
        return None
    return os.path.normpath(top)


def hook_path_for(repo):
    """Absolute path of this repo's post-commit hook, or None.

    `git rev-parse --git-path` resolves `core.hooksPath`, worktrees and a `.git`
    file, and it answers RELATIVE to the directory it ran in — so the result
    has to be joined back onto that directory, not onto the process cwd.
    """
    result = _git(repo, "rev-parse", "--git-path", "hooks/post-commit")
    if result is None or result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    return os.path.normpath(os.path.join(repo, raw))


def husky_user_hook(hook_path):
    """Redirect an install inside husky's generated `_` folder to the user's own.

    husky keeps its runnable hooks in `.husky/_`, regenerates that folder on
    `npm install` and gitignores it. Appending there works until the next
    install silently wipes it. The file husky expects a human to edit is one
    level up, `.husky/post-commit`, so that is where the line belongs.
    """
    hooks_dir = os.path.dirname(hook_path)
    parent = os.path.dirname(hooks_dir)
    if os.path.basename(hooks_dir) == "_" and os.path.basename(parent) == ".husky":
        return os.path.join(parent, os.path.basename(hook_path))
    return hook_path


def shebang_is_shell(content):
    """True if an existing hook is a POSIX shell script we can safely append to.

    A hook with no shebang counts: git runs it with `sh`, and husky's own hooks
    are written that way.
    """
    first = content.split("\n", 1)[0].strip()
    if not first.startswith("#!"):
        return True
    interpreter = first[2:].strip()
    parts = interpreter.split()
    if parts and parts[0].rsplit("/", 1)[-1] == "env" and len(parts) > 1:
        name = parts[1]
    elif parts:
        name = parts[0].rsplit("/", 1)[-1]
    else:
        return False
    return name in SHELL_SHEBANGS


def _write_executable(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass  # Windows has no execute bit; git runs the hook regardless


def install_into(hook_path):
    """Append the devcard line. Returns a short status string."""
    if os.path.exists(hook_path):
        try:
            with open(hook_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            return f"unreadable ({exc.strerror})"
        if MARKER in content:
            return "already installed"
        if not shebang_is_shell(content):
            return "skipped (not a shell hook)"
        if not content.endswith("\n"):
            content += "\n"
        content += hook_line()
    else:
        content = "#!/bin/sh\n" + hook_line()

    try:
        _write_executable(hook_path, content)
    except OSError as exc:
        return f"failed ({exc.strerror})"
    return "installed"


def uninstall_from(hook_path):
    """Remove only the devcard line, leaving any other hook intact."""
    if not os.path.exists(hook_path):
        return "not installed"
    try:
        with open(hook_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as exc:
        return f"unreadable ({exc.strerror})"
    if not any(MARKER in line for line in lines):
        return "not installed"

    kept = [line for line in lines if MARKER not in line]
    # A file that is now nothing but a shebang and blank lines was ours alone.
    meaningful = [l for l in kept if l.strip() and not l.strip().startswith("#!")]
    try:
        if meaningful:
            _write_executable(hook_path, "".join(kept))
            return "line removed"
        os.remove(hook_path)
        return "removed"
    except OSError as exc:
        return f"failed ({exc.strerror})"


def find_repos(root):
    """The repo at `root`, plus every repo one level below it."""
    found = []
    top = repo_root(root)
    if top:
        found.append(top)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        candidate = os.path.join(root, entry)
        if not os.path.isdir(candidate):
            continue
        top = repo_root(candidate)
        if top:
            found.append(top)
    return found


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    uninstall = False
    for flag in ("--uninstall", "--remove"):
        if flag in argv:
            uninstall = True
            argv.remove(flag)

    if not argv:
        print(__doc__)
        return 2

    if _git(os.getcwd(), "--version") is None:
        print("  git not found on PATH — install git first")
        return 1

    seen_hooks = set()
    touched = 0
    for raw_root in argv:
        root = os.path.abspath(raw_root)
        if not os.path.isdir(root):
            print(f"{'no such folder':>22}  {root}")
            continue
        for repo in find_repos(root):
            hook_path = hook_path_for(repo)
            if not hook_path:
                print(f"{'no hooks path':>22}  {repo}")
                continue
            hook_path = husky_user_hook(hook_path)
            # Worktrees of one repository share a hooks directory: install once.
            key = os.path.normcase(hook_path)
            if key in seen_hooks:
                continue
            seen_hooks.add(key)
            touched += 1
            status = uninstall_from(hook_path) if uninstall else install_into(hook_path)
            print(f"{status:>22}  {repo}")
            if status == "skipped (not a shell hook)":
                print(f"{'':>22}  its post-commit is not a shell script; add this line yourself:")
                print(f"{'':>22}    {hook_line().strip()}")

    if touched == 0:
        print("no git repositories found under the given paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
