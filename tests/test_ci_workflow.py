"""Offline contracts for the unified workflow, aggregate gate and base safety policy."""
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = (shutil.which('bash') if os.name != 'nt' else
        shutil.which('bash', path=str(Path(shutil.which('git')).resolve().parents[1] / 'bin')))
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class WorkflowTests(unittest.TestCase):
    def test_workflow_contract(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertTrue(workflow.startswith('# CI profile: public\nname: CI\n'))
        workflows = {path.name for path in (ROOT / '.github/workflows').glob('*.yml')}
        self.assertEqual(workflows, {'ci.yml', 'codeql.yml', 'dependabot-automerge.yml'})
        self.assertIn('  push:\n    branches: [main]', workflow)
        self.assertIn('types: [opened, synchronize, reopened, ready_for_review]', workflow)
        self.assertIn('cron: "41 6 * * 2"', workflow)
        self.assertIn('permissions:\n  contents: read', workflow)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", workflow)
        jobs = dict(re.findall(r'^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)',
                               workflow.split('jobs:\n', 1)[1], re.M | re.S))
        expected = {'safety', 'secrets', 'dependencies', 'hook', 'python-lint', 'package', 'worker'}
        self.assertEqual(set(jobs), expected | {'ci-passed'})
        needs = re.search(r'needs: \[([^\]]+)\]', jobs['ci-passed']).group(1)
        self.assertEqual(set(needs.split(', ')), expected)
        self.assertEqual(re.findall(r'^    name: (.+)$', workflow, re.M), [
            'Safety', 'Secrets scan', 'Dependency review',
            "Hooks (${{ matrix.os == 'ubuntu' && 'Ubuntu' || 'Windows' }}, Python ${{ matrix.python-version }})",
            'Lint', 'Package (pipx)', 'Worker (Node ${{ matrix.node-version }})', 'CI passed'])
        for job in jobs.values():
            self.assertIn('timeout-minutes:', job)
        for line in workflow.splitlines():
            if re.match(r'\s+(?:- )?uses:', line):
                self.assertRegex(line, r'uses: (actions/[\w-]+@[0-9a-f]{40} # v[\d.]+|docker://\S+@sha256:[0-9a-f]{64})$')
        self.assertIn('os: [ubuntu, windows]', jobs['hook'])
        self.assertIn('python-version: ["3.11", "3.14"]', jobs['hook'])
        self.assertIn('node-version: ["22", "24"]', jobs['worker'])
        self.assertIn('python scripts/run_tests.py', jobs['hook'])
        self.assertIn('cache-dependency-path: .github/requirements-ci.txt', jobs['hook'])
        self.assertIn('cache-dependency-path: worker/package-lock.json', jobs['worker'])
        self.assertIn('fetch-depth: 0', jobs['secrets'])
        self.assertIn('fail-on-severity: moderate', jobs['dependencies'])
        self.assertIn("if: github.event_name == 'pull_request'", jobs['dependencies'])
        safety = jobs['safety']
        self.assertIn("if: github.event_name == 'pull_request'", safety)
        self.assertIn('ref: ${{ github.event.pull_request.base.sha }}', safety)
        self.assertIn('sparse-checkout: .github/scripts', safety)
        self.assertIn("if: hashFiles('base-policy/.github/scripts/safety.sh') == ''", safety)
        self.assertIn('One-time bootstrap:', safety)
        self.assertEqual(safety.count('uses: actions/checkout@'), 3)
        self.assertEqual(safety.count('persist-credentials: false'), 3)
        self.assertIn('fetch-depth: 0', safety)
        self.assertIn('bash base-policy/.github/scripts/safety.sh', safety)
        self.assertIn('bash bootstrap-policy/.github/scripts/safety.sh', safety)
        self.assertIn('if: always()', jobs['ci-passed'])
        self.assertNotIn('pull_request_target', workflow)

    @unittest.skipUnless(BASH and shutil.which('jq'), 'Bash and jq required')
    def test_aggregate_rejects_failure_skip_and_cancel_except_non_pr_optional_jobs(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        job = workflow.split('  ci-passed:\n', 1)[1].split('  merge-when-green:\n', 1)[0]
        gate = textwrap.dedent(job.split('        run: |\n', 1)[1]).strip()
        # Exercise the actual workflow command in one shell, including all result pairs.
        commands = ['gate() {\n' + gate + '\n}']
        required = ('hook', 'python-lint', 'package', 'worker', 'secrets')
        for event in ('pull_request', 'push', 'schedule'):
            cases = []
            for safety, dependencies in itertools.product(('success', 'failure', 'skipped', 'cancelled'), repeat=2):
                needs = {key: {'result': 'success'} for key in (*required, 'safety', 'dependencies')}
                needs['safety']['result'] = safety
                needs['dependencies']['result'] = dependencies
                # Only Safety may be skipped, and only outside pull_request.
                expected = dependencies == 'success' and (
                    safety == 'success' or (safety == 'skipped' and event != 'pull_request'))
                cases.append((needs, expected))
            for job, state in itertools.product(required, ('failure', 'skipped', 'cancelled')):
                needs = {key: {'result': 'success'} for key in (*required, 'safety', 'dependencies')}
                needs[job]['result'] = state
                cases.append((needs, False))
            for needs, expected in cases:
                commands.append(f"EVENT_NAME='{event}' NEEDS_JSON='{json.dumps(needs)}' gate >/dev/null 2>&1")
                commands.append(f'[ "$?" -eq {0 if expected else 1} ] || exit 99')
        result = subprocess.run([BASH], input='\n'.join(commands), cwd=ROOT,
                                capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(BASH, 'Bash required')
class SafetyTests(unittest.TestCase):
    def run_policy(self, **changes):
        parent = ROOT / '.agent-test-tmp'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            fake = root / 'bin'
            fake.mkdir()
            scripts = {
                'curl': 'exit "${DOWNLOAD_STATUS:-0}"\n',
                'sha256sum': 'cat >/dev/null\nexit "${CHECKSUM_STATUS:-0}"\n',
                'tar': 'cp "$FAKE_GITLEAKS" "$4/gitleaks"\nchmod +x "$4/gitleaks"\n',
                'gitleaks': 'printf "%s\\n" "$*" > "$SCAN_ARGS"\nexit "${SCAN_STATUS:-0}"\n',
                'gh': '''
                    case "$*" in
                      *'/pulls/'*) printf '%s\\n' "$CHANGED_FILES" ;;
                      *'/contents/.github?ref='*)
                        [ "${API_STATUS:-0}" -eq 0 ] || exit "$API_STATUS"
                        printf '%s\\n' "$BASE_ENTRIES" ;;
                      *'/contents/.github/safety-critical.txt?ref='*)
                        [ "${RULE_STATUS:-0}" -eq 0 ] || exit "$RULE_STATUS"
                        printf '%s\\n' "$BASE_RULES" ;;
                      *) exit 99 ;;
                    esac
                ''',
            }
            for name, content in scripts.items():
                path = fake / name
                path.write_text('#!/usr/bin/env bash\nset -eu\n' + textwrap.dedent(content), newline='\n')
                path.chmod(0o755)
            env = dict(os.environ, FAKE_BIN=fake.as_posix(),
                       PR_DIR=root.as_posix(), TMPDIR=root.as_posix(),
                       REPO='test/repo', PR='123', BASE='a' * 40, COMMITS='3',
                       FAKE_GITLEAKS=(fake / 'gitleaks').as_posix(),
                       SCAN_ARGS=(root / 'scan-args').as_posix(), CHANGED_FILES='docs/test.md',
                       BASE_ENTRIES='scripts\nworkflows', BASE_RULES='')
            env.update(changes)
            # Resolve inside Bash so Windows drive colons never split the mock PATH.
            command = 'export PATH="$(cd "$FAKE_BIN" && pwd):$PATH"; exec bash .github/scripts/safety.sh'
            result = subprocess.run([BASH, '-c', command], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=15,
                                    creationflags=NO_WINDOW)
            args = (root / 'scan-args').read_text() if (root / 'scan-args').exists() else ''
            return result.returncode, result.stdout + result.stderr, args

    def test_scan_pins_and_commit_range(self):
        script = (ROOT / '.github/scripts/safety.sh').read_text()
        self.assertIn('/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz', script)
        self.assertIn('5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba', script)
        code, output, args = self.run_policy()
        self.assertEqual(code, 0, output)
        self.assertEqual(args.strip(), 'git --no-banner --redact --log-opts=-n 3 .')
        self.assertIn('no critical effect', output)

    def test_public_self_protection(self):
        for path in ('.github/scripts/safety.sh', '.github/safety-critical.txt', '.github/workflows/ci.yml'):
            code, output, _ = self.run_policy(CHANGED_FILES=path)
            self.assertEqual(code, 1, output)
            self.assertIn('needs owner:', output)

    def test_base_rules_apply_to_all_pages_and_rename_sources(self):
        code, output, _ = self.run_policy(
            CHANGED_FILES='docs/new.md\ncore/critical.py', BASE_ENTRIES='safety-critical.txt',
            BASE_RULES='# comment\n\n^core/critical\\.py$ :: critical effect')
        self.assertEqual(code, 1, output)
        self.assertIn('core/critical.py (critical effect)', output)
        script = (ROOT / '.github/scripts/safety.sh').read_text()
        self.assertIn('gh api --paginate', script)
        self.assertIn('.previous_filename', script)
        self.assertIn('safety-critical.txt?ref=$BASE', script)

    def test_scan_api_and_rule_failures_fail_closed(self):
        for changes in (dict(DOWNLOAD_STATUS='2'), dict(CHECKSUM_STATUS='2'),
                        dict(SCAN_STATUS='1'), dict(API_STATUS='1'),
                        dict(BASE_ENTRIES='safety-critical.txt', RULE_STATUS='1'),
                        dict(BASE_ENTRIES='safety-critical.txt', BASE_RULES='[ :: invalid regex')):
            with self.subTest(changes=changes):
                code, output, _ = self.run_policy(**changes)
                self.assertNotEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main()
