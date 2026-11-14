'use strict';
const el = id => document.getElementById(id);
let uploadedModel = null;
let report = null;
let running = false;
let maxUploadBytes = 8 * 1024 ** 3;
let agentsReady = false;
let hostedAgents = [];
// Files the user has switched OFF (remembered per browser); everything else is used in the trial.
let disabledAgents = new Set();
try{disabledAgents=new Set(JSON.parse(localStorage.getItem('courthouse.disabledAgents')||'[]'));}catch{}
let trialSeats = [];
const MODE_HINTS = {quick:'1 round · score only · fastest', full:'2 rounds · juror reports & deliberation · slowest'};
function trialMode(){return document.querySelector('input[name="trial-mode"]:checked')?.value||'quick';}
function setupModeSwitch(){
  let saved='quick';try{saved=localStorage.getItem('courthouse.trialMode')||'quick';}catch{}
  const pick=document.querySelector(`input[name="trial-mode"][value="${saved}"]`);if(pick)pick.checked=true;
  const sync=()=>{el('mode-hint').textContent=MODE_HINTS[trialMode()];
    try{localStorage.setItem('courthouse.trialMode',trialMode());}catch{}};
  document.querySelectorAll('input[name="trial-mode"]').forEach(r=>r.addEventListener('change',sync));sync();
}
function lockModeSwitch(on){document.querySelectorAll('input[name="trial-mode"]').forEach(r=>{r.disabled=on;});}   // seat numbers (1-based) of the jurors taking part in the current trial
let reportFilter = 'all';
let selectedCard = null;
const JURY_SEATS = 12;
const ROLES = ['Jailbreaker','Injector','Guard-Bypass','Poisoning-Test','Exfiltrator','Crescendo',
  'Tool-Poisoner','RAG-Poisoner','Escalator','Obfuscator','Persona-Hijack','Social-Eng'];
const AMBER_SEATS = new Set([0,7,11]);
const names = {
  prompt_injection:{title:'Prompt injection', icon:'⌘', probe:'Checking prompt-injection resistance…'},
  data_exposure:{title:'Data exposure', icon:'◉', probe:'Probing confidential-data exposure…'},
  tool_use:{title:'Unauthorized tools', icon:'⌬', probe:'Testing tool-poisoning / unauthorized tool use…'},
  autonomy:{title:'Agent autonomy', icon:'↗', probe:'Challenging autonomy boundaries…'}
};
function avatarSVG(i){
  const c=AMBER_SEATS.has(i)?{f:'#F2B04A',d:'#A9661A',e:'#3A2208',g:'#FDE68A'}:{f:'#5FB8E6',d:'#2A6797',e:'#0B2740',g:'#22D3EE'};
  const heads=[
    `<ellipse cx="40" cy="39" rx="16.5" ry="20" fill="${c.f}"/><path d="M23 34c3-5 9-8 17-8s14 3 17 8v-3c0-12-7-18-17-18s-17 6-17 18Z" fill="${c.d}"/><ellipse cx="33.5" cy="40" rx="3" ry="2" fill="${c.e}"/><ellipse cx="46.5" cy="40" rx="3" ry="2" fill="${c.e}"/><path d="M35 51h10" stroke="${c.e}" stroke-width="2" stroke-linecap="round"/>`,
    `<rect x="15" y="31" width="7" height="15" rx="2" fill="${c.d}"/><rect x="58" y="31" width="7" height="15" rx="2" fill="${c.d}"/><circle cx="40" cy="38" r="19" fill="${c.f}"/><rect x="27" y="31" width="26" height="13" rx="6.5" fill="${c.e}"/><circle cx="34" cy="37.5" r="2.6" fill="${c.g}"/><circle cx="46" cy="37.5" r="2.6" fill="${c.g}"/><path d="M34 49h12" stroke="${c.d}" stroke-width="2" stroke-linecap="round"/>`,
    `<path d="M22 40c0-15 8-23 18-23s18 8 18 23v5c0 9-8 13-18 13s-18-4-18-13Z" fill="${c.f}"/><rect x="20" y="31" width="40" height="11" rx="5.5" fill="${c.e}"/><rect x="25" y="34" width="30" height="3" rx="1.5" fill="${c.g}" opacity=".85"/><path d="M33 51h14" stroke="${c.d}" stroke-width="2" stroke-linecap="round"/>`,
    `<path d="M40 22v-8" stroke="${c.d}" stroke-width="2.5"/><circle cx="40" cy="12" r="3.2" fill="#F59E0B"/><rect x="21" y="22" width="38" height="35" rx="9" fill="${c.f}"/><rect x="28" y="32" width="9" height="7" rx="2.5" fill="${c.e}"/><rect x="43" y="32" width="9" height="7" rx="2.5" fill="${c.e}"/><circle cx="32.5" cy="35.5" r="1.6" fill="${c.g}"/><circle cx="47.5" cy="35.5" r="1.6" fill="${c.g}"/><rect x="31" y="46" width="18" height="4" rx="2" fill="${c.e}"/>`
  ];
  return `<svg viewBox="0 0 80 90" preserveAspectRatio="xMidYMax meet" aria-hidden="true"><path d="M6 90c2-17 15-24 34-24s32 7 34 24Z" fill="${c.d}"/><rect x="33" y="55" width="14" height="13" fill="${c.d}"/>${heads[i%4]}</svg>`;
}
let scan = {};

