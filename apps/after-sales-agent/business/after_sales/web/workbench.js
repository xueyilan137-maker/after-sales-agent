'use strict';
const base = '/api/after-sales';
const $ = id => document.getElementById(id);
const states = {investigating:'调查中', awaiting_information:'等待补充', awaiting_approval:'待人工审批', approved:'已批准，等待执行', manual_review:'待人工处理', awaiting_followup:'等待物流跟进', resolved:'已解决'};
const eventNames = {damage_report_saved:'损坏资料已保存', logistics_report_saved:'物流资料已保存', proposal_created:'方案已生成', proposal_renewed:'方案已重新核对', proposal_blocked:'规则核对未通过', human_approved:'人工已批准', human_rejected:'人工已拒绝', demo_execution_recorded:'演示操作已登记', evidence_attached:'附件已接入', evidence_reviewed:'附件人工核验已记录', shipping_followup_recorded:'物流人工跟进已记录'};
const preferenceLabels = {language:'沟通语言', contact_channel:'沟通渠道', resolution_preference:'处理倾向'};
const preferenceValues = {language:[['zh-CN','中文'],['en','English']], contact_channel:[['in_app','应用内沟通']], resolution_preference:[['ask_each_time','每次询问'],['refund','倾向退款'],['reship','倾向补发']]};
let selected = null, current = null, admin = false, busy = false, ticketCursor = null;
let scenarios = [], runs = [], preferences = [], formRevision = null, formOrder = null;

function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined) el.textContent = String(text); if (cls) el.className = cls; return el; }
function notice(text) {
  $('notice').textContent = text; $('notice').hidden = !text;
  for (const dialog of document.querySelectorAll('dialog')) {
    let message = dialog.querySelector('.dialog-notice');
    if (!message) { message = node('p', '', 'dialog-notice'); message.setAttribute('role','alert'); dialog.append(message); }
    message.textContent = dialog.open ? text : '';
  }
}
function cookie(name) { const part = document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'=')); return part ? part.slice(name.length+1) : ''; }
async function api(path, method='GET', body) {
  const headers = {}, raw = body instanceof Blob;
  if (method !== 'GET') {
    let csrf = cookie('csrf_token');
    if (!csrf) {
      const recovery = await fetch('/api/v1/auth/me', {credentials:'include', cache:'no-store', signal:AbortSignal.timeout(10000)});
      if (!recovery.ok) throw new Error('登录已失效，请返回对话页重新登录。');
      csrf = cookie('csrf_token');
    }
    if (!csrf) throw new Error('会话令牌无法恢复，请返回对话页重新登录。');
    headers['X-CSRF-Token'] = csrf; headers['Content-Type'] = raw ? body.type || 'application/octet-stream' : 'application/json';
  }
  const response = await fetch(base+path, {method, headers, credentials:'include', cache:'no-store', signal:AbortSignal.timeout(15000), body:body===undefined ? undefined : raw ? body : JSON.stringify(body)});
  if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('服务未返回业务响应，请刷新确认登录与服务状态。');
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail==='string' ? detail : Array.isArray(detail) ? '资料格式不符合要求，请核对输入。' : (detail?.code ? detail.code+'：' : '')+(detail?.message||'请求失败，请刷新工单后继续。'));
  }
  return data;
}
async function action(fn) {
  if (busy) return;
  busy = true; notice(''); document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try { await fn(); }
  catch (err) { notice(err.name==='TimeoutError' ? '请求超时，请刷新确认当前状态后再决定是否重试。' : err.message); }
  finally { busy=false; document.querySelectorAll('button').forEach(b=>b.disabled=b.dataset.unavailable==='true'); }
}
function button(text, fn, cls='') { const b=node('button',text,cls); b.type='button'; b.disabled=busy; b.addEventListener('click',()=>action(fn)); return b; }
function badge(status) { return node('span',states[status]||status,'badge '+(status==='awaiting_approval'?'pending':status==='resolved'?'done':'')); }
function pair(dl,key,value) { dl.append(node('dt',key),node('dd',value)); }
function dateText(value) { return value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})+' +08:00' : '暂无'; }
function link(text,url) { const a=node('a',text); a.href=url; a.target='_blank'; a.rel='noopener'; return a; }

