(() => {
  const panel = document.getElementById('learningPerformance');
  if (!panel) return;
  const region = panel.querySelector('.learn-scroll');
  const status = panel.querySelector('[data-status]');
  const filter = key => panel.querySelector(`[data-filter="${key}"]`).value;
  const pct = value => `${(100 * value).toFixed(0)}%`;
  let agent = 'decider', payload, request = 0;
  function small(cell, value) {
    const line = document.createElement('small');
    line.textContent = value;
    cell.append(line);
  }
  function measure(cell, value, interval, hits, denominator, loss) {
    if (!Number.isFinite(value)) {
      cell.textContent = '—';
      small(cell, denominator ? 'Unavailable' : 'N = 0');
      return;
    }
    cell.textContent = `${pct(value)} · ${hits}/${denominator}`;
    const track = document.createElement('span'), fill = document.createElement('span');
    track.className = loss ? 'learn-rate loss' : 'learn-rate';
    fill.style.width = `${100 * value}%`;
    track.append(fill); cell.append(track);
    if (interval) small(cell, `95% CI ${pct(interval[0])}–${pct(interval[1])}`);
  }
  function render() {
    region.hidden = true;
    panel.querySelector('[data-summary-method]').hidden = agent !== 'summarizer';
    if (!payload) return;
    if (payload.status !== 'ok') {status.textContent = payload.message; return;}
    const summarizer = agent === 'summarizer', byWeek = filter('group') === 'week';
    const data = payload[agent], label = byWeek ? 'Week starting' : 'Prompt';
    if (data.status === 'cohort_limit') { status.textContent = 'Too many summaries for this lookback. Select 30 days.'; return; }
    const records = data[filter('group')];
    const stamp = new Date(payload.as_of).toLocaleDateString(undefined, {month:'short', day:'numeric'});
    status.textContent = summarizer
      ? `${data.summaries} timestamped summaries through ${stamp} · ${data.signals} matched ticker episodes · ${data.unattributed} summaries without a captured prompt version.`
      : `${payload.candidate_rows} eligible observations through ${stamp} · ${payload.episodes} distinct ticker episodes. Rates use matured BUY and PASS episodes.`;
    if (!records.length) {status.textContent += ' No observations in this window.'; return;}
    const head = panel.querySelector('thead'), body = panel.querySelector('tbody');
    head.replaceChildren(); body.replaceChildren();
    const tr = head.insertRow();
    const labels = [label, ...(summarizer ? ['Source summaries', 'Matched signals'] : ['Decisions']),
      'Gain recall', 'Loss false-positive rate', summarizer ? 'Actionable precision' : 'BUY precision', 'Mean paper return', 'Outcome coverage'];
    for (const title of labels) {
      const th = document.createElement('th'); th.scope = 'col'; th.textContent = title; tr.append(th);
    }
    for (const r of records) {
      const row = body.insertRow(), title = document.createElement('th');
      title.scope = 'row'; title.textContent = r.label; row.append(title);
      small(title, r.first === r.last ? r.first : `${r.first} – ${r.last}`);
      if (summarizer) {
        const cell = row.insertCell(); cell.textContent = `${r.complete}/${r.summaries} complete`;
        small(cell, `${r.with_cards} with ticker cards`);
      }
      const act = row.insertCell();
      act.textContent = summarizer ? `${r.buys} actionable · ${r.passes} watch/avoid` : `${r.buys} BUY · ${r.passes} PASS`;
      if (!summarizer) small(act, `${r.unassessed} unassessed`);
      measure(row.insertCell(), r.recall, r.recall_interval, r.tp, r.tp + r.fn, false);
      measure(row.insertCell(), r.fpr, r.fpr_interval, r.fp, r.fp + r.tn, true);
      measure(row.insertCell(), r.precision, r.precision_interval, r.tp, r.tp + r.fp, false);
      const mean = row.insertCell();
      mean.textContent = Number.isFinite(r.net_expectancy_pct) ? `${r.net_expectancy_pct >= 0 ? '+' : ''}${r.net_expectancy_pct.toFixed(2)}%` : '—';
      small(mean, `N = ${r.matured_buys} ${summarizer ? 'actionable' : 'BUY'}`);
      const coverage = row.insertCell(); coverage.textContent = `${r.matured}/${r.assessed} matured`;
      small(coverage, `${r.pending} pending · ${r.overdue} overdue · ${r.missing} missing`);
    }
    region.hidden = false;
  }
  async function load() {
    const id = ++request;
    payload = undefined; region.hidden = true; status.textContent = 'Loading saved observations…';
    try {
      const data = await fetchJSON(`/api/feedback/learning?days=${filter('days')}&horizon=${filter('horizon')}`);
      if (id === request) {payload = data; render();}
    } catch {
      if (id === request) status.textContent = 'Saved learning data could not be loaded.';
    }
  }
  panel.querySelectorAll('[data-agent]').forEach(button => button.addEventListener('click', () => {
    agent = button.dataset.agent;
    panel.querySelectorAll('[data-agent]').forEach(b => b.setAttribute('aria-pressed', String(agent === b.dataset.agent)));
    render();
  }));
  panel.querySelectorAll('[data-filter]').forEach(select => select.addEventListener('change', select.dataset.filter === 'group' ? render : load));
  load();
})();