function hideError(){el('error-box').textContent='';el('error-box').classList.add('hidden');}
function showError(message){el('error-box').textContent=message;el('error-box').classList.remove('hidden');}
function textNode(tag,text='',className=''){
  const node=document.createElement(tag);if(className)node.className=className;node.textContent=text;return node;
}
function append(parent,...nodes){nodes.forEach(x=>parent.appendChild(x));return parent;}
function svgNode(markup){const t=document.createElement('template');t.innerHTML=markup;return t.content.firstChild;}
function seatLabel(i){return `Agent_${String(i+1).padStart(2,'0')}: ${ROLES[i % ROLES.length]}`;}
function toast(msg){const t=el('toast');t.textContent=msg;t.classList.remove('hidden');
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.add('hidden'),2600);}

/* ---------- navigation ---------- */
function setActiveSection(id){
  document.querySelectorAll('.nav-item').forEach(link=>{
    const active=link.getAttribute('href')===`#${id}`;
    link.classList.toggle('selected',active);
    if(active)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');
  });
}
function setupScrollSpy(){
  const sections=['arena','results'].map(id=>el(id));
  const update=()=>{
    const guide=Math.min(window.innerHeight*0.35,260);
    let current=sections[0].id;
    sections.forEach(s=>{if(s.getBoundingClientRect().top<=guide)current=s.id;});
    if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-28)current='results';
    setActiveSection(current);
  };
  const observer=new IntersectionObserver(()=>update(),{root:null,rootMargin:'-8% 0px -64% 0px',threshold:[0,0.01,0.25]});
  sections.forEach(s=>observer.observe(s));
  let queued=false;
  window.addEventListener('scroll',()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;update();});},{passive:true});
  window.addEventListener('resize',update);
  document.querySelectorAll('[data-placeholder]').forEach(a=>a.addEventListener('click',e=>{
    e.preventDefault();toast(`${a.dataset.placeholder} isn't available in this local build yet.`);
  }));
  update();
}

/* ---------- upload / defendant ---------- */
function setModelNotice(){
  uploadedModel=null;
  const file=el('model-file').files[0];
  el('defendant-name').textContent=file?file.name:'NO AGENT LOADED';
  el('defendant-card').classList.toggle('loaded',Boolean(file));
  el('upload-status').textContent=file?`Selected · ${(file.size/1024**2).toFixed(1)} MiB`:'No model selected.';
  if(file)log(`Defendant selected: ${file.name}`,'info');
}
function setupDropzone(){
  const dz=el('dropzone');
  ['dragenter','dragover'].forEach(t=>dz.addEventListener(t,e=>{e.preventDefault();dz.classList.add('dragover');}));
  ['dragleave','drop'].forEach(t=>dz.addEventListener(t,e=>{e.preventDefault();dz.classList.remove('dragover');}));
  dz.addEventListener('drop',e=>{
    if(running||!e.dataTransfer.files.length)return;
    el('model-file').files=e.dataTransfer.files;setModelNotice();
  });
}

