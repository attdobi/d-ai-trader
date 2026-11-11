/* Render matched prompt estimates and recorded routing outcomes. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.DAIRouterEconomics=api;
}(typeof window!=='undefined'?window:this,function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=v=>v!==null&&v!==undefined&&v!==''&&typeof v!=='boolean'&&Number.isFinite(Number(v));
  const money=v=>finite(v)?`${Number(v)<0?'−':''}$${Math.abs(Number(v)).toFixed(5)}`:'Unknown';
  const tokens=v=>finite(v)?Number(v).toLocaleString('en-US'):'Unknown';
  function tiles(e, routing = 'shadow') {
    e = e || {};
    const applied = routing === 'applied';
    const activeCapture = e.capture_basis === 'frozen_ltm_baseline_v1';
    const fee = money(e.router_cost_usd ?? e.shadow_incremental_cost_usd);
    const realizedNotes = {
      applied: 'Measuring savings requires a matched baseline request with billed usage.',
      fallback: `The full eligible prompt was served. Recorded router fee ${fee}.`,
      retained: `The full eligible prompt was retained. Recorded router fee ${fee}.`,
      shadow: `The router recorded a shadow comparison. Recorded router fee ${fee}.`,
      replay: `The router scored saved input. Recorded router fee ${fee}.`,
      observer: `The router scored the saved decision afterward. Recorded router fee ${fee}.`,
      unknown: 'The recorded routing outcome is unavailable.',
    };
    const realized = {
      label: 'Realized routing savings',
      value: applied || routing === 'unknown' ? 'Unmeasured' :
        e.status === 'estimated' ? money(e.realized_input_savings_usd) : '$0.00000',
      note: realizedNotes[routing] || realizedNotes.unknown,
    };
    if (e.status !== 'estimated') {
      return [{label: 'Matched token estimates', value: 'Not captured',
        note: 'Estimating cost requires token counts from matched prompt variants.'}, realized];
    }

    const counts = e.token_estimates || {};
    const imageCount = finite(e.image_count) && Number.isInteger(Number(e.image_count)) &&
      Number(e.image_count) >= 0 ? Number(e.image_count) : null;
    const hasImages = imageCount > 0 || e.token_scope === 'text_only';
    const scope = hasImages ? 'text input' : 'input';
    const reduction = hasImages ? e.text_input_reduction_pct : e.potential_input_reduction_pct;
    const reductionNote = finite(reduction)
      ? `${Number(reduction).toFixed(2)}% ${activeCapture ? 'estimated' : 'potential'} ${hasImages ? 'text ' : ''}reduction`
      : `${hasImages ? 'Text reduction' : 'Reduction'} unknown`;
    const out = [
      {label: `Baseline ${scope} · estimate`, value: tokens(activeCapture ? counts.incumbent_full : counts.actual_served),
        note: `${e.decider_model || 'Decider'} · ${hasImages ? 'system and user text' : 'system and user prompt'}`},
      {label: `${activeCapture ? 'Served' : 'Proposed'} ${scope} · estimate`,
        value: tokens(activeCapture ? counts.actual_served : counts.decisions_selected),
        note: `${reductionNote} · matched to this cycle’s baseline`},
      {label: `Estimated net ${hasImages ? 'text ' : ''}input savings`,
        value: money(e.net_input_savings_usd_uncached_estimate),
        note: `Uncached input estimate minus the complete router fee${hasImages ? ', including its images' : ''}. Caching, output and reasoning costs require separate measurement.`},
      realized,
    ];
    if (hasImages) {
      out.push({label: 'Screenshot inputs', value: imageCount === null ? 'Count unknown' : `${tokens(imageCount)} image${imageCount === 1 ? '' : 's'}`,
        note: e.images_preserved_across_variants === true
          ? 'Both prompt variants use identical screenshots. The estimate covers text input.'
          : 'The estimate covers text input. Image usage requires separate measurement.'});
    }
    return out;
  }
  function render(e, routing){return tiles(e, routing).map(t=>`<div class="pg-router-stat"><div class="k">${esc(t.label)}</div><div class="v">${esc(t.value)}</div><div class="s">${esc(t.note)}</div></div>`).join('');}
  function selectionFor(last){
    if(last?.selection)return last.selection;
    const ns=Array.isArray(last?.nodes)?last.nodes:[];
    return {pinned_ids:last?.pinned_ids||[],selected_ids:ns.filter(n=>n.decisions_choice==='include').map(n=>n.node_id),
      skipped_ids:ns.filter(n=>n.decisions_choice==='exclude').map(n=>n.node_id),actual_optional_ids:ns.filter(n=>n.served_in_prompt).map(n=>n.node_id)};
  }
  return {tiles,render,selectionFor};
}));
