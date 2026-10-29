/* Read-only replay of recorded routing. Refresh never invokes a model or changes mode. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.PolicyRouterView=api;
  if(typeof document!=='undefined')api.mount(root);
}(typeof window!=='undefined'?window:this,function(){
  'use strict';
  const list=v=>Array.isArray(v)?v:[];
  const finite=v=>v!==null&&v!==undefined&&v!==''&&typeof v!=='boolean'&&Number.isFinite(Number(v));
  const count=v=>finite(v)&&Number(v)>=0?Number(v):null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=v=>finite(v)?Number(v).toLocaleString('en-US'):'Unknown';
  const money=v=>finite(v)?`${Number(v)<0?'−':''}$${Math.abs(Number(v)).toFixed(5)}`:'Unknown';
  const ids=v=>[...new Set(list(v).filter(x=>typeof x==='string'&&x.length<=180))];
  function dateText(value){
    if(!value)return 'Time not recorded';
    const s=String(value);
    if(!/(?:Z|[+-]\d{2}:?\d{2})$/.test(s))return s.replace('T',' ').slice(0,16)+' (as logged)';
    const date=new Date(s);return Number.isNaN(date.getTime())?'Time not recorded':date.toLocaleString('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' PT';
  }
  function sourceInfo(row){
    const source=String(row?.source_kind||'unknown');
    if(source==='replay')return {key:'replay',label:'Saved-cycle replay',short:'Replay',forward:false,note:'Saved evidence evaluated later; not a forward comparison.'};
    if(source==='observer'||source==='forward_observer'||row?.execution_mode==='observer'||row?.context_summary?.timing==='post_decision'||row?.observer===true)return {key:'observer',label:'Forward observer',short:'Observer',forward:true,note:'Observed after the saved trading decision; did not alter its prompt.'};
    if(source==='live')return {key:'live',label:'In-cycle shadow',short:'In-cycle',forward:true,note:'Shadow relevance comparison; the trading prompt is unchanged.'};
    return {key:'unknown',label:'Timing not recorded',short:'Unknown',forward:false,note:'This record does not establish when routing ran.'};
  }
  function selectionFor(row){
    const nodes=list(row?.nodes),selection=row?.selection||{};
    return {
      pinned:ids(selection.pinned_ids||row?.pinned_ids),
      selected:ids(selection.selected_ids||nodes.filter(n=>n.decisions_choice==='include').map(n=>n.node_id)),
      skipped:ids(selection.skipped_ids||nodes.filter(n=>n.decisions_choice==='exclude').map(n=>n.node_id)),
      actual:ids(selection.actual_optional_ids||nodes.filter(n=>n.served_in_prompt===true).map(n=>n.node_id)),
      actualKnown:Array.isArray(selection.actual_optional_ids)||nodes.some(n=>typeof n.served_in_prompt==='boolean'),
      available:row?.status==='ok'&&Boolean(row?.selection||nodes.some(n=>n.decisions_choice==='include'||n.decisions_choice==='exclude'))
    };
  }
  function filteredRuns(runs,filter='all'){
    return list(runs).filter(r=>finite(r.id)).filter(r=>filter==='all'||(filter==='replay'?sourceInfo(r).key==='replay':sourceInfo(r).forward)).slice().sort((a,b)=>Number(b.id)-Number(a.id));
  }
  function trialModel(trial,now=Date.now()){
    trial=trial||{};
    const parse=v=>typeof v==='string'&&/(?:Z|[+-]\d{2}:?\d{2})$/.test(v)&&Number.isFinite(Date.parse(v))?Date.parse(v):null;
    const start=parse(trial.starts_at||trial.started_at),end=parse(trial.ends_at||trial.expires_at);
    const expired=end!==null&&now>=end,status=expired?'complete':String(trial.status||'not_configured');
    const configured=!['not_started','not_configured','unavailable','none'].includes(status);
    const progress=start!==null&&end!==null&&end>start?Math.max(0,Math.min(1,(now-start)/(end-start))):null;
    return {status,configured,expired,progress,starts_at:trial.starts_at||trial.started_at||null,ends_at:trial.ends_at||trial.expires_at||null,
      heading:expired?'Observation window complete':status==='active'||status==='running'?'One week in shadow':configured?'Shadow evaluation':'No shadow window recorded',
      label:expired?'Review before activation':status==='active'||status==='running'?'Observing':configured?status.replaceAll('_',' '):'Not configured',
      days_remaining:end===null?null:Math.max(0,(end-now)/86400000),
      note:typeof trial.note==='string'?trial.note:'Trial expiry never enables prompt pruning. Review matched costs, coverage and decision quality before changing routing.'};
  }
  function flowModel(row){
    const selected=selectionFor(row),ctx=row?.context_summary||{},image=row?.image_manifest||{};
    const imageCount=count(image.image_count??ctx.image_count),summaryCount=count(ctx.summary_count);
    return {selected,source:sourceInfo(row),summaryCount,imageCount,coverage:image.coverage_status||ctx.image_coverage||'not recorded',
      regime:typeof ctx.regime==='string'?ctx.regime:'Not recorded',
      tickers:ids([...(list(ctx.news_tickers||ctx.news)),...list(ctx.watchlist)]).slice(0,8),
      prompt_version:finite(row?.prompt_version)?Number(row.prompt_version):null,
      status:row?.status||'unknown',actual_prompt_changed:row?.actual_prompt_changed===true};
  }
  function metric(label,value,note){return `<div class="pr-metric"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div><div class="s">${esc(note)}</div></div>`;}
  function flowHTML(row){
    const m=flowModel(row),s=m.selected;
    const keep=s.available?number(s.selected.length):'—',skip=s.available?number(s.skipped.length):'—';
    return `<section class="pr-flow-column evidence" data-flow-stage="0"><span class="pr-flow-step">01 · CYCLE EVIDENCE</span><h4>What was supplied</h4><span class="pr-flow-value">${esc(number(m.summaryCount))}<small>summaries</small></span><p>${esc(number(m.imageCount))} screenshots · ${esc(m.coverage)} coverage</p><p class="pr-flow-cue">Regime: ${esc(m.regime)}</p><p>${m.imageCount!==null&&m.imageCount>0?'Frozen source IDs and hashes preserve the saved image evidence.':m.imageCount===0?'Text-only input; no image pixels were supplied.':'Image input was not recorded for this comparison.'}</p>${m.tickers.length?`<div class="pr-mini-tags">${m.tickers.map(t=>`<span>${esc(t)}</span>`).join('')}</div>`:''}</section><div class="pr-flow-arrow" aria-hidden="true">→</div><section class="pr-flow-column router" data-flow-stage="1"><span class="pr-flow-step">02 · DECISIONS SUBGRAPH</span><h4>Relevance, rule by rule</h4><p>OpenAI Decisions · GPT-6 Luna</p><div class="pr-pinned-line"><strong>${esc(number(s.pinned.length))}</strong> controls always pinned</div><div class="pr-route-split"><div class="pr-route-bucket"><strong>${esc(keep)}</strong><span>Proposed keep</span></div><div class="pr-route-bucket skip"><strong>${esc(skip)}</strong><span>Proposed skip</span></div></div><p style="margin-top:10px">${s.available?'Only optional context is scored. Gates, identity and execution limits stay pinned.':'No valid complete selection was recorded. The existing prompt remains in place.'}</p></section><div class="pr-flow-arrow" aria-hidden="true">→</div><section class="pr-flow-column decider" data-flow-stage="2"><span class="pr-flow-step">03 · ACTUAL DECIDER INPUT</span><h4>Full approved context</h4><span class="pr-flow-value">${esc(s.actualKnown?number(s.actual.length):'Unknown')}<small>optional IDs recorded</small></span><p>Plus the standing policy and code-owned context. ${m.prompt_version!==null?`Policy v${esc(m.prompt_version)}.`:''}</p><span class="pr-flow-unchanged">SHADOW · UNCHANGED INPUT</span><p style="margin-top:10px">This selection placed no order and saved no actual input tokens.</p></section>`;
  }
  function tableHTML(row,bucket){
    const selection=selectionFor(row),items=list(selection[bucket]),nodes=new Map(list(row?.nodes).map(n=>[n.node_id,n]));
    if(!items.length)return `<div class="pr-empty"><h3>${bucket==='actual'&&!selection.actualKnown?'Actual optional IDs unavailable':'No recorded IDs in this group'}</h3><p>${selection.available?'This is the saved selection for this cycle.':'A complete router selection was not recorded; no selection is inferred.'}</p></div>`;
    return `<table><thead><tr><th>Guideline · open in policy explorer</th><th>Relevance estimate</th><th>Actually served</th></tr></thead><tbody>${items.map(id=>{
      const n=nodes.get(id)||{},p=finite(n.decisions_p)&&Number(n.decisions_p)>=0&&Number(n.decisions_p)<=1?Number(n.decisions_p):null;
      const actual=typeof n.served_in_prompt==='boolean'?n.served_in_prompt:selection.actualKnown&&bucket!=='pinned'?selection.actual.includes(id):null;
      return `<tr><td><button type="button" class="pr-node-link" data-router-node-id="${esc(id)}">${esc(id)}</button>${n.title?`<div class="pr-footnote" style="margin:3px 0 0">${esc(n.title)}</div>`:''}</td><td><span class="pr-prob">${bucket==='pinned'?'Always pinned':p===null?'Not recorded':p.toFixed(3)}</span>${p!==null&&bucket!=='pinned'?`<div class="pr-prob-track"><div class="pr-prob-fill" style="width:${(p*100).toFixed(2)}%"></div></div>`:''}</td><td><span class="pr-read-badge${actual===false?' no':''}">${actual===null?'Not recorded':actual?'Yes':'No'}</span></td></tr>`;
    }).join('')}</tbody></table>`;
  }
  function mount(win){
    const $=s=>document.querySelector(s);if(!$('#prRouter'))return;
    const state={active:false,data:null,selected:null,detail:null,bucket:'selected',filter:'all',busy:false,seq:0,detailSeq:0,timer:null,playTimer:null,playing:false,failures:0,followLatest:true,details:new Map()};
    const api='/api/policy-graph/router-cycles';
    const status=(text,error=false)=>{$('#prStatus').textContent=text;$('#prStatus').classList.toggle('is-error',error);};
    const rows=()=>filteredRuns(state.data?.runs,state.filter);
    const stopFlow=()=>{if(state.playTimer)win.clearTimeout(state.playTimer);state.playTimer=null;state.playing=false;$('#prPlayFlow').textContent='▶ Play recorded flow';$('#prFlow').querySelectorAll('[data-flow-stage]').forEach(e=>e.classList.remove('is-playing'));};
    function clearTimer(){if(state.timer)win.clearTimeout(state.timer);state.timer=null;}
    function schedule(){clearTimer();if(state.active&&!document.hidden&&$('#prAutoRefresh').checked&&state.failures<3)state.timer=win.setTimeout(()=>refresh(),30000);}
    function renderTrial(){
      const t=trialModel(state.data?.trial),start=t.starts_at?dateText(t.starts_at):'Start not recorded',end=t.ends_at?dateText(t.ends_at):'End not recorded';
      $('#prTrial').innerHTML=`<div class="pr-trial-head"><div><h3>${esc(t.heading)}</h3><p>${esc(start)} → ${esc(end)}</p></div><span class="pr-trial-label">${esc(t.label)}</span></div>${t.progress!==null?`<div class="pr-trial-track" role="progressbar" aria-label="Shadow observation window elapsed" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(t.progress*100)}"><div class="pr-trial-fill" style="width:${(t.progress*100).toFixed(2)}%"></div></div>`:''}<p style="margin-top:10px">${esc(t.note)} <strong>No automatic go-live.</strong></p>`;
      const trial=state.data?.trial||{};
      if(finite(trial.cycles))$('#prTrial').insertAdjacentHTML('beforeend',`<p class="pr-footnote">This evaluation window: ${esc(number(trial.cycles))} new cycles · ${esc(money(trial.cost_usd))} recorded spend. The cycle browser also includes earlier comparisons and replay probes.</p>`);
      const totals=state.data?.totals||{},known=finite(totals.known_cost_usd)?money(totals.known_cost_usd):money(totals.cost_usd);
      $('#prSummary').innerHTML=metric('Forward comparisons',number(totals.forward_runs??((Number(totals.live_runs)||0)+(Number(totals.observer_runs)||0))),'Observer and in-cycle timing remain labeled')+metric('Replay probes',number(totals.replay_runs),'Historical inputs, separate from forward evidence')+metric('Recorded router spend',finite(totals.cost_usd)?money(totals.cost_usd):known,(Number(totals.unknown_cost_calls)||0)>0?`${number(totals.unknown_cost_calls)} calls have unknown cost; shown amount is known subtotal`:'Complete router fee in the displayed window')+metric('Realized routing savings','$0.00000','Shadow keeps the actual trading prompt unchanged');
    }
    function renderList(){
      const values=rows();$('#prCycleCount').textContent=number(values.length);
      $('#prCycles').innerHTML=values.length?values.map(row=>{const source=sourceInfo(row),selection=selectionFor(row);return `<button type="button" class="pr-cycle-row${String(row.id)===String(state.selected)?' is-selected':''}" data-router-cycle="${esc(row.id)}" aria-pressed="${String(String(row.id)===String(state.selected))}"><span class="pr-cycle-row-head"><strong>#${esc(row.id)} · v${esc(row.prompt_version??'?')}</strong><span class="pr-source${source.forward?' forward':''}">${esc(source.short)}</span></span><small>${esc(dateText(row.decided_at))}</small><span class="pr-row-line"><i class="pr-cycle-dot${row.status==='ok'?'':' failed'}" aria-hidden="true"></i>${esc(selection.available?`${selection.selected.length} keep · ${selection.skipped.length} skip`:row.status||'Unknown')}<span style="margin-left:auto">${esc(money(row.cost_usd))}</span></span></button>`;}).join(''):'<div class="pr-empty"><p>No saved cycles match this filter.</p></div>';
      const asc=values.slice().reverse(),index=asc.findIndex(r=>String(r.id)===String(state.selected));
      $('#prCycleSlider').max=String(Math.max(0,asc.length-1));$('#prCycleSlider').value=String(Math.max(0,index));$('#prCycleSlider').disabled=asc.length<2;$('#prPrevious').disabled=index<=0;$('#prNext').disabled=index<0||index>=asc.length-1;$('#prSliderLabel').textContent=index>=0?`${index+1}/${asc.length}`:'—';
    }
    function renderNodes(){
      if(!state.detail)return;
      document.querySelectorAll('[data-router-nodes]').forEach(button=>{const selected=button.dataset.routerNodes===state.bucket;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});
      $('#prNodeTable').innerHTML=tableHTML(state.detail,state.bucket);
    }
    function renderDetail(row){
      stopFlow();state.detail=row;const m=flowModel(row),s=m.selected;
      $('#prEmpty').hidden=true;$('#prCycleDetail').hidden=false;
      $('#prCycleKicker').textContent=m.source.label;$('#prCycleTitle').textContent=`Cycle #${row.id} · ${dateText(row.decided_at)}`;
      $('#prCycleMeta').textContent=`${row.run_id||'Run ID not recorded'} · policy v${row.prompt_version??'?'} · ${row.model||'Model not recorded'} · ${m.source.note}`;
      $('#prFlow').innerHTML=flowHTML(row);$('#prFlowCaption').textContent=`${m.source.note} Recorded sequence, not a live model trace. Relevance does not estimate trading profit.`;
      $('#prCycleStats').innerHTML=metric('Router API fee',money(row.cost_usd),'Standard-rate usage estimate')+metric('Router input tokens',number(row.input_tokens),'Includes supplied images')+metric('Router latency',finite(row.latency_ms)?`${number(row.latency_ms)} ms`:'Unknown','Measured request duration')+metric('Screenshot evidence',number(m.imageCount),`${m.coverage} coverage`);
      $('#prCycleEconomics').innerHTML=win.DAIRouterEconomics?.render(row.economics)||'<p class="pr-footnote">Matched full-prompt token estimates were not captured for this cycle.</p>';
      for(const [id,key]of[['#prSelectedCount','selected'],['#prSkippedCount','skipped'],['#prPinnedCount','pinned'],['#prActualCount','actual']])$(id).textContent=key==='actual'&&!s.actualKnown?'?':s[key].length;
      $('#prSelectionNote').textContent=row.note||'Optional context is scored for relevance. Standing controls stay pinned. The proposed skip list is not applied during shadow evaluation.';
      renderNodes();
    }
    async function selectCycle(id,manual=true){
      if(!finite(id))return;state.selected=Number(id);if(manual)state.followLatest=false;renderList();stopFlow();
      const seq=++state.detailSeq;
      if(state.details.has(state.selected)){renderDetail(state.details.get(state.selected));return;}
      status('Loading the saved cycle trace…');
      try{
        const response=await fetch(`${api}/${encodeURIComponent(state.selected)}`,{headers:{Accept:'application/json'},cache:'no-store'});
        const payload=await response.json();if(!response.ok)throw new Error(payload.error||`Request failed (${response.status})`);
        const row=payload.cycle||payload;
        if(seq!==state.detailSeq||!state.active)return;
        state.details.set(state.selected,row);renderDetail(row);status('Saved trace loaded. Auto-refresh watches for new cycles while this tab is visible.');
      }catch(error){if(seq!==state.detailSeq)return;status(`Cycle trace unavailable: ${error.message}`,true);$('#prEmpty').hidden=false;$('#prCycleDetail').hidden=true;}
    }
    async function refresh(){
      if(state.busy||!state.active||document.hidden)return;state.busy=true;const seq=++state.seq;clearTimer();$('#prRefresh').disabled=true;status('Reading recorded routing cycles…');
      try{
        const response=await fetch(`${api}?limit=100`,{headers:{Accept:'application/json'},cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);if(seq!==state.seq||!state.active)return;
        state.data=data;state.failures=0;renderTrial();const values=rows();
        if(!values.length){state.selected=null;state.detail=null;$('#prEmpty').hidden=false;$('#prCycleDetail').hidden=true;renderList();status('No recorded cycles yet. New forward observations will appear here.');}
        else{const current=values.find(r=>String(r.id)===String(state.selected)),chosen=state.followLatest||!current?values[0]:current;await selectCycle(chosen.id,false);}
      }catch(error){if(seq===state.seq){state.failures++;status(`Saved cycles unavailable: ${error.message}${state.failures>=3?' Auto-refresh paused; use Refresh cycles to retry.':''}`,true);}}
      finally{state.busy=false;$('#prRefresh').disabled=false;schedule();}
    }
    function setActive(active){state.active=active;if(active){refresh();}else{++state.detailSeq;clearTimer();stopFlow();}}
    function step(delta){const asc=rows().slice().reverse(),i=asc.findIndex(r=>String(r.id)===String(state.selected)),next=asc[i+delta];if(next)selectCycle(next.id);}
    function playFlow(){
      if(state.playing){stopFlow();return;}if(!state.detail)return;
      state.playing=true;$('#prPlayFlow').textContent='■ Stop recorded flow';let stage=0;
      const reduced=win.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      const next=()=>{if(!state.playing||!state.active)return;$('#prFlow').querySelectorAll('[data-flow-stage]').forEach(e=>e.classList.toggle('is-playing',Number(e.dataset.flowStage)===stage));$('#prFlowCaption').textContent=['01 · Inspect the recorded context and image coverage.','02 · Read the stored relevance proposal; pinned controls stay included.','03 · Shadow leaves the actual trading prompt unchanged.'][stage];stage++;state.playTimer=win.setTimeout(stage<3?next:stopFlow,reduced?1500:1150);};next();
    }
    $('#prRefresh').addEventListener('click',()=>{state.failures=0;refresh();});$('#prAutoRefresh').addEventListener('change',schedule);
    $('#prSourceFilter').addEventListener('change',e=>{state.filter=e.target.value;state.followLatest=true;const values=rows();renderList();if(values.length)selectCycle(values[0].id,false);else{$('#prEmpty').hidden=false;$('#prCycleDetail').hidden=true;}});
    $('#prCycles').addEventListener('click',e=>{const button=e.target.closest('[data-router-cycle]');if(button)selectCycle(button.dataset.routerCycle);});
    $('#prCycleSlider').addEventListener('input',e=>{const row=rows().slice().reverse()[Number(e.target.value)];if(row)selectCycle(row.id);});$('#prPrevious').addEventListener('click',()=>step(-1));$('#prNext').addEventListener('click',()=>step(1));$('#prPlayFlow').addEventListener('click',playFlow);
    document.querySelectorAll('[data-router-nodes]').forEach(button=>button.addEventListener('click',()=>{state.bucket=button.dataset.routerNodes;renderNodes();}));
    $('.pr-node-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...e.currentTarget.querySelectorAll('[role=tab]')],i=buttons.indexOf(document.activeElement);if(i<0)return;e.preventDefault();const index=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[index].click();buttons[index].focus();});
    $('#prNodeTable').addEventListener('click',e=>{const button=e.target.closest('[data-router-node-id]');if(!button||!state.detail)return;const p=new URLSearchParams(location.hash.slice(1));p.set('agent','DeciderAgent');if(finite(state.detail.prompt_version))p.set('v',String(state.detail.prompt_version));p.set('node',button.dataset.routerNodeId);p.delete('view');location.hash=p.toString();});
    win.addEventListener('policygraph:viewchange',e=>setActive(e.detail?.view==='router'));
    win.addEventListener('hashchange',()=>setActive(new URLSearchParams(location.hash.slice(1)).get('view')==='router'));
    document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimer();stopFlow();}else if(state.active)refresh();});
    renderTrial();setActive(new URLSearchParams(location.hash.slice(1)).get('view')==='router');
  }
  return {dateText,sourceInfo,selectionFor,filteredRuns,trialModel,flowModel,flowHTML,tableHTML,money,mount};
}));
