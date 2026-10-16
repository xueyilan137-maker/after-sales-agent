"""Operator-only private recovery snapshot, run in the existing Gateway.

No account mutation or model calls. Destination must be a new /tmp directory.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from after_sales import store

root = Path(sys.argv[1])
assert root.parent == Path('/tmp') and not root.exists(), 'Use a new immediate /tmp directory'
root.mkdir(mode=0o700)
for name in ('business','home/data','project'):
    (root/name).mkdir(parents=True,exist_ok=True)
with store.connect(write=True):
    with sqlite3.connect(root/'business/business.sqlite3') as target:
        with sqlite3.connect(f'file:{store.state_dir() / "business.sqlite3"}?mode=ro',uri=True) as source:
            source.backup(target)
    shutil.copytree(store.state_dir()/'customer-memory',root/'business/customer-memory')
    shutil.copy2(store.state_dir()/'.identity-key',root/'business/.identity-key')
with sqlite3.connect('file:/app/backend/.deer-flow/data/deerflow.db?mode=ro',uri=True) as source:
    with sqlite3.connect(root/'home/data/deerflow.db') as target:
        source.backup(target)
secret = os.environ.get('AUTH_JWT_SECRET')
if not secret:
    secret = Path('/app/backend/.deer-flow/.jwt_secret').read_text().strip()
(root/'home/.jwt_secret').write_text(secret)
for name in ('config.yaml','extensions_config.json'):
    shutil.copy2(Path('/app/project')/name,root/'project'/name)
for path in root.rglob('*'):
    path.chmod(0o700 if path.is_dir() else 0o600)
manifest = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}
(root/'snapshot-manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'snapshot':str(root),'files':len(manifest),'business_integrity':sqlite3.connect(root/'business/business.sqlite3').execute('pragma integrity_check').fetchone()[0],
                  'auth_integrity':sqlite3.connect(root/'home/data/deerflow.db').execute('pragma integrity_check').fetchone()[0]}))
