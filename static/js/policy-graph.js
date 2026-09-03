/* Policy graph page — one policy version at a time, every guideline as a node.
 *
 * Talks only to the /api/policy-graph/* routes. RUSH ports are marked (★) and
 * come from /Users/adobi/RUSH/web/policy-graph.js; d3 7.9 is loaded by the
 * template before this deferred script. Exports exactly one global:
 * window.pgOpenNode(id).
 */
(() => {
  'use strict';

  const WIDTH = 900;
  const HEIGHT = 560;
  const API = '/api/policy-graph';
  const LS_AGENT = 'pg.agent';
  const LS_VERSION = 'pg.version';

  // Mirrors policy_graph.model.COLORS — polarity table + root + code ring.
  const COLORS = {
    root: '#42c9ff',
    structure: '#7f8ca6',
    gate: '#ff5f73',
    action: '#29d697',
    caution: '#fadb5f',
    principle: '#b28dff',
    evidence: '#4dd0e1',
    mixed: '#9aa7c7',
    code_ring: '#ff9f43',
    ref: '#7f8ca6'
  };

  const AGENTS = [
    { agent_type: 'DeciderAgent', label: 'Decider', prefix: 'DA' },
    { agent_type: 'SummarizerAgent', label: 'Summarizer', prefix: 'SA' },
    { agent_type: 'FeedbackAgent', label: 'Feedback', prefix: 'FA' }
  ];
  const AGENT_TYPES = new Set(AGENTS.map(a => a.agent_type));

  const ACTOR_LABEL = {
    seed: 'seed',
    weekly: 'weekly loop',
    human: 'human',
    claude_code: 'Claude Code',
    rl_loop: 'RL loop'
  };
  const POLARITY_LABEL = {
    gate: 'hard gate',
    action: 'action',
    caution: 'caution',
    principle: 'identity / principle',
    evidence: 'evidence',
    structure: 'structure',
    mixed: 'mixed'
  };
  const FIELD_LABEL = {
    system_prompt: 'system prompt',
    user_prompt_template: 'user prompt template',
    strategy_directives: 'strategy directives',
    soul: 'soul',
    memory: 'memory'
  };
  const EDGE_KIND_LABEL = {
    subtype_of: 'part of',
    includes: 'includes',
    related_to: 'related to',
    cites: 'cites',
    overlaps: 'overlaps',
    constrains: 'constrains',
    enforced_by: 'enforced by',
    exception_to: 'exception to',
    boundary_with: 'boundary with',
    confused_with: 'confused with',
    clarifies: 'clarifies',
    example_of: 'example of',
    negative_example_of: 'negative example of'
  };
  const LINK_DISTANCE = { subtype_of: 90, includes: 60, related_to: 140, cites: 110, overlaps: 160, constrains: 160, enforced_by: 160 };
  const LINK_STRENGTH = { subtype_of: 0.7, includes: 0.5, related_to: 0.15, cites: 0.1, overlaps: 0.15, constrains: 0.15, enforced_by: 0.15 };

  const state = {
    agent: null,
    version: null,
    current: null,
    versions: [],
    versionNotes: [],
    agents: [],
    payload: null,
    prevPayload: null,
    selected: null,
    layer: 'effective',
    filters: new Set(['all']),
    showRefs: false,
    highlightChanges: true,
    nodeCache: new Map(),
    diffAgainst: null,
    similarity: new Map(),
    pendingPulse: null,
    pendingNode: null,
    graphSeq: 0,
    hashWriting: false,
    rebuildReason: null,
    proposals: [],
    proposalsAgent: null,
    proposalPoll: null
  };

  // Live d3 selections for the current render (null before the first render).
  const view = { svg: null, viewport: null, zoom: null, nodes: null, links: null, simulation: null, neighborMap: new Map() };

  // ------------------------------------------------------------------ helpers
  function qs(selector) { return document.querySelector(selector); }

  // ★ esc
  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
  }

  // ★ truncate
  function truncate(text, max = 26) {
    const value = String(text || '');
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }

  function toast(message, type = 'info') {
    if (typeof showToast === 'function') showToast(message, type);
  }

  function setStatus(message, { error = false, loading = false } = {}) {
    const el = qs('#pgStatus');
    if (!el) return;
    el.classList.toggle('is-error', Boolean(error));
    if (loading) {
      el.innerHTML = `<span class="pe-loading"><span class="pe-spinner" aria-hidden="true"></span><span>${esc(message)}</span></span>`;
    } else {
      el.textContent = message || '';
    }
  }

  async function apiGet(url) {
    const res = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' });
    let body = null;
    try { body = await res.json(); } catch (_) { body = null; }
    if (!res.ok) {
      const err = new Error((body && body.error) || `${res.status} ${res.statusText}`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  async function fetchJSON(url, options = {}) {
    const headers = { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
    const res = await fetch(url, { ...options, headers, cache: 'no-store' });
    let body = null;
    try { body = await res.json(); } catch (_) { body = null; }
    if (!res.ok) {
      const err = new Error((body && body.error) || `${res.status} ${res.statusText}`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function fmtPT(iso) {
    if (!iso) return '—';
    const s = String(iso);
    const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(s);
    if (m) return `${m[1]} ${m[2]} PT`;
    return s;
  }
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtShortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return '';
    return `${MONTHS[Number(m[2]) - 1] || m[2]} ${Number(m[3])}`;
  }
  function fmtDateOnly(iso) {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(iso || ''));
    return m ? m[1] : String(iso || '');
  }
  function actorLabel(kind, createdBy) {
    return ACTOR_LABEL[kind] || createdBy || kind || 'unknown';
  }
  function pct(x, digits = 0) {
    if (x === null || x === undefined || Number.isNaN(Number(x))) return '—';
    return `${(Number(x) * 100).toFixed(digits)} %`;
  }
  function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many || `${one}s`}`;
  }
  function agentMeta(agentType) {
    return AGENTS.find(a => a.agent_type === agentType) || AGENTS[0];
  }
  function versionEntry(version) {
    return state.versions.find(v => Number(v.version) === Number(version)) || null;
  }
  function versionNumbers() {
    return state.versions.map(v => Number(v.version)).filter(Number.isFinite).sort((a, b) => a - b);
  }
  function lsGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function lsSet(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* storage blocked */ } }

  // ------------------------------------------------------------------ graph shape helpers (★)
  function edgeSource(edge) { return String(edge.source?.id ?? edge.source ?? edge.source_node_id ?? ''); }
  function edgeTarget(edge) { return String(edge.target?.id ?? edge.target ?? edge.target_node_id ?? edge.to ?? ''); }
  function edgeType(edge) { return String(edge.edge_type || edge.type || 'subtype_of').toLowerCase(); }

  function familyOf(id) {
    const parts = String(id || '').split('.');
    if (parts.length <= 2) return String(id || '');
    return `${parts[0]}.${parts[1]}`;
  }

  function rootId() { return state.payload?.root_id || `${agentMeta(state.agent).prefix}.root`; }

  function depthOf(node) {
    if (typeof node === 'object' && node && Number.isFinite(node.depth)) return node.depth;
    const id = typeof node === 'object' && node ? node.id : node;
    const value = String(id || '');
    if (value === rootId()) return 0;
    return Math.max(1, value.split('.').length - 1);
  }

  function childrenFor(id, nodes) {
    if (!id) return [];
    return nodes.filter(node => node.id !== id && (node.parent === id || String(node.id).startsWith(`${id}.`)));
  }
  function hasChildren(node, nodes) { return childrenFor(node.id, nodes).length > 0; }

  function isRef(node) {
    const t = String(node.node_type || '').toLowerCase();
    return t === 'ticker' || t === 'concept';
  }

  function nodeRadius(node, nodes) {
    if (node.id === rootId() || String(node.node_type).toLowerCase() === 'root') return 14;
    if (isRef(node)) return 4;
    if (hasChildren(node, nodes)) return 10;
    return 7;
  }

  function nodeLabel(node) {
    return truncate(node.title || node.id || '?', 26);
  }

  // Polarity table + root/ref colour; owner modifiers are strokes, not colours.
  function nodeColor(node) {
    if (node.id === rootId() || String(node.node_type).toLowerCase() === 'root') return COLORS.root;
    if (isRef(node)) return COLORS.ref;
    const polarity = String(node.polarity || '').toLowerCase();
    return COLORS[polarity] || COLORS.mixed;
  }

  function nodeDash(node) {
    if (node.owner === 'code') return '4 2';
    if (node.owner === 'decider_memory') return '1 3';
    return null;
  }
  function nodeFill(node) {
    return node.owner === 'default-file' || node.owner === 'proposal' ? 'var(--surface)' : 'var(--card)';
  }

  function lineagePath(id, nodes) {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const path = [];
    const seen = new Set();
    let cur = byId.get(id);
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      path.push(cur);
      cur = cur.parent && cur.parent !== cur.id ? byId.get(cur.parent) : null;
    }
    return path.reverse();
  }

  function ancestorChain(id, nodes) {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const chain = new Set();
    let cur = byId.get(id);
    while (cur && cur.parent && cur.parent !== cur.id) {
      if (chain.has(cur.parent)) break;
      chain.add(cur.parent);
      cur = byId.get(cur.parent);
    }
    return chain;
  }

  function descendantSet(id, nodes) {
    const byParent = new Map();
    nodes.forEach(n => {
      if (!n.parent) return;
      if (!byParent.has(n.parent)) byParent.set(n.parent, []);
      byParent.get(n.parent).push(n.id);
    });
    const out = new Set();
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      (byParent.get(cur) || []).forEach(child => {
        if (!out.has(child)) { out.add(child); stack.push(child); }
      });
    }
    nodes.forEach(n => { if (n.id !== id && String(n.id).startsWith(`${id}.`)) out.add(n.id); });
    return out;
  }

  // ★ backfillParentEdges — root parametrised, synthetic subtype_of edges.
  function backfillParentEdges(payload, root) {
    const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload?.edges) ? payload.edges : [];
    const nodeIds = new Set(nodes.map(n => n.id));
    const existing = new Set(edges.map(e => `${edgeSource(e)}→${edgeTarget(e)}`));
    let added = 0;
    function add(from, to) {
      const key = `${from}→${to}`;
      if (from === to || !nodeIds.has(from) || !nodeIds.has(to) || existing.has(key)) return false;
      edges.push({ source: from, target: to, edge_type: 'subtype_of', provenance: 'derived:hierarchy', via: null, confidence: 1.0, synthetic: true });
      existing.add(key);
      return true;
    }
    function hasAnyEdge(id) {
      return edges.some(edge => edgeSource(edge) === id || edgeTarget(edge) === id);
    }
    nodes.forEach(node => {
      if (!node || node.id === root) return;
      if (node.parent && nodeIds.has(node.parent)) {
        if (add(node.id, node.parent)) added += 1;
        return;
      }
      const parts = String(node.id).split('.');
      for (let i = parts.length - 1; i > 0; i -= 1) {
        const candidate = parts.slice(0, i).join('.');
        if (nodeIds.has(candidate)) {
          if (add(node.id, candidate)) added += 1;
          return;
        }
      }
      if (!hasAnyEdge(node.id) && nodeIds.has(root)) {
        if (add(node.id, root)) added += 1;
      }
    });
    payload.edges = edges;
    if (added) payload._backfilled_edges = added;
    return payload;
  }

  // ------------------------------------------------------------------ hash / storage
  function readHash() {
    const raw = String(location.hash || '').replace(/^#/, '');
    if (!raw) return {};
    const params = new URLSearchParams(raw);
    const out = {};
    const agent = params.get('agent');
    if (agent && AGENT_TYPES.has(agent)) out.agent = agent;
    const v = params.get('v');
    if (v !== null && v !== '' && /^\d+$/.test(v)) out.version = Number(v);
    const node = params.get('node');
    if (node) out.node = node;
    return out;
  }

  function writeHash() {
    if (!state.agent) return;
    const params = new URLSearchParams();
    params.set('agent', state.agent);
    if (state.version !== null && state.version !== undefined) params.set('v', String(state.version));
    if (state.selected) params.set('node', state.selected);
    const next = `#${params.toString()}`;
    if (location.hash === next) return;
    state.hashWriting = true;
    try {
      history.replaceState(null, '', next);
    } catch (_) {
      location.hash = next;
    }
    window.setTimeout(() => { state.hashWriting = false; }, 0);
  }

  // ------------------------------------------------------------------ agents
  async function loadAgents() {
    try {
      const data = await apiGet(`${API}/agents`);
      state.agents = Array.isArray(data.agents) ? data.agents : [];
    } catch (error) {
      state.agents = [];
      toast(`Could not list agents: ${error.message}`, 'error');
    }
    renderAgentSwitch();
  }

  function renderAgentSwitch() {
    document.querySelectorAll('#pgAgentSwitch .pg-seg').forEach(btn => {
      const info = state.agents.find(a => a.agent_type === btn.dataset.agent);
      btn.classList.toggle('is-active', btn.dataset.agent === state.agent);
      btn.setAttribute('aria-pressed', btn.dataset.agent === state.agent ? 'true' : 'false');
      if (info) {
        const bits = [`active v${info.active_version}`, plural(info.version_count, 'version')];
        if (info.stale) bits.push(`${info.stale} need a rebuild`);
        btn.title = bits.join(' · ');
      }
    });
  }

  // ------------------------------------------------------------------ versions
  async function loadVersions(agent, { retry = true } = {}) {
    setStatus('Loading policy versions…', { loading: true });
    try {
      const data = await apiGet(`${API}/versions?agent=${encodeURIComponent(agent)}`);
      state.versions = (Array.isArray(data.versions) ? data.versions : []).slice().sort((a, b) => Number(a.version) - Number(b.version));
      state.current = data.current ?? null;
      state.versionNotes = Array.isArray(data.notes) ? data.notes : [];
      return data;
    } catch (error) {
      if (error.status === 503 && retry) {
        setStatus('policy graph is being rebuilt — retrying…', { loading: true });
        showRebuildControl('busy');
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        return loadVersions(agent, { retry: false });
      }
      state.versions = [];
      state.current = null;
      state.versionNotes = [];
      setStatus(`Could not load policy versions: ${error.message}`, { error: true });
      toast(`Policy versions: ${error.message}`, 'error');
      if (error.status === 503) showRebuildControl('busy');
      return null;
    }
  }

  // ★ populateVersions — "v21 · Claude Code · Sep 2 · policy"
  function populateVersions(selected) {
    const select = qs('#pgVersion');
    if (!select) return;
    const list = state.versions;
    if (!list.length) {
      select.innerHTML = '<option value="">No policy versions for this agent yet</option>';
      select.disabled = true;
      updateVersionStepper();
      return;
    }
    select.disabled = false;
    select.innerHTML = list.map(v => {
      const label = [`v${v.version}`, actorLabel(v.actor_kind, v.created_by), fmtShortDate(v.created_at), v.kind || 'policy']
        .filter(Boolean).join(' · ');
      return `<option value="${esc(v.version)}"${Number(v.version) === Number(selected) ? ' selected' : ''}>${esc(label)}</option>`;
    }).join('');
    if (selected !== null && selected !== undefined) select.value = String(selected);
    updateVersionStepper();
  }

  // ★ stepper
  function setupVersionStepper() {
    const prev = qs('#pgPrev');
    const next = qs('#pgNext');
    if (prev && prev.dataset.ready !== 'true') {
      prev.dataset.ready = 'true';
      prev.addEventListener('click', () => stepVersion(-1));
    }
    if (next && next.dataset.ready !== 'true') {
      next.dataset.ready = 'true';
      next.addEventListener('click', () => stepVersion(1));
    }
  }

  function stepVersion(delta) {
    const select = qs('#pgVersion');
    const list = versionNumbers();
    if (!select || !list.length) return;
    const current = Number(select.value);
    const index = Math.max(0, list.indexOf(current));
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= list.length) return;
    select.value = String(list[nextIndex]);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function updateVersionStepper() {
    setupVersionStepper();
    const prev = qs('#pgPrev');
    const next = qs('#pgNext');
    const list = versionNumbers();
    const current = state.version !== null && state.version !== undefined ? Number(state.version) : Number(qs('#pgVersion')?.value);
    const index = list.indexOf(current);
    const hasPrevious = index > 0;
    const hasNext = index >= 0 && index < list.length - 1;
    if (prev) {
      prev.disabled = !hasPrevious;
      prev.textContent = hasPrevious ? `Previous: v${list[index - 1]}` : 'Previous';
    }
    if (next) {
      next.disabled = !hasNext;
      next.textContent = hasNext ? `Next: v${list[index + 1]}` : 'Latest version';
      next.setAttribute('aria-label', hasNext ? `Load policy version ${list[index + 1]}` : 'This is the latest policy version');
    }
    const badge = qs('#pgActiveBadge');
    if (badge) badge.hidden = !(state.current !== null && Number(state.current) === current);
  }


  // ------------------------------------------------------------------ timeline strip (§11.4)
  function reviewGlyphs(v) {
    const out = [];
    const r = v.review || null;
    if (r && r.critic_verdict) {
      const ok = r.critic_verdict === 'approve';
      const cls = r.critic_auto ? 'auto' : ok ? 'ok' : 'bad';
      const glyph = r.critic_auto ? 'C·' : ok ? 'C✓' : 'C✗';
      const conf = Number.isFinite(Number(r.critic_confidence)) && r.critic_confidence !== null ? ` ${Number(r.critic_confidence).toFixed(2)}` : '';
      const title = `critic ${ok ? 'approved' : 'rejected'}${conf}${r.critic_auto ? ' (automatic)' : ''}${r.critic_reason ? ` — ${String(r.critic_reason).slice(0, 120)}` : ''}`;
      out.push(`<span class="${cls}" title="${esc(title)}">${glyph}</span>`);
    }
    if (r && r.human_verdict) {
      const hv = r.human_verdict;
      const cls = hv === 'approve' ? 'ok' : hv === 'partial' ? 'half' : 'bad';
      const glyph = hv === 'approve' ? 'H✓' : hv === 'partial' ? 'H½' : 'H✗';
      const sections = Array.isArray(r.human_sections) ? r.human_sections : (r.human_sections ? [String(r.human_sections)] : []);
      const title = `human ${hv}${sections.length ? ` — sections: ${sections.join(', ')}` : ''}`;
      out.push(`<span class="${cls}" title="${esc(title)}">${glyph}</span>`);
    }
    const o = v.outcome || null;
    if (o && o.measurable && o.winrate_delta !== null && o.winrate_delta !== undefined) {
      const pts = Math.round(Number(o.winrate_delta) * 100);
      const cls = pts >= 0 ? 'pos' : 'neg';
      const title = `${plural(o.n_closed || 0, 'closed trade')}, win rate ${pct(o.win_rate)} vs prior ${pct(o.prior_win_rate)}${o.lineage_window ? '; lineage window' : ''} · ${o.clock || ''}`;
      out.push(`<span class="${cls}" title="${esc(title)}">${pts >= 0 ? '+' : '−'}${Math.abs(pts)}</span>`);
    } else if (o) {
      const title = o.reason ? String(o.reason) : `not yet measurable (${plural(o.n_closed || 0, 'closed trade')})`;
      out.push(`<span title="${esc(title)}">·</span>`);
    }
    if (Number(v.rewrites) > 0) {
      out.push(`<span title="${esc(`row rewritten in place ${v.rewrites}× after creation — earlier guideline files kept`)}">↻${v.rewrites}</span>`);
    }
    return out.join('');
  }

  function chipHtml(v) {
    const classes = ['pg-chip'];
    if (v.kind === 'reminder_only') classes.push('pg-chip--hollow');
    if (Number(v.version) === Number(state.version)) classes.push('pg-chip--active');
    if (v.is_active || Number(v.version) === Number(state.current)) classes.push('pg-chip--current');
    const actor = String(v.actor_kind || 'seed');
    const delta = v.delta_vs_prev || {};
    const pulseCount = Number(delta.added || 0) + Number(delta.changed || 0);
    const barWidth = Math.min(64, pulseCount ? 4 + pulseCount * 3 : 0);
    const titleBits = [`v${v.version}`, fmtPT(v.created_at), `by ${actorLabel(v.actor_kind, v.created_by)}`];
    if (v.kind === 'reminder_only') titleBits.push('weekly reminder appended — same policy lineage');
    else if (v.kind) titleBits.push(v.kind);
    if (v.description) titleBits.push(String(v.description).slice(0, 140));
    if (v.stale) titleBits.push('needs rebuild from database');
    if (v.roundtrip && v.roundtrip !== 'ok') titleBits.push(`round-trip ${v.roundtrip}`);
    return `<button type="button" class="${classes.join(' ')}" data-version="${esc(v.version)}" title="${esc(titleBits.join(' · '))}" aria-label="${esc(`Policy version ${v.version}`)}" aria-pressed="${Number(v.version) === Number(state.version) ? 'true' : 'false'}">
        <span class="pg-chip-actor ${esc(actor)}" aria-hidden="true"></span>
        <span class="pg-chip-label">v${esc(v.version)}</span>
        <span class="pg-chip-date">${esc(fmtShortDate(v.created_at))}</span>
        <span class="pg-chip-glyphs">${reviewGlyphs(v)}</span>
        <span class="pg-chip-bar" style="width:${barWidth}px" aria-hidden="true"></span>
      </button>`;
  }

  function ghostChipHtml(candidate, fromVersion) {
    const c = candidate.critic_verdict === 'approve' ? 'C✓' : candidate.critic_verdict ? 'C✗' : '';
    const h = candidate.human_verdict === 'approve' ? 'H✓' : candidate.human_verdict === 'partial' ? 'H½' : candidate.human_verdict ? 'H✗' : '';
    const conf = Number.isFinite(Number(candidate.critic_confidence)) && candidate.critic_confidence !== null ? ` ${Number(candidate.critic_confidence).toFixed(1)}` : '';
    const title = `rejected candidate from v${fromVersion}${c ? ` · critic ${candidate.critic_verdict === 'approve' ? '✓' : '✗'}${conf}` : ''}${h ? ` · human ${candidate.human_verdict === 'approve' ? '✓' : candidate.human_verdict === 'partial' ? '½' : '✗'}` : ''}${candidate.created_at ? ` · ${fmtDateOnly(candidate.created_at)}` : ''}`;
    return `<span class="pg-chip pg-chip--ghost" title="${esc(title)}" aria-label="${esc(title)}">
        <span class="pg-chip-label">✕</span>
        <span class="pg-chip-date">${esc(fmtShortDate(candidate.created_at))}</span>
        <span class="pg-chip-glyphs"><span class="${candidate.critic_auto ? 'auto' : candidate.critic_verdict === 'approve' ? 'ok' : 'bad'}">${esc(candidate.critic_auto ? 'C·' : c)}</span><span class="${candidate.human_verdict === 'approve' ? 'ok' : candidate.human_verdict === 'partial' ? 'half' : 'bad'}">${esc(h)}</span></span>
      </span>`;
  }

  function renderTimeline() {
    const strip = qs('#pgTimeline');
    if (!strip) return;
    const versions = state.versions;
    if (!versions.length) {
      strip.innerHTML = '<p class="pg-timeline-note">No policy versions for this agent yet.</p>';
      return;
    }
    // Group consecutive chips by lineage_version so reminder-only followers share an underline.
    const groups = [];
    versions.forEach(v => {
      const lineage = v.lineage_version ?? v.version;
      const last = groups[groups.length - 1];
      if (last && last.lineage === lineage) last.items.push(v);
      else groups.push({ lineage, items: [v] });
    });
    const html = groups.map(group => {
      const chips = group.items.map(v => {
        const ghosts = (Array.isArray(v.rejected_candidates) ? v.rejected_candidates : []).map(c => ghostChipHtml(c, v.version)).join('');
        return chipHtml(v) + ghosts;
      }).join('');
      const underline = group.items.length > 1
        ? `<span class="pg-lineage-line" title="${esc(`same policy lineage as v${group.lineage}`)}"></span>`
        : '<span class="pg-lineage-line" style="opacity:0"></span>';
      return `<div class="pg-chip-group"><div class="pg-chip-row">${chips}</div>${underline}</div>`;
    }).join('');
    const list = versionNumbers();
    const index = list.indexOf(Number(state.version));
    strip.innerHTML = `<button type="button" class="pg-timeline-step" id="pgTimelinePrev" aria-label="Previous policy version"${index <= 0 ? ' disabled' : ''}>‹</button>${html}<button type="button" class="pg-timeline-step" id="pgTimelineNext" aria-label="Next policy version"${index < 0 || index >= list.length - 1 ? ' disabled' : ''}>›</button>`;
    strip.querySelectorAll('.pg-chip[data-version]').forEach(chip => {
      chip.addEventListener('click', () => {
        const select = qs('#pgVersion');
        if (!select) return;
        select.value = String(chip.dataset.version);
        select.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
    qs('#pgTimelinePrev')?.addEventListener('click', () => stepVersion(-1));
    qs('#pgTimelineNext')?.addEventListener('click', () => stepVersion(1));
    const active = strip.querySelector('.pg-chip--active');
    if (active && typeof active.scrollIntoView === 'function') {
      try { active.scrollIntoView({ block: 'nearest', inline: 'center' }); } catch (_) { /* older browsers */ }
    }
  }

  function renderTimelineNote() {
    const meta = qs('#pgVersionMeta');
    if (!meta) return;
    const v = versionEntry(state.version);
    const notes = [];
    if (v) {
      const since = v.activation?.created_at || v.created_at;
      const inForce = v.activation ? `v${v.version} in force since ${fmtPT(since)}` : `v${v.version} saved ${fmtPT(v.created_at)} · activation: not recorded`;
      let window_ = '';
      if (v.outcome && v.outcome.reason && !v.outcome.measurable && v.outcome.n_closed === undefined) {
        window_ = `window: ${v.outcome.reason}`;
      } else if (v.outcome) {
        window_ = `window: ${plural(v.outcome.n_closed || 0, 'closed trade')} so far`;
      } else {
        window_ = 'window: no direct trade attribution';
      }
      notes.push(`${inForce} · ${window_}`);
    }
    state.versionNotes.forEach(n => notes.push(String(n)));
    const existing = meta.querySelector('.pg-timeline-note');
    if (existing) existing.remove();
    const p = document.createElement('p');
    p.className = 'pg-timeline-note';
    p.textContent = notes.join(' · ');
    meta.appendChild(p);
  }

  // "v21 · 2026-09-02 14:57 PT · by Claude Code · 41 guidelines · +9 added · 3 changed · 1 removed · …"
  function renderVersionMeta() {
    const meta = qs('#pgVersionMeta');
    if (!meta) return;
    const v = versionEntry(state.version);
    const p = state.payload;
    if (!v && !p) { meta.innerHTML = ''; return; }
    const bits = [];
    const version = p?.version ?? v?.version;
    bits.push(`v${version}`);
    bits.push(fmtPT(p?.created_at || v?.created_at));
    bits.push(`by ${actorLabel(p?.actor_kind || v?.actor_kind, p?.created_by || v?.created_by)}`);
    const count = p?.stats?.nodes ?? v?.node_count;
    if (Number.isFinite(Number(count))) bits.push(plural(Number(count), 'guideline'));
    const delta = p?.stats || v?.delta_vs_prev || {};
    const hasPrev = (p && p.previous_version !== null && p.previous_version !== undefined) || (v && v.parent_version !== null && v.parent_version !== undefined);
    if (hasPrev) {
      bits.push(`+${Number(delta.added || 0)} added`);
      bits.push(`${Number(delta.changed || 0)} changed`);
      bits.push(`${Number(delta.removed || 0)} removed`);
      if (Number(delta.renamed || 0)) bits.push(`${delta.renamed} renamed`);
    } else {
      bits.push('first version');
    }
    const sourceChanged = Array.isArray(v?.delta_vs_prev?.source_changed) ? v.delta_vs_prev.source_changed : [];
    sourceChanged.forEach(field => {
      const now = v?.fields?.[field];
      bits.push(now === 'inherited' ? `${field} now inherited from the default file (was stored)` : `${field} now stored (was inherited)`);
    });
    Object.entries(v?.fields || {}).forEach(([field, mode]) => {
      if (mode === 'inherited' && !sourceChanged.includes(field)) bits.push(`${field} inherited from the default file`);
    });
    if (v?.review) {
      const r = v.review;
      const critic = r.critic_verdict ? `critic ${r.critic_verdict === 'approve' ? '✓' : '✗'}${r.critic_confidence !== null && r.critic_confidence !== undefined ? ` ${Number(r.critic_confidence).toFixed(2)}` : ''}${r.critic_auto ? ' (auto)' : ''}` : '';
      const human = r.human_verdict ? `human ${r.human_verdict === 'approve' ? '✓' : r.human_verdict === 'partial' ? '½' : '✗'}` : '';
      if (critic || human) bits.push([critic, human].filter(Boolean).join(' → '));
    }
    if (v?.outcome) {
      const o = v.outcome;
      if (o.measurable) {
        const pts = o.winrate_delta !== null && o.winrate_delta !== undefined ? Math.round(Number(o.winrate_delta) * 100) : null;
        bits.push(`realized: win rate ${pct(o.win_rate)}${pts !== null ? ` (${pts >= 0 ? '+' : '−'}${Math.abs(pts)} pts vs prior)` : ''} over ${plural(o.n_closed || 0, 'closed trade')}`);
      } else if (o.reason) {
        bits.push(`realized: ${o.reason}`);
      } else {
        bits.push(`realized: not yet measurable (${plural(o.n_closed || 0, 'closed trade')})`);
      }
    }
    if (v?.stale) bits.push('files older than the database row');
    if (v?.roundtrip && v.roundtrip !== 'ok') bits.push(`round-trip ${v.roundtrip}`);
    meta.innerHTML = `<div>${bits.map(b => esc(b)).join('<span class="pg-sep">·</span>')}</div>`;
    renderTimelineNote();
  }

  // ------------------------------------------------------------------ rebuild control (D15)
  function showRebuildControl(reason) {
    const slot = qs('#pgRebuildSlot');
    if (!slot) return;
    state.rebuildReason = reason || null;
    if (!reason) { slot.innerHTML = ''; return; }
    if (qs('#pgRebuild')) return;
    const titles = {
      stale: 'The guideline files are older than the database row — rebuild them from the database.',
      mismatch: 'The compiled prompt does not match the database row byte-for-byte — rebuild from the database.',
      busy: 'The policy graph is being rebuilt by another process — try again in a moment.'
    };
    slot.innerHTML = `<button type="button" id="pgRebuild" class="pe-btn secondary pg-btn-small" title="${esc(titles[reason] || '')}">Rebuild from database</button>`;
    qs('#pgRebuild').addEventListener('click', rebuildFromDatabase);
  }

  async function rebuildFromDatabase() {
    const btn = qs('#pgRebuild');
    if (!state.agent) return;
    if (btn) { btn.disabled = true; btn.textContent = 'Rebuilding…'; }
    setStatus('Rebuilding the policy graph from the database…', { loading: true });
    try {
      const body = { agent_type: state.agent, version: state.version ?? 'all', force: true };
      const result = await fetchJSON(`${API}/rebuild`, { method: 'POST', body: JSON.stringify(body) });
      const actions = (result.results || []).map(r => `v${r.version} ${r.action}`).join(', ');
      toast(`Rebuilt from database${actions ? `: ${actions}` : ''}`, 'success');
      state.nodeCache.clear();
      showRebuildControl(null);
      await loadVersions(state.agent);
      populateVersions(state.version);
      renderTimeline();
      await loadGraph(state.agent, state.version, { keepSelection: true });
    } catch (error) {
      toast(`Rebuild failed: ${error.message}`, 'error');
      setStatus(`Rebuild failed: ${error.message}`, { error: true });
      if (btn) { btn.disabled = false; btn.textContent = 'Rebuild from database'; }
    }
  }

  // ------------------------------------------------------------------ graph loading
  function graphUrl(agent, version) {
    const params = new URLSearchParams();
    params.set('agent', agent);
    if (version !== null && version !== undefined && version !== '') params.set('version', String(version));
    params.set('layer', state.layer);
    if (state.showRefs) params.set('refs', '1');
    return `${API}/graph?${params.toString()}`;
  }

  async function loadGraph(agent, version, { pulse = false, keepSelection = false, openNode = null, retry = true } = {}) {
    const seq = ++state.graphSeq;
    setStatus(`Loading v${version ?? 'current'} policy graph…`, { loading: true });
    let payload;
    try {
      payload = await apiGet(graphUrl(agent, version));
    } catch (error) {
      if (seq !== state.graphSeq) return;
      if (error.status === 503 && retry) {
        setStatus('policy graph is being rebuilt — retrying…', { loading: true });
        showRebuildControl('busy');
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        return loadGraph(agent, version, { pulse, keepSelection, openNode, retry: false });
      }
      if (error.status === 503) showRebuildControl('busy');
      setStatus(`Could not load the policy graph: ${error.message}`, { error: true });
      toast(`Policy graph: ${error.message}`, 'error');
      return;
    }
    if (seq !== state.graphSeq) return;

    backfillParentEdges(payload, payload.root_id);
    decorateWithProposals(payload);
    const previousSelected = keepSelection ? state.selected : null;
    state.prevPayload = state.payload;
    state.payload = payload;
    state.version = Number(payload.version);
    state.selected = null;
    lsSet(LS_AGENT, agent);
    lsSet(LS_VERSION, String(state.version));

    const select = qs('#pgVersion');
    if (select && select.value !== String(state.version)) select.value = String(state.version);

    qs('#pgTitle').textContent = payload.title || `${agentMeta(agent).label} policy v${payload.version}`;
    const entry = versionEntry(state.version);
    qs('#pgBlurb').textContent = entry?.description || `Every guideline the ${agentMeta(agent).label} runs on in policy version ${payload.version}.`;

    if (pulse) {
      const added = new Set();
      const changed = new Set();
      (payload.nodes || []).forEach(n => {
        if (n.change === 'added') added.add(n.id);
        else if (n.change === 'changed' || n.change === 'renamed') changed.add(n.id);
      });
      state.pendingPulse = added.size || changed.size ? { added, changed } : null;
    } else {
      state.pendingPulse = null;
    }

    updateLinks(payload);
    updateVersionStepper();
    renderTimeline();
    renderVersionMeta();
    renderGraph(payload);
    renderLegend(payload);
    renderRemoved(payload);
    applyFilters();
    renderChangeAgainstOptions();
    loadChangeList(state.diffAgainst);

    const stats = payload.stats || {};
    const bits = [`Loaded ${plural(Number(stats.nodes ?? payload.nodes?.length ?? 0), 'guideline')}, ${plural(Number(stats.edges ?? payload.edges?.length ?? 0), 'link')}`];
    if (payload.previous_version !== null && payload.previous_version !== undefined) {
      bits.push(`+${Number(stats.added || 0)} added`);
      bits.push(`${Number(stats.changed || 0)} changed`);
      bits.push(`${Number(stats.removed || 0)} removed vs v${payload.previous_version}`);
    } else {
      bits.push('first version — nothing to compare with');
    }
    bits.push(`round-trip ${payload.roundtrip || 'unknown'}`);
    if (payload.rebuilt_on_read) bits.push('rebuilt from database on load');
    if (payload.stale) bits.push('files older than the database row');
    setStatus(bits.join(' · '), { error: payload.roundtrip === 'mismatch' });

    if (payload.stale) showRebuildControl('stale');
    else if (payload.roundtrip === 'mismatch') showRebuildControl('mismatch');
    else showRebuildControl(null);

    const target = openNode || state.pendingNode || previousSelected;
    state.pendingNode = null;
    if (target && payload.nodes?.some(n => n.id === target)) applySelection(target);
    else applySelection(null);

    rememberVersion();
    writeHash();
  }

  function updateLinks(payload) {
    const links = payload.links || {};
    const setLink = (id, href) => {
      const a = qs(id);
      if (!a) return;
      if (href) { a.href = href; a.removeAttribute('aria-disabled'); }
      else { a.href = '#'; a.setAttribute('aria-disabled', 'true'); }
    };
    setLink('#pgCompiledLink', state.layer === 'stored' ? (links.compiled_stored || links.compiled_effective) : (links.compiled_effective || links.compiled_stored));
    setLink('#pgRuntimeLink', links.runtime_preview);
    setLink('#pgBundleLink', links.bundle);
    const lab = qs('#pgPromptLabLink');
    if (lab) lab.href = '/prompt-evolution';
  }

  // ------------------------------------------------------------------ render graph (★)
  function linkClass(edge) {
    const type = edgeType(edge);
    return EDGE_KIND_LABEL[type] ? type : 'subtype_of';
  }

  function laneX(node) {
    const field = node.field || '';
    if (node.owner === 'code' || node.owner === 'decider_memory' || node.owner === 'runtime') return WIDTH / 2;
    if (field === 'system_prompt' || field === 'user_prompt_template') return WIDTH * 0.18;
    if (field === 'strategy_directives') return WIDTH / 2;
    if (field === 'soul' || field === 'memory') return WIDTH * 0.82;
    return WIDTH / 2;
  }

  function laneY(node) {
    if (node.owner === 'code' || node.owner === 'decider_memory' || node.owner === 'runtime') return HEIGHT - 70;
    return 60 + depthOf(node) * 95;
  }

  function renderGraph(payload) {
    const wrap = qs('#pgSvgWrap');
    if (!wrap) return;
    if (view.simulation) { view.simulation.stop(); view.simulation = null; }
    if (!window.d3) {
      wrap.innerHTML = '<div class="pe-error">Graph library failed to load — the compiled prompt links still work.</div>';
      view.svg = null; view.nodes = null; view.links = null;
      return;
    }
    wrap.innerHTML = `<svg id="pgSvg" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="${esc(payload.title || 'Policy graph')}"></svg>`;

    const allNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const nodes = allNodes.map(node => ({ ...node }));
    const nodeSet = new Set(nodes.map(n => n.id));
    const links = (Array.isArray(payload.edges) ? payload.edges : [])
      .map(edge => ({ ...edge, source: edgeSource(edge), target: edgeTarget(edge), sourceId: edgeSource(edge), targetId: edgeTarget(edge), kind: edgeType(edge) }))
      .filter(edge => nodeSet.has(edge.sourceId) && nodeSet.has(edge.targetId));

    const svg = d3.select('#pgSvg');
    const viewport = svg.append('g').attr('class', 'pg-viewport');
    const zoom = d3.zoom().scaleExtent([0.55, 4]).on('zoom', event => viewport.attr('transform', event.transform));
    svg.call(zoom);
    svg.on('click', () => applySelection(null));
    view.svg = svg; view.viewport = viewport; view.zoom = zoom;

    viewport.append('rect').attr('width', WIDTH).attr('height', HEIGHT).attr('rx', 14).attr('fill', 'var(--surface)');

    const neighborMap = new Map();
    nodes.forEach(node => neighborMap.set(node.id, new Set([node.id])));
    links.forEach(link => {
      neighborMap.get(link.sourceId)?.add(link.targetId);
      neighborMap.get(link.targetId)?.add(link.sourceId);
    });
    view.neighborMap = neighborMap;

    const link = viewport.append('g').attr('class', 'pg-links')
      .selectAll('line').data(links).join('line')
      .attr('class', edge => `pg-link ${linkClass(edge)}${edge.proposed ? ' proposed' : ''}`);
    link.append('title').text(edge => `${EDGE_KIND_LABEL[edge.kind] || edge.kind}${edge.via ? ` via ${edge.via}` : ''}${edge.confidence !== null && edge.confidence !== undefined && edge.kind === 'overlaps' ? ` · ${Math.round(Number(edge.confidence) * 100)} % similar` : ''}`);

    const node = viewport.append('g').attr('class', 'pg-nodes')
      .selectAll('g').data(nodes).join('g')
      .attr('class', d => {
        const cls = ['pg-node', d.id === payload.root_id || hasChildren(d, allNodes) ? 'parent-node' : 'leaf-node'];
        if (d.status === 'inert') cls.push('is-inert');
        if (d.ghost) cls.push(`pg-ghost-${d.ghost}`);
        return cls.join(' ');
      })
      .attr('data-id', d => d.id)
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('aria-label', d => `${d.id}: ${d.title || d.id}`)
      .call(d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended));

    node.append('circle').attr('class', 'pg-ring').attr('r', d => nodeRadius(d, allNodes) + 4);
    node.filter(d => d.owner === 'code').append('circle')
      .attr('class', 'pg-owner-ring')
      .attr('r', d => nodeRadius(d, allNodes) + 3)
      .attr('fill', 'none').attr('stroke', COLORS.code_ring).attr('stroke-width', 1.2).attr('opacity', 0.85);
    node.append('circle').attr('class', 'pg-core')
      .attr('r', d => nodeRadius(d, allNodes))
      .attr('fill', d => nodeFill(d))
      .attr('stroke', d => nodeColor(d))
      .attr('stroke-width', 2.4)
      .attr('stroke-dasharray', d => nodeDash(d));
    node.append('text')
      .attr('y', d => nodeRadius(d, allNodes) + 13)
      .attr('text-anchor', 'middle')
      .attr('font-size', d => isRef(d) ? 9 : 11)
      .text(d => nodeLabel(d));
    node.append('title').text(d => `${d.title || d.id}\n${d.id}`);

    node.on('mouseover', (_, d) => highlight(d.id))
      .on('mouseout', clearHighlight)
      .on('focus', (_, d) => highlight(d.id))
      .on('blur', clearHighlight)
      .on('click', (event, d) => { event.stopPropagation(); applySelection(d.id); })
      .on('keydown', (event, d) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); applySelection(d.id); }
      });

    const charge = nodes.length > 80 ? -180 : -260;
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id)
        .distance(edge => LINK_DISTANCE[edge.kind] ?? 110)
        .strength(edge => LINK_STRENGTH[edge.kind] ?? 0.3))
      .force('charge', d3.forceManyBody().strength(charge))
      .force('center', d3.forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', d3.forceCollide().radius(d => nodeRadius(d, allNodes) + (isRef(d) ? 12 : hasChildren(d, allNodes) ? 34 : 22)))
      .force('y', d3.forceY(d => laneY(d)).strength(0.12))
      .force('x', d3.forceX(d => laneX(d)).strength(0.05));
    if (nodes.some(isRef)) {
      simulation.force('radial', d3.forceRadial(d => isRef(d) ? 250 : 0, WIDTH / 2, HEIGHT / 2).strength(d => isRef(d) ? 0.4 : 0));
    }

    simulation.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    view.nodes = node; view.links = link; view.simulation = simulation;
    applyChangeClasses();

    if (state.pendingPulse) {
      const { added, changed } = state.pendingPulse;
      state.pendingPulse = null;
      let didPulse = false;
      const trigger = () => {
        if (didPulse) return;
        didPulse = true;
        pulseNodes(added, 'pulse-new');
        pulseNodes(changed, 'pulse-changed');
      };
      simulation.on('end.pulse', trigger);
      window.setTimeout(trigger, 900);
    }

    function highlight(id) {
      const neighbors = neighborMap.get(id) || new Set([id]);
      node.classed('hover-dim', d => !neighbors.has(d.id)).classed('hover-trace', d => neighbors.has(d.id));
      link.classed('hover-dim', d => d.sourceId !== id && d.targetId !== id).classed('hover-trace', d => d.sourceId === id || d.targetId === id);
    }
    function clearHighlight() {
      node.classed('hover-dim hover-trace', false);
      link.classed('hover-dim hover-trace', false);
    }
    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    }
    function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null; d.fy = null;
    }
  }

  // ★ pulseNodes — 2.4 s, green for new, amber for changed.
  function pulseNodes(ids, cls = 'pulse-new') {
    if (!ids?.size || !view.nodes) return;
    const circles = view.nodes.select('circle.pg-core').filter(d => ids.has(d.id));
    if (circles.empty()) return;
    circles.classed(cls, true);
    window.setTimeout(() => circles.classed(cls, false), 2400);
  }

  function applyChangeClasses() {
    if (!view.nodes) return;
    const on = state.highlightChanges;
    view.nodes
      .classed('pg-changed-added', d => on && d.change === 'added')
      .classed('pg-changed-changed', d => on && (d.change === 'changed' || d.change === 'whitespace'))
      .classed('pg-changed-renamed', d => on && d.change === 'renamed')
      .classed('pg-source-changed', d => on && d.change === 'source_changed');
  }

  function resetZoom() {
    if (!view.svg || !view.zoom) return;
    view.svg.transition().duration(350).call(view.zoom.transform, d3.zoomIdentity);
  }

  // ------------------------------------------------------------------ legend (rows only for kinds present)
  function renderLegend(payload) {
    const legend = qs('#pgLegend');
    if (!legend) return;
    const nodes = payload.nodes || [];
    const present = new Set();
    nodes.forEach(n => {
      if (n.id === payload.root_id || n.node_type === 'root') present.add('root');
      else if (n.owner === 'code') present.add('code');
      else if (n.owner === 'decider_memory') present.add('ltm');
      else if (n.node_type === 'template') present.add('template');
      else if (isRef(n)) present.add('ref');
      else present.add(String(n.polarity || 'mixed'));
      if (n.owner === 'default-file') present.add('inherited');
      if (n.ghost) present.add('proposed');
    });
    const rows = [
      ['root', 'root', COLORS.root, ''],
      ['gate', 'hard gate', COLORS.gate, ''],
      ['action', 'action', COLORS.action, ''],
      ['caution', 'caution', COLORS.caution, ''],
      ['principle', 'identity / principle', COLORS.principle, ''],
      ['evidence', 'evidence & lessons', COLORS.evidence, ''],
      ['mixed', 'mixed', COLORS.mixed, ''],
      ['structure', 'structure', COLORS.structure, ''],
      ['template', 'template text', COLORS.structure, ''],
      ['inherited', 'inherited from default file', COLORS.principle, 'hollow'],
      ['code', 'code-owned (read-only)', COLORS.code_ring, 'dashed'],
      ['ltm', 'long-term memory row (read-only)', COLORS.evidence, 'dotted'],
      ['ref', 'reference (ticker / concept)', COLORS.ref, ''],
      ['proposed', 'proposed change awaiting your review', COLORS.action, 'ghost']
    ].filter(([key]) => present.has(key))
      .map(([, label, color, mod]) => `<span><i class="${mod}" style="color:${color};background:${mod === 'hollow' ? 'var(--surface)' : color}"></i>${esc(label)}</span>`);
    const kinds = new Set((payload.edges || []).map(e => edgeType(e)));
    const edgeRows = [
      ['subtype_of', 'part of'],
      ['includes', 'assembled into the prompt'],
      ['related_to', 'related (link or shared tag)'],
      ['cites', 'cites a ticker'],
      ['overlaps', 'overlaps with code or memory row'],
      ['constrains', 'code constrains this rule'],
      ['enforced_by', 'enforced by code']
    ].filter(([kind]) => kinds.has(kind))
      .map(([kind, label]) => `<span><i class="pg-legend-line ${kind}"></i>${esc(label)}</span>`);
    legend.innerHTML = rows.concat(edgeRows).join('');
  }

  // ------------------------------------------------------------------ removed chips
  function renderRemoved(payload) {
    const box = qs('#pgRemoved');
    if (!box) return;
    const removed = Array.isArray(payload.removed_nodes) ? payload.removed_nodes : [];
    if (!removed.length || payload.previous_version === null || payload.previous_version === undefined) { box.innerHTML = ''; return; }
    box.innerHTML = `<span>Removed since v${esc(payload.previous_version)}:</span>` + removed.map(r =>
      `<button type="button" class="pg-removed-chip" data-id="${esc(r.id)}" title="${esc(`${r.id} · ${FIELD_LABEL[r.field] || r.field || ''} — open it in v${payload.previous_version}`)}">${esc(truncate(r.title || r.id, 34))}</button>`
    ).join('');
    box.querySelectorAll('.pg-removed-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const select = qs('#pgVersion');
        state.pendingNode = btn.dataset.id;
        if (select) {
          select.value = String(payload.previous_version);
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
    });
  }

  // ------------------------------------------------------------------ filters
  function nodeMatchesFilter(node, filters) {
    if (filters.has('all')) return true;
    if (node.id === rootId()) return true;
    if (filters.has('code') && node.owner === 'code') return true;
    if (filters.has('ltm') && (node.owner === 'decider_memory' || node.node_type === 'ltm')) return true;
    if (filters.has('system') && node.field === 'system_prompt') return true;
    if (filters.has('user') && node.field === 'user_prompt_template') return true;
    if (filters.has('directives') && node.field === 'strategy_directives') return true;
    if (filters.has('soul') && node.field === 'soul') return true;
    if (filters.has('memory') && node.field === 'memory' && node.owner !== 'decider_memory') return true;
    return false;
  }

  function applyFilters() {
    document.querySelectorAll('#pgFieldFilter .pg-chip-filter').forEach(btn => {
      const on = state.filters.has(btn.dataset.filter);
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (!view.nodes) return;
    const visible = new Set();
    view.nodes.each(d => { if (nodeMatchesFilter(d, state.filters)) visible.add(d.id); });
    view.nodes.classed('is-hidden', d => !visible.has(d.id));
    view.links.classed('is-hidden', d => !(visible.has(d.sourceId) && visible.has(d.targetId)));
  }

  function toggleFilter(key) {
    if (key === 'all') {
      state.filters = new Set(['all']);
    } else {
      state.filters.delete('all');
      if (state.filters.has(key)) state.filters.delete(key);
      else state.filters.add(key);
      if (!state.filters.size) state.filters = new Set(['all']);
    }
    applyFilters();
  }

  // ------------------------------------------------------------------ selection (★)
  function applySelection(id) {
    state.selected = id || null;
    if (view.nodes) {
      view.nodes.classed('selected ancestor descendant dimmed', false);
      view.links.classed('ancestor-edge descendant-edge dimmed', false);
    }
    const nodes = state.payload?.nodes || [];
    if (!id) {
      qs('#pgPanelEmpty').hidden = false;
      qs('#pgPanelBody').hidden = true;
      writeHash();
      return;
    }
    const ancestors = ancestorChain(id, nodes);
    const descendants = descendantSet(id, nodes);
    const related = new Set([id, ...ancestors, ...descendants]);
    if (view.nodes) {
      view.nodes
        .classed('selected', d => d.id === id)
        .classed('ancestor', d => ancestors.has(d.id))
        .classed('descendant', d => descendants.has(d.id))
        .classed('dimmed', d => !related.has(d.id));
      view.links
        .classed('ancestor-edge', d => (ancestors.has(d.sourceId) && (d.targetId === id || ancestors.has(d.targetId))) || (ancestors.has(d.targetId) && (d.sourceId === id || ancestors.has(d.sourceId))))
        .classed('descendant-edge', d => (descendants.has(d.sourceId) || d.sourceId === id) && (descendants.has(d.targetId) || d.targetId === id))
        .classed('dimmed', d => !(related.has(d.sourceId) && related.has(d.targetId)));
    }
    const node = nodes.find(n => n.id === id);
    if (node) openPanel(node);
    writeHash();
  }

  // ------------------------------------------------------------------ details panel
  function typeSentence(node) {
    const type = String(node.node_type || 'guideline');
    const pol = POLARITY_LABEL[node.polarity] || node.polarity || 'mixed';
    const src = node.polarity_source === 'authored' ? 'authored' : 'derived';
    return `${type} · ${pol} (${src})`;
  }

  function changeSentence(node, payload, detail) {
    const prev = payload.previous_version;
    switch (node.change) {
      case 'added': return `added in v${payload.version}`;
      case 'changed': return prev !== null && prev !== undefined ? `changed vs v${prev}` : `changed in v${payload.version}`;
      case 'whitespace': return prev !== null && prev !== undefined ? `whitespace-only change vs v${prev}` : 'whitespace-only change';
      case 'renamed': {
        const sim = detail?.similarity ?? state.similarity?.get(node.id);
        return `renamed from ${node.renamed_from || '?'}${Number.isFinite(Number(sim)) ? ` (${Math.round(Number(sim) * 100)}% similar)` : ''}`;
      }
      case 'source_changed':
        return node.owner === 'default-file'
          ? 'now inherited from the default file (was stored in the version)'
          : 'now stored in the version (was inherited from the default file)';
      case 'same':
      default: {
        if (detail && Array.isArray(detail.changed_in) && detail.changed_in.length) {
          return `unchanged since v${Math.max(...detail.changed_in.map(Number))}`;
        }
        if (detail && Number.isFinite(Number(detail.first_seen))) return `unchanged since v${detail.first_seen}`;
        if (node.owner === 'code') return 'code-owned — versioned with the repository, not the policy';
        if (node.owner === 'decider_memory') return 'memory row — not part of the policy version';
        return prev !== null && prev !== undefined ? `unchanged vs v${prev}` : 'first version';
      }
    }
  }

  function inheritedInfo(node, payload) {
    const raw = node.inherited || null;
    const segField = node.field;
    const fromPayload = payload.inherited && segField ? payload.inherited[segField] : null;
    const info = (raw && typeof raw === 'object') ? raw : (fromPayload && typeof fromPayload === 'object' ? fromPayload : {});
    return {
      path: info.inherited_from || info.source_path || info.from || info.path || (typeof raw === 'string' ? raw : ''),
      sha: info.inherited_git_sha || info.git_sha || info.sha || null,
      resolution: info.inherited_resolution || info.resolution || null,
      date: info.blob_date || info.committed_at || info.created_at || null
    };
  }

  function ownerSentence(node, payload) {
    const owner = node.owner || 'db';
    const v = payload.version;
    if (owner === 'proposal') return `Proposed in proposal #${node.proposal_id ?? '?'} — not part of the policy yet`;
    if (owner === 'db') {
      const m = /prompt_versions#(\d+)/.exec(String(node.provenance || ''));
      const id = m ? m[1] : payload.prompt_version_id;
      return `Stored in prompt_versions #${id ?? '?'} (v${v})`;
    }
    if (owner === 'default-file') {
      const inh = inheritedInfo(node, payload);
      const where = inh.resolution === 'worktree' ? 'working tree copy' : inh.resolution === 'live-mirror' ? 'live file' : `git blob${inh.date ? ` at ${fmtDateOnly(inh.date)}` : ''}`;
      const field = FIELD_LABEL[node.field] || node.field || 'field';
      return `Inherited from ${inh.path || 'the default file'}${inh.sha ? ` @${String(inh.sha).slice(0, 8)}` : ''} (${where}) — the stored version has an empty ${field}`;
    }
    if (owner === 'code') {
      const prov = String(node.provenance || '').replace(':', ' · ');
      const sha = payload.code?.git_sha || node.git_sha || null;
      const fires = node.fires === true ? `fires for v${v}` : node.fires === false ? `does not fire for v${v}` : null;
      const cond = node.condition ? ` (${plainCondition(node.condition)})` : '';
      return `Code-owned: ${prov || 'repository code'}${sha ? ` (as of ${sha})` : ''} — read-only${fires ? ` · ${fires}${cond}` : cond}`;
    }
    if (owner === 'decider_memory') {
      const x = node.extra || {};
      const rowId = String(node.id).split('.').pop();
      const kind = node.kind ?? x.kind;
      const source = node.source ?? x.source;
      const weight = node.weight ?? x.weight;
      const injected = node.injected ?? x.injected;
      const bits = [`decider_memory row #${rowId}`];
      if (kind) bits.push(String(kind));
      if (source) bits.push(String(source));
      if (weight !== undefined && weight !== null) bits.push(`weight ${Number(weight).toFixed(1)}`);
      if (injected === true) bits.push(`injected (top ${payload.ltm?.injected_limit ?? '?'}; ticker-matched rows can displace it)`);
      else if (injected === false) bits.push('not injected by default');
      if (node.id === `${payload.prefix}.ltm`) return `decider_memory rows${payload.ltm?.snapshot === 'reconstructed' ? ' — rows as of today, filtered by creation date (no row history exists)' : ' — live rows'}`;
      if (payload.ltm?.snapshot === 'reconstructed') bits.push('rows as of today, filtered by creation date');
      return bits.join(' · ');
    }
    if (owner === 'runtime') return 'Per-cycle data — not policy text';
    if (owner === 'generated') return 'Generated description of this policy version — not prompt text';
    return owner;
  }

  function plainCondition(cond) {
    const c = String(cond || '');
    const m = /'([^']+)' not in user_prompt_template and '([^']+)' not in strategy_directives/.exec(c);
    if (m) return `${m[1]} absent from template and directives`;
    const m2 = /'([^']+)' not in user_prompt_template/.exec(c);
    if (m2 && /not IS_MARGIN_ACCOUNT/.test(c)) return `cash account and ${m2[1]} absent from template`;
    if (m2) return `${m2[1]} absent from template`;
    return c;
  }

  function statusSentence(node) {
    const status = String(node.status || 'active');
    const badges = [];
    if (status === 'inert') badges.push('<span class="pg-badge-inert">inert</span>');
    if (node.owner === 'default-file' || status === 'inherited') badges.push('<span class="pg-badge-inherited">inherited</span>');
    if (node.locked) badges.push('<span class="pg-badge-locked">locked</span>');
    if (node.owner === 'code') badges.push('<span class="pg-badge-code">code</span>');
    const compiled = node.compiled === 'stored' ? 'part of the stored prompt'
      : node.compiled === 'effective-only' ? 'used at runtime, not stored in the version'
        : 'never compiled into the prompt';
    let text;
    if (status === 'inert') text = 'Not executed at runtime — only the soul is injected';
    else if (status === 'inactive') text = node.owner === 'code' ? 'inactive for this version' : 'inactive row';
    else if (status === 'read-only') text = 'read-only';
    else if (status === 'generated') text = 'generated';
    else if (status === 'proposed') text = 'proposed — awaiting your review';
    else text = status;
    return `${esc(text)} · ${esc(compiled)}${badges.length ? ' ' + badges.join(' ') : ''}`;
  }

  function fillMeta(id, html) {
    const dd = qs(`${id} dd`);
    if (dd) dd.innerHTML = html;
  }

  function openPanel(node) {
    const payload = state.payload;
    if (!payload || !node) return;
    qs('#pgPanelEmpty').hidden = true;
    const body = qs('#pgPanelBody');
    body.hidden = false;

    const kicker = qs('#pgNodeId');
    kicker.textContent = node.id;
    kicker.style.setProperty('--node-color', nodeColor(node));
    qs('#pgNodeTitle').textContent = node.title || node.id;

    const crumbs = qs('#pgCrumbs');
    const lineage = lineagePath(node.id, payload.nodes || []);
    crumbs.innerHTML = lineage.length > 1
      ? lineage.map((n, i) => i === lineage.length - 1
        ? `<span class="pg-crumb-current">${esc(truncate(n.title || n.id, 24))}</span>`
        : `<button type="button" class="pg-crumb" data-node-id="${esc(n.id)}">${esc(truncate(n.title || n.id, 24))}</button>`)
        .join('<span class="pg-crumb-sep" aria-hidden="true">›</span>')
      : '';
    crumbs.querySelectorAll('.pg-crumb').forEach(btn => btn.addEventListener('click', () => applySelection(btn.dataset.nodeId)));

    fillMeta('#pgNodeType', esc(typeSentence(node)));
    if (node.parent) {
      const parentNode = (payload.nodes || []).find(n => n.id === node.parent);
      fillMeta('#pgNodeParent', parentNode
        ? `<button type="button" data-node-id="${esc(node.parent)}" title="${esc(node.parent)}">${esc(parentNode.title || node.parent)}</button>`
        : esc(node.parent));
      qs('#pgNodeParent dd button')?.addEventListener('click', event => applySelection(event.currentTarget.dataset.nodeId));
    } else {
      fillMeta('#pgNodeParent', '— (policy root)');
    }
    fillMeta('#pgNodeOwner', esc(ownerSentence(node, payload)));
    fillMeta('#pgNodeStatus', statusSentence(node));
    fillMeta('#pgNodeChange', esc(changeSentence(node, payload, null)));

    qs('#pgNodeHealth').innerHTML = '<p class="pg-muted">Loading history…</p>';
    qs('#pgNodeMarkdown').innerHTML = renderMarkdown(node.body, node);
    qs('#pgNodeMarkdown').querySelectorAll('a[data-pg-node]').forEach(a => {
      a.addEventListener('click', event => { event.preventDefault(); applySelection(a.dataset.pgNode); });
    });

    const details = qs('#pgNodeDiff');
    details.hidden = !(node.change && node.change !== 'same' && payload.previous_version !== null && payload.previous_version !== undefined);
    details.open = false;
    details.querySelector('summary').textContent = payload.previous_version !== null && payload.previous_version !== undefined
      ? `What changed vs v${payload.previous_version}` : 'What changed';
    qs('#pgNodeDiffView').innerHTML = '';

    qs('#pgNodeOverlaps').innerHTML = '';
    renderNodeLinks(node, payload);

    const filesBase = payload.links?.files || '';
    const fileUrl = `${API}/file?agent=${encodeURIComponent(payload.agent_type)}&version=${encodeURIComponent(payload.version)}&id=${encodeURIComponent(node.id)}`;
    qs('#pgNodeFile').innerHTML = node.owner === 'proposal'
      ? 'Not a file yet — it becomes one when the proposal is applied.'
      : `Source file: <a href="${esc(fileUrl)}" target="_blank" rel="noopener"><code>${esc(`${filesBase}${node.id}.md`)}</code></a>`;

    renderNodeProposal(node);
    loadNodeDetail(node);
  }

  function renderNodeLinks(node, payload) {
    const box = qs('#pgNodeLinks');
    const edges = (payload.edges || []).filter(e => !e.synthetic && edgeType(e) !== 'subtype_of');
    const byId = new Map((payload.nodes || []).map(n => [n.id, n]));
    const outgoing = edges.filter(e => edgeSource(e) === node.id);
    const incoming = edges.filter(e => edgeTarget(e) === node.id);
    if (!outgoing.length && !incoming.length) { box.innerHTML = ''; return; }
    const chip = (edge, otherId) => {
      const other = byId.get(otherId);
      const kind = EDGE_KIND_LABEL[edgeType(edge)] || edgeType(edge);
      return `<button type="button" class="pg-link-chip" data-node-id="${esc(otherId)}" title="${esc(`${kind}${edge.via ? ` via ${edge.via}` : ''} · ${otherId}`)}"><span class="pg-link-kind">${esc(kind)}</span>${esc(truncate(other?.title || otherId, 30))}</button>`;
    };
    box.innerHTML = `${outgoing.length ? `<h4>Links out</h4><div class="pg-link-chips">${outgoing.map(e => chip(e, edgeTarget(e))).join('')}</div>` : ''}
      ${incoming.length ? `<h4>Links in</h4><div class="pg-link-chips">${incoming.map(e => chip(e, edgeSource(e))).join('')}</div>` : ''}`;
    box.querySelectorAll('.pg-link-chip').forEach(btn => btn.addEventListener('click', () => {
      if (!pgOpenNode(btn.dataset.nodeId)) toast(`${btn.dataset.nodeId} is not shown in this view`, 'info');
    }));
  }

  async function loadNodeDetail(node) {
    const payload = state.payload;
    if (node.owner === 'proposal') {
      qs('#pgNodeHealth').innerHTML = `<p class="pg-muted">Proposed guideline — not in policy v${esc(payload.version)} yet. Approve it in Proposed changes to ship it.</p>`;
      return;
    }
    const key = `${payload.agent_type}@${payload.version}#${node.id}`;
    let detail = state.nodeCache.get(key);
    if (!detail) {
      try {
        detail = await apiGet(`${API}/node?agent=${encodeURIComponent(payload.agent_type)}&version=${encodeURIComponent(payload.version)}&id=${encodeURIComponent(node.id)}`);
        state.nodeCache.set(key, detail);
      } catch (error) {
        if (state.selected !== node.id) return;
        qs('#pgNodeHealth').innerHTML = `<p class="pg-muted">History unavailable: ${esc(error.message)}</p>`;
        return;
      }
    }
    if (state.selected !== node.id || state.payload !== payload) return;
    renderHealth(node, detail, payload);
    fillMeta('#pgNodeChange', esc(changeSentence(node, payload, detail)));
    const details = qs('#pgNodeDiff');
    if (Array.isArray(detail.diff_vs_previous) && detail.diff_vs_previous.length && node.change !== 'same') {
      details.hidden = false;
      renderDiff(detail.diff_vs_previous, qs('#pgNodeDiffView'));
    } else if (!details.hidden) {
      renderDiff([], qs('#pgNodeDiffView'));
    }
    const overlaps = Array.isArray(detail.overlaps) ? detail.overlaps : [];
    const box = qs('#pgNodeOverlaps');
    if (overlaps.length) {
      box.innerHTML = `<h4>Also appears in</h4><div class="pg-link-chips">${overlaps.map(o =>
        `<button type="button" class="pg-link-chip" data-node-id="${esc(o.id)}" title="${esc(`${o.id} · ${Math.round(Number(o.confidence || 0) * 100)} % similar`)}">${esc(truncate(o.title || o.id, 30))} <span class="pg-link-kind">${Math.round(Number(o.confidence || 0) * 100)} %</span></button>`).join('')}</div>`;
      box.querySelectorAll('.pg-link-chip').forEach(btn => btn.addEventListener('click', () => {
        if (!pgOpenNode(btn.dataset.nodeId)) toast(`${btn.dataset.nodeId} is hidden in the "stored guidelines only" view`, 'info');
      }));
    } else {
      box.innerHTML = '';
    }
  }

  function renderHealth(node, detail, payload) {
    const box = qs('#pgNodeHealth');
    const total = state.versions.length;
    const bits = [];
    if (Number.isFinite(Number(detail.first_seen))) bits.push(`In policy since v${detail.first_seen}`);
    if (Number.isFinite(Number(detail.present_in))) bits.push(`present in ${detail.present_in} of ${total} versions`);
    if (Array.isArray(detail.changed_in) && detail.changed_in.length) bits.push(`changed in ${detail.changed_in.map(v => `v${v}`).join(', ')}`);
    const history = Array.isArray(detail.history) ? detail.history : [];
    const rows = history.map(h => {
      const entry = versionEntry(h.version);
      const o = entry?.outcome || (Number(h.version) === Number(payload.version) ? detail.version_outcome : null);
      return { version: h.version, change: h.change, outcome: o };
    }).filter(r => r.outcome && r.outcome.n_closed !== undefined);
    let table = '';
    if (rows.length) {
      table = `<table><thead><tr><th>version</th><th>trades closed</th><th>win rate</th><th>Δ vs prior</th></tr></thead><tbody>${rows.map(r => {
        const o = r.outcome;
        const delta = o.winrate_delta !== null && o.winrate_delta !== undefined ? `${Number(o.winrate_delta) >= 0 ? '+' : '−'}${Math.abs(Math.round(Number(o.winrate_delta) * 100))} pts` : '—';
        return `<tr><td>v${esc(r.version)}${r.change && r.change !== 'same' ? ` <span class="pg-muted">(${esc(r.change)})</span>` : ''}</td><td>${esc(o.n_closed ?? 0)}</td><td>${esc(o.measurable ? pct(o.win_rate) : `— (${o.n_closed ?? 0} < 5)`)}</td><td>${esc(o.measurable ? delta : '—')}</td></tr>`;
      }).join('')}</tbody><caption>version-level signal, not per-guideline</caption></table>`;
    } else if (payload.agent_type !== 'DeciderAgent') {
      table = '<p class="pg-muted">No direct trade attribution for this agent.</p>';
    }
    const c = detail.citations && !detail.citations.error ? detail.citations : null;
    let cites = '';
    if (c && (c.decisions || c.closed)) {
      const acts = Object.entries(c.by_action || {}).map(([a, n]) => `${n} ${a}`).join(', ');
      const wr = c.win_rate !== null && c.win_rate !== undefined ? pct(c.win_rate) : '—';
      const pnl = Number.isFinite(Number(c.pnl)) ? `${Number(c.pnl) >= 0 ? '+' : '−'}$${Math.abs(Number(c.pnl)).toFixed(0)}` : '—';
      const avg = c.avg_gain_pct !== null && c.avg_gain_pct !== undefined ? `${Number(c.avg_gain_pct) >= 0 ? '+' : ''}${Number(c.avg_gain_pct).toFixed(2)}%` : '—';
      const recent = (c.recent_closed || []).slice(0, 5).map(r => `${r.ticker} ${Number(r.gain_pct) >= 0 ? '+' : ''}${Number(r.gain_pct).toFixed(1)}%`).join(' · ');
      cites = `<div class="pg-cites"><strong>Cited by ${plural(c.decisions, 'decision')}</strong>${acts ? ` (${esc(acts)})` : ''} · ${plural(c.closed, 'closed trade')}${c.closed ? ` · win rate ${esc(wr)} (${c.wins}W/${c.losses}L) · avg ${esc(avg)} · P&amp;L ${esc(pnl)}` : ''}${recent ? `<div class="pg-muted">${esc(recent)}</div>` : ''}</div>`;
    }
    const note = !cites && detail.attribution_note ? `<p class="pg-muted">${esc(detail.attribution_note)}</p>` : '';
    box.innerHTML = `<h4>History &amp; health</h4>${bits.length ? `<div>${esc(bits.join(' · '))}</div>` : '<div class="pg-muted">No history recorded for this guideline.</div>'}${cites}${table}${note}`;
  }

  // ------------------------------------------------------------------ markdown (★ extended)
  function resolveLink(target, node) {
    const payload = state.payload;
    if (!payload) return null;
    const ids = new Set((payload.nodes || []).map(n => n.id));
    const raw = String(target || '').trim();
    if (!raw) return null;
    if (node && node.links && typeof node.links === 'object' && !Array.isArray(node.links)) {
      const mapped = node.links[raw] || node.links[raw.toLowerCase()];
      if (mapped && ids.has(mapped)) return mapped;
    }
    if (ids.has(raw)) return raw;
    const prefix = payload.prefix || rootId().split('.')[0];
    const slug = raw.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
    if (ids.has(`${prefix}.${slug}`)) return `${prefix}.${slug}`;
    const bySuffix = (payload.nodes || []).filter(n => String(n.id).endsWith(`.${slug}`) || String(n.id).endsWith(`.${slug.replace(/_/g, '')}`));
    if (bySuffix.length === 1) return bySuffix[0].id;
    return null;
  }

  function inlineMarkdown(text, node) {
    let html = esc(text);
    const codes = [];
    html = html.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    html = html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, target, alias) => {
      const resolved = resolveLink(target, node);
      const label = alias || target;
      return resolved
        ? `<a data-pg-node="${esc(resolved)}" href="#" title="${esc(resolved)}">${label}</a>`
        : `<code>${label}</code>`;
    });
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(^|[^*\w])\*([^*\n]+)\*(?![\w*])/g, '$1<em>$2</em>');
    html = html.replace(/(^|[\s(>])#([A-Za-z][\w-]*)/g, '$1<span class="pg-tag">#$2</span>');
    if (node && node.owner === 'code') {
      html = html.replace(/\{([a-z_][a-z0-9_]*)\}/g, '<span class="pg-placeholder" title="filled at runtime">{$1}</span>');
    }
    html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[Number(i)]}</code>`);
    return html;
  }

  function renderMarkdown(markdown, node) {
    const text = String(markdown ?? '');
    if (!text.trim()) return '<p class="pg-muted">This guideline has no text of its own — it groups the guidelines below it.</p>';
    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    const listStack = []; // [{type, indent}]
    let i = 0;

    const closeLists = (toIndent = -1) => {
      while (listStack.length && listStack[listStack.length - 1].indent > toIndent) {
        html.push(`</li></${listStack.pop().type}>`);
      }
    };
    const closeAll = () => closeLists(-1);

    // Leading YAML block → <pre>
    if (lines[0] === '---') {
      const end = lines.findIndex((l, idx) => idx > 0 && l === '---');
      if (end > 0) {
        html.push(`<pre class="pg-yaml"><code>${esc(lines.slice(0, end + 1).join('\n'))}</code></pre>`);
        i = end + 1;
      }
    }

    for (; i < lines.length; i += 1) {
      const line = lines[i];
      const trimmed = line.trim();

      if (trimmed.startsWith('<!--')) {
        closeAll();
        const buf = [line];
        while (!buf[buf.length - 1].includes('-->') && i + 1 < lines.length) { i += 1; buf.push(lines[i]); }
        html.push(`<div class="pg-comment">${esc(buf.join('\n').replace(/^\s*<!--\s?/, '').replace(/\s?-->\s*$/, ''))}</div>`);
        continue;
      }
      if (/^```/.test(trimmed)) {
        closeAll();
        const buf = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i].trim())) { buf.push(lines[i]); i += 1; }
        html.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
        continue;
      }
      if (!trimmed) { closeAll(); continue; }
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { closeAll(); html.push('<hr />'); continue; }

      const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
      if (heading) {
        closeAll();
        const level = Math.min(6, heading[1].length + 2);
        html.push(`<h${level}>${inlineMarkdown(heading[2], node)}</h${level}>`);
        continue;
      }
      if (trimmed.startsWith('>')) {
        closeAll();
        const buf = [trimmed.replace(/^>\s?/, '')];
        while (i + 1 < lines.length && lines[i + 1].trim().startsWith('>')) { i += 1; buf.push(lines[i].trim().replace(/^>\s?/, '')); }
        html.push(`<blockquote>${buf.map(b => `<p>${inlineMarkdown(b, node)}</p>`).join('')}</blockquote>`);
        continue;
      }
      const item = /^(\s*)([-*+]|\d+[.)])\s+(.+)$/.exec(line.replace(/\t/g, '    '));
      if (item) {
        const indent = item[1].length;
        const type = /^\d/.test(item[2]) ? 'ol' : 'ul';
        const top = listStack[listStack.length - 1];
        if (!top || indent > top.indent) {
          const startAttr = type === 'ol' ? ` start="${parseInt(item[2], 10)}"` : '';
          html.push(`<${type}${startAttr}><li>`);
          listStack.push({ type, indent });
        } else {
          closeLists(indent);
          const cur = listStack[listStack.length - 1];
          if (cur && cur.type === type) {
            html.push('</li><li>');
          } else {
            if (cur) { html.push(`</li></${listStack.pop().type}>`); }
            const startAttr = type === 'ol' ? ` start="${parseInt(item[2], 10)}"` : '';
            html.push(`<${type}${startAttr}><li>`);
            listStack.push({ type, indent });
          }
        }
        html.push(inlineMarkdown(item[3], node));
        continue;
      }
      if (listStack.length && /^\s{2,}/.test(line)) {
        // continuation line inside a list item
        html.push(` ${inlineMarkdown(trimmed, node)}`);
        continue;
      }
      closeAll();
      html.push(`<p>${inlineMarkdown(trimmed, node)}</p>`);
    }
    closeAll();
    return html.join('') || '<p class="pg-muted">No text.</p>';
  }

  // Copy of prompt-evolution.js renderDiff — that file's globals are not shared with this page.
  function renderDiff(lines, container) {
    if (!container) return;

    container.innerHTML = '';

    if (!Array.isArray(lines) || lines.length === 0) {
      const empty = document.createElement('span');
      empty.className = 'pe-diff-line';
      empty.textContent = 'No diff output available.';
      container.appendChild(empty);
      return;
    }

    lines.forEach((line) => {
      const row = document.createElement('span');
      row.className = 'pe-diff-line';

      if (line.startsWith('@@')) {
        row.classList.add('hunk');
      } else if (line.startsWith('+')) {
        row.classList.add('add');
      } else if (line.startsWith('-')) {
        row.classList.add('remove');
      }

      row.textContent = line;
      container.appendChild(row);
    });
  }

  // ------------------------------------------------------------------ change list card
  function renderChangeAgainstOptions() {
    const select = qs('#pgDiffAgainst');
    if (!select) return;
    const older = versionNumbers().filter(v => v < Number(state.version));
    const prev = state.payload?.previous_version;
    const preferred = state.diffAgainst !== null && older.includes(Number(state.diffAgainst)) ? Number(state.diffAgainst)
      : (prev !== null && prev !== undefined ? Number(prev) : (older.length ? older[older.length - 1] : null));
    if (!older.length) {
      select.innerHTML = '<option value="">nothing older</option>';
      select.disabled = true;
      state.diffAgainst = null;
      return;
    }
    select.disabled = false;
    select.innerHTML = older.slice().reverse().map(v => `<option value="${v}"${v === preferred ? ' selected' : ''}>v${v}${v === Number(prev) ? ' (previous)' : ''}</option>`).join('');
    state.diffAgainst = preferred;
  }

  async function loadChangeList(against) {
    const list = qs('#pgChangeList');
    const title = qs('#pgChangeTitle');
    if (!list || !state.payload) return;
    const to = Number(state.version);
    if (against === null || against === undefined || !Number.isFinite(Number(against))) {
      title.textContent = 'What changed';
      list.innerHTML = '<li class="pg-change-empty">This is the first policy version — nothing to compare with.</li>';
      return;
    }
    const from = Number(against);
    title.textContent = `What changed vs v${from}`;
    list.innerHTML = '<li class="pg-change-empty"><span class="pe-loading"><span class="pe-spinner" aria-hidden="true"></span><span>Comparing…</span></span></li>';
    const seq = state.graphSeq;
    let data;
    try {
      data = await apiGet(`${API}/diff?agent=${encodeURIComponent(state.agent)}&from=${from}&to=${to}`);
    } catch (error) {
      if (seq !== state.graphSeq) return;
      list.innerHTML = `<li class="pg-change-empty">Could not compare: ${esc(error.message)}</li>`;
      return;
    }
    if (seq !== state.graphSeq || Number(state.version) !== to) return;
    renderChangeList(data);
  }

  function renderChangeList(data) {
    const list = qs('#pgChangeList');
    const rows = (Array.isArray(data.nodes) ? data.nodes : []).filter(n => n.change && n.change !== 'same');
    state.similarity = new Map(rows.filter(r => r.change === 'renamed').map(r => [r.id, r.similarity]));
    const order = { added: 0, changed: 1, renamed: 2, source_changed: 3, removed: 4, whitespace: 5 };
    rows.sort((a, b) => (order[a.change] ?? 9) - (order[b.change] ?? 9) || String(a.id).localeCompare(String(b.id)));
    if (!rows.length) {
      list.innerHTML = '<li class="pg-change-empty">No guideline changed in this version.</li>';
      return;
    }
    const summary = data.summary || {};
    const fieldsChanged = Object.entries(data.fields || {}).filter(([, v]) => v && v.changed).map(([f]) => FIELD_LABEL[f] || f);
    list.innerHTML = `<li class="pg-change-empty">+${Number(summary.added || 0)} added · ${Number(summary.changed || 0)} changed · ${Number(summary.removed || 0)} removed · ${Number(summary.renamed || 0)} renamed${fieldsChanged.length ? ` · fields: ${esc(fieldsChanged.join(', '))}` : ''}</li>` +
      rows.map((r, idx) => {
        const stats = r.stats || {};
        const kindLabel = r.change === 'source_changed' ? 'source changed' : r.change;
        const canOpen = r.change !== 'removed' && state.payload?.nodes?.some(n => n.id === r.id);
        return `<li><details data-idx="${idx}">
          <summary>
            <span class="pg-change-kind ${esc(r.change)}">${esc(kindLabel)}</span>
            <span class="pg-change-id">${esc(r.id)}${r.renamed_from ? ` <span class="pg-muted">← ${esc(r.renamed_from)}${Number.isFinite(Number(r.similarity)) ? ` (${Math.round(Number(r.similarity) * 100)}%)` : ''}</span>` : ''}</span>
            <span class="pg-change-title">${esc(r.title || '')}${r.field ? ` <span class="pg-muted">· ${esc(FIELD_LABEL[r.field] || r.field)}</span>` : ''}</span>
            <span class="pg-change-stats"><span class="add">+${Number(stats.added || 0)}</span> <span class="rem">−${Number(stats.removed || 0)}</span></span>
            ${canOpen ? `<button type="button" class="pg-change-open" data-node-id="${esc(r.id)}">Open</button>` : ''}
          </summary>
          <div class="pe-diff-view" data-diff-idx="${idx}"></div>
        </details></li>`;
      }).join('');
    list.querySelectorAll('details').forEach(det => {
      det.addEventListener('toggle', () => {
        if (!det.open) return;
        const idx = Number(det.dataset.idx);
        const view_ = det.querySelector('.pe-diff-view');
        if (view_ && !view_.dataset.rendered) {
          renderDiff(rows[idx].diff || [], view_);
          view_.dataset.rendered = 'true';
        }
      });
    });
    list.querySelectorAll('.pg-change-open').forEach(btn => btn.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      pgOpenNode(btn.dataset.nodeId);
    }));
  }

  // ------------------------------------------------------------------ public: open a node
  function pgOpenNode(id) {
    const nodeId = String(id || '');
    if (!nodeId || !state.payload) return false;
    if (!(state.payload.nodes || []).some(n => n.id === nodeId)) return false;
    applySelection(nodeId);
    qs('#pgGraphCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return true;
  }
  window.pgOpenNode = pgOpenNode;

  // ------------------------------------------------------------------ proposals (the loop edits the graph)
  const PROPOSAL_STATUS_LABEL = {
    drafting: 'drafting',
    critiquing: 'critic reviewing',
    review: 'awaiting your review',
    applied: 'applied',
    rejected: 'rejected',
    failed: 'failed'
  };
  const ACTION_LABEL = { edit: 'edit', add: 'new guideline', remove: 'remove' };

  function proposalsInReview() {
    return (state.proposals || []).filter(p => p.status === 'review');
  }

  function proposalTargets(p) {
    const targets = new Set([Number(p.base_version)]);
    if (p.applies_to && p.applies_to.ok && Number.isFinite(Number(p.applies_to.target_version))) targets.add(Number(p.applies_to.target_version));
    return targets;
  }

  // Ghost nodes: proposed additions appear as dotted nodes; edited / removed guidelines are marked.
  function decorateWithProposals(payload) {
    if (!payload || !Array.isArray(payload.nodes)) return;
    payload.nodes = payload.nodes.filter(n => n.owner !== 'proposal');
    payload.edges = (payload.edges || []).filter(e => !e.proposed);
    payload.nodes.forEach(n => { delete n.ghost; delete n.proposal_id; delete n.proposed_body; });
    const version = Number(payload.version);
    proposalsInReview().forEach(p => {
      if (!proposalTargets(p).has(version)) return;
      (p.files || []).forEach(f => {
        if (f.action === 'add') {
          const parent = payload.nodes.find(n => n.id === f.parent);
          if (!parent) return;
          payload.nodes.push({
            id: f.id, title: f.title || f.id, node_type: 'proposed', polarity: 'action', polarity_source: 'derived',
            parent: f.parent, field: f.field, depth: String(f.id).split('.').length - 1, owner: 'proposal', status: 'proposed',
            compiled: 'stored', locked: false, provenance: `proposal#${p.id}`, order: 10000, tags: [], tickers: [], links: {},
            body: f.body || '', sep_before: '', sep_after: '', change: null, has_children: false,
            ghost: 'add', proposal_id: p.id, proposed_body: f.body || ''
          });
          payload.edges.push({ source: f.id, target: f.parent, edge_type: 'subtype_of', provenance: 'proposal', proposed: true, synthetic: false });
        } else {
          const node = payload.nodes.find(n => n.id === f.id || n.id === f.proposed_id);
          if (!node) return;
          node.ghost = f.action === 'remove' ? 'remove' : 'edit';
          node.proposal_id = p.id;
          node.proposed_body = f.body || '';
        }
      });
    });
  }

  function stopProposalPoll() {
    if (state.proposalPoll) { window.clearTimeout(state.proposalPoll); state.proposalPoll = null; }
  }

  async function loadProposals(agent, { quiet = false } = {}) {
    stopProposalPoll();
    if (!agent) return null;
    let data;
    try {
      data = await apiGet(`${API}/proposals?agent=${encodeURIComponent(agent)}`);
    } catch (error) {
      if (!quiet) toast(`Proposals: ${error.message}`, 'error');
      state.proposals = [];
      state.proposalsAgent = agent;
      renderProposals();
      return null;
    }
    if (agent !== state.agent) return data;
    const before = state.proposals || [];
    const busyBefore = before.some(p => p.status === 'drafting' || p.status === 'critiquing');
    state.proposals = Array.isArray(data.proposals) ? data.proposals : [];
    state.proposalsAgent = agent;
    renderProposals();
    const busyNow = state.proposals.some(p => p.status === 'drafting' || p.status === 'critiquing');
    if (busyNow) {
      state.proposalPoll = window.setTimeout(() => loadProposals(agent, { quiet: true }), 3000);
    } else if (busyBefore) {
      const done = state.proposals.find(p => !before.some(b => b.id === p.id && b.status === p.status));
      if (done && done.status === 'review') toast(`Proposal #${done.id} is ready for your review`, 'success');
      else if (done && done.status === 'failed') toast(`Proposal #${done.id} failed: ${done.error || 'unknown error'}`, 'error');
      if (state.payload) loadGraph(state.agent, state.version, { keepSelection: true });
    }
    return data;
  }

  function fileBadge(text, cls) { return `<span class="pg-badge ${esc(cls)}">${esc(text)}</span>`; }

  function fileCardHtml(p, f) {
    const critic = f.critic || null;
    const interactive = p.status === 'review';
    const checked = interactive ? (f.primary || !(critic && critic.verdict === 'reject')) : (p.status === 'applied' ? (p.human?.approved || []).includes(f.id) : false);
    const badges = [
      f.primary ? fileBadge('primary', 'primary') : '',
      fileBadge(ACTION_LABEL[f.action] || f.action, f.action),
      f.kind ? fileBadge(f.kind === 'major' ? 'changes behavior' : 'wording', f.kind) : '',
      f.field ? `<span class="pg-muted">${esc(FIELD_LABEL[f.field] || f.field)}</span>` : ''
    ].filter(Boolean).join('');
    const stats = f.diff_stats ? `<span class="pg-change-stats"><span class="add">+${Number(f.diff_stats.added || 0)}</span> <span class="rem">−${Number(f.diff_stats.removed || 0)}</span></span>` : '';
    const title = f.action === 'add' ? (f.title || f.id) : (f.old_title || f.title || f.id);
    const idLabel = f.action === 'add' ? `${f.id} (new)` : f.id;
    const grid = [
      ['What', f.what], ['Why', f.why], ['Expected effect', f.expected_effect], ['Falsified if', f.falsified_if]
    ].filter(([, v]) => v).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
    const criticLine = critic
      ? `<p class="pg-file-critic">${fileBadge(critic.verdict === 'approve' ? 'critic ✓' : 'critic ✗', critic.verdict === 'approve' ? 'critic-ok' : 'critic-bad')} ${esc(critic.reason || '')}</p>`
      : '';
    const control = interactive
      ? `<label><input type="checkbox" class="pg-file-approve" data-file-id="${esc(f.id)}"${checked ? ' checked' : ''}${f.primary ? ' disabled' : ''} /> ${esc(title)}</label>${f.primary ? '<span class="pg-muted">(the primary change ships or the proposal is rejected)</span>' : ''}`
      : `<span class="${checked ? '' : 'pg-muted'}"><strong>${esc(title)}</strong>${p.status === 'applied' && !checked ? ' (not shipped)' : ''}</span>`;
    return `<div class="pg-file-card${interactive && !checked ? ' is-off' : ''}" data-file-id="${esc(f.id)}">
        <div class="pg-file-head">${control}<button type="button" class="pg-file-id" data-node-id="${esc(f.action === 'add' ? f.id : (f.proposed_id || f.id))}" title="Show on the graph">${esc(idLabel)}</button>${badges}${stats}</div>
        ${grid ? `<dl class="pg-file-grid">${grid}</dl>` : ''}
        ${criticLine}
        ${Array.isArray(f.diff) && f.diff.length ? `<details class="pg-file-diff"${f.primary && interactive ? ' open' : ''}><summary>${f.action === 'add' ? 'Proposed text' : f.action === 'remove' ? 'Text to remove' : 'What would change'}</summary><div class="pe-diff-view"></div></details>` : ''}
      </div>`;
  }

  function proposalCardHtml(p) {
    const status = String(p.status || '');
    const busy = status === 'drafting' || status === 'critiquing';
    const classes = ['pg-proposal', `pg-proposal--${status}`];
    if (busy) classes.push('pg-proposal--busy');
    const title = [`<strong>Proposal #${esc(p.id)}</strong>`, `<span class="pg-proposal-status ${esc(status)}">${esc(PROPOSAL_STATUS_LABEL[status] || status)}</span>`,
      `drafted ${esc(fmtPT(p.created_at))}`, `against v${esc(p.base_version)}`];
    if (p.model) title.push(`model ${esc(p.model)}`);
    if (p.focus) title.push(`focus: “${esc(p.focus)}”`);
    if (p.result_version !== null && p.result_version !== undefined) title.push(`<button type="button" class="pg-link-chip pg-proposal-version" data-version="${esc(p.result_version)}">became v${esc(p.result_version)}</button>`);
    let critic = '';
    if (p.critic) {
      const ok = p.critic.verdict === 'approve';
      const conf = Number.isFinite(Number(p.critic.confidence)) ? ` ${Number(p.critic.confidence).toFixed(2)}` : '';
      const gates = Array.isArray(p.critic.unexecutable_gates) && p.critic.unexecutable_gates.length ? ` Unexecutable gates: ${p.critic.unexecutable_gates.join('; ')}.` : '';
      const ship = p.critic.ship_first ? ` Ship first: ${p.critic.ship_first}.` : '';
      critic = `<p class="pg-proposal-critic"><span class="${ok ? 'ok' : 'bad'}">Critic ${ok ? '✓ approve' : '✗ reject'}${conf}${p.critic.auto ? ' (automatic)' : ''}</span> — ${esc(p.critic.reason || '')}${esc(ship)}${esc(gates)}</p>`;
    }
    const human = p.human && (status === 'applied' || status === 'rejected')
      ? `<p class="pg-proposal-critic">You ${status === 'applied' ? (p.human.verdict === 'partial' ? 'shipped part of it' : 'shipped it') : 'rejected it'}${p.human.reason ? ` — ${esc(p.human.reason)}` : ''}${p.human_at ? ` · ${esc(fmtPT(p.human_at))}` : ''}</p>`
      : '';
    const busyLine = busy ? `<p class="pg-proposal-critic"><span class="pe-loading"></span> ${status === 'drafting' ? 'The drafter is reading the guideline files, the diagnostics and the trade evidence…' : 'The critic is judging each guideline file…'}</p>` : '';
    const error = status === 'failed' ? `<p class="pg-proposal-error">${esc(p.error || 'unknown error')}</p>` : '';
    const reasoning = p.reasoning ? `<p class="pg-proposal-reasoning">${esc(p.reasoning)}</p>` : '';
    const files = (p.files || []).length ? `<div class="pg-proposal-files">${(p.files || []).map(f => fileCardHtml(p, f)).join('')}</div>` : '';
    let actions = '';
    if (status === 'review') {
      const applies = p.applies_to || {};
      const target = Number.isFinite(Number(applies.target_version)) ? Number(applies.target_version) : Number(p.base_version);
      const note = applies.ok === false
        ? `<p class="pg-muted">Cannot apply: ${esc(applies.reason || 'the active version moved')}</p>`
        : `<p class="pg-muted">${applies.reason ? esc(applies.reason) + ' · ' : ''}Approved files compile into v${target + 1} and activate immediately; the trader picks it up on its next cycle.</p>`;
      actions = `<div class="pg-proposal-actions">${note}
          <button type="button" class="pe-btn pg-btn-small pg-proposal-apply" data-proposal-id="${esc(p.id)}"${applies.ok === false ? ' disabled' : ''}>Apply approved guidelines → v${target + 1}</button>
          <button type="button" class="pe-btn secondary pg-btn-small pg-proposal-reject" data-proposal-id="${esc(p.id)}">Reject proposal</button>
        </div>`;
    } else if (status === 'failed') {
      actions = `<div class="pg-proposal-actions"><button type="button" class="pe-btn secondary pg-btn-small pg-proposal-reject" data-proposal-id="${esc(p.id)}" data-reason="failed">Discard</button></div>`;
    }
    return `<article class="${classes.join(' ')}" data-proposal-id="${esc(p.id)}">
        <div class="pg-proposal-title">${title.join('<span class="pg-sep">·</span>')}</div>
        ${busyLine}${error}${reasoning}${critic}${human}${files}${actions}
      </article>`;
  }

  function renderProposals() {
    const box = qs('#pgProposalList');
    const form = qs('#pgProposeForm');
    if (!box) return;
    const list = state.proposals || [];
    const busy = list.some(p => p.status === 'drafting' || p.status === 'critiquing');
    const button = qs('#pgPropose');
    if (button) {
      button.disabled = busy;
      button.textContent = busy ? 'Drafting…' : `Propose a change to ${agentMeta(state.agent).label} v${state.current ?? '?'}`;
    }
    if (form) form.hidden = false;
    const open = list.filter(p => p.status === 'review' || p.status === 'drafting' || p.status === 'critiquing' || p.status === 'failed');
    const history = list.filter(p => !open.includes(p));
    const historyHtml = history.length
      ? `<details class="pg-proposal-history"><summary>${history.length === 1 ? '1 earlier proposal' : `${history.length} earlier proposals`}</summary><ul>${history.map(p => {
        const primary = (p.files || []).find(f => f.primary) || (p.files || [])[0] || {};
        const c = p.critic ? `<span class="${p.critic.verdict === 'approve' ? 'ok' : 'bad'}">critic ${p.critic.verdict === 'approve' ? '✓' : '✗'}</span>` : '';
        const v = p.result_version !== null && p.result_version !== undefined ? `<button type="button" class="pg-link-chip pg-proposal-version" data-version="${esc(p.result_version)}">v${esc(p.result_version)}</button>` : '';
        return `<li><strong>#${esc(p.id)}</strong><span class="pg-proposal-status ${esc(p.status)}">${esc(PROPOSAL_STATUS_LABEL[p.status] || p.status)}</span><span>${esc(fmtShortDate(p.created_at))}</span><span>${esc(primary.what || primary.id || '')}</span>${c}${v}<button type="button" class="pg-link-chip pg-proposal-open" data-proposal-id="${esc(p.id)}">details</button></li>`;
      }).join('')}</ul></details>`
      : '';
    box.innerHTML = open.map(proposalCardHtml).join('') + historyHtml;

    box.querySelectorAll('.pg-file-card').forEach(card => {
      const details = card.querySelector('.pg-file-diff .pe-diff-view');
      if (!details) return;
      const pid = Number(card.closest('.pg-proposal')?.dataset.proposalId);
      const p = list.find(x => Number(x.id) === pid);
      const f = (p?.files || []).find(x => x.id === card.dataset.fileId);
      if (f) renderDiff(f.diff, details);
    });
    box.querySelectorAll('.pg-file-approve').forEach(input => input.addEventListener('change', () => {
      input.closest('.pg-file-card')?.classList.toggle('is-off', !input.checked);
      const article = input.closest('.pg-proposal');
      const count = article ? article.querySelectorAll('.pg-file-approve:checked').length : 0;
      const total = article ? article.querySelectorAll('.pg-file-approve').length : 0;
      const btn = article?.querySelector('.pg-proposal-apply');
      if (btn && total) btn.textContent = btn.textContent.replace(/^Apply (approved|\d+ of \d+) guidelines?/, count === total ? 'Apply approved guidelines' : `Apply ${count} of ${total} guidelines`);
    }));
    box.querySelectorAll('.pg-file-id').forEach(btn => btn.addEventListener('click', () => {
      if (!pgOpenNode(btn.dataset.nodeId)) toast(`${btn.dataset.nodeId} is not on the graph for v${state.version}`, 'info');
    }));
    box.querySelectorAll('.pg-proposal-apply').forEach(btn => btn.addEventListener('click', () => applyProposal(Number(btn.dataset.proposalId))));
    box.querySelectorAll('.pg-proposal-reject').forEach(btn => btn.addEventListener('click', () => rejectProposal(Number(btn.dataset.proposalId), btn.dataset.reason)));
    box.querySelectorAll('.pg-proposal-version').forEach(btn => btn.addEventListener('click', () => {
      const select = qs('#pgVersion');
      if (!select) return;
      select.value = String(btn.dataset.version);
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }));
    box.querySelectorAll('.pg-proposal-open').forEach(btn => btn.addEventListener('click', () => {
      const p = list.find(x => Number(x.id) === Number(btn.dataset.proposalId));
      if (!p) return;
      const holder = document.createElement('div');
      holder.innerHTML = proposalCardHtml(p);
      const li = btn.closest('li');
      li.replaceWith(holder.firstElementChild);
      holder.firstElementChild?.querySelectorAll('.pg-file-card').forEach(card => {
        const f = (p.files || []).find(x => x.id === card.dataset.fileId);
        const view = card.querySelector('.pe-diff-view');
        if (f && view) renderDiff(f.diff, view);
      });
    }));
  }

  async function proposeChange(event) {
    if (event) event.preventDefault();
    if (!state.agent) return;
    const input = qs('#pgProposeFocus');
    const focus = input ? input.value.trim() : '';
    const button = qs('#pgPropose');
    if (button) { button.disabled = true; button.textContent = 'Drafting…'; }
    try {
      const res = await fetchJSON(`${API}/proposals`, { method: 'POST', body: JSON.stringify({ agent_type: state.agent, focus }) });
      toast(`Drafting proposal #${res.id} against v${res.base_version} — usually one to two minutes`, 'info');
      if (input) input.value = '';
      await loadProposals(state.agent, { quiet: true });
    } catch (error) {
      toast(`Could not start a proposal: ${error.message}`, 'error');
      renderProposals();
    }
  }

  async function applyProposal(id) {
    const article = document.querySelector(`.pg-proposal[data-proposal-id="${id}"]`);
    if (!article) return;
    const approved = Array.from(article.querySelectorAll('.pg-file-approve')).filter(i => i.checked || i.disabled).map(i => i.dataset.fileId);
    const btn = article.querySelector('.pg-proposal-apply');
    if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
    try {
      const res = await fetchJSON(`${API}/proposals/${id}/apply`, { method: 'POST', body: JSON.stringify({ approved }) });
      toast(`${agentMeta(state.agent).label} policy v${res.version} is now active (${res.approved.length} guideline${res.approved.length === 1 ? '' : 's'} from proposal #${id})`, 'success');
      try { new BroadcastChannel('dai-prompts').postMessage({ type: 'prompt-applied', agent: state.agent, version: res.version }); } catch (_) { /* unsupported */ }
      state.nodeCache.clear();
      await loadAgents();
      await loadVersions(state.agent);
      await loadProposals(state.agent, { quiet: true });
      populateVersions(res.version);
      renderTimeline();
      await loadGraph(state.agent, res.version, { pulse: true });
    } catch (error) {
      toast(`Could not apply proposal #${id}: ${error.message}`, 'error');
      await loadProposals(state.agent, { quiet: true });
    }
  }

  async function rejectProposal(id, presetReason) {
    let reason = presetReason || '';
    if (!presetReason) {
      reason = window.prompt(`Reject proposal #${id}? Optional reason (recorded for the critic's calibration):`, '');
      if (reason === null) return;
    }
    try {
      await fetchJSON(`${API}/proposals/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
      toast(presetReason ? `Proposal #${id} discarded` : `Proposal #${id} rejected`, 'info');
      await loadProposals(state.agent, { quiet: true });
      if (state.payload) await loadGraph(state.agent, state.version, { keepSelection: true });
    } catch (error) {
      toast(`Could not reject proposal #${id}: ${error.message}`, 'error');
    }
  }

  function renderNodeProposal(node) {
    const box = qs('#pgNodeProposal');
    if (!box) return;
    if (!node || !node.ghost) { box.innerHTML = ''; return; }
    const p = (state.proposals || []).find(x => Number(x.id) === Number(node.proposal_id));
    const f = p ? (p.files || []).find(x => x.id === node.id || x.proposed_id === node.id) : null;
    const verb = node.ghost === 'add' ? 'adds this guideline' : node.ghost === 'remove' ? 'removes this guideline' : 'changes this guideline';
    box.innerHTML = `<h4>Proposal #${esc(node.proposal_id)} ${esc(verb)}</h4>
      ${f && f.what ? `<p>${esc(f.what)}</p>` : ''}
      ${f && Array.isArray(f.diff) && f.diff.length ? '<div class="pe-diff-view"></div>' : ''}
      <button type="button" class="pg-link-chip pg-node-proposal-go">Review it in Proposed changes</button>`;
    const view = box.querySelector('.pe-diff-view');
    if (view && f) renderDiff(f.diff, view);
    box.querySelector('.pg-node-proposal-go')?.addEventListener('click', () => {
      const article = document.querySelector(`.pg-proposal[data-proposal-id="${node.proposal_id}"]`);
      if (article && typeof article.scrollIntoView === 'function') article.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  // ------------------------------------------------------------------ agent / version flow
  async function selectAgent(agent, { version = null, node = null, pulse = false } = {}) {
    if (!AGENT_TYPES.has(agent)) agent = AGENTS[0].agent_type;
    state.agent = agent;
    state.selected = null;
    state.pendingNode = node || null;
    state.diffAgainst = null;
    renderAgentSwitch();
    lsSet(LS_AGENT, agent);
    const data = await loadVersions(agent);
    await loadProposals(agent, { quiet: true });
    if (!data) { populateVersions(null); renderTimeline(); return; }
    if (!state.versions.length) {
      populateVersions(null);
      renderTimeline();
      qs('#pgTitle').textContent = `${agentMeta(agent).label} policy`;
      qs('#pgBlurb').textContent = 'No policy versions for this agent yet.';
      setStatus('No policy versions for this agent yet');
      return;
    }
    const numbers = versionNumbers();
    let target = version !== null && numbers.includes(Number(version)) ? Number(version) : null;
    if (target === null && state.current !== null && numbers.includes(Number(state.current))) target = Number(state.current);
    if (target === null) target = numbers[numbers.length - 1];
    state.version = target;
    populateVersions(target);
    renderTimeline();
    await loadGraph(agent, target, { pulse });
  }

  function onVersionChange() {
    const select = qs('#pgVersion');
    if (!select || select.value === '') return;
    const next = Number(select.value);
    if (!Number.isFinite(next)) return;
    const forward = state.version !== null && next > Number(state.version);
    state.diffAgainst = null;
    loadGraph(state.agent, next, { pulse: forward });
  }

  function wireControls() {
    document.querySelectorAll('#pgAgentSwitch .pg-seg').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.agent === state.agent) return;
        const remembered = lsGet(`${LS_VERSION}.${btn.dataset.agent}`);
        selectAgent(btn.dataset.agent, { version: remembered ? Number(remembered) : null });
      });
    });
    qs('#pgVersion')?.addEventListener('change', onVersionChange);
    qs('#pgProposeForm')?.addEventListener('submit', proposeChange);
    setupVersionStepper();
    qs('#pgLayer')?.addEventListener('change', event => {
      state.layer = event.target.value === 'stored' ? 'stored' : 'effective';
      state.nodeCache.clear();
      loadGraph(state.agent, state.version, { keepSelection: true });
    });
    qs('#pgHighlightChanges')?.addEventListener('change', event => {
      state.highlightChanges = Boolean(event.target.checked);
      applyChangeClasses();
    });
    qs('#pgShowRefs')?.addEventListener('change', event => {
      state.showRefs = Boolean(event.target.checked);
      loadGraph(state.agent, state.version, { keepSelection: true });
    });
    qs('#pgFit')?.addEventListener('click', resetZoom);
    document.querySelectorAll('#pgFieldFilter .pg-chip-filter').forEach(btn => {
      btn.addEventListener('click', () => toggleFilter(btn.dataset.filter));
    });
    qs('#pgPanelClear')?.addEventListener('click', () => applySelection(null));
    const kicker = qs('#pgNodeId');
    const copyId = async () => {
      const id = kicker.textContent;
      if (!id) return;
      try {
        await navigator.clipboard.writeText(id);
        toast(`Copied ${id}`, 'success');
      } catch (_) {
        toast('Clipboard unavailable — select the id to copy it', 'warning');
      }
    };
    kicker?.addEventListener('click', copyId);
    kicker?.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); copyId(); } });
    qs('#pgDiffAgainst')?.addEventListener('change', event => {
      state.diffAgainst = event.target.value === '' ? null : Number(event.target.value);
      loadChangeList(state.diffAgainst);
    });
    ['#pgCompiledLink', '#pgRuntimeLink', '#pgBundleLink'].forEach(sel => {
      qs(sel)?.addEventListener('click', event => {
        if (event.currentTarget.getAttribute('aria-disabled') === 'true') event.preventDefault();
      });
    });

    window.addEventListener('hashchange', () => {
      if (state.hashWriting) return;
      const h = readHash();
      if (!h.agent && h.version === undefined && !h.node) return;
      const agent = h.agent || state.agent;
      if (agent !== state.agent) { selectAgent(agent, { version: h.version ?? null, node: h.node || null }); return; }
      if (h.version !== undefined && Number(h.version) !== Number(state.version)) {
        state.pendingNode = h.node || null;
        const select = qs('#pgVersion');
        if (select) { select.value = String(h.version); onVersionChange(); }
        return;
      }
      if (h.node && h.node !== state.selected) pgOpenNode(h.node);
    });

    // Prompt Lab broadcasts on 'dai-prompts' when a new version is applied.
    try {
      const channel = new BroadcastChannel('dai-prompts');
      channel.onmessage = event => {
        const data = event?.data || {};
        if (data.type !== 'prompt-applied') return;
        loadAgents();
        loadProposals(state.agent, { quiet: true });
        if (data.agent && data.agent !== state.agent) return;
        (async () => {
          const before = state.current;
          const res = await loadVersions(state.agent);
          if (!res) return;
          const target = state.current !== null ? Number(state.current) : versionNumbers().slice(-1)[0];
          populateVersions(target);
          renderTimeline();
          toast(`${agentMeta(state.agent).label} policy v${target} is now active`, 'info');
          await loadGraph(state.agent, target, { pulse: Number(before) !== Number(target) });
        })();
      };
    } catch (_) {
      // BroadcastChannel unsupported — the page still refreshes on reload.
    }

    // bfcache restores skip DOMContentLoaded: refresh the versions list so the strip is current.
    window.addEventListener('pageshow', event => {
      if (!event.persisted || !state.agent) return;
      (async () => {
        const res = await loadVersions(state.agent);
        if (!res) return;
        populateVersions(state.version);
        renderTimeline();
        renderVersionMeta();
        setStatus(`Refreshed policy versions for ${agentMeta(state.agent).label}`);
      })();
    });
  }

  // Remember the version per agent so switching agents lands where you left off.
  function rememberVersion() {
    if (state.agent && state.version !== null) lsSet(`${LS_VERSION}.${state.agent}`, String(state.version));
  }

  async function init() {
    if (!qs('#pgSvgWrap')) return;
    wireControls();
    const hash = readHash();
    const agent = hash.agent || lsGet(LS_AGENT) || AGENTS[0].agent_type;
    let version = hash.version;
    if (version === undefined) {
      const remembered = lsGet(`${LS_VERSION}.${agent}`) ?? (lsGet(LS_AGENT) === agent ? lsGet(LS_VERSION) : null);
      version = remembered !== null && remembered !== '' && /^\d+$/.test(String(remembered)) ? Number(remembered) : null;
    }
    if (!window.d3) {
      const wrap = qs('#pgSvgWrap');
      if (wrap) wrap.innerHTML = '<div class="pe-error">Graph library failed to load — the compiled prompt links still work.</div>';
    }
    await loadAgents();
    await selectAgent(agent, { version, node: hash.node || null });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