async function load(append=false) {
  const data=await api('/tickets'+(append&&ticketCursor?'?before='+encodeURIComponent(ticketCursor):''));
  if (!append) $('tickets').replaceChildren();
  if (!append&&!data.tickets.length) $('tickets').append(node('li','暂无售后工单','muted empty'));
  for (const ticket of data.tickets) {
    const li=node('li'), b=button('',async()=>{selected=ticket.ticket_id;await load()},'ticket-button');
    b.dataset.ticketId=ticket.ticket_id; b.setAttribute('aria-current',String(selected===ticket.ticket_id));
    b.append(node('div',ticket.ticket_id,'mono'),node('div',(ticket.case_kind==='logistics'?'物流 · ':'损坏 · ')+ticket.order_id,'tiny muted'),badge(ticket.status));
    li.append(b); $('tickets').append(li);
  }
  ticketCursor=data.next_cursor; $('more-tickets').hidden=!ticketCursor;
  if (selected) { current=await api('/tickets/'+encodeURIComponent(selected)); render(current); }
}
async function loadRuns() {
  const result=await api('/demo-runs'); runs=result.runs;
  $('saved-run').replaceChildren(node('option','选择已有实例'));
  $('saved-run').firstChild.value='';
  for (const run of runs) { const option=node('option',run.order_id+' · '+run.scenario_id); option.value=run.order_id; $('saved-run').append(option); }
}
function resolutions(kind, value='') {
  const entries=kind==='logistics' ? [['carrier_inquiry','登记演示物流调查']] : [['','尚未确认，等待补充'],['reship','补发'],['refund','退款']];
  $('resolution').replaceChildren();
  for (const [id,label] of entries) { const option=node('option',label); option.value=id; $('resolution').append(option); }
  $('resolution').value=kind==='logistics'?'carrier_inquiry':value;
}
function reportForm(ticket, orderId='ORD-2026-0017', kind='damage') {
  formRevision=ticket?.revision??null; formOrder=ticket?.order_id??null;
  $('order').value=ticket?.order_id||orderId; $('order').readOnly=!!ticket;
  $('damage').value=ticket?.damage_description||''; $('evidence').value=ticket?.evidence_note||'';
  $('case-kind').value=ticket?.case_kind||kind; $('case-kind').disabled=!!ticket;
  resolutions($('case-kind').value,ticket?.requested_resolution||'');
  $('report-context').textContent=ticket ? '编辑工单版本 '+ticket.revision+'；资料变化会使旧方案和审批失效。' : '新申报由系统记录首次时间；可先读取此订单已有资料。';
  if (!$('report-dialog').open) $('report-dialog').showModal();
}
async function useOrder(orderId) {
  const order=await api('/orders/'+encodeURIComponent(orderId));
  if (order.existing_ticket) reportForm(await api('/tickets/'+order.existing_ticket.ticket_id));
  else { const scenario=scenarios.find(s=>s.scenario_id===order.scenario_id); reportForm(null,order.order_id,scenario?.case_kind||'damage'); }
}

