'use strict';

const $ = id => document.getElementById(id);
const all = sel => Array.from(document.querySelectorAll(sel));
const SESSION_KEY = 'retail_lending_mvp_session';
const makeSession = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-local');
let sid = sessionStorage.getItem(SESSION_KEY);
if (!sid) { sid = makeSession(); sessionStorage.setItem(SESSION_KEY, sid); }

const app = {
  state: null,
  view: 'home',
  history: [],
  sending: false,
  baseline: null,
  scenario: {cap: 30, overrides: {}},
  scenarioResult: null,
  allocationSelection: null,
  refs: [],
  preset: 'base',
  computeSeq: 0
};
const PRODUCTS = ['주택담보대출','신용대출','보험계약대출'];
const SHORT_NAMES = {'주택담보대출':'주택담보', '신용대출':'신용대출','보험계약대출':'보험계약'};
const formatNum = n => new Intl.NumberFormat('ko-KR',{maximumFractionDigits:1}).format(n);
const signed = n => `${n > 0 ? '+' : n < 0 ? '−' : ''}${formatNum(Math.abs(n))}`;
const amt = n => `${signed(n)}억`;
const el = (tag, cls, text) => { const t=document.createElement(tag); if(cls)t.className=cls; if(text!==undefined)t.textContent=text; return t; };
function toast(message, bad=false){
  const t=$('toast');t.textContent=message;t.style.background=bad?'#a55345':'#253452';t.classList.add('show');
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('show'),4300);
}
async function api(path, options={}){
  const headers={'X-Session-Id':sid,...(options.headers||{})};
  let body=options.body;
  if (body && !(body instanceof FormData)) {headers['Content-Type']='application/json';body=JSON.stringify(body);}
  const res=await fetch(path,{...options,headers,body});
  if(!res.ok){let detail=`서버 오류 ${res.status}`;try{const d=await res.json();detail=d.detail||detail;}catch(e){}throw new Error(detail);}
  return res.json();
}
function go(view){
  const allowed=['home','chat','reports','scenario','data','allocation'];
  if(!allowed.includes(view))return;
  app.view=view;
  all('.view').forEach(e=>e.classList.toggle('active',e.id==='view-'+view));
  all('.navitem').forEach(e=>e.classList.toggle('active',e.dataset.view===view));
  window.scrollTo({top:0,behavior:'smooth'});
  if(view==='reports')renderReport();
  if(view==='scenario')renderScenario();
  if(view==='data')renderRefs();
  if(view==='allocation')document.dispatchEvent(new Event('allocation:open'));
}
function cleanNumber(n){const v=Number(n);return Number.isFinite(v)?v:0;}
async function loadState(){
  const data=await api('/api/state');
  app.state=data;
  app.baseline=data.portfolio;
  app.refs=data.references;
  app.scenarioResult=data.portfolio;
  app.scenario={cap:data.portfolio.assumed_cap,overrides:{}};
  $('periodLabel').innerHTML=`▣ ${data.month.slice(0,4)}년 ${Number(data.month.slice(5))}월 <small>예시 기준</small>`;
  const live=data.health.mode==='live';
  const provider=data.health.provider==='gemini'?'Gemini':data.health.provider==='openai'?'OpenAI':'LLM';
  $('modePill').textContent=live?`● ${provider} API 설정됨`:'◌ 시연 모드';
  $('modePill').classList.toggle('live',live);
  $('modeSide').textContent=live?`${provider} · 대화 테스트 필요`:'규칙 기반 데모';
  $('footerMode').textContent=live?`${provider} API 설정됨`:'규칙 기반 데모';
  renderHome();renderScenarioFields();renderScenario();renderRefs();renderReport();
  document.dispatchEvent(new Event('portfolio:loaded'));
}
function renderHome(){
  if(!app.state)return;
  const b=app.baseline;
  const notes=app.refs;
  const numMarket=notes.filter(r=>r.category==='market').length;
  const numPolicy=notes.filter(r=>r.category==='policy').length;
  const summary=$('marketSummary'); summary.replaceChildren();
  const textRows=[
    {icon:'⌁',tone:'neutral',text:app.watch?`자동 탐색 ${app.watch.rows.length}건`:numMarket?`시장환경 근거 ${numMarket}건 등록`:'시장환경 근거 미등록',sub:app.watch?'공식 발표·언론 구분 · 자료 관리에서 확인':numMarket?'사용자 등록 자료 · 사실 확인 필요':'자료 관리에서 자동 탐색 상태 확인'},
    {icon:'▤',tone:'neutral',text:numPolicy?`정책·규제 근거 ${numPolicy}건 등록`:'정책·규제 근거 미등록',sub:numPolicy?'회사별 적용기준 별도 검증':'규제 적용·관리범위 확인 필요'},
    {icon:'!',tone:b.assumed_remaining<0?'warn':'neutral',text:`가정한도 잔여 ${amt(b.assumed_remaining)}`,sub:'총잔액 기준 · 법적 한도 아님'},
  ];
  textRows.forEach(r=>{let row=el('div','insight-row'),circle=el('span','circ '+r.tone,r.icon),copy=el('span','');copy.append(document.createTextNode(r.text),el('br'),el('small','',r.sub));row.append(circle,copy);summary.append(row);});
  const chart=$('miniChart');chart.replaceChildren();
  const max=Math.max(1,...b.rows.map(r=>Math.abs(r.net)));
  b.rows.forEach(r=>{
    const row=el('div','bar-row');row.append(el('span','',SHORT_NAMES[r.product]));
    const track=el('div','bar-track'), bar=el('div','bar-fill '+(r.net<0?'negative':'positive'));
    bar.style.width=`${Math.min(50,Math.abs(r.net)/max*50)}%`;
    track.append(bar);row.append(track,el('span','bar-number',amt(r.net)));chart.append(row);
  });
  $('totalNet').textContent=amt(b.total_net);
  $('dataOriginSmall').textContent=app.state.data_origin + ' · 단위: 억 원';
  $('dataSourceLabel').textContent=app.state.data_origin;
}
function renderScenarioFields(){
  if(!app.baseline)return;
  const div=$('scenarioFields');div.replaceChildren();
  for(const r of app.baseline.rows){
    for(const field of ['execution','repayment']){
      const wrapper=el('div','scenario-field');
      const label=el('label','',`${SHORT_NAMES[r.product]} ${field==='execution'?'실행':'회수'}`);
      const box=el('div','number-wrap');
      const input=el('input');input.type='number';input.min='0';input.max='1000000000';input.step='10';
      input.value=r[field];input.dataset.product=r.product;input.dataset.field=field;
      input.setAttribute('aria-label',`${r.product} ${field==='execution'?'실행':'회수'} 금액`);
      input.addEventListener('input',()=>{
        if(input.value==='')return;
        app.allocationSelection=null;
        const key=`${r.product}.${field}`;
        app.scenario.overrides[key]=cleanNumber(input.value);
        setPreset('manual');scheduleScenario();
      });
      box.append(input,el('span','','억'));wrapper.append(label,box);div.append(wrapper);
    }
  }
  $('capValue').value=app.scenario.cap;
}
function setPreset(which){
  app.preset=which;
  all('.preset').forEach(b=>b.classList.toggle('active',b.dataset.preset===which));
}
function applyPreset(which){
  if(!app.baseline)return;
  app.allocationSelection=null;
  app.scenario.overrides={};
  const byName=Object.fromEntries(app.baseline.rows.map(r=>[r.product,r]));
  if(which==='adverse'){
    // Report's educational stress case: policy-loan net +60 relative to baseline.
    app.scenario.overrides['보험계약대출.execution']=byName['보험계약대출'].execution+60;
  }
  if(which==='favorable'){
    // Educational sensitivity: credit execution +20 and mortgage execution -20.
    app.scenario.overrides['신용대출.execution']=byName['신용대출'].execution+20;
    app.scenario.overrides['주택담보대출.execution']=Math.max(0,byName['주택담보대출'].execution-20);
  }
  setPreset(which);
  all('#scenarioFields input').forEach(input=>{
    const r=byName[input.dataset.product];const key=`${r.product}.${input.dataset.field}`;
    input.value=app.scenario.overrides[key]??r[input.dataset.field];
  });
  scheduleScenario();
}
let scenarioTimer;
function scheduleScenario(){clearTimeout(scenarioTimer);scenarioTimer=setTimeout(updateScenario,220);}
async function updateScenario(){
  const seq=++app.computeSeq;
  if(!Number.isFinite(app.scenario.cap)||app.scenario.cap<0){toast('가정한도는 0 이상이어야 합니다.',true);return;}
  try{
    const data=await api('/api/scenario',{method:'POST',body:app.scenario});
    if(seq!==app.computeSeq)return;
    app.scenarioResult=data;
    renderScenario();renderReport();
  }catch(e){toast(e.message,true);}
}
function renderScenario(){
  if(!app.scenarioResult)return;
  const r=app.scenarioResult;
  $('scenarioTotal').textContent=amt(r.total_net);
  $('scenarioRemaining').textContent=amt(r.assumed_remaining);
  $('scenarioRemaining').style.color=r.assumed_remaining<0?'#d36a45':'#16886d';
  const fill=$('meterFill');fill.style.width=`${Math.max(0,Math.min(100, r.total_net / (r.assumed_cap || 1) * 100))}%`;
  fill.classList.toggle('over',r.assumed_remaining<0);
  const warn=$('scenarioWarning');warn.textContent=r.assumed_remaining<0?
    `가정한도를 ${formatNum(Math.abs(r.assumed_remaining))}억 원 초과합니다. 이것이 규제상 한도 초과를 의미하지는 않습니다.`:
    `가정한도 대비 ${formatNum(r.assumed_remaining)}억 원의 여유가 있습니다. 관리대상 잔액은 별도 계산이 필요합니다.`;
  warn.classList.toggle('warning',r.assumed_remaining<0);
  $('scenarioSource').textContent=app.state?.data_origin||'자료';
  const tbody=$('scenarioTable');tbody.replaceChildren();
  r.rows.forEach(rec=>{const tr=el('tr');[SHORT_NAMES[rec.product],formatNum(rec.execution),formatNum(rec.repayment),amt(rec.net)].forEach(t=>tr.append(el('td','',t)));tbody.append(tr);});
}
function renderReport(){
  const r=app.scenarioResult||app.baseline;if(!r || !app.state)return;
  $('reportNet').textContent=amt(r.total_net);$('reportRoom').textContent=amt(r.assumed_remaining);
  $('reportRefs').textContent=`${app.refs.length}건`;
  $('reportSubtitle').textContent=`${app.state.month} · ${app.state.data_origin} · ${app.allocationSelection?.label || '시나리오 가정 적용'}`;
  const list=$('reportRows');list.replaceChildren();
  r.rows.forEach(x=>{const row=el('div','report-row');row.append(el('strong','',x.product),el('strong','',`${amt(x.net)} (실행 ${formatNum(x.execution)} / 회수 ${formatNum(x.repayment)})`));list.append(row);});
}
function renderRefs(){
  if(!app.state)return;
  $('refCount').textContent=app.refs.length;
  const list=$('refList');list.replaceChildren();
  if(!app.refs.length){list.append(el('p','empty-refs','등록된 외부자료가 없습니다.'));return;}
  app.refs.slice().reverse().forEach(r=>{
    const box=el('div','ref-item');box.append(el('b','',r.title),el('p','',r.content.slice(0,200)),el('small','',`${r.category==='market'?'시장':'정책'} · ${r.published_at||'공표일 미입력'}`));
    if(r.source_url){const a=el('a','download-link','원문 링크 열기 ↗');a.href=r.source_url;a.target='_blank';a.rel='noopener noreferrer';box.append(a);}
    list.append(box);
  });
}
function showEmptyChat(){
  $('chatMessages').replaceChildren();
  const wrap=el('div','empty-chat');wrap.append(el('div','empty-symbol','✦'),el('h3','','분석할 내용을 입력해주세요'),el('p','','예: “신용대출 순증목표 달성 가능성을 알려줘.”'));$('chatMessages').append(wrap);
}
function impactEvidenceLink(evidence){
  const link=el('a','impact-link',`${evidence.publisher} 원문 ↗`);
  link.href=evidence.url;link.target='_blank';link.rel='noopener noreferrer';
  return link;
}

