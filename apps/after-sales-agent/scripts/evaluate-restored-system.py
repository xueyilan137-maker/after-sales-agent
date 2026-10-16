"""Eight predeclared HTTP samples and restored-state checks, no model calls.

Run only inside the named network-none recovery container. Private output /tmp.
"""
import hashlib
import http.cookiejar
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE='http://127.0.0.1:8001'
results=[]
class Client:
    def __init__(self):
        self.jar=http.cookiejar.CookieJar()
        self.http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def call(self,method,path,body=None,expected=200,form=False):
        headers={'Origin':BASE}
        csrf=next((c.value for c in self.jar if c.name=='csrf_token'),None)
        if csrf: headers['X-CSRF-Token']=csrf
        raw=None
        if body is not None:
            raw=urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        request=urllib.request.Request(BASE+path,data=raw,headers=headers,method=method)
        try: response=self.http.open(request,timeout=15)
        except urllib.error.HTTPError as e: response=e
        value=json.loads(response.read())
        assert response.code==expected, {'path':path,'actual':response.code,'expected':expected,'error':value}
        return value

deadline=time.monotonic()+90
while True:
    try:
        urllib.request.urlopen(BASE+'/health',timeout=2).close(); break
    except Exception:
        if time.monotonic()>deadline: raise
        time.sleep(2)

source=Path('/recovery-snapshot')
auth=sqlite3.connect('/app/backend/.deer-flow/data/deerflow.db')
original_auth=sqlite3.connect('file:/recovery-snapshot/home/data/deerflow.db?mode=ro&immutable=1',uri=True)
assert auth.execute('select * from users order by id').fetchall()==original_auth.execute('select * from users order by id').fetchall()
business=sqlite3.connect('/app/after-sales-data/business.sqlite3')
original_business=sqlite3.connect('file:/recovery-snapshot/business/business.sqlite3?mode=ro&immutable=1',uri=True)
tables=['orders','tickets','proposals','movements','events','demo_runs','evidence','shipping_followups']
for table in tables:
    assert business.execute('select * from '+table+' order by rowid').fetchall()==original_business.execute('select * from '+table+' order by rowid').fetchall(), table
memory_hash=lambda root:{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
assert memory_hash(Path('/app/after-sales-data/customer-memory'))==memory_hash(source/'business/customer-memory')
credentials=json.loads(Path('/recovery-credentials.json').read_text())
fixtures=json.loads(Path('/recovery-fixtures.json').read_text())
clients={}
for label in ('a','b'):
    c=clients[label]=Client()
    c.call('GET','/api/v1/auth/setup-status')
    c.call('POST','/api/v1/auth/login/local',{'username':credentials[label]['email'],'password':credentials[label]['password'],'remember_me':'false'},form=True)
    me=c.call('GET','/api/v1/auth/me')
    assert me['id']==credentials[label]['id'] and me['system_role']=='user'
    ticket=c.call('GET','/api/after-sales/tickets/'+fixtures[label]['ticket_id'])
    assert ticket['ticket_id']==fixtures[label]['ticket_id']
    assert c.call('GET','/api/after-sales/customer-memory')['preferences']==[]
recovery={'original_user_records_equal':True,'business_eight_tables_equal':True,'memory_files_equal':True,
          'real_password_logins':2,'owner_fixtures_read':2,'empty_preferences_consistent':True,
          **json.loads(Path('/tmp/recovery-bootstrap-result.json').read_text())}
Path('/tmp/recovery-result.json').write_text(json.dumps(recovery,indent=2))

c=clients['a']
def scenario(case,scenario_id,description,evidence='评测合成文字资料',preference='reship',logistics=False,expected='manual_review'):
    started=time.monotonic()
    order=c.call('POST','/api/after-sales/demo-runs',{'scenario_id':scenario_id})['order']
    body={'order_id':order['order_id'],'damage_description':description,'evidence_note':evidence,
          'requested_resolution':None if logistics else preference,'case_kind':'logistics' if logistics else 'damage'}
    ticket=c.call('POST','/api/after-sales/tickets',body)
    proposal=c.call('POST','/api/after-sales/tickets/'+ticket['ticket_id']+'/proposal',{})
    assert proposal['status']==expected and not proposal['operations']
    results.append({'case':case,'expected':expected,'actual':proposal['status'],'pass':True,'seconds':round(time.monotonic()-started,3),'ticket_id':ticket['ticket_id']})
    return proposal
try:
    scenario('E01_missing_information','damage-in-window','杯柄松脱',evidence='',preference=None,expected='awaiting_information')
    pending=scenario('E02_complete_intake','damage-in-window','杯沿可见缺口，客户选择补发',expected='awaiting_approval')
    scenario('E03_late_claim','damage-late','发现杯体裂纹，需要处理')
    scenario('E04_high_value','damage-high-value','高金额合成商品出现裂痕')
    scenario('E05_delivery_conflict','shipping-disputed','轨迹写签收但客户声明没有收到',logistics=True)
    before=business.execute('select count(*) from movements').fetchone()[0]
    c.call('POST','/api/after-sales/proposals/'+pending['proposals'][0]['proposal_id']+'/execute',{},expected=403)
    assert business.execute('select count(*) from movements').fetchone()[0]==before
    results.append({'case':'E06_unprivileged_execution','expected':403,'actual':403,'pass':True})
    c.call('GET','/api/after-sales/tickets/'+fixtures['b']['ticket_id'],expected=404)
    results.append({'case':'E07_cross_owner','expected':404,'actual':404,'pass':True})
    found=c.call('GET','/api/after-sales/knowledge?query=holdout_qzx_827461&ticket_id='+pending['ticket_id'])
    assert not found['matches'] and not found['cases']
    results.append({'case':'E08_no_retrieval_match','expected':'empty','actual':'empty','pass':True})
finally:
    Path('/tmp/engineering-evaluation.json').write_text(json.dumps({'model_called':False,'samples':results,'scope':'restored Gateway HTTP, ordinary real sessions; not Agent score'},ensure_ascii=False,indent=2))
print(json.dumps({'recovery':recovery,'engineering_passed':len(results),'engineering_total':8}))
