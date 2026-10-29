/* Cost estimates are counterfactual; shadow routing never saves actual tokens. */
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
  function tiles(e){
    e=e||{};
    if(e.status!=='estimated')return [{label:'Token savings',value:'Not captured',note:'This saved comparison has no matched full-prompt token snapshot. Character differences are not dollar savings.'},
      {label:'Realized routing savings',value:'$0.00000',note:'Shadow mode preserves the actual trading prompt; the router adds its API fee.'}];
    const t=e.token_estimates||{};
    const imageCount=finite(e.image_count)&&Number.isInteger(Number(e.image_count))&&Number(e.image_count)>=0?Number(e.image_count):null;
    const hasImages=(imageCount!==null&&imageCount>0)||e.token_scope==='text_only';
    // Never use the text denominator for a multimodal percentage. Image token
    // profiles are unknown here; their input stays present on every variant.
    const reduction=hasImages?e.text_input_reduction_pct:e.potential_input_reduction_pct;
    const reductionNote=finite(reduction)?`${Number(reduction).toFixed(2)}% potential ${hasImages?'text ':''}reduction`:`${hasImages?'Text reduction':'Reduction'} unknown`;
    const out=[{label:`Actual ${hasImages?'text':'full'} input · estimate`,value:tokens(t.actual_served),note:`${e.decider_model||'Decider'} · system and user ${hasImages?'text; image tokens excluded':'context included'}`},
      {label:`Proposed ${hasImages?'text':'full'} input · estimate`,value:tokens(t.decisions_selected),note:`${reductionNote} · same cycle and rendering${hasImages?'; no total-input percentage claimed':''}`},
      {label:`Potential net ${hasImages?'text-':''}input saving`,value:money(e.net_input_savings_usd_uncached_estimate),note:hasImages?'Uncached text reduction minus complete router fee, including its images; excludes output/reasoning changes. Cache-adjusted saving unknown.':'Uncached input estimate minus router fee; excludes output/reasoning changes. Cache-adjusted saving unknown.'},
      {label:'Realized routing savings',value:money(e.realized_input_savings_usd),note:`Shadow adds ${money(e.shadow_incremental_cost_usd)}. Decision-quality impact is unmeasured.`}];
    if(hasImages)out.push({label:'Screenshot inputs',value:imageCount===null?'Count unknown':`${tokens(imageCount)} image${imageCount===1?'':'s'}`,
      note:(e.images_preserved_across_variants===true?'Identical screenshots remain in actual, all-candidate and proposed inputs.':'Screenshot preservation is not confirmed for this capture.')+' Image-only tokens and cost are unavailable here; no image savings are credited.'});
    return out;
  }
  function render(e){return tiles(e).map(t=>`<div class="pg-router-stat"><div class="k">${esc(t.label)}</div><div class="v">${esc(t.value)}</div><div class="s">${esc(t.note)}</div></div>`).join('');}
  function selectionFor(last){
    if(last?.selection)return last.selection;
    const ns=Array.isArray(last?.nodes)?last.nodes:[];
    return {pinned_ids:last?.pinned_ids||[],selected_ids:ns.filter(n=>n.decisions_choice==='include').map(n=>n.node_id),
      skipped_ids:ns.filter(n=>n.decisions_choice==='exclude').map(n=>n.node_id),actual_optional_ids:ns.filter(n=>n.served_in_prompt).map(n=>n.node_id)};
  }
  return {tiles,render,selectionFor};
}));