function renderImpactGrades(grades){
  const grid=el('div','impact-grid');
  for(const grade of grades){
    const column=el('section','impact-column');
    const card=el('div','impact-card');
    card.append(el('h3','impact-axis',grade.axis),el('strong','impact-level',grade.level),
                el('span','impact-confidence',`근거 ${grade.confidence}`));
    const survey=grade.evidence.filter(item=>!item.effective_at);
    if(survey.length){
      const details=el('details','impact-survey');
      details.append(el('summary','','판정 근거 보기'),el('p','impact-reason',grade.reason));
      for(const item of survey){
        const row=el('p','',item.text+' ');
        row.append(impactEvidenceLink(item));details.append(row);
      }
      card.append(details);
    }
    if(!survey.length)card.append(el('p','impact-reason',grade.reason));
    column.append(card);
    const policies=grade.evidence.filter(item=>item.effective_at);
    if(policies.length){
      const list=el('details','impact-policies');
      list.append(el('summary','','공급 정책 '+policies.length+'건 보기'));
      for(const item of policies){
        const policy=el('article','impact-policy');
        const scope=item.text.replace(new RegExp('^'+item.effective_at+' 시행 · '),'');
        const meta=el('div','impact-meta');
        const effective=el('time','',`시행 ${item.effective_at}`);
        effective.dateTime=item.effective_at;
        meta.append(effective,impactEvidenceLink(item));
        policy.append(el('h5','',item.title),el('p','',scope),meta);
        list.append(policy);
      }
      column.append(list);
    }
    grid.append(column);
  }
  return grid;
}

