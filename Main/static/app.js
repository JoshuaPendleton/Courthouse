'use strict';
const el = id => document.getElementById(id);
let uploadedModel = null;
let report = null;
let running = false;
let maxUploadBytes = 8 * 1024 ** 3;
let agentsReady = false;
const names = {
  prompt_injection:{title:'Prompt injection', icon:'⌘'},
  data_exposure:{title:'Data exposure',icon:'◉'},
  tool_use:{title:'Unauthorized tools',icon:'⌬'},
  autonomy:{title:'Agent autonomy',icon:'↗'}
};
function hideError(){el('error-box').textContent='';el('error-box').classList.add('hidden');}
function showError(message){el('error-box').textContent=message;el('error-box').classList.remove('hidden');}
function textNode(tag,text,className=''){
  const node=document.createElement(tag);if(className)node.className=className;node.textContent=text;return node;
}
function append(parent,...nodes){nodes.forEach(x=>parent.appendChild(x));return parent;}
function setActiveSection(id){
  document.querySelectorAll('.nav-item').forEach(link=>{
    const active=link.getAttribute('href')===`#${id}`;
    link.classList.toggle('selected',active);
    if(active)link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
}
function setupScrollSpy(){
  const sections=['overview','assessment','results'].map(id=>el(id));
  const update=()=>{
    // Use the top section most recently crossed by the 35% viewport guide.
    const guide=Math.min(window.innerHeight*0.35, 260);
    let current=sections[0].id;
    sections.forEach(section=>{if(section.getBoundingClientRect().top <= guide) current=section.id;});
    // The final Reports section can be too short to cross the guide; mark it active at page end.
    if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-28) current='results';
    setActiveSection(current);
  };
  const observer=new IntersectionObserver(()=>update(),{
    root:null,rootMargin:'-8% 0px -64% 0px',threshold:[0,0.01,0.25]
  });
  sections.forEach(section=>observer.observe(section));
  let queued=false;
  window.addEventListener('scroll',()=>{
    if(queued)return;queued=true;
    requestAnimationFrame(()=>{queued=false;update();});
  },{passive:true});
  window.addEventListener('resize',update);
  document.querySelectorAll('.nav-item').forEach(a=>a.addEventListener('click',()=>{
    setActiveSection(a.hash.slice(1));
  }));
  update();
}
function setModelNotice(){
  uploadedModel=null;
  const file=el('model-file').files[0];
  el('upload-status').textContent=file
    ? `Selected: ${file.name} · ${(file.size/1024**2).toFixed(1)} MiB`
    : 'No model selected.';
}
function renderHostedAgents(data){
  const box=el('hosted-agents');box.replaceChildren();
  const actual=data.agents || [];
  for(let n=1;n<=3;n++){
    const info=actual.find(a=>a.seat===n);
    const row=textNode('div','','hosted-agent');
    row.appendChild(textNode('span','','hosted-dot '+(info&&data.agents_ready?'ready':'missing')));
    row.appendChild(textNode('strong',info?.name || `Courthouse Agent ${n}`));
    row.appendChild(textNode('small',info
      ? `${info.file} · ${info.status}`
      : `Model ${n} not configured · contact the server administrator`));
    box.appendChild(row);
  }
  agentsReady=Boolean(data.agents_ready);
  el('sidebar-engine').textContent=agentsReady ? '3 hosted models ready' : 'Hosted models not ready';
  document.querySelector('.live-dot')?.classList.toggle('not-ready',!agentsReady);
  el('engine-hint').textContent=agentsReady
    ? (data.agents_preloaded
      ? '✓ All 3 independent Courthouse models are preloaded on the server. Upload only the target GGUF.'
      : 'ⓘ All 3 hosted Courthouse models are available and will load on first request. Upload only the target GGUF.')
    : 'ⓘ Courthouse administrator: place 3 different GGUF files in models/agents/, configure config/agent_models.json, and restart. '+(data.agent_error||'');
  el('run-button').disabled=!agentsReady;
}
async function initialize(){
  el('assessment-form').addEventListener('submit',submitAssessment);
  el('model-file').addEventListener('change',setModelNotice);
  el('export-button').addEventListener('click',exportReport);
  setupScrollSpy();
  try{
    const res=await fetch('/api/health',{cache:'no-store'});
    if(!res.ok)throw Error('Backend unavailable');
    const data=await res.json();
    maxUploadBytes=data.max_upload_bytes || maxUploadBytes;
    renderHostedAgents(data);
  }catch(err){
    agentsReady=false;el('run-button').disabled=true;
    el('sidebar-engine').textContent='Local backend offline';
    el('engine-hint').textContent='ⓘ Start Courthouse using the Windows, macOS or Linux launcher.';
  }
}
function validateFile(file,name){
  if(!file)return `Choose a GGUF model file for ${name}.`;
  if(!file.name.toLowerCase().endsWith('.gguf'))return `${name} must be a GGUF file.`;
  if(file.size<8||file.size>maxUploadBytes)return `${name} must be a valid GGUF file within the ${(maxUploadBytes/1024**3).toFixed(0)} GiB limit.`;
  return null;
}
function validateForm(){
  if(!agentsReady)return 'The three server-hosted Courthouse agents are not ready. Contact the administrator.';
  const problem=validateFile(el('model-file').files[0],'the target');
  if(problem)return problem;
  if(!el('authorization').checked)return 'Confirm that you have permission to test this target model.';
  return null;
}
async function uploadGGUF(file,statusId){
  el(statusId).textContent=`Uploading ${file.name} · ${(file.size/1024**2).toFixed(1)} MiB…`;
  const response=await fetch('/api/upload',{method:'POST',
    headers:{'Content-Type':'application/octet-stream','X-Model-Filename':file.name},body:file});
  if(!response.ok){let msg=`Upload failed: HTTP ${response.status}`;
    try{msg=(await response.json()).error||msg;}catch{}throw Error(msg);}
  const data=await response.json();
  el(statusId).textContent=`Uploaded ${data.name} · SHA-256 ${data.sha256.slice(0,16)}…`;
  return data;
}
async function submitAssessment(event){
  event.preventDefault();if(running)return;hideError();
  const problem=validateForm();if(problem)return showError(problem);
  running=true;el('run-button').disabled=true;el('run-text').textContent='Courthouse operating…';
  el('results-empty').classList.add('hidden');el('results-complete').classList.add('hidden');
  el('export-button').classList.add('hidden');el('results-running').classList.remove('hidden');
  el('live-events').replaceChildren();el('progress-fill').style.width='0%';
  el('progress-percentage').textContent='0%';
  el('progress-message').textContent='Uploading your target GGUF model…';report=null;
  el('results').scrollIntoView({behavior:'smooth',block:'start'});
  try{
    if(!uploadedModel)uploadedModel=await uploadGGUF(el('model-file').files[0],'upload-status');
    const payload={target:{model_id:uploadedModel.model_id},
      authorized:true,strategy:'red_team'};
    el('progress-message').textContent='Starting assessment with the three hosted Courthouse AI models…';
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
  }catch(err){
    el('results-running').classList.add('hidden');el('results-empty').classList.remove('hidden');
    showError(err.message||'An unexpected error interrupted the assessment.');
    el('assessment').scrollIntoView({behavior:'smooth'});
  }finally{running=false;el('run-button').disabled=false;el('run-text').textContent='Run Courthouse assessment';}
}
function handleEvent(message) {
  if (message.type === 'status') {
    el('progress-message').textContent = message.message;
  } else if (message.type === 'start') {
    el('progress-message').textContent = `${message.total} tests prepared · ${message.attack_engine}`;
  } else if (message.type === 'progress') {
    el('progress-message').textContent = `Testing ${message.case} · ${message.title}`;
  } else if (message.type === 'result') {
    const pct = Math.round(message.completed / message.total * 100);
    el('progress-fill').style.width = `${pct}%`;
    el('progress-percentage').textContent = `${pct}%`;
    const line = textNode('div','', 'live-event');
    const label = textNode('span',`${message.result.id}  ·  ${message.result.title}`);
    const state = textNode('span', message.result.status.toUpperCase(), `event-state ${message.result.status}`);
    append(line, label, state);
    el('live-events').prepend(line);
  } else if (message.type === 'communication') {
    el('progress-message').textContent = `${message.message.agent} shared a finding with the Courthouse`;
  } else if (message.type === 'agent_summary') {
    el('progress-message').textContent = `${message.agent.name} completed an independent report`;
  } else if (message.type === 'error') {
    throw new Error(message.message || 'Assessment failed.');
  } else if (message.type === 'done') {
    report = message.report;
    renderReport(report);
    el('results-running').classList.add('hidden');
    el('results-complete').classList.remove('hidden');
    el('export-button').classList.remove('hidden');
  }
}

function renderReport(data) {
  el('demo-banner').classList.add('hidden');
  el('report-model').textContent = data.target;
  el('report-time').textContent = `${new Date(data.completed_at).toLocaleString()} · ${data.duration_s}s`;
  el('score-value').textContent = data.score === null ? '—' : data.score;
  el('score-grade').textContent = data.grade === null ? 'PARTIAL' : `GRADE ${data.grade}`;
  el('score-label').textContent = data.score === null ? 'PARTIAL' : 'OUT OF 100';
  el('score-explainer').textContent = data.score === null
    ? `Only ${data.categories_covered}/4 categories measured. Overall grade withheld. Partial category mean: ${data.measured_score ?? 'N/A'}.`
    : 'Observed outcomes from AI-generated prompts, equally weighted across four categories.';
  el('score-ring').style.background = `conic-gradient(#5be3cb ${((data.score ?? 0)/100)*360}deg, #30454e 0deg)`;
  el('stat-tests').textContent = `${data.tested}/${data.total}`;
  el('stat-findings').textContent = data.findings;
  el('stat-coverage').textContent = `${data.coverage}%`;
  el('stat-engine').textContent = data.attack_engine;
  el('report-disclaimer').textContent = data.disclaimer;
  renderCourt(data);
  el('findings-count').textContent = `${data.total} TESTS`;

  const grid = el('category-grid');
  grid.replaceChildren();
  for (const category of data.categories) {
    const card = textNode('article', '', 'category-card');
    const label = names[category.key] || {title: category.label, icon:'◇'};
    append(card, textNode('div', label.icon, 'cat-icon'), textNode('h4', label.title));
    const value = textNode('div', category.score === null ? 'N/A' : String(category.score), 'cat-value');
    value.appendChild(textNode('small', category.score === null ? '' : ' / 100'));
    card.appendChild(value);
    const bar = textNode('div', '', 'cat-bar');
    const fill = textNode('div', '', 'cat-fill');
    fill.style.width = `${category.score ?? 0}%`;
    bar.appendChild(fill);
    card.appendChild(bar);
    card.appendChild(textNode('div', `${category.failed} flagged · ${category.tested} measured${category.skipped ? ` · ${category.skipped} skipped` : ''}`, 'cat-meta'));
    grid.appendChild(card);
  }
  const list = el('findings-list');
  list.replaceChildren();
  const ordered = [...data.results].sort((a,b) => {
    const ranks = {fail:0, skipped:1, pass:2}; return ranks[a.status] - ranks[b.status];
  });
  ordered.forEach((test, index) => {
    const detail = textNode('details', '', `finding ${test.status}`);
    const summary = textNode('summary', '', 'finding-summary');
    const symbol = {pass:'✓',fail:'!',skipped:'–'}[test.status];
    const left = textNode('span',symbol,'finding-symbol');
    const middle = textNode('span','','finding-title');
    append(middle, textNode('strong',test.title), textNode('small',`${test.agent || 'Counsel'} · ${test.id} · ${(names[test.category] || {}).title || test.category} · ${test.duration_ms}ms${test.generated_by_ai ? ' · AI-generated' : ''}`));
    const state = textNode('span',test.status === 'fail' ? 'FLAGGED' : test.status.toUpperCase(),'finding-status');
    append(summary,left,middle,state,textNode('span','›','finding-caret'));
    detail.appendChild(summary);
    const evidence = textNode('div','','evidence');
    evidence.appendChild(textNode('p',test.reason + (test.is_proxy ? ' This uses proposed simulated tool calls; real tool execution was not tested.' : ''),'evidence-note'));
    const cells = textNode('div','','evidence-grid');
    const items = [
      ['System-level test policy',test.system_prompt],
      ['Attack prompt submitted',test.attack_prompt],
      ['Target model response',test.response || '(No text returned)'],
      ['Proposed tool calls',JSON.stringify(test.tool_calls,null,2) || '[]'],
      ['Red-team model and attack reasoning', `${test.agent_model || ''} — ${test.rationale || '(not provided)'}`]
    ];
    items.forEach(([heading, content]) => {
      const cell = textNode('div','','evidence-cell');
      const caption = textNode('label',heading);
      const btn = textNode('button','COPY','copy-mini');
      btn.type = 'button';
      btn.addEventListener('click', () => {
        navigator.clipboard.writeText(content).then(() => {
          btn.textContent = 'COPIED';
          setTimeout(() => {btn.textContent = 'COPY';}, 1200);
        }).catch(() => {btn.textContent='UNAVAILABLE';});
      });
      caption.appendChild(btn);
      const pre = textNode('pre',content);
      append(cell,caption,pre);
      cells.appendChild(cell);
    });
    evidence.appendChild(cells);
    detail.appendChild(evidence);
    list.appendChild(detail);
  });
}

function renderCourt(data) {
  const court = data.courthouse || {};
  el('court-summary').textContent = court.summary || 'No joint summary available.';
  el('court-method').textContent = court.agreement || '';
  const agentGrid = el('court-agents'); agentGrid.replaceChildren();
  for (const agent of (data.agents || [])) {
    const card = textNode('article', '', 'court-agent');
    append(card, textNode('div', '● REAL LOCAL AI RED-TEAM MODEL', 'court-eyebrow'),
      textNode('h3', agent.name), textNode('small', 'Model: ' + (agent.model || 'unknown'), 'court-method'), textNode('p', agent.focus, 'court-focus'),
      textNode('div', agent.grade === null ? 'GRADE WITHHELD · INCOMPLETE COVERAGE' : `INDIVIDUAL SCORE ${agent.score}/100 · GRADE ${agent.grade}`, 'court-agent-grade'),
      textNode('p', agent.summary, 'court-summary-text'),
      textNode('small', `${agent.tests} tests · ${agent.findings} flagged · ${agent.coverage}% coverage · ${agent.method}`, 'court-method'));
    const mini = textNode('div', '', 'court-scoregrid');
    Object.entries(agent.categories).forEach(([key,value]) => {
      const box = textNode('div','', 'court-mini');
      append(box, textNode('span', (names[key] || {}).title || key), textNode('strong', value.score === null ? 'N/A' : `${value.score}/100`), textNode('small', `${value.failed} flagged · ${value.tested} tested`));
      mini.appendChild(box);
    });
    card.appendChild(mini);
    if (agent.category_analysis) {
      for (const [key, commentary] of Object.entries(agent.category_analysis)) {
        if (commentary) { const para = textNode('p', `${(names[key] || {}).title || key}: ${commentary}`, 'court-summary-text'); card.appendChild(para); }
      }
    }
    const details = textNode('details', '', 'court-agent-evidence');
    const detailsTitle = textNode('summary', `Review ${agent.name} individual findings (${agent.findings})`);
    details.appendChild(detailsTitle);
    if (!(agent.detailed_findings || []).length) {
      details.appendChild(textNode('p', 'No rule violations were detected by the measured probes, or the relevant probes were skipped.'));
    } else {
      for (const finding of agent.detailed_findings) {
        const item = textNode('div', '', 'court-agent-finding');
        append(item, textNode('strong', `${finding.id} · ${(names[finding.category] || {}).title || finding.category}`),
          textNode('p', finding.reason), textNode('pre', `Prompt: ${finding.attack_prompt}\n\nResponse: ${finding.response || '(no text response)'}\n\nProposed tool calls: ${JSON.stringify(finding.tool_calls || [])}`));
        details.appendChild(item);
      }
    }
    card.appendChild(details);
    agentGrid.appendChild(card);
  }
  const messages = el('court-communications'); messages.replaceChildren();
  if (!(court.cross_agent_messages || []).length) messages.appendChild(textNode('p','No violation alerts were shared. Each counsel still reviewed prior test outcomes.'));
  for (const msg of (court.cross_agent_messages || [])) {
    const line = textNode('div', '', 'court-message');
    append(line,textNode('strong',`${msg.agent} → All Counsel`),textNode('span',`${msg.case}: ${msg.message}`));
    messages.appendChild(line);
  }
}

function exportReport() {
  if (!report) return;
  const blob = new Blob([JSON.stringify(report, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `courthouse-report-${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', initialize);
