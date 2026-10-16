"""Publication guard regressions; synthetic strings, no real credentials."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_guard', Path(__file__).parents[1] / 'check-release.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='release-guard-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.override = patch.object(guard, 'ROOT', self.root)
        self.override.start()
        self.addCleanup(self.override.stop)

    def scan(self, staged=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = guard.scan(staged)
        return result, output.getvalue()

    def write(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def test_blank_example_does_not_consume_next_line(self):
        self.write('deepseek.env.example', 'DEEPSEEK_API_KEY=\nDEER_FLOW_DATE_TIMEZONE=Asia/Shanghai\n')
        self.assertEqual(0, self.scan()[0])

    def test_nonworking_recovery_sentinel_allowed(self):
        self.write('fixture.txt', 'DEEPSEEK_API_KEY=disabled-isolated-recovery')
        self.assertEqual(0, self.scan()[0])

    def test_realistic_key_fails_without_echo(self):
        secret = 'sk-' + 'a1B2c3' * 8
        self.write('config.txt', 'API_KEY=' + secret)
        result, output = self.scan()
        self.assertEqual(1, result)
        self.assertNotIn(secret, output)

    def test_private_filename_fails_even_empty(self):
        self.write('account-credentials.private.json', '{}')
        self.assertEqual(1, self.scan()[0])

    def test_broken_private_evidence_link_fails(self):
        self.write('README.md', '[private](.local/not-published.txt)')
        self.assertEqual(1, self.scan()[0])

    def test_invalid_source_and_json_fail(self):
        self.write('broken.py', 'def broken(')
        self.write('broken.json', '{')
        self.assertEqual(1, self.scan()[0])

    def test_index_blob_is_scanned_even_when_worktree_clean(self):
        self.write('safe.txt', 'clean worktree')
        secret = 'sk-' + 'y' * 32
        def git(*args):
            if args == ('rev-parse', '--show-toplevel'):
                return str(self.root).encode()
            if args == ('ls-files', '--stage', '-z'):
                return b'100644 abc 0\tsafe.txt\0'
            if args == ('show', ':safe.txt'):
                return secret.encode()
            raise AssertionError(args)
        with patch.object(guard, 'git', side_effect=git):
            result, output = self.scan(staged=True)
        self.assertEqual(1, result)
        self.assertNotIn(secret, output)

    def test_parent_repository_is_rejected(self):
        with patch.object(guard, 'git', return_value=str(self.root.parent).encode()):
            self.assertEqual(1, self.scan(staged=True)[0])


if __name__ == '__main__':
    unittest.main()
