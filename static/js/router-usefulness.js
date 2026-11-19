(() => {
  const dialog = document.getElementById('prReviewDialog');
  if (!dialog) return;
  const byId = id => document.getElementById(id);
  const api = '/api/policy-graph/router-usefulness';
  let record = null, config = '', offset = 0, requestId = 0, saving = false;
  const status = text => { byId('prReviewStatus').textContent = text; };

  function render(data) {
    config = data.config_hash;
    record = data.item;
    const s = data.summary;
    byId('prReviewCoverage').textContent =
      `${s.reviewed} reviewed · ${s.unjudged} unjudged · ${s.unavailable} missing evidence · ${s.cycles} scored live cycles (up to ${data.window_cycles})`;
    const recall = s.reviewed_recall === null ? 'Awaiting needed judgments' :
      `${(100 * s.reviewed_recall).toFixed(1)}% reviewed recall · ${s.proposed_misses} proposed misses among ${s.needed} needed`;
    byId('prReviewResults').textContent = `${recall} · ${s.active_omitted} actually omitted among ${s.active_needed} reviewed needed on active cycles.`;
    byId('prReviewItem').hidden = !record;
    if (!record) {
      status('No reviewable items in this queue.');
      return;
    }
    status(`${data.queue_size} items in this queue.${record.judgment ? ' Current judgment: ' + record.judgment + '.' : ''}`);
    byId('prReviewCycle').textContent = `Cycle #${record.comparison_id} · ${record.as_of} as logged · policy v${record.version}`;
    byId('prReviewPolicy').href = '/policy-graph#' + new URLSearchParams({agent:'DeciderAgent', v:record.version});
    byId('prReviewHeadlineBasis').textContent = record.headline_basis;
    const c = record.context;
    const terms = [['Held', c.holdings], ['Watchlist', c.watchlist], ['Quarantined', c.quarantined], ['In the news', c.news]];
    byId('prReviewContext').textContent = [c.regime, ...terms.filter(([, values]) => values?.length)
      .map(([name, values]) => name + ' ' + values.join(', '))].filter(Boolean).join(' · ');
    const headlines = record.headlines.length ? record.headlines : ['No matching source headlines recorded.'];
    byId('prReviewHeadlines').replaceChildren(...headlines.map(head => {
      const li = document.createElement('li'); li.textContent = head; return li;
    }));
    byId('prReviewBody').textContent = record.body;
    byId('prReviewBasis').textContent = record.node_id + ' · ' + record.basis;
    dialog.querySelector('[data-review-label="clear"]').hidden = !record.judgment;
  }

  async function load() {
    const id = ++requestId;
    record = null;
    byId('prReviewItem').hidden = true;
    status('Loading saved evidence…');
    try {
      const params = new URLSearchParams({queue: byId('prReviewQueue').value, offset});
      const response = await fetch(api + '?' + params, {cache: 'no-store'});
      if (!response.ok) throw new Error('Could not load saved reviews.');
      const data = await response.json();
      if (id === requestId) render(data);
    } catch (error) {
      if (id === requestId) {
        status(error.message);
        byId('prReviewCoverage').textContent = error.message;
      }
    }
  }

  dialog.addEventListener('click', async event => {
    const button = event.target.closest('[data-review-label]');
    if (!button || !record || saving) return;
    const {comparison_id, node_id, evidence_hash, revision} = record;
    saving = true;
    dialog.querySelectorAll('button,select').forEach(el => { el.disabled = true; });
    try {
      const response = await fetch(api, {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({config_hash:config, comparison_id, node_id, evidence_hash, revision, judgment:button.dataset.reviewLabel})});
      if (!response.ok) throw new Error(response.status === 409 ? 'Evidence changed. Reopen the review to refresh.' : 'Could not save the judgment.');
      await load();
    } catch (error) { status(error.message); }
    finally {
      saving = false;
      dialog.querySelectorAll('button,select').forEach(el => { el.disabled = false; });
    }
  });
  byId('prReviewOpen').addEventListener('click', () => { offset = 0; dialog.showModal(); load(); });
  byId('prReviewClose').addEventListener('click', () => dialog.close());
  byId('prReviewNext').addEventListener('click', () => { offset = (offset + 1) % 40001; load(); });
  byId('prReviewQueue').addEventListener('change', () => { offset = 0; load(); });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); load(); }
    }); observer.observe(byId('prReviewOpen'));
  }
})();
