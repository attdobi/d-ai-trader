/* Learning map: presentation only. No order, policy activation or model-call endpoints. */
(function (root, factory) {
  'use strict';
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  if (typeof document !== 'undefined') helpers.mount(root);
}(typeof window !== 'undefined' ? window : this, function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const list = value => Array.isArray(value) ? value : [];
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const revisionKey = n => String(n.key || `${n.id}:${n.source_hash || n.body || ''}`);
  const versionsOf = n => list(n.versions).map(Number);
  const number = (n, fallback = '—') => finite(n) ? Number(n).toLocaleString() : fallback;
  const rate = n => finite(n) ? `${(Number(n) * 100).toFixed(1)}%` : '—';
  const returnText = n => finite(n) ? `${Number(n) > 0 ? '+' : ''}${Number(n).toFixed(2)}%` : 'Pending';
  const short = (s, limit = 40) => String(s || '').length > limit ? String(s).slice(0, limit - 1) + '…' : String(s || '');
  const dateText = value => {
    if(!value)return 'Time not recorded';
    const raw=String(value);
    if(/(?:Z|[+-]\d{2}:\d{2})$/.test(raw)) {
      const date=new Date(raw);
      if(!Number.isNaN(date.getTime()))return date.toLocaleString('en-US',{timeZone:'America/Los_Angeles',year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' PT';
    }
    return raw.replace('T',' ').slice(0,16)+' (as logged)';
  };
  const cited = c => list(c.cited || c.citations).map(n => typeof n === 'string' ? n : n.node_id || n.id).filter(Boolean);
  const casesFor = data => {
    const seen=new Set();
    return [...list(data?.opportunities?.cases), ...list(data?.evidence)].filter(c=>{
      const key=`${c.input_id??c.source_input_id??c.id}:${c.ticker||''}`;
      if(seen.has(key))return false;seen.add(key);return true;
    }).sort((a,b)=>String(b.observed_at||'').localeCompare(String(a.observed_at||'')));
  };

  function snapshot(landmarks, version, previousVersion) {
    const all = list(landmarks);
    const current = all.filter(n => versionsOf(n).includes(Number(version)));
    const previous = previousVersion === null || previousVersion === undefined ? [] : all.filter(n => versionsOf(n).includes(Number(previousVersion)));
    const before = new Map(previous.map(n => [n.id, n]));
    const after = new Map(current.map(n => [n.id, n]));
    const points = current.map(n => ({...n, lifecycle: !before.has(n.id) ? 'added' : revisionKey(before.get(n.id)) !== revisionKey(n) ? 'modified' : 'unchanged'}));
    const retired = previous.filter(n => !after.has(n.id)).map(n => ({...n, lifecycle:'retired'}));
    const trails = current.filter(n => before.has(n.id) && revisionKey(before.get(n.id)) !== revisionKey(n)).map(n => ({id:n.id, from:before.get(n.id), to:n}));
    return {points, retired, trails, previous:before};
  }

  function outcomeFor(item, horizon) {
    const raw = item?.outcomes || item?.paper_outcomes || {};
    if (Array.isArray(raw)) return raw.find(o => Number(o.horizon ?? o.sessions) === Number(horizon)) || null;
    return raw[String(horizon)] || raw[Number(horizon)] || null;
  }

  function lineDiff(before, after) {
    const a = String(before || '').split('\n'), b = String(after || '').split('\n');
    // Long documents retain both exact texts without an expensive browser diff.
    if (a.length > 250 || b.length > 250) return null;
    const lengths = Array.from({length:a.length + 1}, () => new Uint16Array(b.length + 1));
    for (let i=a.length-1;i>=0;i--) for (let j=b.length-1;j>=0;j--) lengths[i][j] = a[i] === b[j] ? 1 + lengths[i+1][j+1] : Math.max(lengths[i+1][j], lengths[i][j+1]);
    const out=[]; let i=0,j=0;
    while (i<a.length || j<b.length) {
      if (i<a.length && j<b.length && a[i] === b[j]) { out.push({kind:'same', text:a[i++]}); j++; }
      else if (j<b.length && (i === a.length || lengths[i][j+1] >= lengths[i+1][j])) out.push({kind:'added',text:b[j++]});
      else out.push({kind:'removed',text:a[i++]});
    }
    return out;
  }

  function replayInputIds(data, incumbentVersion, count) {
    const seen=new Set(), ids=[];
    for(const c of casesFor(data)) {
      const id=Number(c.input_id??c.source_input_id);
      if(Number(c.prompt_version)!==Number(incumbentVersion)||!Number.isInteger(id)||id<=0||seen.has(id))continue;
      seen.add(id);ids.push(id);
      if(ids.length>=Math.max(1,Math.min(6,Number(count)||1)))break;
    }
    return ids;
  }

  function extent(landmarks, projection = {}) {
    if (projection.frozen) return {x:[0,1],y:[0,1]};
    const points = list(landmarks).filter(n => finite(n.x) && finite(n.y));
    if (!points.length) return {x:[-1,1],y:[-1,1]};
    return {x:[Math.min(...points.map(n=>Number(n.x))),Math.max(...points.map(n=>Number(n.x)))], y:[Math.min(...points.map(n=>Number(n.y))),Math.max(...points.map(n=>Number(n.y)))]};
  }

  const marketThemes = item => [...new Set(list(item?.market_themes).map(String).filter(Boolean))].length ? [...new Set(list(item.market_themes).map(String).filter(Boolean))] : ['general'];
  const inMarketTheme = (item, theme) => !theme || marketThemes(item).includes(theme);
  const themeCatalog = data => list(data?.theme_catalog).length ? list(data.theme_catalog) : [{id:'general',label:'General policy',description:'No market topic recorded.'}];
  function sourceObservations(data, theme='', search='') {
    const query=String(search||'').toLowerCase();
    return list(data?.source_observations?.observations).filter(row=>inMarketTheme(row,theme)&&(!query||`${row.text||''} ${row.source_agent||''}`.toLowerCase().includes(query)));
  }
  function themeCounts(theme, guidelines) {
    return `${number(guidelines,0)} guidelines · ${number(theme?.news_observation_count,0)} news · ${number(theme?.feedback_hypothesis_count,0)} hypotheses`;
  }
  function sourceExcerpt(row, theme='') {
    const text=String(row?.text||'Text unavailable');
    const evidence=list(row?.theme_evidence).filter(e=>e.theme_id===theme).flatMap(e=>list(e.matches));
    const at=evidence.map(word=>text.toLowerCase().indexOf(String(word).toLowerCase())).filter(i=>i>=0).sort((a,b)=>a-b)[0];
    if(!theme||at===undefined||text.length<=450)return short(text,450);
    const start=Math.max(0,at-130),end=Math.min(text.length,start+450);
    return (start?'…':'')+text.slice(start,end)+(end<text.length?'…':'');
  }
  function themePosition(id, theme, box) {
    // Category positions are a readable grid, separate from stored embeddings.
    // The layout receives the whole version before display filters are applied.
    const index=list(box.member_ids).indexOf(String(id));
    if(index>=0) {
      const columns=box.point_columns,cellWidth=(box.width-40)/columns;
      return {x:box.x+20+(index%columns+.5)*cellWidth,y:box.y+64+Math.floor(index/columns)*54};
    }
    // Backward-compatible placement when no membership list is available.
    const hash = text => {let n=2166136261;for(const c of String(text)){n^=c.charCodeAt(0);n=Math.imul(n,16777619);}return n>>>0;};
    const angle=hash(`${theme}:${id}`)/4294967296*Math.PI*2;
    const radius=Math.sqrt(hash(`${id}:${theme}:radius`)/4294967296)*.94;
    return {x:box.x+box.width/2+Math.cos(angle)*radius*Math.max(12,box.width/2-24),
      y:box.y+48+(box.height-60)/2+Math.sin(angle)*radius*Math.max(12,(box.height-70)/2)};
  }
  function themeLayout(catalog, width, landmarks=[]) {
    const membership=theme=>[...new Set(list(landmarks).filter(n=>marketThemes(n).includes(theme.id)).map(n=>String(n.id)))].sort();
    const rows=list(catalog).map(theme=>({...theme,member_ids:membership(theme)})).sort((a,b)=>{
      const priority=group=>group.member_ids.length>12||(group.id==='general'&&group.member_ids.length>4)?2:group.member_ids.length?1:0;
      return priority(b)-priority(a); // Stable ties retain the catalog order.
    });
    const columns=width>=1100?3:width>=560?2:1,gap=12,fullWidth=width-32;
    const cellWidth=(fullWidth-gap*(columns-1))/columns,groups=[];
    let column=0,y=14,rowHeight=0;
    const flush=()=>{if(column){y+=rowHeight+gap;column=0;rowHeight=0;}};
    for(const theme of rows) {
      const member_ids=theme.member_ids;
      const wide=member_ids.length>12||(theme.id==='general'&&member_ids.length>4);
      if(wide)flush();
      const groupWidth=wide?fullWidth:cellWidth;
      const point_columns=Math.max(1,Math.min(member_ids.length,Math.floor((groupWidth-40)/108)));
      const height=member_ids.length?Math.max(150,64+Math.ceil(member_ids.length/point_columns)*54):94;
      groups.push({...theme,x:16+column*(cellWidth+gap),y,width:groupWidth,height,member_ids,point_columns});
      if(wide){y+=height+gap;}else{column++;rowHeight=Math.max(rowHeight,height);if(column===columns)flush();}
    }
    flush();
    return {width,height:y+13,groups};
  }
  function themeEvidenceLabel(node, themeId) {
    const evidence=list(node?.theme_evidence).filter(e=>!themeId||e.theme_id===themeId);
    const direct=evidence.some(e=>e.source==='direct_text'),linked=evidence.some(e=>e.source==='cited_case');
    return direct&&linked?'Mentioned in rule text and linked by cited cases':direct?'Mentioned in rule text':linked?'Linked through version-matched cited cases':'No explicit market topic recorded';
  }
  function caseThemeEvidenceLabel(item, themeId) {
    const evidence=list(item?.theme_evidence).filter(e=>e.theme_id===themeId),reference=evidence.some(e=>e.source==='ticker_reference'),context=evidence.some(e=>e.source==='case_context');
    if(themeId==='general')return 'No explicit topic in saved context or issuer reference';
    if(reference&&context)return 'Saved context and curated issuer exposure; topic association does not verify an event';
    if(reference)return 'Curated issuer/industry exposure; no cycle catalyst or event inferred';
    return 'Matched saved context; topic association does not verify an event';
  }

  function mount(win) {
    const $ = s => document.querySelector(s);
    if (!$('#plLearning')) return;
    const state = {active:false, lens:'evolution', layout:'themes', marketTheme:'', data:null, agent:null, version:null, index:0, search:'', theme:'', showRetired:true, selected:null, caseId:null, horizon:3, seq:0, controller:null, timer:null, loadingKey:null, replayPreview:null, previewSeq:0, replayBusy:false, jobId:null, pollTimer:null, pollCount:0, pollErrors:0, reduced:win.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false};
    const agentFromPage = () => new URLSearchParams(location.hash.slice(1)).get('agent') || document.querySelector('#pgAgentSwitch .is-active')?.dataset.agent || 'DeciderAgent';
    const versionFromPage = () => Number($('#pgVersion')?.value || new URLSearchParams(location.hash.slice(1)).get('v'));
    const versions = () => list(state.data?.versions).filter(v=>finite(v.version)).slice().sort((a,b)=>Number(a.version)-Number(b.version));
    const current = () => versions()[state.index] || null;
    const status = (text, error=false) => { $('#plStatus').textContent=text; $('#plStatus').classList.toggle('is-error', error); };
    const empty = (title,text) => `<div class="pl-empty"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
    const typeView = n => win.PolicyGraphSchema?.nodeView(n) || {title:n.title || n.id,typeLabel:n.node_type || 'Guideline',color:'#8ab4cc',structural:false};

    function writeView(selectedView) {
      const p = new URLSearchParams(location.hash.slice(1));
      if (['learning','router'].includes(selectedView)) p.set('view',selectedView); else p.delete('view');
      history.replaceState(null,'',`#${p.toString()}`);
    }
    function openExplorer(id,version) {
      setView(false);
      if(versionFromPage()===Number(version)&&win.pgOpenNode?.(id))return;
      const p=new URLSearchParams(location.hash.slice(1));p.set('agent',state.agent||'DeciderAgent');
      if(finite(version))p.set('v',String(version));p.set('node',id);p.delete('view');location.hash=p.toString();
    }
    function setView(value, update=true) {
      const active=value===true||value==='learning',selectedView=active?'learning':value==='router'?'router':'explorer';
      state.active=active;
      document.querySelector('.pg-page')?.classList.toggle('pl-learning-active',active);
      document.querySelector('.pg-page')?.classList.toggle('pr-router-active',selectedView==='router');
      const routerPanel=$('#prRouter');if(routerPanel)routerPanel.hidden=selectedView!=='router';
      $('#plLearning').hidden=!active;
      document.querySelectorAll('[data-policy-view]').forEach(b=>{const selected=b.dataset.policyView===selectedView; b.setAttribute('aria-selected',String(selected)); b.tabIndex=selected?0:-1;});
      if (update) writeView(selectedView);
      if(typeof win.CustomEvent==='function')win.dispatchEvent(new win.CustomEvent('policygraph:viewchange',{detail:{view:selectedView}}));
      if (active) { load(); win.requestAnimationFrame(renderMap);if(state.jobId)pollReplay(); } else {stopPlayback();if(state.pollTimer)win.clearTimeout(state.pollTimer);state.pollTimer=null;}
    }
    function setLens(lens) {
      if (!['evolution','evidence','comparison'].includes(lens)) return;
      state.lens=lens;
      document.querySelectorAll('[data-learning-lens]').forEach(b=>{const selected=b.dataset.learningLens===lens;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});
      for(const [id,key] of [['#plEvolution','evolution'],['#plEvidence','evidence'],['#plComparison','comparison']]) $(id).hidden=key!==lens;
      if(lens!=='evolution') stopPlayback();
      if(lens==='evolution') win.requestAnimationFrame(renderMap);
    }
    async function load(force=false) {
      const agent=state.agent || agentFromPage(), version=state.version ?? versionFromPage();
      if (!Number.isFinite(version)) return;
      const key=`${agent}:${version}`;
      if (!force && state.loadingKey===key) return;
      const keepVersion=force&&state.agent===agent?current()?.version:null,keepSelected=force?state.selected:null,keepCase=force?state.caseId:null;
      const seq=++state.seq;
      state.controller?.abort(); state.controller=new AbortController(); state.loadingKey=key;
      stopPlayback(); status('Loading policy history and recorded evidence…');
      try {
        const query=new URLSearchParams({agent,version:String(version),days:'90'});
        const response=await fetch(`/api/policy-graph/learning?${query}`,{headers:{Accept:'application/json'},cache:'no-store',signal:state.controller.signal});
        const data=await response.json();
        if(!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
        if(seq!==state.seq) return;
        state.data=data; state.agent=agent;state.version=version;
        const history=versions(), selected=history.findIndex(v=>Number(v.version)===Number(keepVersion??data.selected_version??version));
        state.index=selected>=0?selected:Math.max(0,history.length-1);state.selected=list(data.landmarks).some(n=>revisionKey(n)===keepSelected)?keepSelected:null;state.caseId=casesFor(data).some(c=>String(c.id)===String(keepCase))?keepCase:null;
        render();status(`${number(history.length)} policy versions · ${number(list(data.landmarks).length)} text revisions · saved evidence only`);
      } catch(error) {
        if(error.name==='AbortError' || seq!==state.seq) return;
        state.loadingKey=null;
        status(`Learning map unavailable: ${error.message}`,true);
        $('#plMap').innerHTML=empty('History could not be loaded.','The policy explorer remains available. Try opening Learning map again.');
      }
    }
    function render() {
      const themes=new Map();list(state.data?.landmarks).forEach(n=>list(n.tags).forEach(tag=>themes.set(String(tag),(themes.get(String(tag))||0)+1)));
      const themeOptions=[...themes.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,16);
      $('#plTheme').innerHTML='<option value="">All policy sections</option><optgroup label="Policy sections"><option value="strategy_directives">Trading rules</option><option value="soul">Identity</option><option value="memory">Learned context</option></optgroup>'+(themeOptions.length?`<optgroup label="Recorded policy tags">${themeOptions.map(([tag])=>`<option value="tag:${esc(tag)}">#${esc(tag.replace(/^#/,''))}</option>`).join('')}</optgroup>`:'');
      $('#plTheme').value=state.theme;if($('#plTheme').value!==state.theme)state.theme='';
      const marketOptions='<option value="">All market themes</option>'+themeCatalog(state.data).map(t=>`<option value="${esc(t.id)}">${esc(t.path_label||t.label)}</option>`).join('');
      for(const id of ['#plMarketTheme','#plEvidenceTheme']){$(id).innerHTML=marketOptions;$(id).value=state.marketTheme;}
      if($('#plMarketTheme').value!==state.marketTheme)state.marketTheme='';
      renderTimeline();renderMap();renderInspector();renderEvidence();renderReplays();configureReplayForm();
      $('#plNotes').innerHTML=list(state.data?.notes).map(note=>`<p>${esc(note)}</p>`).join('');
    }
    function renderTimeline() {
      const history=versions(), version=current();
      $('#plTimeline').max=String(Math.max(0,history.length-1));$('#plTimeline').value=String(state.index);$('#plTimeline').disabled=history.length<2;
      $('#plTimeline').setAttribute('aria-valuetext',version?`Policy version ${version.version}`:'No policy versions');
      $('#plPrevious').disabled=state.index<=0;$('#plNext').disabled=state.index>=history.length-1;
      $('#plPlay').disabled=history.length<2 || state.reduced;
      $('#plPlay').title=state.reduced?'Automatic playback is disabled by your reduced-motion preference. Use the version steps.':'';
      $('#plVersionLabel').textContent=version?`v${version.version}`:'—';
      $('#plVersionDescription').textContent=version?`${dateText(version.created_at)} · ${version.description || 'Policy snapshot'}`:'No policy history recorded.';
      const s=version?snapshot(state.data?.landmarks,version.version,history[state.index-1]?.version):null;
      $('#plVersionChanges').textContent=s?`${s.points.filter(n=>n.lifecycle==='added').length} added · ${s.trails.length} modified · ${s.retired.length} retired`:'';
    }
    function setIndex(index) {
      const selected=list(state.data?.landmarks).find(n=>revisionKey(n)===state.selected);
      state.index=Math.max(0,Math.min(versions().length-1,Number(index)||0));
      if(selected){const next=getSnapshot();const replacement=[...next.points,...next.retired].find(n=>n.id===selected.id);state.selected=replacement?revisionKey(replacement):null;}
      renderTimeline();renderMap();renderInspector();
    }
    function stopPlayback() {
      if(state.timer) win.clearInterval(state.timer);
      state.timer=null;$('#plPlay').textContent='▶ Play history';$('#plPlay').setAttribute('aria-label','Play policy history');
    }
    function startPlayback() {
      if(state.timer) { stopPlayback();return; }
      if(state.reduced || versions().length<2) return;
      if(state.index>=versions().length-1) setIndex(0);
      $('#plPlay').textContent='Ⅱ Pause history';$('#plPlay').setAttribute('aria-label','Pause policy history');
      state.timer=win.setInterval(()=>{if(state.index>=versions().length-1) stopPlayback();else setIndex(state.index+1);},1500);
    }
    function getSnapshot() {
      const history=versions();return snapshot(state.data?.landmarks,current()?.version,history[state.index-1]?.version);
    }
    function matches(n) {
      const schema=typeView(n); if(schema.structural) return false;
      if(state.theme && (state.theme.startsWith('tag:')?!list(n.tags).map(String).includes(state.theme.slice(4)):n.field!==state.theme)) return false;
      if(!inMarketTheme(n,state.marketTheme)) return false;
      const text=`${n.id} ${n.title} ${n.body} ${list(n.tags).join(' ')} ${marketThemes(n).map(id=>themeCatalog(state.data).find(t=>t.id===id)?.label||id).join(' ')}`.toLowerCase();
      return !state.search || text.includes(state.search.toLowerCase());
    }
    function renderThemeSummary() {
      const catalog=themeCatalog(state.data),theme=catalog.find(t=>t.id===state.marketTheme);
      const currentNodes=getSnapshot().points;
      const populated=catalog.filter(t=>currentNodes.some(n=>marketThemes(n).includes(t.id)));
      const summary=theme ? `${theme.path_label||theme.label}: ${themeCounts(theme,currentNodes.filter(n=>inMarketTheme(n,theme.id)).length)} · ${number(theme.case_count,0)} displayed decision cases. ${theme.description||''}` : `${populated.length} themes contain guidelines in this version. News observations and feedback hypotheses are counted separately from learned rules. Parent/child themes overlap; do not sum them as independent events.`;
      $('#plThemeSummary').innerHTML=`<p>${esc(summary)}</p><p class="pl-boundary-note"><span>Decision boundary: not validated</span> These regions group recorded topics. Testing a BUY/PASS boundary requires matched routed/full decisions and later outcomes; colors do not estimate profitability.</p>`;
      renderSourceObservations();
    }
    function renderSourceObservations() {
      const target=$('#plSourceList'),summary=$('#plSourceSummary'),reviewBox=$('#plTaxonomyReview');
      if(!target||!summary||!reviewBox)return;
      const inventory=state.data?.source_observations||{},rows=sourceObservations(state.data,state.marketTheme,state.search),review=state.data?.taxonomy_review;
      summary.textContent=inventory.available===false?'Observation history unavailable; no topic or lesson inferred.':`${number(inventory.safe_record_count,0)} safe parsed source records in the ${number(inventory.window_days,90)}-day window · ${rows.length} matching sampled records · showing up to 8. These news reports and feedback hypotheses are not independent events, assessed trades or approved rules. ${inventory.truncated?'The scan was capped. ':''}${inventory.sample_truncated?'The displayed sample is bounded and balanced by topic. ':''}`;
      reviewBox.innerHTML=review?`<p class="pl-footnote"><strong>${esc(review.taxonomy_version)} · Sol organization review</strong> · ${number(list(review.topics).length)} source-grounded topics · ${esc(dateText(review.created_at))}. No trading policy was changed.</p><details><summary>Inspect the organization review and suggested categories</summary>${list(review.topics).map(topic=>`<p><strong>${esc(topic.label)}</strong>${String(topic.id).startsWith('proposed_')?' · Suggested addition; not installed':''}<br>${esc(topic.description)}<br><small>${esc(topic.evidence?.[0]?.record_id||'')} · “${esc(topic.evidence?.[0]?.quote||'')}”</small></p>`).join('')}<p>${esc(list(review.limitations).join(' '))}</p></details>`:'';
      target.innerHTML=rows.length?rows.slice(0,8).map(row=>`<article class="pl-source-card"><div class="pl-type-line"><strong>${esc(row.source_kind==='feedback_hypothesis'?'Feedback hypothesis':'News observation')}</strong><span>${esc(row.source_agent||'Recorded source')}</span></div><small>${esc(row.record_id)} · ${esc(dateText(row.observed_at))}</small><p>${esc(sourceExcerpt(row,state.marketTheme))}</p>${String(row.text||'').length>450?`<details><summary>Full saved observation</summary><p>${esc(row.text)}</p></details>`:''}<small>${esc(marketThemes(row).map(id=>themeCatalog(state.data).find(t=>t.id===id)?.label||id).join(' · '))}</small></article>`).join(''):empty('No sampled source observations match.','This does not turn a general rule into a theme-specific lesson. Try another topic or clear the search.');
    }
    function renderMap() {
      const target=$('#plMap');if(!state.data || !state.active || state.lens!=='evolution') return;
      const focusedKey=target.contains(document.activeElement)?document.activeElement?.dataset?.landmarkKey:null;
      const s=getSnapshot(), points=s.points.filter(matches), retired=state.showRetired?s.retired.filter(matches):[];
      const themed=state.layout==='themes',catalog=themeCatalog(state.data);
      const width=Math.max(320,Math.floor(target.clientWidth||650));
      const grouping=themeLayout(catalog,width,[...s.points,...s.retired].filter(n=>!typeView(n).structural)),height=themed?grouping.height:Math.max(400,Math.min(560,width*.7));
      const bounds=extent(state.data.landmarks,state.data.projection);
      const project=(n,themeId)=>themed?themePosition(n.id,themeId,grouping.groups.find(g=>g.id===themeId)):{x:35+(Number(n.x)-bounds.x[0])/(bounds.x[1]-bounds.x[0]||1)*(width-70),y:35+(Number(n.y)-bounds.y[0])/(bounds.y[1]-bounds.y[0]||1)*(height-85)};
      const visible=[...points,...retired].filter(n=>themed||finite(n.x)&&finite(n.y));
      const marks=visible.flatMap(node=>themed?marketThemes(node).filter(id=>grouping.groups.some(g=>g.id===id)).map(themeId=>({node,themeId})): [{node,themeId:null}]);
      $('#plMapCount').textContent=`${points.length} current · ${retired.length} retired${themed&&marks.length>visible.length?' · multi-theme rules repeat':''}`;
      const types=new Map();points.forEach(n=>{const v=typeView(n);types.set(v.typeLabel,{color:v.color,count:(types.get(v.typeLabel)?.count||0)+1});});
      if($('#plTypeKey'))$('#plTypeKey').innerHTML=[...types.entries()].map(([label,v])=>`<span><i style="background:${esc(v.color)}"></i>${esc(label)} ${v.count}</span>`).join('');
      renderThemeSummary();
      const projection=state.data.projection||{};
      $('#plProjectionNote').textContent=themed?'Descriptive category layout. Topic labels come from explicit text or version-matched cited observations; inspect a rule to see its provenance. Positions inside a category are for legibility, not embeddings or a learned trading surface.':(projection.note||'Fixed coordinates describe text similarity, not expected return or the Decider’s full decision surface.')+(projection.pending?` ${projection.pending} revisions await compatible coordinates and are not plotted in this arrangement.`:'');
      if(!marks.length&&!themed) {target.innerHTML=empty('No landmarks in this view.','Choose another version, market theme, policy section or search.');return;}
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('height',String(height));svg.setAttribute('role','group');svg.setAttribute('aria-label',`${themed?'Market-theme groups':'Text-similarity landscape'} for policy version ${current()?.version}. Select a rule to inspect its history.`);
      const ns=(tag,attrs={},text)=>{const el=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;return el;};
      if(themed) {
        for(const group of grouping.groups) {
          const muted=state.marketTheme&&state.marketTheme!==group.id,box=ns('g',{class:`pl-theme-group${muted?' is-muted':''}`,'data-market-theme':group.id});
          box.append(ns('rect',{x:group.x,y:group.y,width:group.width,height:group.height,rx:10}));
          box.append(ns('text',{class:'pl-theme-title',x:group.x+12,y:group.y+21},short(group.label,Math.max(12,Math.floor((group.width-24)/6.3)))));
          const count=points.filter(n=>marketThemes(n).includes(group.id)).length;
          box.append(ns('text',{class:'pl-theme-count',x:group.x+12,y:group.y+38},themeCounts(group,count)));
          if(!count)box.append(ns('text',{class:'pl-theme-empty',x:group.x+group.width/2,y:group.y+group.height/2+16,'text-anchor':'middle'},Number(group.observation_count)>0?'Observations recorded; no guideline here':'No matching guidelines here'));
          svg.append(box);
        }
      } else {
        for(let x=35;x<width-20;x+=65)svg.append(ns('line',{class:'pl-grid',x1:x,y1:25,x2:x,y2:height-35}));
        for(let y=35;y<height-30;y+=65)svg.append(ns('line',{class:'pl-grid',x1:25,y1:y,x2:width-25,y2:y}));
        if(state.showRetired)for(const t of s.trails.filter(t=>matches(t.to))){const a=project(t.from),b=project(t.to);if(![a.x,a.y,b.x,b.y].every(Number.isFinite))continue;svg.append(ns('path',{class:'pl-trail',d:`M${a.x},${a.y} L${b.x},${b.y}`}));svg.append(ns('circle',{cx:a.x,cy:a.y,r:3,fill:'#ab905c',opacity:.45}));}
      }
      const labelPoints=new Set(points.filter(n=>n.lifecycle!=='unchanged').slice(0,4).map(revisionKey));
      if(!labelPoints.size)points.slice(0,3).forEach(n=>labelPoints.add(revisionKey(n)));
      const labelBoxes=[];
      function addLabel(g,p,title) {
        const text=short(title,width<450?19:28),w=text.length*6,anchor=p.x>width*.65?'end':'start';
        for(const dy of [-13,25,-29,41]) {
          const x=anchor==='end'?-14:14,left=anchor==='end'?p.x+x-w:p.x+x,box={left,right:left+w,top:p.y+dy-11,bottom:p.y+dy+3};
          if(box.left<5||box.right>width-5||box.top<5||box.bottom>height-25||labelBoxes.some(b=>box.left<b.right+5&&box.right>b.left-5&&box.top<b.bottom+3&&box.bottom>b.top-3))continue;
          labelBoxes.push(box);g.append(ns('text',{class:'pl-point-label',x,y:dy,'text-anchor':anchor},text));break;
        }
      }
      for(const {node:n,themeId} of marks){const p=project(n,themeId),v=typeView(n),key=revisionKey(n);const selected=key===state.selected,themeName=catalog.find(t=>t.id===themeId)?.label;const g=ns('g',{class:`pl-point pl-${n.lifecycle}${selected?' is-selected':''}`,transform:`translate(${p.x},${p.y})`,role:'button',tabindex:0,'aria-label':`${v.typeLabel}: ${v.title}. ${n.lifecycle} in version ${current()?.version}${themeName?'. Theme: '+themeName:''}`,'aria-pressed':selected?'true':'false','data-landmark-key':key});g.append(ns('circle',{class:'pl-hit',r:14,fill:'transparent'}));g.append(ns('circle',{class:'pl-selection',r:12}));g.append(ns('circle',{class:'pl-lifecycle',r:9}));g.append(ns('circle',{class:'pl-mark',r:5.5,fill:v.color}));g.append(ns('title',{},`${v.title}\n${n.id}\n${n.lifecycle} · ${v.typeLabel}${themeName?'\n'+themeName+': '+themeEvidenceLabel(n,themeId):''}`));if(themed){const box=grouping.groups.find(group=>group.id===themeId),limit=Math.max(10,Math.min(26,Math.floor((box.width-40)/box.point_columns/6.3)-2));g.append(ns('text',{class:'pl-point-label pl-theme-point-label',x:0,y:20,'text-anchor':'middle'},short(v.title,limit)));}else if(labelPoints.has(key)||selected)addLabel(g,p,v.title);const select=()=>{state.selected=key;stopPlayback();renderMap();renderInspector();};g.addEventListener('click',select);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}});svg.append(g);}
      svg.append(ns('text',{class:'pl-axis-label',x:width-25,y:height-8,'text-anchor':'end'},themed?'TOPIC GROUPS · DESCRIPTIVE LAYOUT':'FIXED TEXT-SIMILARITY COORDINATES'));
      target.replaceChildren(svg);
      if(focusedKey)[...target.querySelectorAll('[data-landmark-key]')].find(g=>g.dataset.landmarkKey===focusedKey)?.focus();
    }
    function reviewText(value) { if(value===true)return 'Approved';if(value===false)return 'Rejected';return value===null||value===undefined||value===''?'Not recorded':String(value); }
    function membershipHTML(item, caseContext=false) {
      const catalog=themeCatalog(state.data);
      return '<div class="pl-topic-badges">'+marketThemes(item).map(id=>{
        const label=catalog.find(t=>t.id===id)?.label||id;
        const note=caseContext?caseThemeEvidenceLabel(item,id):themeEvidenceLabel(item,id);
        return `<span class="pl-topic-badge"><strong>${esc(label)}</strong><small>${esc(note)}</small></span>`;
      }).join('')+'</div>';
    }
    function renderInspector() {
      const panel=$('#plInspector'),all=list(state.data?.landmarks),node=all.find(n=>revisionKey(n)===state.selected);
      if(!node){panel.innerHTML='<span class="pg-eyebrow">SELECT A LANDMARK</span><h3>Every rule has a history.</h3><p class="pg-muted">Choose a point to read its exact text, compare revisions, and inspect the cases and reviews connected to it.</p>';return;}
      const v=typeView(node),s=getSnapshot(),previous=s.previous.get(node.id),currentVersion=Number(current()?.version),entry=s.points.find(n=>revisionKey(n)===state.selected)||s.retired.find(n=>revisionKey(n)===state.selected),lifecycle=entry?.lifecycle||'Historical revision';
      const cases=casesFor(state.data).filter(c=>cited(c).includes(node.id));
      const reviews=list(state.data?.reviews).filter(r=>Number(r.to_version)===currentVersion);
      const diff=previous&&revisionKey(previous)!==revisionKey(node)?lineDiff(previous.body,node.body):null;
      panel.innerHTML=`<div class="pl-type-line"><span style="color:${esc(v.color)}">${esc(v.typeLabel)}</span><span>${esc(lifecycle)}</span></div><h3>${esc(v.title)}</h3><p class="pl-node-id">${esc(node.id)}</p><div class="pl-text-block">${esc(node.body || 'No text recorded.')}</div>${diff?`<details open><summary>Exact text change from previous version</summary><div class="pl-diff">${diff.map(l=>`<span class="${l.kind}">${esc(l.kind==='added'?'+ ':l.kind==='removed'?'− ':'  ')}${esc(l.text)}</span>`).join('')}</div></details>`:''}${previous&&!diff&&revisionKey(previous)!==revisionKey(node)?`<details><summary>Previous exact text</summary><div class="pl-text-block">${esc(previous.body)}</div></details>`:''}<h4>Market themes · source of the association</h4>${membershipHTML(node)}<h4>Review of v${esc(currentVersion)}</h4>${reviews.length?reviews.map(r=>`<p class="pl-type-line"><span>Critic: ${esc(reviewText(r.critic_verdict))}</span><span>Human: ${esc(reviewText(r.human_verdict))}</span></p>`).join(''):'<p class="pl-footnote">No review record for this version. This does not imply approval.</p>'}<h4>Linked opportunity observations · ${cases.length}</h4>${cases.length?`<div class="pl-mini-list">${cases.slice(0,6).map(c=>`<button type="button" class="pl-case-link" data-case-id="${esc(c.id)}">${esc(c.ticker)} · ${esc(c.action || 'Not assessed')}<small>${esc(dateText(c.observed_at))} · policy v${esc(c.prompt_version ?? 'unknown')}</small></button>`).join('')}</div><p class="pl-footnote">Linked by citations, across recorded versions. These associations do not establish the rule’s individual effect.</p>`:'<p class="pl-footnote">No candidate observations cite this guideline yet.</p>'}<button type="button" class="pl-button" id="plOpenGraphNode">Open in policy explorer ↗</button>`;
      panel.querySelectorAll('[data-case-id]').forEach(b=>b.addEventListener('click',()=>{state.caseId=b.dataset.caseId;setLens('evidence');renderEvidence();$('#plEvidence').scrollIntoView({block:'start',behavior:'auto'});}));
      $('#plOpenGraphNode')?.addEventListener('click',()=>openExplorer(node.id,currentVersion));
    }
    function horizonMetrics() {
      const o=state.data?.opportunities||{},m=o.metrics_by_horizon?.[String(state.horizon)] || o.metrics?.by_horizon?.[String(state.horizon)];
      if(m)return m;
      if(Number(o.metrics?.horizon ?? 3)===state.horizon)return o.metrics||{};
      return {};
    }
    function metric(label,value,note) {return `<div class="pl-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;}
    function renderEvidence() {
      if(!state.data)return;
      const allCases=casesFor(state.data),cases=allCases.filter(c=>inMarketTheme(c,state.marketTheme)),m=horizonMetrics();
      const first=(...names)=>names.map(n=>m[n]).find(v=>v!==null&&v!==undefined);
      const uncertainty=(denominator,interval)=>`n=${number(denominator)}${Array.isArray(interval)&&interval.every(finite)?` · 95% interval ${rate(interval[0])}–${rate(interval[1])}`:''}`;
      $('#plEvidenceMetrics').innerHTML=[metric('Bought winners · precision',rate(first('precision','win_rate')),`Profitable BUYs / BUYs excluding break-even · ${uncertainty(m.buy_denominator,m.precision_interval)}`),metric('Winner recall',rate(first('winner_recall','recall')),`Winners bought / eligible winners · ${uncertainty(m.winner_denominator,m.recall_interval)}`),metric('Loss false-positive rate',rate(first('false_positive_rate','fpr')),`Losing candidates bought / eligible losers · ${uncertainty(m.loser_denominator,m.fpr_interval)}`),metric('Net paper expectancy',finite(first('expectancy_pct','mean_net_return_pct','net_expectancy_pct'))?returnText(first('expectancy_pct','mean_net_return_pct','net_expectancy_pct')):'—',`${state.horizon}-session horizon · declared costs`)].join('');
      const pending=allCases.filter(c=>!outcomeFor(c,state.horizon)||outcomeFor(c,state.horizon).status!=='matured').length;
      const history=allCases.filter(c=>c.coverage==='historical_decision_log').length;
      const displayScope=state.marketTheme?`Showing ${cases.length} of ${allCases.length} displayed observations for ${themeCatalog(state.data).find(t=>t.id===state.marketTheme)?.label||state.marketTheme}. The quality metrics above describe the full prospective cohort, not this theme subset. `:'Quality metrics describe the full prospective cohort. ';
      $('#plCoverageNote').textContent=displayScope+`${number(m.episodes)} prospective episodes · ${number(m.assessed)} assessed · ${number(m.matured)} matured · ${number(m.unmatured)} awaiting outcomes. ${history} historical decision-log observations are shown as evidence and excluded from recall. `+(state.data.opportunities?.coverage_note||'')+' '+(m.note || state.data.opportunities?.note || `${allCases.length} observations available; ${pending} pending or unavailable at this horizon. Unknown evidence is not a loss or a PASS.`);
      $('#plCases').innerHTML=cases.length?cases.map(c=>{const o=outcomeFor(c,state.horizon),ret=o?.status==='matured'?o.net_return_pct:null;return `<button type="button" class="pl-case-row${String(c.id)===String(state.caseId)?' is-selected':''}" data-case-id="${esc(c.id)}"><span><strong>${esc(c.ticker)}</strong><small>v${esc(c.prompt_version ?? '?')}</small></span><span>${esc(dateText(c.observed_at))}<small>${esc(String(c.coverage||'Coverage unknown').replaceAll('_',' '))}</small></span><span>${esc(c.action || 'Not assessed')}<small>Model action</small></span><span class="pl-return ${finite(ret)?(Number(ret)>=0?'positive':'negative'):''}">${esc(c.coverage==='historical_decision_log'&&!o?'Not measured':returnText(ret))}<small>Paper · ${state.horizon}s</small></span></button>`;}).join(''):empty(state.marketTheme?'No saved observations match this theme.':'The opportunity ledger starts prospectively.','New cycles will record eligible candidates before the model decides. Outcomes remain pending until their declared trading-session horizon matures. Historical chosen trades cannot reconstruct missed opportunities.');
      $('#plCases').querySelectorAll('[data-case-id]').forEach(b=>b.addEventListener('click',()=>{state.caseId=b.dataset.caseId;renderEvidence();}));
      renderCaseInspector(cases.find(c=>String(c.id)===String(state.caseId)));
    }
    function detailGrid(values) {
      const display=value=>Array.isArray(value)?value.slice(0,12).join(', '):value&&typeof value==='object'?Object.entries(value).slice(0,6).map(([k,v])=>`${k}: ${v}`).join('; '):String(value);
      return '<dl class="pl-data">'+Object.entries(values).filter(([,v])=>v!==undefined&&v!==null&&v!=='').map(([key,value])=>`<div><dt>${esc(key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase()))}</dt><dd>${esc(display(value))}</dd></div>`).join('')+'</dl>';
    }
    function ruleReference(c,id) {
      const landmark=list(state.data?.landmarks).some(n=>n.id===id&&versionsOf(n).includes(Number(c.prompt_version)));
      if(landmark)return `<button type="button" class="pl-case-link" data-rule-id="${esc(id)}">${esc(id)}</button>`;
      return `<span class="pl-reference-tag">${esc(id)}<small>Runtime or memory reference · outside frozen policy landmarks</small></span>`;
    }
    function renderCaseInspector(c) {
      const panel=$('#plCaseInspector');if(!c){panel.innerHTML='<span class="pg-eyebrow">CASE DETAILS</span><h3>A setup at a point in time.</h3><p class="pg-muted">Select an observation to see its action, coverage, recorded features, cited rules and paper outcomes.</p>';return;}
      const features=c.features||c.features_json||{},outcome=outcomeFor(c,state.horizon),rules=cited(c);
      panel.innerHTML=`<span class="pg-eyebrow">RECORDED OPPORTUNITY</span><h3>${esc(c.ticker)} · ${esc(c.action || 'Not assessed')}</h3><p class="pl-node-id">${esc(dateText(c.observed_at))} · input ${esc(c.input_id ?? c.source_input_id ?? 'not linked')}</p><p>${esc(c.reason || c.decision_reason || 'No model rationale recorded.')}</p><dl class="pl-data"><div><dt>Policy at decision</dt><dd>v${esc(c.prompt_version ?? 'unknown')}</dd></div><div><dt>Coverage</dt><dd>${esc(String(c.coverage||'Unknown').replaceAll('_',' '))}</dd></div><div><dt>Reference price</dt><dd>${esc(c.reference_price ?? c.price ?? 'Unknown')}</dd></div><div><dt>Price source</dt><dd>${esc(c.price_source || c.reference_source || 'Unknown')}</dd></div></dl><h4>Paper outcome · ${state.horizon} sessions</h4><p>${outcome?.status==='matured'?`${esc(returnText(outcome.net_return_pct))} net assumed return`:c.coverage==='historical_decision_log'?'Not measured — historical chosen decisions do not reconstruct prospective opportunity outcomes.':`${esc(outcome?.status || 'Pending')} — awaiting valid entry and horizon bars`}</p>${outcome?detailGrid({entry_session:outcome.entry_date,exit_session:outcome.exit_date,paper_entry_price:outcome.entry_price,paper_exit_price:outcome.exit_price,cost_per_side_bps:outcome.side_cost_bps,maximum_adverse_move:finite(outcome.mae_pct)?returnText(outcome.mae_pct):null,maximum_favorable_move:finite(outcome.mfe_pct)?returnText(outcome.mfe_pct):null}):''}<h4>Market themes</h4>${membershipHTML(c,true)}<h4>Decision-time features</h4>${Object.keys(features).length?detailGrid(features):'<p class="pl-footnote">Not recorded</p>'}<h4>Cited rules</h4>${rules.length?`<div class="pl-mini-list">${rules.map(id=>ruleReference(c,id)).join('')}</div>`:'<p class="pl-footnote">No guideline citation recorded.</p>'}<p class="pl-footnote">The model action is not an execution confirmation. Paper outcomes do not include portfolio sizing or actual fills.</p>`;
      panel.querySelectorAll('[data-rule-id]').forEach(b=>b.addEventListener('click',()=>{const node=list(state.data.landmarks).find(n=>n.id===b.dataset.ruleId&&versionsOf(n).includes(Number(c.prompt_version)));if(!node){openExplorer(b.dataset.ruleId,c.prompt_version);return;}const i=versions().findIndex(v=>Number(v.version)===Number(c.prompt_version));if(i>=0)state.index=i;state.selected=revisionKey(node);setLens('evolution');renderTimeline();renderMap();renderInspector();}));
    }
    function renderReplays() {
      const runs=list(state.data?.replays?.runs);
      $('#plReplays').innerHTML=runs.length?runs.map(run=>{const m=run.metrics||run.summary||{},pairs=list(run.pairs||run.comparisons||run.rows||run.cases),inc=run.incumbent_version??run.from_version,cand=run.candidate_version??run.to_version;return `<article class="pl-replay"><div class="pl-replay-head"><h4>Incumbent v${esc(inc??'?')} → candidate v${esc(cand??'?')}</h4><span class="pl-badge">${esc(run.status||'Recorded replay')}</span></div><p>${esc(dateText(run.created_at))} · ${esc(run.model||'Model recorded per pair')} · ${esc(run.reasoning_effort||'Reasoning recorded in manifest')}</p><p class="pl-node-id">Frozen cohort ${esc(run.cohort_id||run.cohort_hash||run.id||'Unknown')} · ${esc(run.source_kind||'Paired replay')}</p><div class="pl-replay-metrics"><span>Comparable cases<strong>${esc(number(m.comparable??m.comparable_cases??m.paired_cases??run.case_count??pairs.length))}</strong></span><span>Changed actions<strong>${esc(number(run.action_flips??m.changed_actions??m.action_changes))}</strong></span><span>Errors / unscored<strong>${esc(number(run.errors??m.errors??run.error_count))}</strong></span><span>Estimated replay API cost<strong>${finite(run.cost_usd)?'$'+Number(run.cost_usd).toFixed(4):'Not recorded'}</strong></span></div>${m.incumbent||m.candidate?`<p>${esc(m.note||'Paired paper evaluation')}</p><div class="pl-replay-table"><table><thead><tr><th>Paper metric</th><th>Incumbent</th><th>Candidate</th></tr></thead><tbody>${[['Precision','precision'],['Winner recall','recall'],['Loss false-positive rate','fpr'],['Participation','participation']].map(([label,key])=>`<tr><td>${esc(label)}</td><td>${esc(rate(m.incumbent?.[key]))}</td><td>${esc(rate(m.candidate?.[key]))}</td></tr>`).join('')}<tr><td>Net expectancy per BUY</td><td>${esc(finite(m.incumbent?.mean_net_return_pct)?returnText(m.incumbent.mean_net_return_pct):'—')}</td><td>${esc(finite(m.candidate?.mean_net_return_pct)?returnText(m.candidate.mean_net_return_pct):'—')}</td></tr><tr><td>Paper net P&amp;L · $1,000 per BUY</td><td>${esc(finite(m.incumbent?.paper_pnl_per_1000_tickets)?'$'+Number(m.incumbent.paper_pnl_per_1000_tickets).toFixed(2):'—')}</td><td>${esc(finite(m.candidate?.paper_pnl_per_1000_tickets)?'$'+Number(m.candidate.paper_pnl_per_1000_tickets).toFixed(2):'—')}</td></tr></tbody></table></div>`:''}${pairs.length?`<div class="pl-replay-table"><table><thead><tr><th>Saved case</th><th>Incumbent</th><th>Candidate</th><th>Shared paper outcome</th></tr></thead><tbody>${pairs.slice(0,100).map(p=>`<tr class="${p.action_changed?'pl-action-flipped':''}"><td>${esc(p.ticker||p.case_id||p.source_input_id||'Saved input')}</td><td>${esc(p.incumbent_action||p.incumbent?.action||'Unscored')}</td><td>${esc(p.candidate_action||p.candidate?.action||'Unscored')}</td><td>${esc(finite(p.net_return_pct??outcomeFor(p,m.horizon||3)?.net_return_pct)?returnText(p.net_return_pct??outcomeFor(p,m.horizon||3)?.net_return_pct):'Pending / not linked')}</td></tr>`).join('')}</tbody></table></div>`:''}<details><summary>Evaluation manifest and metrics</summary><div class="pl-text-block">${esc(JSON.stringify({metrics:m,notes:run.notes||run.note,incumbent_hash:run.incumbent_policy_hash||run.incumbent_hash,candidate_hash:run.candidate_policy_hash||run.candidate_hash},null,2))}</div></details><p>Replayed actions are hypothetical. A policy comparison does not activate a candidate or establish future performance.</p></article>`;}).join(''):empty('No paired policy comparison has been recorded.','Choose saved inputs and a candidate above, then preview the exact comparison. Both policies use the same cases, model and reasoning settings. Paid model calls start only when you click Run.');
    }

    function configureReplayForm() {
      const history=versions(),cases=casesFor(state.data),sourceVersions=[...new Set(cases.filter(c=>finite(c.prompt_version)&&finite(c.input_id??c.source_input_id)).map(c=>Number(c.prompt_version)))].sort((a,b)=>b-a);
      const incumbent=$('#plReplayIncumbent'),candidate=$('#plReplayCandidate');
      const oldIncumbent=incumbent.value,oldCandidate=candidate.value;
      incumbent.innerHTML=sourceVersions.map(v=>`<option value="${v}">v${v} · saved inputs</option>`).join('')||'<option value="">No saved inputs</option>';
      if(oldIncumbent!==''&&sourceVersions.includes(Number(oldIncumbent)))incumbent.value=oldIncumbent;
      candidate.innerHTML=history.slice().reverse().map(v=>`<option value="${Number(v.version)}">v${Number(v.version)}${v.is_active?' · active':''}</option>`).join('')||'<option value="">No stored versions</option>';
      const fallback=history.slice().reverse().find(v=>Number(v.version)!==Number(incumbent.value));
      candidate.value=oldCandidate!==''&&history.some(v=>Number(v.version)===Number(oldCandidate))?oldCandidate:String(fallback?.version??history[history.length-1]?.version??'');
      invalidateReplay();
      if(state.jobId)replayControls(true);
    }
    function replayBody() {
      return {source_input_ids:replayInputIds(state.data,Number($('#plReplayIncumbent').value),Number($('#plReplayCount').value)),candidate_version:Number($('#plReplayCandidate').value),assembly_mode:$('#plReplayMode').value,outcome_spec:{horizon:Number($('#plReplayHorizon').value)}};
    }
    function invalidateReplay() {
      state.previewSeq++;state.replayPreview=null;
      const body=replayBody(),available=state.data?.agent==='DeciderAgent'&&body.source_input_ids.length&&finite(body.candidate_version),busy=state.replayBusy||Boolean(state.jobId);
      $('#plReplayPreview').disabled=!available||busy;
      $('#plReplayRun').disabled=true;$('#plReplayRun').textContent='Preview before running';
      $('#plReplayCohortNote').textContent=available?`${body.source_input_ids.length} exact saved input${body.source_input_ids.length===1?'':'s'} selected from incumbent v${$('#plReplayIncumbent').value}. Both policies will use the same original market context, model and reasoning effort. Preview validates compatibility without model calls.`:'Paired trade-policy replay needs saved Decider inputs and a stored candidate version.';
      if(!busy)$('#plReplayPlan').innerHTML='';
    }
    function replayControls(busy) {
      $('#plReplayForm').querySelectorAll('select').forEach(s=>{s.disabled=busy;});
      $('#plReplayPreview').disabled=busy||!replayBody().source_input_ids.length||state.data?.agent!=='DeciderAgent';
    }
    async function replayRequest(url, body) {
      const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);return data;
    }
    async function previewReplay(e) {
      e.preventDefault();if(state.replayBusy||state.jobId)return;
      state.replayBusy=true;replayControls(true);$('#plReplayRun').disabled=true;
      const body=replayBody(),seq=++state.previewSeq;state.replayPreview=null;
      $('#plReplayPlan').textContent='Validating saved inputs, policy changes and model settings…';
      try {
        const plan=await replayRequest('/api/policy-graph/learning/replay-preview',body);
        if(seq!==state.previewSeq)return;
        if(plan.compatible!==true) {$('#plReplayPlan').innerHTML=`<p class="pl-plan-error">This comparison is not compatible.</p>${list(plan.errors).map(error=>`<p>${esc(typeof error==='string'?error:JSON.stringify(error))}</p>`).join('')}<p>${esc(plan.note||'Choose other saved inputs or policy scope.')}</p>`;return;}
        state.replayPreview={body:JSON.parse(JSON.stringify(body)),plan};
        const calls=Number(plan.model_calls)||body.source_input_ids.length*2;
        $('#plReplayRun').textContent=`Run ${calls} model calls`;$('#plReplayRun').disabled=false;
        $('#plReplayPlan').innerHTML=`<strong>Ready to compare incumbent v${esc(plan.incumbent_version??$('#plReplayIncumbent').value)} with candidate v${esc(plan.candidate_version??body.candidate_version)}.</strong>${detailGrid({saved_inputs:body.source_input_ids.length,model_calls:calls,cases:plan.case_count,prospective_cases:plan.prospective_case_count,model:plan.model,reasoning_effort:plan.reasoning_effort||'Default',policy_scope:body.assembly_mode==='full_policy'?'Full stored policy':'Captured subgraph edits',paper_horizon:body.outcome_spec.horizon+' sessions'})}<p>${esc(plan.note||'Same frozen cases and context on both sides.')} · ${esc(number(plan.images_per_side||0))} recorded images per policy side</p><p><strong>Running sends both saved decision prompts and any recorded frozen screenshots to the OpenAI API at api.openai.com and incurs usage charges. These prompts include recorded holdings, cash and portfolio context, plus any identifiers captured in the original cycle.</strong> Cost is recorded from actual usage after completion. No orders are placed and neither policy is activated.</p><p class="pl-node-id">Cohort ${esc(plan.cohort_hash||'not available')}</p>`;
      } catch(error) {if(seq===state.previewSeq)$('#plReplayPlan').innerHTML=`<p class="pl-plan-error">Could not prepare comparison: ${esc(error.message)}</p>`;}
      finally {state.replayBusy=false;replayControls(false);}
    }
    async function runReplay() {
      if(!state.replayPreview||state.replayBusy||state.jobId)return;
      state.replayBusy=true;replayControls(true);$('#plReplayRun').disabled=true;
      const preview=state.replayPreview;
      try {
        const job=await replayRequest('/api/policy-graph/learning/replay',{...preview.body,expected_cohort_hash:preview.plan.cohort_hash});
        state.jobId=job.job_id;state.pollCount=0;state.pollErrors=0;
        $('#plReplayPlan').innerHTML='<strong>Paired replay queued.</strong><p>The saved comparison runs independently of trading. Results and actual usage will appear here when it completes.</p>';
        $('#plReplayRefresh').hidden=false;
        pollReplay();
      } catch(error) {$('#plReplayPlan').innerHTML=`<p class="pl-plan-error">Comparison was not started: ${esc(error.message)}</p>`;state.replayPreview=null;}
      finally {state.replayBusy=false;replayControls(Boolean(state.jobId));}
    }
    async function pollReplay() {
      if(!state.jobId||state.polling||!state.active||document.hidden)return;
      if(state.pollTimer)win.clearTimeout(state.pollTimer);state.pollTimer=null;state.polling=true;
      try {
        const response=await fetch(`/api/policy-graph/learning/replay-jobs/${encodeURIComponent(state.jobId)}`,{headers:{Accept:'application/json'},cache:'no-store'});
        const job=await response.json();if(!response.ok)throw new Error(job.error||`Status unavailable (${response.status})`);
        state.pollCount++;state.pollErrors=0;
        if(job.status==='complete') {
          if(job.result){state.data.replays=state.data.replays||{};state.data.replays.runs=[job.result,...list(state.data.replays.runs).filter(r=>String(r.id)!==String(job.result.id))];renderReplays();}
          $('#plReplayPlan').innerHTML='<strong>Paired comparison complete.</strong><p>Inspect the action changes and paper metrics below. Pending outcomes and insufficient sample sizes remain unscored.</p>';
          state.jobId=null;state.replayPreview=null;$('#plReplayRefresh').hidden=true;replayControls(false);
        } else if(job.status==='error') {
          $('#plReplayPlan').innerHTML=`<p class="pl-plan-error">Comparison ended: ${esc(job.error||'Replay failed. Inspect the recorded result before retrying.')}</p>`;
          state.jobId=null;state.replayPreview=null;$('#plReplayRefresh').hidden=true;replayControls(false);
        } else $('#plReplayPlan').innerHTML=`<strong>Paired replay ${esc(job.status||'running')}.</strong><p>Both policies use the same frozen inputs. You can leave this page; the comparison continues without placing trades.</p>`;
      } catch(error) {
        state.pollErrors++;$('#plReplayPlan').innerHTML=`<p class="pl-plan-error">Status check failed: ${esc(error.message)}</p><p>The comparison may still be running. Check its status before starting another.</p>`;
      } finally {
        state.polling=false;
        if(state.jobId&&state.active&&!document.hidden&&state.pollCount<180&&state.pollErrors<3)state.pollTimer=win.setTimeout(pollReplay,2000);
      }
    }

    document.querySelectorAll('[data-policy-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.policyView)));
    document.querySelectorAll('[data-learning-lens]').forEach(b=>b.addEventListener('click',()=>setLens(b.dataset.learningLens)));
    for(const selector of ['.pl-subnav','.pl-lenses']) $(selector)?.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...e.currentTarget.querySelectorAll('[role="tab"]')],i=buttons.indexOf(document.activeElement);if(i<0)return;e.preventDefault();const target=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[target].click();buttons[target].focus();});
    $('#plTimeline').addEventListener('input',e=>{stopPlayback();setIndex(e.target.value);});
    $('#plPrevious').addEventListener('click',()=>{stopPlayback();setIndex(state.index-1);});
    $('#plNext').addEventListener('click',()=>{stopPlayback();setIndex(state.index+1);});
    $('#plPlay').addEventListener('click',startPlayback);
    $('#plSearch').addEventListener('input',e=>{state.search=e.target.value.trim();renderMap();});
    $('#plTheme').addEventListener('change',e=>{state.theme=e.target.value;renderMap();});
    $('#plLayout').addEventListener('change',e=>{state.layout=e.target.value==='similarity'?'similarity':'themes';renderMap();});
    function setMarketTheme(value) {
      state.marketTheme=themeCatalog(state.data).some(t=>t.id===value)?value:'';
      for(const id of ['#plMarketTheme','#plEvidenceTheme'])$(id).value=state.marketTheme;
      const selected=list(state.data?.landmarks).find(n=>revisionKey(n)===state.selected);
      if(selected&&!inMarketTheme(selected,state.marketTheme))state.selected=null;
      renderMap();renderInspector();renderEvidence();
    }
    for(const id of ['#plMarketTheme','#plEvidenceTheme'])$(id).addEventListener('change',e=>setMarketTheme(e.target.value));
    $('#plShowRetired').addEventListener('change',e=>{state.showRetired=e.target.checked;renderMap();});
    $('#plHorizon').addEventListener('change',e=>{state.horizon=Number(e.target.value);renderEvidence();});
    $('#plRefresh')?.addEventListener('click',()=>load(true));
    $('#plReplayForm').addEventListener('submit',previewReplay);
    $('#plReplayForm').querySelectorAll('select').forEach(select=>select.addEventListener('change',invalidateReplay));
    $('#plReplayRun').addEventListener('click',runReplay);
    $('#plReplayRefresh').addEventListener('click',()=>{state.pollCount=0;state.pollErrors=0;pollReplay();});
    win.addEventListener('hashchange',()=>{const p=new URLSearchParams(location.hash.slice(1));state.agent=p.get('agent')||state.agent;const v=p.get('v');if(v!==null&&finite(v))state.version=Number(v);setView(p.get('view'),false);});
    win.addEventListener('policygraph:loaded',e=>{state.agent=e.detail?.agent||agentFromPage();state.version=e.detail?.version??versionFromPage();if(state.active)load();});
    if(win.ResizeObserver){const observer=new ResizeObserver(()=>{if(state.active)win.requestAnimationFrame(renderMap);});observer.observe($('#plMap'));}
    document.addEventListener('visibilitychange',()=>{if(document.hidden){stopPlayback();if(state.pollTimer)win.clearTimeout(state.pollTimer);state.pollTimer=null;}else if(state.jobId)pollReplay();});
    setView(new URLSearchParams(location.hash.slice(1)).get('view'),false);
  }
  return {snapshot,outcomeFor,lineDiff,extent,rate,returnText,casesFor,replayInputIds,dateText,marketThemes,inMarketTheme,themeCatalog,themePosition,themeLayout,themeEvidenceLabel,caseThemeEvidenceLabel,sourceObservations,themeCounts,sourceExcerpt,mount};
}));