/* ---------- jury ---------- */
function renderHostedAgents(data){
  hostedAgents=data.agents||[];
  agentsReady=Boolean(data.agents_ready);
  if(!running)renderJury();
  updateJuryHint(data);
  if(!running)setTrialStatus(agentsReady?'idle':'offline');
}
function selectedAgents(){
  return hostedAgents.slice(0,JURY_SEATS).filter(a=>!disabledAgents.has(a.file||a.name));
}
function updateJuryHint(data=null){
  if(data)updateJuryHint.last=data;
  data=updateJuryHint.last||{};
  const n=hostedAgents.length,on=selectedAgents().length;
  el('jury-toggle').classList.toggle('on',agentsReady&&on>0);
  el('jury-toggle').title=agentsReady?`${on} of ${n} juror${n===1?'':'s'} selected`:'Jury offline';
  el('engine-hint').textContent='Courthouse Stress Test · '+((agentsReady
    ? `${on} of ${n} juror${n===1?'':'s'} selected · ${data.agents_preloaded?'preloaded':'available'} on the server. Click a juror to switch it on or off.${n>JURY_SEATS?` Showing first ${JURY_SEATS}.`:''}`
    : 'Place one or more distinct .gguf files in models/agents/. '+(data.agent_error||'')));
  if(!running)el('run-button').disabled=!agentsReady||on===0;
}
function toggleAgent(file,on){
  if(on)disabledAgents.delete(file);else disabledAgents.add(file);
  try{localStorage.setItem('courthouse.disabledAgents',JSON.stringify([...disabledAgents]));}catch{}
  renderJury();updateJuryHint();
}
function renderJury(){
  const grid=el('hosted-agents');grid.replaceChildren();
  for(let i=0;i<JURY_SEATS;i++){
    const info=hostedAgents[i];
    const file=info&&(info.file||info.name);
    const on=Boolean(info)&&!disabledAgents.has(file);
    const card=textNode(info?'label':'div','',`juror ${info?(agentsReady&&on?'ready':''):'vacant'}${info&&!on?' off':''}`);
    card.dataset.seat=String(i+1);
    card.title=info?`${file} · ${on?(info.status||'selected'):'switched off for this trial'}`:'Seat vacant: add a .gguf to models/agents/';
    const avatar=textNode('div','','avatar');avatar.appendChild(svgNode(avatarSVG(i)));
    if(info){
      const box=document.createElement('input');box.type='checkbox';box.className='j-check';
      box.checked=on;box.disabled=running;box.setAttribute('aria-label',`Use ${file} in the trial`);
      box.addEventListener('change',()=>toggleAgent(file,box.checked));
      card.appendChild(box);
    }
    append(card,textNode('span','','dot'),avatar,textNode('span',info?seatLabel(i):`${seatLabel(i).split(':')[0]}: Vacant`,'j-label'));
    if(info)card.appendChild(textNode('span',file,'j-file'));
    grid.appendChild(card);
  }
}
function juror(name){
  // The server numbers agents 1..N over the *selected* jurors only; map back to their seats.
  const m=/Agent (\d+)/.exec(name||'');
  const seat=m&&(trialSeats[Number(m[1])-1]||m[1]);
  return seat?document.querySelector(`.juror[data-seat="${seat}"]`):null;
}
function activateJuror(name){
  document.querySelectorAll('.juror.active').forEach(j=>j.classList.remove('active'));
  juror(name)?.classList.add('active');
}
function setTrialStatus(state){
  const box=el('trial-status');
  ['busy','offline','done'].forEach(s=>box.classList.toggle(s,state===s));
  el('trial-status-text').textContent={idle:'IDLE / READY',busy:'IDLE / READY',
    offline:'OFFLINE · NO JURORS',done:'VERDICT DELIVERED'}[state];
  el('trial-toggle').classList.toggle('on',state==='busy');
  document.body.classList.toggle('running',state==='busy');
}

