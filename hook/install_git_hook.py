#!/usr/bin/env python3
"""Install the devcard post-commit hook into git repos.

Usage:
    python install_git_hook.py <path> [<path> ...]

Each <path> can be a repo or a folder containing repos (scanned one level
deep, plus the folder itself). The hook is APPENDED to any existing
post-commit hook, so tools like husky keep working. Running twice is safe —
already-installed repos are skipped.
"""
import os
import stat
import sys

HOOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devcard_git_hook.py")
MARKER = "# devcard-hook"


def find_repos(root):
    repos = []
    if os.path.isdir(os.path.join(root, ".git")):
        repos.append(root)
    try:
        for entry in os.listdir(root):
            candidate = os.path.join(root, entry)
            if os.path.isdir(os.path.join(candidate, ".git")):
                repos.append(candidate)
    except OSError:
        pass
    return repos


def install_into(repo):
    hook_path = os.path.join(repo, ".git", "hooks", "post-commit")
    python = sys.executable.replace("\\", "/")
    script = HOOK_SCRIPT.replace("\\", "/")
    line = f'"{python}" -S "{script}" >/dev/null 2>&1 &  {MARKER}\n'

    if os.path.exists(hook_path):
        with open(hook_path, encoding="utf-8") as f:
            content = f.read()
        if MARKER in content:
            return "already installed"
        if not content.endswith("\n"):
            content += "\n"
        content += line
    else:
        content = "#!/bin/sh\n" + line

    with open(hook_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return "installed"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    seen = set()
    for root in sys.argv[1:]:
        root = os.path.abspath(root)
        for repo in find_repos(root):
            if repo in seen:
                continue
            seen.add(repo)
            print(f"{install_into(repo):>18}  {repo}")
    if not seen:
        print("no git repos found under the given paths")


if __name__ == "__main__":
    main()