function render(ticket) {
  const detail=$('detail'); detail.replaceChildren();
  const top=node('div',undefined,'row'); top.append(node('h2',ticket.ticket_id,'mono'),badge(ticket.status)); detail.append(top);
  if (ticket.order.clock) detail.append(node('p','独立合成场景 · 业务时钟 '+dateText(ticket.business_reported_at)+'。真实申报 '+dateText(ticket.reported_at)+'；审批有效期按真实时间。','clock-note tiny'));
  const dl=node('dl');
  pair(dl,'问题类型',ticket.case_kind==='logistics'?'物流异常':'商品损坏'); pair(dl,'订单',ticket.order_id);
  pair(dl,'商品',ticket.order.items.map(i=>i.name+' × '+i.quantity).join('、')); pair(dl,'签收',dateText(ticket.order.delivered_at));
  pair(dl,'首次申报',dateText(ticket.reported_at)); pair(dl,'业务申报',dateText(ticket.business_reported_at));
  pair(dl,'本次偏好',ticket.requested_resolution==='refund'?'退款':ticket.requested_resolution==='reship'?'补发':ticket.requested_resolution==='carrier_inquiry'?'登记物流调查':'等待补充');
  pair(dl,'问题描述',ticket.damage_description||'尚未提供'); detail.append(dl,node('h3','客户证据说明'),node('div',ticket.evidence_note||'尚未提供','evidence'));
  if (ticket.case_kind==='logistics') {
    detail.append(node('h3','原始合成物流事件'));
    for (const event of ticket.order.shipping_events||[]) detail.append(node('p',dateText(event.occurred_at)+' · '+event.description,'tiny'));
  }
  renderEvidence(detail,ticket);
  if (!ticket.operations.length) {
    const actions=node('div',undefined,'actions'); actions.append(button('补充资料',async()=>reportForm(ticket)),button('生成处理方案',async()=>{
      const result=await api('/tickets/'+ticket.ticket_id+'/proposal','POST',{}); await load();
      const reasons=[...(result.missing_fields||[]).map(f=>({damage_description:'问题描述',evidence_note:'证据说明',requested_resolution:'本次处理偏好'}[f]||f)),...(result.reasons||[])];
      if (reasons.length) notice('仍需处理：'+reasons.join('；'));
    },'primary')); detail.append(actions);
  }
  const latest=ticket.proposals[0];
  if (latest) {
    const card=node('div',undefined,'proposal'), p=latest.payload;
    card.append(node('div',latest.proposal_id+' · '+latest.status,'mono muted'),node('h3','处理方案 · 资料版本 '+latest.ticket_revision));
    card.append(node('p',p.resolution==='refund'?'演示退款':p.resolution==='reship'?'演示补发':'演示物流调查'));
    if (p.resolution==='refund') card.append(node('div','¥ '+(p.refund_amount_minor/100).toFixed(2),'amount'));
    else if (p.resolution==='reship') card.append(node('p',p.items.map(i=>i.name+' × '+i.quantity).join('、')));
    card.append(node('p','审批有效期至 '+dateText(latest.expires_at),'tiny muted'));
    const refs=node('p',undefined,'tiny'); for (const ref of p.citations) refs.append(link(ref.clause_id+' ',ref.source)); card.append(refs); detail.append(card);
  }
  if (ticket.operations.length) {
    detail.append(node('h3','执行结果')); for (const op of ticket.operations) detail.append(node('p',op.operation_id,'mono'),node('p',op.message));
  }
  for (const followup of ticket.followups) detail.append(node('p','人工合成跟进：'+followup.outcome+' · '+followup.note,'evidence'));
  renderKnowledge(detail,ticket); renderAudit(detail,ticket); renderReview(ticket,latest);
}