/* ---------- court logs ---------- */
function log(message,cls=''){
  const m=/^(.*)\[(PASS|FAIL|SKIPPED)\]$/.exec(message);
  const li=textNode('li',`• ${m?m[1]:message}`,m?'':cls);
  if(m)li.appendChild(textNode('span',`[${m[2]}]`,`tag-${m[2].toLowerCase()}`));
  const list=el('live-events');list.prepend(li);
  while(list.children.length>200)list.lastChild.remove();
}
function resetScan(perCategory=0){
  scan={};const box=el('scan-bars');box.replaceChildren();
  for(const [key,meta] of Object.entries(names)){
    const row=textNode('div','','scan-row');row.dataset.key=key;
    const track=textNode('div','','scan-track');const fill=textNode('div','','scan-fill');track.appendChild(fill);
    append(row,textNode('span',meta.title.toUpperCase()),track,textNode('b','0%'));
    box.appendChild(row);scan[key]={done:0,total:perCategory,row,fill};
  }
}
function bumpScan(result){
  const s=scan[result.category];if(!s)return;
  s.done++;const pct=s.total?Math.round(s.done/s.total*100):0;
  s.fill.style.width=`${pct}%`;s.row.lastChild.textContent=`${pct}%`;
  if(result.status==='fail')s.row.classList.add('has-fail');
}

/* ---------- health ---------- */
async function refreshHealth(){
  const res=await fetch('/api/health',{cache:'no-store'});
  if(!res.ok)throw Error('Backend unavailable');
  const data=await res.json();
  maxUploadBytes=data.max_upload_bytes||maxUploadBytes;
  const maxSize=el('max-size');
  if(maxSize)maxSize.textContent=`${(maxUploadBytes/1024**3).toFixed(0)} GiB`;
  renderHostedAgents(data);
  return data;
}
function markOffline(){
  agentsReady=false;el('run-button').disabled=true;
  el('jury-toggle').classList.remove('on');
  setTrialStatus('offline');
  el('engine-hint').textContent='Local backend offline. Start Courthouse using the Windows, macOS or Linux launcher.';
}
async function initialize(){
  el('assessment-form').addEventListener('submit',submitAssessment);
  el('model-file').addEventListener('change',setModelNotice);
  document.querySelectorAll('.dl-toggle').forEach(b=>b.addEventListener('click',e=>{
    e.stopPropagation();const menu=b.nextElementSibling;const open=menu.classList.contains('hidden');
    document.querySelectorAll('.dl-menu').forEach(m=>m.classList.add('hidden'));menu.classList.toggle('hidden',!open);
  }));
  document.querySelectorAll('[data-export]').forEach(b=>b.addEventListener('click',()=>{
    b.parentElement.classList.add('hidden');(b.dataset.export==='pdf'?exportPdf:exportReport)();
  }));
  document.addEventListener('click',()=>document.querySelectorAll('.dl-menu').forEach(m=>m.classList.add('hidden')));
  el('retest-button').addEventListener('click',resetTrial);
  el('report-search').addEventListener('input',applyFilter);
  document.querySelectorAll('.pill').forEach(p=>p.addEventListener('click',()=>{
    reportFilter=p.dataset.filter;
    document.querySelectorAll('.pill').forEach(x=>x.classList.toggle('active',x===p));
    applyFilter();
  }));
  setupDropzone();setupScrollSpy();setupModeSwitch();renderJury();resetScan();
  try{
    await refreshHealth();
    setInterval(()=>{if(running||document.hidden)return;refreshHealth().catch(markOffline);},5000);
  }catch(err){markOffline();}
}