function addBubble(role, text, tools=[], sources=[], citations=[], grades=[]){
  const box=el('div','msg '+role);box.append(el('div','avatar',role==='user'?'●':'✦'));
  const wrap=el('div');const bubble=el('div','bubble',grades.length?'':text);wrap.append(bubble);
  if(grades.length){
    box.classList.add('msg-impact');
    const [heading,...notes]=text.split('\n');
    bubble.append(el('h2','impact-title',heading),renderImpactGrades(grades));
    if(notes.length)bubble.append(el('p','impact-reason',notes.join('\n')));
  }
  if(citations.length){
    const list=el('ul');
    citations.forEach(citation=>{
      const item=el('li','',citation.text+' ');
      const url=new URL(citation.url);
      if(url.protocol==='https:'){
        const link=el('a','download-link',`원문 · ${citation.publisher} · ${citation.published_at||'공표일 미확인'} ↗`);
        url.hash=':~:text='+encodeURIComponent(citation.text.slice(0,90)).replaceAll('-','%2D');
        link.href=url.href;link.title=citation.title;link.target='_blank';link.rel='noopener noreferrer';
        item.append(link);
      }
      list.append(item);
    });
    bubble.append(list);
  }
  if(tools.length)wrap.append(el('div','tool-trace','실행 도구: '+tools.join(' · ')));
  if(sources.length){
    const details=el('details','answer-sources');details.append(el('summary','',`근거 출처 ${sources.length}건`));
    sources.forEach(source=>{
      try{
        const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))return;
        const a=el('a','download-link',`${source.title} · ${source.published_at||'공표일 미확인'}`);
        a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';details.append(a);
      }catch(e){}
    });wrap.append(details);
  }
  box.append(wrap);const target=$('chatMessages');
  const empty=target.querySelector('.empty-chat');if(empty)empty.remove();
  target.append(box);
  if(grades.length){
    target.scrollTop+=box.getBoundingClientRect().top-target.getBoundingClientRect().top-target.clientTop;
  }else{target.scrollTop=target.scrollHeight;}
  return box;
}
async function ask(text){
  if(!text.trim()||app.sending)return;
  go('chat');
  app.sending=true;
  $('sendChat').disabled=true;
  addBubble('user',text);
  const spinner=addBubble('assistant','자료와 계산 근거를 확인하고 있습니다…');
  try{
    const result=await api('/api/chat',{method:'POST',body:{message:text,history:app.history.slice(-8),scenario:app.scenario}});
    spinner.remove();const reply=addBubble('assistant',result.answer,result.tools_used||[],result.sources||[],result.citations||[],result.impact_grades||[]);
    if (result.proxy_ticket) {
      const choose = el('button','btn light','차이를 확인하고 거래량 지표 선택');
      const decline = el('button','btn light','사용하지 않음');
      decline.onclick = () => { choose.remove(); decline.remove(); };
      choose.onclick = async () => {
        choose.disabled = true;
        try {
          const selected = await api('/api/indicator/proxy/' + result.proxy_ticket,{method:'POST'});
          choose.remove(); decline.remove();
          addBubble('assistant',selected.answer);
          await openIndicatorDraft(selected.draft);
        } catch (err) { toast(err.message,true); choose.disabled=false; }
      };
      reply.lastElementChild.append(choose,decline);
    }
    if (result.draft) {
      const button = el('button','btn light','가정 검토 및 배분안 비교');
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await openIndicatorDraft(result.draft); }
        catch (err) { toast(err.message,true); }
        finally { button.disabled = false; }
      });
      reply.lastElementChild.append(button);
    }
    app.history.push({role:'user',content:text},{role:'assistant',content:result.answer});
  }catch(e){spinner.remove();addBubble('assistant','분석 요청을 완료하지 못했습니다. '+e.message);toast(e.message,true);}
  finally{app.sending=false;$('sendChat').disabled=false;$('chatInput').focus({preventScroll:true});}
}
async function saveReference(ev){
  ev.preventDefault();const submit=$('refForm').querySelector('button[type="submit"]');submit.disabled=true;
  try{
    const ref={category:$('refCategory').value,title:$('refTitle').value.trim(),content:$('refContent').value.trim(),source_url:$('refUrl').value.trim(),published_at:$('refDate').value};
    const data=await api('/api/references',{method:'POST',body:ref});app.refs=data.references;app.state.references=data.references;
    renderRefs();renderHome();renderReport();$('refForm').reset();toast('근거자료를 등록했습니다. 자동 진위검증 자료가 아닌 사용자 입력 자료입니다.');
  }catch(e){toast(e.message,true);}finally{submit.disabled=false;}
}
async function uploadPortfolio(){
  const file=$('portfolioFile').files?.[0];if(!file)return;
  const form=new FormData();form.append('file',file);
  try{
    const data=await api('/api/upload',{method:'POST',body:form});
    app.state.data_origin=data.origin;app.baseline=data.portfolio;
    app.scenario.cap=data.portfolio.assumed_cap;app.scenario.overrides={};
    app.allocationSelection=null;
    app.scenarioResult=data.portfolio;setPreset('base');
    ++app.computeSeq;
    clearTimeout(scenarioTimer);
    renderScenarioFields();renderHome();renderScenario();renderReport();
    document.dispatchEvent(new Event('portfolio:loaded'));
    toast('3개 상품의 집계자료가 반영되었습니다. 자료값의 진위는 검증되지 않았습니다.');
  }catch(e){toast(e.message,true);}finally{$('portfolioFile').value='';}
}
async function downloadReport(){
  const btn=$('downloadReport');btn.disabled=true;
  try{
    const body={...app.scenario,allocation:app.allocationSelection?.reference};
    const res=await fetch('/api/report',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Id':sid},body:JSON.stringify(body)});
    if(!res.ok){const j=await res.json();throw new Error(j.detail||'보고서 생성 실패');}
    const blob=await res.blob();const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=`소매여신_전략분석_${app.state.month}.html`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('HTML 보고서를 내려받았습니다. 파일에서 인쇄 / PDF 저장도 가능합니다.');
  }catch(e){toast(e.message,true);}finally{btn.disabled=false;}
}
function bind(){
  all('.navitem').forEach(b=>b.addEventListener('click',()=>go(b.dataset.view)));
  all('[data-go]').forEach(b=>b.addEventListener('click',()=>go(b.dataset.go)));
  all('[data-ask]').forEach(b=>b.addEventListener('click',()=>ask(b.dataset.ask)));
  $('chatForm').addEventListener('submit',e=>{e.preventDefault();const input=$('chatInput');const text=input.value.trim();if(text){input.value='';ask(text);}});
  $('clearChat').addEventListener('click',()=>{app.history=[];showEmptyChat();toast('새 대화를 시작했습니다.');});
  all('.preset').forEach(b=>b.addEventListener('click',()=>applyPreset(b.dataset.preset)));
  $('resetScenario').addEventListener('click',()=>{app.scenario.cap=30;$('capValue').value=30;applyPreset('base');toast('예시 조건으로 초기화했습니다.');});
  $('capValue').addEventListener('input',e=>{if(e.target.value==='')return;app.allocationSelection=null;app.scenario.cap=cleanNumber(e.target.value);setPreset('manual');scheduleScenario();});
  $('scenarioAsk').addEventListener('click',()=>ask('현재 시나리오 조건과 계산 결과를 바탕으로 가정한도 여력 및 상품별 대응 전략을 구체적으로 분석해 줘.'));
  $('portfolioFile').addEventListener('change',uploadPortfolio);
  $('refForm').addEventListener('submit',saveReference);
  $('clearRefs').addEventListener('click',async()=>{if(!confirm('세션에 등록된 모든 외부 근거를 삭제할까요?'))return;try{await api('/api/references',{method:'DELETE'});app.refs=[];renderRefs();renderHome();renderReport();toast('등록된 근거를 삭제했습니다.');}catch(e){toast(e.message,true);}});
  $('downloadReport').addEventListener('click',downloadReport);
}
async function main(){bind();try{await loadState();}catch(e){toast('서버에 연결할 수 없습니다. FastAPI 서버 실행 상태를 확인하세요. '+e.message,true);}}
main();
