'use strict';
let watching=false;
async function refreshWatch(force=false){
  if(watching)return;watching=true;
  $('watchState').textContent='공식 발표와 경제신문 공개 목록을 확인하고 있습니다…';
  try{
    const data=await api('/api/market-watch',{method:'POST',headers:{'X-External-Request':'1'},body:{keywords:$('watchKeywords').value,days:Number($('watchDays').value),force,enabled:$('watchEnabled').value==='on'}});
    app.watch=data;if(app.state)renderHome();
    $('watchState').textContent=`${data.rows.length}건 · ${data.fetched_at||''} · ${data.note}`;
    $('watchSources').replaceChildren();$('watchItems').replaceChildren();
    data.source_status.forEach(source=>{
      const p=el('p','note',`${source.name}: ${source.ok?'목록 조회 성공':'조회 실패'}${source.cached?' (캐시)':''} `);
      if(!source.ok)p.append(el('span','',source.error+' '));
      const a=el('a','','수집처 열기 ↗');a.href=source.feed_url;a.target='_blank';a.rel='noopener noreferrer';p.append(a);$('watchSources').append(p);
    });
    data.rows.forEach(item=>{
      const card=el('div','ref-item');card.append(el('small','',`${item.kind==='official'?'공공기관 발표':'언론 보도'} · ${item.publisher} · ${item.published_at||'공표일 미확인'}`));
      const a=el('a','download-link',item.title);a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';card.append(a);
      if(item.excerpt)card.append(el('p','',item.excerpt));
      card.append(el('small','',item.scope));
      if(['금융위원회','금융감독원'].includes(item.publisher)){
        const button=el('button','btn light','원문 분석');
        button.type='button';
        const result=el('div','','');
        result.setAttribute('aria-live','polite');
        button.addEventListener('click',()=>analyzeRelease(item,button,result));
        const controls=el('div','','');
        controls.append(button);
        card.append(controls,result);
      }
      $('watchItems').append(card);
    });
  }catch(e){$('watchState').textContent='탐색 실패: '+e.message;}
  finally{watching=false;}
}
async function analyzeRelease(item,button,result){
  button.disabled=true;
  result.textContent='공식 보도자료 본문 확인 중…';
  try{
    const data=await api('/api/market-watch/analyze',{method:'POST',headers:{'X-External-Request':'1'},body:{url:item.url}});
    const list=el('ul','','');
    for(const passage of data.evidence){
      const entry=el('li','',passage+' ');
      const source=el('a','download-link',`원문 · ${data.publisher} · ${data.published_at||'공표일 미확인'} ↗`);
      source.href=data.url+'#:~:text='+encodeURIComponent(passage.slice(0,90)).replaceAll('-','%2D');
      source.target='_blank';
      source.rel='noopener noreferrer';
      entry.append(source);
      list.append(entry);
    }
    result.replaceChildren(el('strong','','본문에서 확인한 근거'),list,el('p','note',data.note));
  }catch(e){result.textContent=e.message;}
  finally{button.disabled=false;}
}
$('watchForm').addEventListener('submit',event=>{event.preventDefault();refreshWatch(true);});
$('watchEnabled').addEventListener('change',()=>refreshWatch(false));
$('watchAnalyze').addEventListener('click',async()=>{
  await refreshWatch(false);
  if($('watchEnabled').value==='off'){toast('자동 탐색을 켠 뒤 분석해 주세요.',true);return;}
  ask('자동 탐색에서 수집된 공식 발표와 경제신문 자료를 요약하고 소매여신 전략에 미치는 영향을 분석해 줘. ① 확인된 사실과 발표일·원문 ② 언론 해석 ③ 주담대·신용·보험계약대출 시사점 ④ 추가 검증을 구분해 줘. 제목·RSS 요약만 읽은 자료는 그 범위를 밝혀줘. 조회에 실패한 기관 및 불확실한 시행일·수치를 명시하고 예시 실적과 실제 외부자료를 구분해 줘.');
});
refreshWatch(false);
setInterval(()=>{if($('watchEnabled').value==='on')refreshWatch(false);},900000);