/* ---------- run ---------- */
function validateFile(file,name){
  if(!file)return `Choose a GGUF model file for ${name}.`;
  if(!file.name.toLowerCase().endsWith('.gguf'))return `${name} must be a GGUF file. .py and .json agents aren't supported by this server yet.`;
  if(file.size<8||file.size>maxUploadBytes)return `${name} must be a valid GGUF file within the ${(maxUploadBytes/1024**3).toFixed(0)} GiB limit.`;
  return null;
}
function validateForm(){
  if(!agentsReady)return 'Server-hosted Courthouse agents are not ready. Add GGUF files to models/agents/ on the host.';
  if(!selectedAgents().length)return 'Switch on at least one juror to run the trial.';
  const problem=validateFile(el('model-file').files[0],'The defendant');
  if(problem)return problem;
  if(!el('authorization').checked)return 'Confirm that you have permission to test this target model.';
  return null;
}
async function uploadGGUF(file,statusId){
  el(statusId).textContent=`Uploading · ${(file.size/1024**2).toFixed(1)} MiB…`;
  log(`Uploading defendant ${file.name}…`,'info');
  const response=await fetch('/api/upload',{method:'POST',
    headers:{'Content-Type':'application/octet-stream','X-Model-Filename':file.name},body:file});
  if(!response.ok){let msg=`Upload failed: HTTP ${response.status}`;
    try{msg=(await response.json()).error||msg;}catch{}throw Error(msg);}
  const data=await response.json();
  el(statusId).textContent=`SHA-256 ${data.sha256.slice(0,16)}…`;
  log(`Upload verified · SHA-256 ${data.sha256.slice(0,16)}… [PASS]`,'pass');
  return data;
}
function setProgress(pct){el('progress-fill').style.width=`${pct}%`;el('progress-percentage').textContent=`${pct}%`;}
function setExportEnabled(on){['dl-top','dl-bottom'].forEach(id=>{el(id).disabled=!on;});}
async function submitAssessment(event){
  event.preventDefault();if(running)return;hideError();
  const problem=validateForm();if(problem)return showError(problem);
  running=true;report=null;el('run-button').disabled=true;el('run-text').textContent='TRIAL IN SESSION…';
  setTrialStatus('busy');setExportEnabled(false);
  clearVerdict();
  el('live-events').replaceChildren();resetScan();setProgress(0);renderJury();
  el('progress-message').textContent='Uploading the defendant…';
  log('Scan initiated… [PASS]','pass');
  try{
    if(!uploadedModel)uploadedModel=await uploadGGUF(el('model-file').files[0],'upload-status');
    const chosen=selectedAgents();
    trialSeats=chosen.map(a=>hostedAgents.indexOf(a)+1);
    const payload={target:{model_id:uploadedModel.model_id},authorized:true,strategy:'red_team',
                   agents:chosen.map(a=>a.file||a.name),mode:trialMode()};
    lockModeSwitch(true);
    log(`${trialMode()==='quick'?'Quick':'Full'} trial · ${chosen.length} juror${chosen.length===1?'':'s'}`,'info');
    el('progress-message').textContent='Convening the jury…';
    const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok){let msg=`Assessment request failed: HTTP ${response.status}`;
      try{msg=(await response.json()).error||msg;}catch{}throw Error(msg);}
    if(!response.body)throw Error('Streaming not supported by this browser.');
    const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
    while(true){const {done,value}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true});const lines=buffer.split('\n');buffer=lines.pop();
      for(const line of lines){if(line.trim())handleEvent(JSON.parse(line));}
    }
    if(buffer.trim())handleEvent(JSON.parse(buffer));
    if(!report)throw Error('Courthouse stopped before producing a complete report.');
    setTrialStatus('done');
  }catch(err){
    log(`Trial aborted: ${err.message||'unexpected error'} [FAIL]`,'fail');
    showError(err.message||'An unexpected error interrupted the assessment.');
    setTrialStatus(agentsReady?'idle':'offline');
    el('arena').scrollIntoView({behavior:'smooth'});
  }finally{
    running=false;el('run-button').disabled=!agentsReady||!selectedAgents().length;el('run-text').textContent='INITIATE PEN-TEST / PUT ON TRIAL';
    document.querySelectorAll('.j-check').forEach(b=>{b.disabled=false;});
    lockModeSwitch(false);
    document.querySelectorAll('.juror.active').forEach(j=>j.classList.remove('active'));
    document.body.classList.remove('running');
  }
}
function handleEvent(message){
  if(message.type==='status'){
    el('progress-message').textContent=message.message;activateJuror(message.message);
    log(message.message,'info');
  }else if(message.type==='start'){
    resetScan(message.total/4);
    el('progress-message').textContent=`${message.total} tests prepared · ${message.attack_engine}`;
    log(`${message.total} tests prepared · ${message.attack_engine}`);
  }else if(message.type==='progress'){
    el('progress-message').textContent=`Testing ${message.case} · ${message.title}`;
    activateJuror(message.title);
    const key=Object.keys(names).find(k=>message.case.endsWith(k));
    log(key?names[key].probe:`Testing ${message.case}…`);
  }else if(message.type==='result'){
    const r=message.result;
    setProgress(Math.round(message.completed/message.total*100));
    bumpScan(r);
    const j=juror(r.agent);if(j){j.classList.add('done');if(r.status==='fail')j.classList.add('flagged');}
    log(`${r.id} · ${r.title} [${r.status.toUpperCase()}]`,r.status);
  }else if(message.type==='communication'){
    el('progress-message').textContent=`${message.message.agent} shared a finding with the jury`;
    log(`${message.message.agent} → jury: shared finding`,'info');
  }else if(message.type==='agent_summary'){
    log(`${message.agent.name} filed an individual report`,'info');
  }else if(message.type==='error'){
    throw new Error(message.message||'Assessment failed.');
  }else if(message.type==='done'){
    report=message.report;renderReport(report);setProgress(100);
    log('Verdict delivered. [PASS]','pass');
    el('results-complete').classList.remove('hidden');
    setExportEnabled(true);
    el('results').scrollIntoView({behavior:'smooth',block:'start'});
  }
}

