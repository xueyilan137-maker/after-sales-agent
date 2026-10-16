"""Start the restored Gateway in an isolated container, never production."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

source = Path('/recovery-snapshot')
manifest = json.loads((source/'snapshot-manifest.json').read_text())
assert all(hashlib.sha256((source/p).read_bytes()).hexdigest()==h for p,h in manifest.items())
for name, destination in (('business','/app/after-sales-data'),('home','/app/backend/.deer-flow'),('project','/app/project')):
    shutil.copytree(source/name,destination,dirs_exist_ok=True)
suffix = '.before-business-20261015T000000000000'
config = Path('/app/project/config.yaml')
extension = Path('/app/project/extensions_config.json')
expected = {}
for p in (config,extension):
    expected[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    shutil.copy2(p,p.with_name(p.name+suffix))
config.write_text('config_version: 45\nrecovery_probe: true\n')
extension.write_text('{"recovery_probe":true}')
before_files = set(config.parent.glob('*.before-business-*'))
subprocess.run(['/app/backend/.venv/bin/python','/app/business-mcp/configure_business.py','--restore-suffix',suffix],check=True)
assert all(hashlib.sha256(p.read_bytes()).hexdigest()==expected[p.name] for p in (config,extension))
assert len(set(config.parent.glob('*.before-business-*')) - before_files)==2
assert Path('/app/backend/.deer-flow/.jwt_secret').read_bytes()==(source/'home/.jwt_secret').read_bytes()
assert Path('/app/after-sales-data/.identity-key').read_bytes()==(source/'business/.identity-key').read_bytes()
Path('/tmp/recovery-bootstrap-result.json').write_text(json.dumps({'snapshot_hashes_match':True,'original_restore_command_passed':True,'current_pair_backed_up':True,'auth_and_mcp_signing_material_restored':True}))
os.chdir('/app/backend')
os.execv('/app/backend/.venv/bin/python',['/app/backend/.venv/bin/python','-m','uvicorn','app.gateway.app:app','--host','127.0.0.1','--port','8001','--workers','1'])
