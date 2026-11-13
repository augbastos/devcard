"""Run every Python test module in its own process, bounded by CPU count."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run_module(path):
    command = [sys.executable, "-m", "unittest", "discover", "-s", path.parent.name,
               "-p", path.name, "-v"]
    if path.parent.name == "tests":
        command += ["-t", "."]
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return result.returncode, result.stdout, time.perf_counter() - started


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    modules = [path for folder in ("hook", "tests")
               for path in (ROOT / folder).glob("test_*.py")]
    if not modules:
        parser.error("no test modules found")
    # Start larger modules first to avoid leaving a long integration suite last.
    modules.sort(key=lambda path: path.stat().st_size, reverse=True)
    started = time.perf_counter()
    failed = False
    with ThreadPoolExecutor(max_workers=min(args.jobs, os.cpu_count() or 1, len(modules))) as pool:
        pending = {pool.submit(run_module, path): path for path in modules}
        for future in as_completed(pending):
            path = pending[future].relative_to(ROOT)
            try:
                code, output, seconds = future.result()
            except Exception as exc:
                print(f"FAIL {path}: {exc}", flush=True)
                failed = True
                continue
            print(f"{path}: {seconds:.2f}s (exit {code})\n{output}", flush=True)
            failed |= code != 0
    print(f"{len(modules)} modules in {time.perf_counter() - started:.2f}s", flush=True)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
