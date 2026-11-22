'use strict';
async function externalStatus(){
  try{
    const state=await api('/api/external/status');
    $('externalStatus').textContent=['ecos','dart'].map(name=>`${name.toUpperCase()}: ${state[name].configured?'키 설정됨 · 실제 조회로 확인 필요':'미설정'}`).join(' / ');
  }catch(e){$('externalStatus').textContent=e.message;}
}
function externalRender(data){
  const target=$('externalResults');
  const previous=document.getElementById(`result-${data.provider}`);if(previous)previous.remove();
  const box=el('section','external-result');box.id=`result-${data.provider}`;
  box.append(el('h4','',data.provider.toUpperCase()));
  if(!data.ok){box.append(el('p','',`조회하지 못했습니다: ${data.error}`));target.append(box);return;}
  box.append(el('p','',`조회 성공 · ${data.fetched_at} · ${data.cached?'캐시 사용':'기관 API 조회'} · ${data.rows.length}건`));
  box.append(el('p','note',data.note));
  const scroll=el('div','external-table-scroll'),table=el('table'),head=el('thead'),tr=el('tr');
  const labels=data.provider==='ecos'?['지표','값','단위','기준시점','공표일']:data.provider==='dart'?['회사','공시 제목','접수일']:['계정','재무제표','당기 명칭','당기 금액','전기 명칭','전기 금액','통화'];
  labels.forEach(label=>tr.append(el('th','',label)));head.append(tr);table.append(head);
  const body=el('tbody');
  data.rows.forEach(row=>{
    const line=el('tr');
    const values=data.provider==='ecos'?[row.name,row.value,row.unit,row.reference_period,row.published_at||'미확인']:data.provider==='dart'?[row.company,row.title,row.published_at]:[row.account,row.statement,row.current_period,row.current_amount,row.previous_period,row.previous_amount,row.currency];
    values.forEach((value,index)=>{
      const cell=el('td','',value??'미확인');
      if(data.provider==='dart'&&index===1){const a=el('a','',row.title);a.href=row.url;a.target='_blank';a.rel='noopener noreferrer';cell.replaceChildren(a);}
      line.append(cell);
    });body.append(line);
  });table.append(body);scroll.append(table);box.append(scroll);target.append(box);
}
async function fetchExternal(provider){
  const button=$(provider==='ecos'?'fetchEcos':provider==='dart'?'fetchDart':'fetchFinancial');button.disabled=true;
  try{
    const data=await api('/api/external/query',{method:'POST',headers:{'X-External-Request':'1'},body:{provider,corp_code:provider!=='ecos'?$('dartCorp').value.trim():'',force:true,year:provider==='dart_financial'?$('dartYear').value:'',report:$('dartReport').value,fs_div:$('dartFs').value}});
    externalRender(data);toast(data.ok?'공식 데이터를 조회했습니다. 대화 분석에 반영합니다.':data.error,!data.ok);
  }catch(e){toast(e.message,true);}finally{button.disabled=false;}
}
$('externalKeyForm').addEventListener('submit',async ev=>{
  ev.preventDefault();const button=ev.currentTarget.querySelector('button[type="submit"]');button.disabled=true;
  try{
    await api('/api/external/config',{method:'POST',headers:{'X-External-Request':'1'},body:{ecos:$('ecosKey').value.trim(),dart:$('dartKey').value.trim()}});
    $('ecosKey').value='';$('dartKey').value='';await externalStatus();toast('키를 암호화해 저장했습니다. 조회 버튼으로 연결을 확인하세요.');
  }catch(e){toast(e.message,true);}finally{button.disabled=false;}
});
$('fetchEcos').addEventListener('click',()=>fetchExternal('ecos'));
$('fetchDart').addEventListener('click',()=>fetchExternal('dart'));
$('fetchFinancial').addEventListener('click',()=>fetchExternal('dart_financial'));
$('dartYear').value=Number(new Intl.DateTimeFormat('en',{timeZone:'Asia/Seoul',year:'numeric'}).format(new Date()))-1;
externalStatus();
