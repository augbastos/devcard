"""Access to the capture hook's modules (hook/devcard_lib.py and friends).

Installed with pipx, the hook modules sit next to this package in
site-packages, where the hooks also run from. In a clone they live in hook/,
beside this package — the fallback below covers that, so `python -m devcard`
works from a checkout without installing anything.
"""
import os
import sys

HOOK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hook")

try:
    import devcard_lib as lib  # noqa: F401
except ImportError:
    sys.path.insert(0, HOOK_DIR)
    import devcard_lib as lib  # noqa: F401

import devcard_usage as usage  # noqa: E402, F401
import devcard_activity as activity  # noqa: E402, F401


def hook_script(name):
    """Absolute path of one of the hook entrypoints, wherever they were installed."""
    return os.path.join(os.path.dirname(os.path.abspath(lib.__file__)), name)
