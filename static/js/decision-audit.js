(() => {
  const panel = document.getElementById('pgDecisionAudit');
  if (!panel) return;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const pacific = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
  const labelTime = cycle => cycle.at ? pacific.format(new Date(cycle.at)) : 'Unknown time';
  const labelGate = id => id.split('.').at(-1).replaceAll('_', ' ');
  const hash = () => new URLSearchParams(location.hash.slice(1));
  const count = (rows, key) => rows.reduce((total, row) => total + (row[key] || 0), 0);
  const primaryGates = cycle => cycle.considered.filter(row => row.passed && row.cited.length).map(row => row.cited[0]);
  const tile = (label, value) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
  let cycles = [];
  let selected = Number(hash().get('cycle'));
  let gate = '';
  let loaded = false;
  let request = 0;

  function citations(cycle, ids) {
    if (!ids.length) return '<p class="pg-muted">No guideline citation recorded.</p>';
    return `<div class="da-citations">${ids.map(id => {
      const status = !cycle.served_logged ? 'serving log unavailable' : cycle.served_citations.includes(id) ? 'served in this cycle' : 'serving unverified';
      const text = `${labelGate(id)} · ${status}`;
      if (cycle.version == null || !id.startsWith('DA.')) return `<span title="${esc(id)}">${esc(text)}</span>`;
      const href = `/policy-graph#${new URLSearchParams({agent:'DeciderAgent', v:cycle.version, node:id})}`;
      return `<a href="${esc(href)}" title="${esc(id)}">${esc(text)}</a>`;
    }).join('')}</div>`;
  }

  function detail(cycle) {
    if (!cycle) { $('daDetail').textContent = 'No cycles match the selected filters.'; return; }
    const meta = [cycle.version == null ? 'Policy version unavailable' : `Policy v${cycle.version}`,
      [cycle.model, cycle.reasoning].filter(Boolean).join(' · '), cycle.regime || 'Regime unavailable',
      cycle.risk_score == null ? null : `Event pressure ${cycle.risk_score}/100`,
      cycle.macro_window == null ? null : cycle.macro_window ? 'Macro window' : 'Outside macro window',
      cycle.session_recovery_supplied == null ? null : cycle.session_recovery_supplied ? 'Session recovery supplied' : 'Session recovery absent'];
    const rows = (items, action) => items.map(item => `<div class="da-row"><strong>${esc(item.ticker || 'Unknown ticker')}</strong>
      <span class="da-action">${esc(action(item))}</span><p>${esc(item.reason || 'Reason unavailable.')}</p>
      ${item.signals ? `<p class="pg-muted">${esc(item.signals)}</p>` : ''}
      ${item.execution_error ? `<p class="pg-muted">${esc(item.execution_error)}</p>` : ''}${citations(cycle, item.cited)}</div>`).join('');
    const group = (title, content, open = false) => `<details class="da-group"${open ? ' open' : ''}><summary>${esc(title)}</summary>${content}</details>`;
    const assessed = new Set([...cycle.considered, ...cycle.decisions].map(row => row.ticker));
    const cash = cycle.cash_reason || (cycle.model_buys === 0 ? 'The model reply contains no BUY and no cash reason was recorded.' : '');
    const screened = cycle.screened.map(item => {
      const distance = item.ma_distance_pct;
      const geometry = distance == null ? 'Unavailable' : distance <= 0 ? 'MA at or above entry' : `${distance.toFixed(2)}% below entry`;
      return `<tr><td>${esc(item.ticker)}${item.held ? ' <span class="pg-muted">Held</span>' : ''}</td><td>${assessed.has(item.ticker) ? 'Recorded' : 'Unavailable'}</td><td>${esc(geometry)}</td></tr>`;
    }).join('');
    $('daDetail').innerHTML = `<h3>${esc(labelTime(cycle))} PT</h3>
      <p class="pg-muted">${esc(meta.filter(Boolean).join(' · '))}</p>
      ${cycle.run_id ? `<p class="pg-muted">Run <code>${esc(cycle.run_id)}</code></p>` : ''}
      ${cycle.router ? `<p class="pg-muted"><a class="pg-link" href="#view=router&amp;comparison=${encodeURIComponent(cycle.router.id)}">Decisions shadow comparison</a> · ${esc(cycle.router.status)}</p>` : ''}
      <div class="da-pipeline">${tile('Model BUYs', cycle.model_buys ?? 'Unavailable')}${tile('Recorded BUYs', cycle.stored_buys)}${tile('Confirmed BUY fills', cycle.filled_buys)}</div>
      ${cash ? `<div class="da-cash"><strong>Cash rationale</strong><p>${esc(cash)}</p>${cycle.cash_cited.length ? citations(cycle, cycle.cash_cited) : ''}</div>` : ''}
      ${cycle.missing_decisions.length ? group('Model proposals without a matching stored decision', rows(cycle.missing_decisions, row => row.action.toUpperCase()), true) : ''}
      ${cycle.decisions.length ? group('Recorded decisions', rows(cycle.decisions, row => [row.action.toUpperCase(), row.execution, row.status !== row.execution && row.status].filter(Boolean).join(' · ')), true) : ''}
      ${cycle.considered.length ? group(`Model assessments (${cycle.considered.length})`, rows(cycle.considered, row => row.verdict.toUpperCase()), cycle.model_buys === 0) : '<p class="pg-muted">Candidate assessments unavailable for this cycle.</p>'}
      ${screened ? group(`Supplied screener (${cycle.screened.length})`, `<p class="pg-muted">The MA column compares the saved reference price with its 20-day average. Other supported levels can supply a stop.</p><table><thead><tr><th>Ticker</th><th>Assessment</th><th>20-day MA distance</th></tr></thead><tbody>${screened}</tbody></table>`) : ''}`;
  }

  function select(cycle) {
    selected = cycle?.id ?? null;
    const params = hash();
    if (selected != null) params.set('cycle', selected);
    else params.delete('cycle');
    history.replaceState(null, '', `#${params}`);
    $('daCycles').querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.cycle) === selected)));
    detail(cycle);
  }

  function render() {
    const regime = $('daRegime').value;
    const scope = cycles.filter(cycle => !regime || cycle.regime === regime);
    const counts = new Map();
    for (const cycle of scope) for (const id of primaryGates(cycle)) counts.set(id, (counts.get(id) || 0) + 1);
    if (!counts.has(gate)) gate = '';
    const visible = gate ? scope.filter(cycle => primaryGates(cycle).includes(gate)) : scope;
    const missing = visible.filter(cycle => cycle.model_buys === null).length;
    const noBuy = visible.filter(cycle => cycle.model_buys === 0).length;
    const passes = visible.flatMap(cycle => cycle.considered).filter(row => row.passed);
    $('daStatus').textContent = cycles.length ? `${visible.length} of ${cycles.length} saved cycles · Pacific time` : 'No decision cycles recorded.';
    $('daSummary').innerHTML = visible.length ? [tile('Cycles with no model BUY', `${noBuy}/${visible.length - missing || '–'}`),
      tile('Model reply unavailable', missing), tile('Recorded BUYs', count(visible,'stored_buys')),
      tile('Confirmed BUY fills', count(visible,'filled_buys')), tile('Pass / watch assessments with citations', `${passes.filter(row => row.cited.length).length}/${passes.length || '–'}`)].join('') : '';
    const top = [...counts].sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0,5);
    $('daGates').innerHTML = top.length ? `<h3>Most cited pass or watch gates</h3><p class="pg-muted">First citation per assessment. Select a gate to filter cycles.</p>${top.map(([id, n]) => `<button type="button" data-gate="${esc(id)}" aria-pressed="${id === gate}"><span>${esc(labelGate(id))}</span><meter aria-label="${esc(labelGate(id))} count" min="0" max="${top[0][1]}" value="${n}"></meter><strong>${n}</strong></button>`).join('')}` : '';
    const max = Math.max(1, ...visible.map(cycle => Math.max(cycle.model_buys || 0, cycle.filled_buys)));
    $('daCycles').innerHTML = visible.map(cycle => `<button type="button" class="da-cycle" data-cycle="${cycle.id}" aria-label="${esc(labelTime(cycle))} PT, ${cycle.model_buys ?? 'unknown'} model buys, ${cycle.filled_buys} confirmed buy fills"><span>${esc(labelTime(cycle))}<small>${esc(cycle.regime || 'Regime unavailable')}</small></span><span class="da-bars" aria-hidden="true"><i style="--width:${(cycle.model_buys || 0) / max * 100}%"></i><i style="--width:${cycle.filled_buys / max * 100}%"></i></span><span aria-hidden="true">${cycle.model_buys ?? '–'} / ${cycle.filled_buys}</span></button>`).join('');
    select(visible.find(cycle => cycle.id === selected) || visible[0]);
  }

  async function load() {
    const current = ++request;
    $('daStatus').textContent = 'Loading saved decision cycles…';
    try {
      const res = await fetch(`/api/policy-graph/decision-audit?limit=${encodeURIComponent($('daLimit').value)}`, {cache: 'no-store'});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (current !== request || panel.hidden) return;
      cycles = data.cycles;
      const selectRegime = $('daRegime');
      const previous = selectRegime.value;
      const regimes = [...new Set(cycles.map(cycle => cycle.regime).filter(Boolean))].sort();
      selectRegime.replaceChildren(new Option('All regimes',''), ...regimes.map(value => new Option(value,value)));
      selectRegime.value = regimes.includes(previous) ? previous : '';
      loaded = true;
      render();
    } catch (error) {
      if (current === request) $('daStatus').textContent = `Saved decision cycles unavailable (${error.message}).`;
    }
  }

  $('daCycles').addEventListener('click', event => {
    const id = Number(event.target.closest('button[data-cycle]')?.dataset.cycle);
    const cycle = cycles.find(row => row.id === id);
    if (cycle) select(cycle);
  });
  $('daGates').addEventListener('click', event => {
    const id = event.target.closest('button[data-gate]')?.dataset.gate;
    if (!id) return;
    gate = gate === id ? '' : id;
    render();
    [...$('daGates').querySelectorAll('button')].find(button => button.dataset.gate === id)?.focus();
  });
  $('daRegime').addEventListener('change', render);
  $('daLimit').addEventListener('change', load);
  $('daRefresh').addEventListener('click', load);
  window.addEventListener('policygraph:viewchange', event => {
    if (event.detail?.view !== 'audit') return;
    selected = Number(hash().get('cycle')) || selected;
    if (!loaded) load(); else render();
  });
  if (!panel.hidden) load();
})();