function renderEvidence(detail,ticket) {
  detail.append(node('h3','图片附件 · 人工核验'));
  if (!ticket.attachments.length) detail.append(node('p','暂无附件；客户文字陈述也可提交人工审批。','tiny muted'));
  for (const item of ticket.attachments) {
    const card=node('div',undefined,'attachment'), source=base+'/evidence/'+item.evidence_id;
    card.append(link(item.filename,source),node('p',item.review_status==='accepted'?'人工已接受':item.review_status==='rejected'?'人工未接受':'待人工核验','badge'));
    const image=node('img'); image.src=source; image.alt='客户提供的附件：'+item.filename; image.loading='lazy'; card.append(image);
    card.append(node('p','SHA256 '+item.sha256,'mono tiny muted')); if(item.review_note) card.append(node('p',item.review_note,'tiny'));
    if (admin&&!ticket.operations.length) {
      const note=node('textarea'); note.maxLength=1000; note.setAttribute('aria-label',item.filename+' 的人工核验说明'); note.placeholder='填写人工核验说明；不会自动分析图片'; card.append(note);
      const actions=node('div',undefined,'actions');
      for (const [decision,label] of [['accepted','接受此附件'],['rejected','不接受此附件']]) actions.append(button(label,async()=>{
        if(!note.value.trim()) throw new Error('请填写附件核验说明。');
        await api('/tickets/'+ticket.ticket_id+'/evidence/'+item.evidence_id+'/review','POST',{decision,note:note.value,expected_revision:ticket.revision}); await load(); notice('人工核验已记录，需重新生成处理方案。');
      })); card.append(actions);
    }
    detail.append(card);
  }
  if (!ticket.operations.length) {
    const input=node('input'); input.type='file'; input.accept='image/png,image/jpeg,image/webp'; input.setAttribute('aria-label','选择证据图片');
    detail.append(input,node('p','每张工单最多 5 张；每张 4 MiB、1000 万像素以内。仅做格式解码和哈希记录。','tiny muted'),button('接入图片附件',async()=>{
      const file=input.files[0]; if(!file) throw new Error('请先选择图片。'); if(file.size>4*1024*1024) throw new Error('图片不得超过 4 MiB。');
      await api('/tickets/'+ticket.ticket_id+'/evidence?'+new URLSearchParams({filename:file.name,expected_revision:ticket.revision}),'POST',file); await load();
    }));
  }
}
function renderReview(ticket,latest) {
  const review=$('review-area'); review.replaceChildren();
  if (!admin) { review.append(node('p','人工审核和跟进需交互式管理员登录。')); return; }
  if (ticket.status==='awaiting_followup') {
    review.append(node('p','调查已登记，等待人工记录合成跟进。'));
    const note=node('textarea'); note.maxLength=1000; note.placeholder='合成跟进说明（必填）'; note.setAttribute('aria-label','物流跟进说明'); review.append(note);
    for(const [outcome,label] of [['delivered','记录演示送达并关闭'],['manual_review','记录转人工处理']]) review.append(button(label,async()=>{await api('/tickets/'+ticket.ticket_id+'/followup','POST',{outcome,note:note.value,expected_revision:ticket.revision});await load()}));
    return;
  }
  if (latest&&['pending','approved'].includes(latest.status)&&Date.parse(latest.expires_at)<Date.now()) { review.append(node('p','方案已过期，请生成新方案后重新审批。')); return; }
  if (latest?.status==='pending') {
    review.append(node('p','核对陈述、附件、订单与适用政策后决定。'));
    const label=node('label',undefined,'check'), check=node('input'); check.type='checkbox'; label.append(check,node('span','已核对证据并确认此合成方案')); review.append(label);
    const note=node('textarea'); note.maxLength=1000; note.placeholder='审核备注（选填）'; note.setAttribute('aria-label','方案审核备注'); review.append(note);
    const actions=node('div',undefined,'actions');
    for(const [decision,text,cls] of [['approve','批准方案','primary'],['reject','拒绝 / 转人工','danger']]) actions.append(button(text,async()=>{
      if(decision==='approve'&&!check.checked) throw new Error('请先确认已核对证据。');
      await api('/proposals/'+latest.proposal_id+'/review','POST',{expected_digest:latest.digest,decision,note:note.value,evidence_confirmed:check.checked}); await load();
    },cls)); review.append(actions);
    if(ticket.attachments.some(a=>a.review_status!=='accepted')) review.append(node('p','批准前逐一核验附件，再重新生成方案。','tiny'));
  } else if(latest?.status==='approved') review.append(node('p','人工审批已记录，可执行演示方案。'),button('执行演示处理',async()=>{await api('/proposals/'+latest.proposal_id+'/execute','POST',{});await load()},'primary'));
  else review.append(node('p',ticket.status==='resolved'?'处理结果已归档。':latest?.status==='rejected'?'方案被拒绝，等待人工补充资料。':'暂无可审核方案。'));
}
function renderAudit(detail,ticket) {
  detail.append(node('h3','审计记录'));
  const timeline=node('ul',undefined,'timeline');
  function append(events) {
    for(const event of events) {
      const li=node('li'); li.append(node('div',eventNames[event.kind]||event.kind),node('small',dateText(event.created_at)));
      if(event.payload.reasons?.length) li.append(node('p',event.payload.reasons.join('；'),'tiny'));
      if(event.payload.note) li.append(node('p',event.payload.note,'tiny')); timeline.append(li);
      if(event.payload.proposal_id) li.append(link('读取原始方案 ↗',base+'/proposals/'+event.payload.proposal_id));
    }
  }
  append([...ticket.events].reverse()); detail.append(timeline);
  let cursor=ticket.events[0]?.event_id;
  if(cursor) {
    const more=button('加载更早记录',async()=>{const data=await api('/tickets/'+ticket.ticket_id+'/events?before='+cursor);append(data.events);cursor=data.next_cursor;if(!cursor)more.remove()}); detail.append(more);
  }
}
function renderKnowledge(detail,ticket) {
  const box=node('details'), summary=node('summary','检索政策与设计示例'); box.append(summary);
  const query=node('input'); query.maxLength=500; query.placeholder='如：损坏期限、证据、物流停滞'; query.setAttribute('aria-label','政策与案例检索');
  const results=node('div'); box.append(query,button('检索',async()=>{
    if(!query.value.trim()) throw new Error('请输入检索内容。');
    const data=await api('/knowledge?'+new URLSearchParams({query:query.value,ticket_id:ticket.ticket_id})); results.replaceChildren();
    results.append(node('p','适用日期 '+data.as_of+' · 本地词法检索','tiny muted'));
    if(!data.matches.length) results.append(node('p','没有匹配政策条款，请人工核对；相似度不是业务资格判断。'));
    for(const match of data.matches) results.append(link(match.clause_id+' · '+match.title,match.citation.source),node('p',match.text,'tiny'));
    for(const item of data.cases) results.append(link('设计示例 · '+item.title,item.source),node('p',item.text,'tiny muted'));
  }),results); detail.append(box);
}

