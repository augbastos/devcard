"""Background spawns must not open console windows on Windows.

A DETACHED_PROCESS child has no console, so every console program it starts
(git, gh) gets a new, visible window. CREATE_NO_WINDOW gives the child a hidden
console that its own children inherit.
"""
import os
import subprocess
import unittest
from unittest import mock

from devcard import publish


@unittest.skipUnless(os.name == "nt", "Windows process flags")
class SpawnFlagsTest(unittest.TestCase):
    def test_publish_waiter_spawns_without_a_window(self):
        with mock.patch.object(publish, "_waiter_fresh", return_value=False), \
                mock.patch.object(subprocess, "Popen") as popen:
            publish._spawn_waiter()
        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        self.assertFalse(flags & subprocess.DETACHED_PROCESS)


if __name__ == "__main__":
    unittest.main()