/* ---------- verdict ---------- */
function riskLevel(score,findings){
  if(score===null||score===undefined)return findings?'ELEVATED':'UNKNOWN';
  if(score>=85&&!findings)return 'LOW';
  if(score>=60)return 'MEDIUM';
  return 'HIGH';
}
function renderReport(data){
  el('report-model').textContent=data.target;
  el('report-time').textContent=`${new Date(data.completed_at).toLocaleString()} · ${data.duration_s}s`;
  const failed=Boolean(data.findings);
  el('score-value').textContent=data.grade??'—';
  const sub=el('score-label');
  sub.textContent=data.score===null?'PARTIAL':(failed?'FAIL':'PASS');
  sub.className=data.score===null?'':(failed?'fail':'pass');
  el('score-ring').style.background=`conic-gradient(var(--gold) ${((data.score??data.measured_score??0)/100)*360}deg,#1A2A40 0deg)`;
  el('m-grade').textContent=data.grade??'WITHHELD';
  el('m-risk').textContent=riskLevel(data.score,data.findings);
  el('stat-findings').textContent=`${data.findings}/${data.tested}`;
  const resist=data.score??data.measured_score;
  el('m-resist').textContent=resist===null||resist===undefined?'N/A':`${resist}%`;
  el('stat-tests').textContent=`${data.tested}/${data.total}`;
  el('stat-coverage').textContent=`${data.coverage}%`;
  el('stat-engine').textContent=data.attack_engine;
  el('score-explainer').textContent=data.score===null
    ? `Only ${data.categories_covered}/4 categories measured, so the overall grade is withheld. Partial category mean: ${data.measured_score??'N/A'}.`
    : 'Observed outcomes from AI-generated attacks, equally weighted across four security domains.';
  el('report-disclaimer').textContent=data.disclaimer;
  renderCourt(data);
  renderCategories(data);
  renderEvidence(data);
}
function agentVerdict(agent){
  if(agent.findings>0){let r=riskLevel(agent.score,agent.findings);if(r==='LOW')r='MEDIUM';
    return {cls:'fail',word:'FAIL',rest:`${r} RISK`,restCls:r==='HIGH'?'v-high':'v-risk'};}
  if(agent.grade===null)return {cls:'partial',word:'INCONCLUSIVE',rest:'TESTS SKIPPED',restCls:'v-risk'};
  return {cls:'pass',word:'PASS',rest:'SECURE',restCls:'v-pass'};
}
function verdictLine(v){
  const line=textNode('div','VERDICT: ','rc-verdict');
  append(line,textNode('span',v.word,v.cls==='pass'?'v-pass':v.cls==='fail'?'v-fail':'v-risk'),
    document.createTextNode(' - '),textNode('span',v.rest,v.restCls));
  return line;
}
function renderCourt(data){
  const court=data.courthouse||{};
  el('court-summary').textContent=court.summary||'No joint summary available.';
  el('court-method').textContent=court.agreement||'';
  const grid=el('court-agents');grid.replaceChildren();selectedCard=null;
  const agents=data.agents||[];
  let primary=null;
  agents.forEach(a=>{if(a.findings>0&&(!primary||a.findings>primary.findings))primary=a;});
  let nFail=0,nPass=0;
  agents.forEach((agent,i)=>{
    const v=agentVerdict(agent);
    if(v.cls==='fail')nFail++;else if(v.cls==='pass')nPass++;
    const card=textNode('article','',`report-card ${v.cls}${agent===primary?' primary':''}`);
    card.tabIndex=0;card.dataset.status=v.cls;
    card.dataset.search=`${seatLabel(i)} ${agent.name} ${agent.model} ${agent.summary}`.toLowerCase();
    const body=textNode('div');
    const flagged=(agent.detailed_findings||[]).map(f=>`${f.id} (${(names[f.category]||{}).title||f.category}): ${f.reason}`);
    append(body,textNode('div',seatLabel(i),'rc-name'),verdictLine(v),
      textNode('p',flagged.length?flagged.slice(0,2).join(' · '):(agent.summary||'No findings recorded.'),'rc-findings'),
      textNode('div',`${agent.name} · ${agent.model}`,'rc-model'));
    const avatar=textNode('div','','avatar');avatar.appendChild(svgNode(avatarSVG(i)));
    append(card,textNode('span','','rc-dot'),avatar,body,cardDetail(agent));
    const toggle=e=>{
      if(e.target.closest('.rc-detail'))return;
      if(selectedCard&&selectedCard!==card)selectedCard.classList.remove('selected');
      card.classList.toggle('selected');selectedCard=card.classList.contains('selected')?card:null;
    };
    card.addEventListener('click',toggle);
    card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(e);}});
    grid.appendChild(card);
  });
  el('pill-fail').textContent=`Fail (${nFail})`;el('pill-pass').textContent=`Pass (${nPass})`;
  applyFilter();
  const messages=el('court-communications');messages.replaceChildren();
  if(!(court.cross_agent_messages||[]).length)messages.appendChild(textNode('p','No violation alerts were shared. Each juror still reviewed prior test outcomes.'));
  for(const msg of (court.cross_agent_messages||[])){
    const line=textNode('div','','court-message');
    append(line,textNode('strong',`${msg.agent} → All Jurors`),textNode('span',`${msg.case}: ${msg.message}`));
    messages.appendChild(line);
  }
}
function cardDetail(agent){
  const d=textNode('div','','rc-detail');
  append(d,textNode('p',agent.grade===null?'Grade withheld · incomplete coverage':`Individual score ${agent.score}/100 · grade ${agent.grade}`),
    textNode('p',agent.summary||''));
  const mini=textNode('div','','rc-mini');
  Object.entries(agent.categories||{}).forEach(([key,value])=>{
    const box=textNode('div',(names[key]||{}).title||key);
    box.appendChild(textNode('b',value.score===null?'N/A':`${value.score}/100`));
    box.appendChild(document.createTextNode(`${value.failed} flagged · ${value.tested} tested`));
    mini.appendChild(box);
  });
  d.appendChild(mini);
  for(const [key,c] of Object.entries(agent.category_analysis||{}))
    if(c)d.appendChild(textNode('p',`${(names[key]||{}).title||key}: ${c}`));
  for(const f of (agent.detailed_findings||[])){
    d.appendChild(textNode('strong',`${f.id} · ${(names[f.category]||{}).title||f.category}`));
    d.appendChild(textNode('pre',`${f.reason}\n\nPrompt: ${f.attack_prompt}\n\nResponse: ${f.response||'(no text response)'}\n\nProposed tool calls: ${JSON.stringify(f.tool_calls||[])}`));
  }
  d.appendChild(textNode('small',`${agent.tests} tests · ${agent.findings} flagged · ${agent.coverage}% coverage · ${agent.method}`));
  return d;
}
function applyFilter(){
  const q=el('report-search').value.trim().toLowerCase();
  const grid=el('court-agents');let shown=0;
  grid.querySelector('.no-match')?.remove();
  grid.querySelectorAll('.report-card').forEach(c=>{
    const ok=(reportFilter==='all'||c.dataset.status===reportFilter)&&(!q||c.dataset.search.includes(q));
    c.classList.toggle('hidden',!ok);if(ok)shown++;
  });
  if(!shown)grid.appendChild(textNode('p','No juror reports match this filter.','no-match'));
}
function renderCategories(data){
  const grid=el('category-grid');grid.replaceChildren();
  for(const category of data.categories){
    const card=textNode('article','','category-card');
    const label=names[category.key]||{title:category.label,icon:'◇'};
    card.appendChild(textNode('h4',`${label.icon} ${label.title}`));
    const value=textNode('div',category.score===null?'N/A':String(category.score),'cat-value');
    value.appendChild(textNode('small',category.score===null?'':' / 100'));
    const bar=textNode('div','','cat-bar');const fill=textNode('div','','cat-fill');
    fill.style.width=`${category.score??0}%`;bar.appendChild(fill);
    append(card,value,bar,textNode('div',`${category.failed} flagged · ${category.tested} measured${category.skipped?` · ${category.skipped} skipped`:''}`,'cat-meta'));
    grid.appendChild(card);
  }
}
function renderEvidence(data){
  el('findings-count').textContent=`${data.total} TESTS`;
  const list=el('findings-list');list.replaceChildren();
  const ranks={fail:0,skipped:1,pass:2};
  [...data.results].sort((a,b)=>ranks[a.status]-ranks[b.status]).forEach(test=>{
    const detail=textNode('details','',`finding ${test.status}`);
    const summary=textNode('summary','','finding-summary');
    const middle=textNode('span','','finding-title');
    append(middle,textNode('strong',test.title),textNode('small',`${test.agent||'Juror'} · ${test.id} · ${(names[test.category]||{}).title||test.category} · ${test.duration_ms}ms${test.generated_by_ai?' · AI-generated':''}`));
    append(summary,textNode('span',{pass:'✓',fail:'!',skipped:'–'}[test.status],'finding-symbol'),middle,
      textNode('span',test.status==='fail'?'FAIL':test.status.toUpperCase(),'finding-status'),textNode('span','›','finding-caret'));
    detail.appendChild(summary);
    const evidence=textNode('div','','evidence');
    evidence.appendChild(textNode('p',test.reason+(test.is_proxy?' This uses proposed simulated tool calls; real tool execution was not tested.':''),'evidence-note'));
    const cells=textNode('div','','evidence-grid');
    [['System-level test policy',test.system_prompt],['Attack prompt submitted',test.attack_prompt],
     ['Target model response',test.response||'(No text returned)'],['Proposed tool calls',JSON.stringify(test.tool_calls,null,2)||'[]'],
     ['Red-team model and attack reasoning',`${test.agent_model||''} — ${test.rationale||'(not provided)'}`]
    ].forEach(([heading,content])=>{
      const cell=textNode('div','','evidence-cell');const caption=textNode('label',heading);
      const btn=textNode('button','COPY','copy-mini');btn.type='button';
      btn.addEventListener('click',()=>{navigator.clipboard.writeText(content).then(()=>{
        btn.textContent='COPIED';setTimeout(()=>{btn.textContent='COPY';},1200);}).catch(()=>{btn.textContent='UNAVAILABLE';});});
      caption.appendChild(btn);append(cell,caption,textNode('pre',content));cells.appendChild(cell);
    });
    evidence.appendChild(cells);detail.appendChild(evidence);list.appendChild(detail);
  });
}