async function loadMemory() {
  const data=await api('/customer-memory'); preferences=data.preferences; $('memory-list').replaceChildren();
  if(!preferences.length) $('memory-list').append(node('p','暂无已确认偏好。','empty'));
  for(const item of preferences) {
    const row=node('div',undefined,'memory-item'), value=preferenceValues[item.key].find(v=>v[0]===item.value)?.[1]||item.value;
    row.append(node('strong',preferenceLabels[item.key]+' · '+value),node('small','人工确认 · '+dateText(item.confirmed_at)),node('p',item.source_note,'tiny'));
    if(admin) row.append(button('纠正此偏好',async()=>{$('memory-key').value=item.key;memoryValues();$('memory-source').focus()}),button('遗忘此偏好',async()=>{await api('/customer-memory/'+item.fact_id+'/forget','POST',{expected_digest:item.digest});await loadMemory()},'danger'));
    $('memory-list').append(row);
  }
  $('memory-form').hidden=!admin; memoryValues();
}
function memoryValues() {
  const key=$('memory-key').value; $('memory-value').replaceChildren();
  for(const [value,label] of preferenceValues[key]) { const option=node('option',label); option.value=value; $('memory-value').append(option); }
  const existing=preferences.find(item=>item.key===key); if(existing) $('memory-value').value=existing.value;
}

$('refresh').addEventListener('click',()=>action(async()=>{await load();await loadRuns()}));
$('more-tickets').addEventListener('click',()=>action(()=>load(true)));
$('new-report').addEventListener('click',()=>action(async()=>reportForm(null)));
$('lookup-order').addEventListener('click',()=>action(()=>useOrder($('order').value)));
$('case-kind').addEventListener('change',()=>resolutions($('case-kind').value));
for(const id of ['close-dialog','cancel-dialog']) $(id).addEventListener('click',()=>$('report-dialog').close());
$('report-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  const body=Object.fromEntries(new FormData(event.target)); body.case_kind=$('case-kind').value;
  if(formRevision!==null&&formOrder===$('order').value) body.expected_revision=formRevision;
  const ticket=await api('/tickets','POST',body); selected=ticket.ticket_id; $('report-dialog').close(); await load();
})});
$('scenario').addEventListener('change',()=>{$('scenario-description').textContent=scenarios.find(s=>s.scenario_id===$('scenario').value)?.description||''});
$('create-run').addEventListener('click',()=>action(async()=>{const run=await api('/demo-runs','POST',{scenario_id:$('scenario').value});await loadRuns();await useOrder(run.order.order_id)}));
$('use-run').addEventListener('click',()=>action(async()=>{if(!$('saved-run').value)throw new Error('请选择近期演示实例。');await useOrder($('saved-run').value)}));
$('open-memory').addEventListener('click',()=>action(async()=>{await loadMemory();$('memory-dialog').showModal()}));
$('close-memory').addEventListener('click',()=>$('memory-dialog').close());
$('memory-key').addEventListener('change',memoryValues);
$('memory-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  const key=$('memory-key').value, existing=preferences.find(item=>item.key===key);
  await api('/customer-memory','POST',{key,value:$('memory-value').value,source_note:$('memory-source').value,expected_digest:existing?.digest??null});
  $('memory-source').value='';await loadMemory();
})});
action(async()=>{
  const state=await api('/status');admin=state.human_review_available;
  const data=await api('/scenarios');scenarios=data.scenarios;
  for(const scenario of scenarios) { const option=node('option',scenario.title);option.value=scenario.scenario_id;$('scenario').append(option); }
  $('scenario-description').textContent=scenarios[0]?.description||'';
  await load();await loadRuns();
});
