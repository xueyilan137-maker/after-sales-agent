"""Dependency-free publication guard; never prints matched credential values."""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', 'vendor', '.local', '.venv', 'node_modules', '__pycache__'}
BAD_PARTS = EXCLUDED - {'.git'} | {'.deer-flow', '.next', 'backups'}
BAD_SUFFIXES = ('.sqlite', '.sqlite3', '.db', '.pem', '.key', '.log', '.tar', '.tar.gz', '.zip', '.png', '.jpg', '.webp', '.pyc')
RULES = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider-key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'jwt': re.compile(r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
    'aws-key': re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    'personal-windows-path': re.compile(r'[A-Za-z]:[\\/]Users[\\/][^\s/\\]+', re.I),
    'credential-literal': re.compile(r'''(?:api[_-]?key|secret|password|access[_-]?token)[ \t]*[:=][ \t]*['"]?([A-Za-z0-9_+/=-]{24,})''', re.I),
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def scan(staged=False):
    errors = []
    if staged:
        if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != ROOT:
            print('FAIL <index> [not-an-independent-repository]')
            return 1
        entries = [e.split(b'\t', 1) for e in git('ls-files', '--stage', '-z').split(b'\0') if e]
        paths = []
        for metadata, raw_name in entries:
            name = raw_name.decode('utf-8')
            if metadata.split()[0] not in (b'100644', b'100755'):
                errors.append((name, 'index-mode-or-submodule'))
            paths.append(name)
        if not paths:
            errors.append(('<index>', 'empty-index'))
        contents = {p: git('show', ':' + p) for p in paths}
    else:
        paths = []
        # Ignore generated/private trees; staged mode separately rejects them.
        import os
        for current, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
            paths.extend((Path(current) / f).relative_to(ROOT).as_posix() for f in sorted(files))
        contents = {p: (ROOT / p).read_bytes() for p in paths if not (ROOT / p).is_symlink()}
        for p in set(paths) - set(contents):
            errors.append((p, 'symlink'))
    for name, raw in contents.items():
        path = PurePosixPath(name)
        if any(p in BAD_PARTS for p in path.parts) or name.endswith(BAD_SUFFIXES) or \
           (path.name.startswith('.env') and path.name != '.env.example') or \
           re.search(r'account-(?:credentials|fixtures)|checkpoint.*\.json|\.before-business-', path.name):
            errors.append((name, 'private-or-generated-file'))
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            errors.append((name, 'non-text-file'))
            continue
        for rule, pattern in RULES.items():
            for match in pattern.finditer(text):
                if rule == 'credential-literal' and match.group(1) == 'disabled-isolated-recovery':
                    continue  # Explicit non-working isolated-recovery sentinel.
                errors.append((name + ':' + str(text.count('\n', 0, match.start()) + 1), rule))
        try:
            if name.endswith('.py'):
                ast.parse(text, filename=name)
            if name.endswith('.json'):
                json.loads(text)
        except (SyntaxError, ValueError):
            errors.append((name, 'syntax'))
        if name.endswith('.md'):
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
                target = target.strip('<>').split('#', 1)[0]
                if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('/api/'):
                    continue
                resolved = ((ROOT / name).parent / unquote(target)).resolve()
                try:
                    relative = resolved.relative_to(ROOT).as_posix()
                except ValueError:
                    errors.append((name, 'link-outside-repo'))
                    continue
                if staged:
                    exists = relative in contents or any(p.startswith(relative.rstrip('/') + '/') for p in contents)
                else:
                    exists = resolved.exists()
                if not exists:
                    errors.append((name, 'broken-link:' + target))
    for location, rule in errors:
        print(f'FAIL {location} [{rule}]')
    print(json.dumps({'mode': 'staged' if staged else 'source', 'files': len(contents), 'failures': len(errors)}))
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true')
    sys.exit(scan(parser.parse_args().staged))