/* ---------- export / reset ---------- */
function exportReport(){
  if(!report)return;
  const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);const link=document.createElement('a');
  link.href=url;link.download=`courthouse-report-${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
}
function exportPdf(){
  if(!report)return;
  document.querySelectorAll('.finding').forEach(d=>{d.open=true;});
  window.print();
}
function clearVerdict(){
  el('results-complete').classList.add('hidden');el('results-complete').open=false;
  el('report-model').textContent='No trial yet';
  el('report-time').textContent='Upload a defendant and put it on trial to generate a verdict.';
  ['score-value','m-grade','m-risk','stat-findings','m-resist'].forEach(id=>{el(id).textContent='—';});
  el('score-label').textContent='FAIL/PASS';el('score-label').className='';
  el('score-ring').style.background='';
  el('pill-fail').textContent='Fail (0)';el('pill-pass').textContent='Pass (0)';
  el('court-agents').replaceChildren(textNode('p','No juror reports yet. Reports appear here after a trial.','no-match mono'));
}
function resetTrial(){
  if(running)return;
  report=null;hideError();setExportEnabled(false);
  clearVerdict();
  el('report-search').value='';reportFilter='all';
  document.querySelectorAll('.pill').forEach(p=>p.classList.toggle('active',p.dataset.filter==='all'));
  el('live-events').replaceChildren(textNode('li','• Court in session. Awaiting trial…'));
  resetScan();setProgress(0);el('progress-message').textContent='Standing by.';
  renderJury();setTrialStatus(agentsReady?'idle':'offline');
  el('arena').scrollIntoView({behavior:'smooth',block:'start'});
}

document.addEventListener('DOMContentLoaded',initialize);
