const AGENT_TYPES = ['SummarizerAgent', 'DeciderAgent', 'FeedbackAgent', 'CompanyExtractionAgent'];
const AGENT_LABELS = {
  SummarizerAgent: 'Summarizer',
  DeciderAgent: 'Decider',
  FeedbackAgent: 'Feedback',
  CompanyExtractionAgent: 'Company extraction'
};

const selectedVersions = {
  SummarizerAgent: [],
  DeciderAgent: [],
  FeedbackAgent: [],
  CompanyExtractionAgent: []
};
let promptHistoryNeedsRefresh = true;
let promptHistoryRequest = 0;

// Notify any other open dashboard page (e.g. the Feedback tab) that a new
// prompt version was activated, so it can refresh its version display
// instantly instead of waiting for its poll interval.
// Listen for the same event from other pages (the Policy Graph tab applies proposals): a
// candidate drafted against an older version will be refused at apply, so say so up front.
try {
  const _promptChannel = new BroadcastChannel('dai-prompts');
  _promptChannel.onmessage = (event) => {
    const data = event?.data || {};
    if (data.type !== 'prompt-applied' || !data.agent) return;
    const label = (typeof AGENT_LABELS !== 'undefined' && AGENT_LABELS[data.agent]) || data.agent;
    setPromptLabMessage(`${label} v${data.version} was activated from the Policy Graph tab. Candidates drafted against an older version will be refused when applied — run the generation again to build on the current policy.`);
    document.querySelectorAll('.prompt-lab-candidate-tab, [data-candidate-agent]').forEach((el) => el.classList.add('stale'));
    void loadPromptHistory();
  };
} catch (_) {
  // BroadcastChannel unsupported — the server-side base_version check still protects the apply.
}

function broadcastPromptApplied(agentType, version) {
  try {
    const channel = new BroadcastChannel('dai-prompts');
    channel.postMessage({ type: 'prompt-applied', agent: agentType, version });
    channel.close();
  } catch (_) {
    // BroadcastChannel unsupported — other pages fall back to polling.
  }
}

// Record the human's approve/reject on a candidate review row. Fire-and-forget:
// this is training data for the critic, but must never block the UI.
function recordReviewDecision(reviewId, verdict, toVersion, sections) {
  if (!reviewId) return;
  try {
    const body = { review_id: reviewId, verdict, to_version: toVersion };
    if (sections) body.sections = sections;
    fetch('/api/prompt-evolution/record-decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(() => {});
  } catch (_) { /* ignore */ }
}

function setHidden(element, hidden) {
  if (!element) return;
  element.classList.toggle('pe-hidden', hidden);
}

function formatPercent(value, digits = 1, withSign = false) {
  const num = Number(value ?? 0);
  if (Number.isNaN(num)) return '--';
  const sign = withSign && num > 0 ? '+' : '';
  return `${sign}${num.toFixed(digits)}%`;
}

function formatDate(value) {
  if (!value) return 'Unknown date';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return 'Unknown date';
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTrade(trade) {
  if (!trade || !trade.ticker) return '--';
  const gain = Number(trade.gain ?? 0);
  const sign = gain > 0 ? '+' : '';
  return `${trade.ticker} (${sign}${gain.toFixed(2)}%)`;
}

async function apiJSON(url, options = {}) {
  const requestOptions = {
    ...options,
    headers: {
      ...(options.headers || {})
    }
  };

  if (requestOptions.body && !requestOptions.headers['Content-Type']) {
    requestOptions.headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, requestOptions);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message = typeof payload === 'object'
      ? (payload.error || payload.message || `${response.status} ${response.statusText}`)
      : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }

  return payload;
}

async function loadPerformanceContext() {
  const loadingEl = document.getElementById('performanceLoading');
  const contentEl = document.getElementById('performanceContent');
  const errorEl = document.getElementById('performanceError');
  const statsEl = document.getElementById('performanceStats');
  const headlinesEl = document.getElementById('recentHeadlines');

  setHidden(loadingEl, false);
  setHidden(contentEl, true);
  setHidden(errorEl, true);

  try {
    const data = await apiJSON('/api/prompt-evolution/performance-context');
    const stats = data?.stats || {};

    // 7-day API spend + projected monthly burn rate.
    let spend7 = null;
    let monthly = null;
    try {
      const cost = await apiJSON('/api/cost-usage?days=7');
      if (typeof cost?.total_cost === 'number') {
        spend7 = cost.total_cost;
        monthly = (spend7 / 7) * 30.4;  // avg daily × ~month length
      }
    } catch (_) { /* cost optional */ }
    const fmtUsd = (v) => (typeof v === 'number') ? ('$' + v.toFixed(2)) : '—';

    const statCards = [
      { label: 'Win Rate', value: formatPercent(stats.win_rate, 1) },
      { label: 'Avg Profit', value: formatPercent(stats.avg_profit_pct, 2, true) },
      { label: 'Total Trades', value: String(stats.total_trades ?? 0) },
      { label: 'Best Trade', value: formatTrade(stats.best_trade) },
      { label: 'Worst Trade', value: formatTrade(stats.worst_trade) },
      { label: 'API Spend (7d)', value: fmtUsd(spend7) },
      { label: 'Est. Monthly Burn', value: (typeof monthly === 'number') ? (fmtUsd(monthly) + '/mo') : '—' }
    ];

    statsEl.innerHTML = '';
    statCards.forEach((item) => {
      const box = document.createElement('div');
      box.className = 'pe-stat-box';

      const value = document.createElement('div');
      value.className = 'pe-stat-value';
      value.textContent = item.value;

      const label = document.createElement('span');
      label.className = 'pe-stat-label';
      label.textContent = item.label;

      box.appendChild(value);
      box.appendChild(label);
      statsEl.appendChild(box);
    });

    headlinesEl.innerHTML = '';
    const headlines = Array.isArray(data?.headlines) ? data.headlines.slice(0, 5) : [];
    if (headlines.length === 0) {
      const emptyLine = document.createElement('li');
      emptyLine.textContent = 'No recent headlines available.';
      headlinesEl.appendChild(emptyLine);
    } else {
      headlines.forEach((headline) => {
        const item = document.createElement('li');
        item.textContent = headline;
        headlinesEl.appendChild(item);
      });
    }

    setHidden(contentEl, false);
  } catch (error) {
    errorEl.textContent = `Failed to load performance context: ${error.message}`;
    setHidden(errorEl, false);
  } finally {
    setHidden(loadingEl, true);
  }
}

function resetSelectionStyles(agentType, version, selected) {
  const selector = `.pe-version-item[data-agent="${agentType}"][data-version="${version}"]`;
  const node = document.querySelector(selector);
  if (!node) return;
  node.classList.toggle('is-selected', selected);
}

function clearAllSelections() {
  AGENT_TYPES.forEach((agentType) => {
    selectedVersions[agentType] = [];
    const nodes = document.querySelectorAll(`.pe-version-item[data-agent="${agentType}"]`);
    nodes.forEach((node) => node.classList.remove('is-selected'));
  });
  setHidden(document.getElementById('diffPanel'), true);
}

async function loadDiff(agentType, firstVersion, secondVersion) {
  const diffPanel = document.getElementById('diffPanel');
  const diffMeta = document.getElementById('diffMeta');
  const systemDiff = document.getElementById('systemDiff');
  const userDiff = document.getElementById('userDiff');
  const strategyDiff = document.getElementById('strategyDiff');

  const [versionA, versionB] = [Number(firstVersion), Number(secondVersion)].sort((a, b) => a - b);

  setHidden(diffPanel, false);
  diffMeta.textContent = `Loading diff for ${AGENT_LABELS[agentType]} v${versionA} → v${versionB}...`;
  systemDiff.innerHTML = '';
  userDiff.innerHTML = '';
  if (strategyDiff) strategyDiff.innerHTML = '';

  try {
    const data = await apiJSON(`/api/prompt-evolution/diff/${encodeURIComponent(agentType)}/${versionA}/${versionB}`);
    diffMeta.textContent = `Comparing ${AGENT_LABELS[agentType]} versions v${data.version_a} → v${data.version_b}`;
    renderDiff(data.system_prompt_diff, systemDiff);
    renderDiff(data.user_prompt_diff, userDiff);
    if (strategyDiff) {
      renderDiff(data.strategy_directives_diff || [], strategyDiff);
    }
  } catch (error) {
    diffMeta.textContent = `Failed to load diff: ${error.message}`;
    renderDiff([], systemDiff);
    renderDiff([], userDiff);
    if (strategyDiff) {
      renderDiff([], strategyDiff);
    }
  }
}

function handleVersionToggle(agentType, version) {
  const selected = selectedVersions[agentType] || [];
  const existingIndex = selected.indexOf(version);

  if (existingIndex >= 0) {
    selected.splice(existingIndex, 1);
    resetSelectionStyles(agentType, version, false);
  } else {
    selected.push(version);
    resetSelectionStyles(agentType, version, true);

    if (selected.length > 2) {
      const removed = selected.shift();
      resetSelectionStyles(agentType, removed, false);
    }
  }

  selectedVersions[agentType] = selected;

  const diffPanel = document.getElementById('diffPanel');
  if (selected.length === 2) {
    loadDiff(agentType, selected[0], selected[1]);
    diffPanel.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  } else {
    setHidden(diffPanel, true);
  }
}

function renderTimeline(agentType, entries) {
  const container = document.getElementById(`timeline-${agentType}`);
  if (!container) return;

  container.innerHTML = '';
  const sortedEntries = [...entries].sort((a, b) => Number(b.version ?? 0) - Number(a.version ?? 0));

  if (sortedEntries.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'pe-empty';
    empty.textContent = 'No versions found.';
    container.appendChild(empty);
    return;
  }

  sortedEntries.forEach((entry) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'pe-version-item';
    button.dataset.agent = agentType;
    button.dataset.version = entry.version;

    const top = document.createElement('div');
    top.className = 'pe-version-top';

    const versionBadge = document.createElement('span');
    versionBadge.className = 'pe-badge';
    versionBadge.textContent = `v${entry.version}`;

    const dateText = document.createElement('span');
    dateText.className = 'pe-date';
    dateText.textContent = formatDate(entry.created_at);

    top.appendChild(versionBadge);
    top.appendChild(dateText);

    const description = document.createElement('p');
    description.className = 'pe-description';
    description.textContent = entry.description || 'No description provided.';

    button.appendChild(top);
    button.appendChild(description);

    if (entry.strategy_directives_preview) {
      const strategyPreview = document.createElement('p');
      strategyPreview.className = 'pe-description';
      strategyPreview.textContent = `Strategy: ${entry.strategy_directives_preview}`;
      button.appendChild(strategyPreview);
    }

    if (entry.soul_preview) {
      const soulPreview = document.createElement('p');
      soulPreview.className = 'pe-description';
      soulPreview.textContent = `Soul: ${entry.soul_preview}`;
      button.appendChild(soulPreview);
    }

    if (entry.memory_preview) {
      const memoryPreview = document.createElement('p');
      memoryPreview.className = 'pe-description';
      memoryPreview.textContent = `Memory: ${entry.memory_preview}`;
      button.appendChild(memoryPreview);
    }

    if (entry.is_active) {
      const active = document.createElement('span');
      active.className = 'pe-active';
      active.textContent = 'Active';
      button.appendChild(active);
    }

    button.addEventListener('click', () => handleVersionToggle(agentType, entry.version));
    container.appendChild(button);
  });
}

async function loadPromptHistory() {
  const request = ++promptHistoryRequest;
  if (document.getElementById('promptTimelineCard')?.hidden) {
    promptHistoryNeedsRefresh = true;
    return;
  }
  promptHistoryNeedsRefresh = false;
  const loadingEl = document.getElementById('historyLoading');
  const columnsEl = document.getElementById('timelineColumns');
  const errorEl = document.getElementById('historyError');

  setHidden(loadingEl, false);
  setHidden(columnsEl, true);
  setHidden(errorEl, true);
  clearAllSelections();

  try {
    const data = await apiJSON('/api/prompt-evolution/history');
    if (request !== promptHistoryRequest) return;

    AGENT_TYPES.forEach((agentType) => {
      const entries = Array.isArray(data?.[agentType]) ? data[agentType] : [];
      renderTimeline(agentType, entries);
    });

    setHidden(columnsEl, false);
  } catch (error) {
    if (request !== promptHistoryRequest) return;
    promptHistoryNeedsRefresh = true;
    errorEl.textContent = `Failed to load prompt history: ${error.message}`;
    setHidden(errorEl, false);
  } finally {
    if (request === promptHistoryRequest) setHidden(loadingEl, true);
  }
}

function setupPromptLabViews() {
  const updateTab = document.getElementById('peUpdateTab');
  const historyTab = document.getElementById('peHistoryTab');
  const updateView = document.getElementById('peUpdateView');
  const historyView = document.getElementById('promptTimelineCard');
  if (!updateTab || !historyTab || !updateView || !historyView) return;

  const tabs = [updateTab, historyTab];
  function showView(tab) {
    const showHistory = tab === historyTab;
    for (const button of tabs) {
      button.setAttribute('aria-selected', String(button === tab));
      button.tabIndex = button === tab ? 0 : -1;
    }
    updateView.hidden = showHistory;
    historyView.hidden = !showHistory;
    if (showHistory && promptHistoryNeedsRefresh) void loadPromptHistory();
  }

  function selectView(tab) {
    const switchingViews = tab.getAttribute('aria-selected') !== 'true';
    showView(tab);
    const url = new URL(window.location.href);
    url.hash = tab === historyTab ? 'history' : '';
    window.history.replaceState(window.history.state, '', url);
    if (switchingViews) window.scrollTo(0, 0);
  }

  for (const tab of tabs) {
    tab.addEventListener('click', () => selectView(tab));
    tab.addEventListener('keydown', (event) => {
      let next;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        next = tab === updateTab ? historyTab : updateTab;
      } else if (event.key === 'Home') {
        next = updateTab;
      } else if (event.key === 'End') {
        next = historyTab;
      } else {
        return;
      }
      event.preventDefault();
      selectView(next);
      next.focus();
    });
  }

  const showViewFromUrl = () => showView(window.location.hash === '#history' ? historyTab : updateTab);
  window.addEventListener('hashchange', showViewFromUrl);
  showViewFromUrl();
}

function setPromptLabMessage(message) {
  const messageEl = document.getElementById('promptLabMessage');
  if (!messageEl) return;
  messageEl.textContent = message;
}

function clearPromptLabAlerts() {
  setHidden(document.getElementById('promptLabError'), true);
  setHidden(document.getElementById('promptLabSuccess'), true);
}

function showPromptLabError(message) {
  const errorEl = document.getElementById('promptLabError');
  if (!errorEl) return;
  errorEl.textContent = message;
  setHidden(errorEl, false);
}

function showPromptLabSuccess(message) {
  const successEl = document.getElementById('promptLabSuccess');
  if (!successEl) return;
  successEl.textContent = message;
  setHidden(successEl, false);
}

function setupPromptLab() {
  const agentSelect = document.getElementById('promptLabAgentType');
  const generateBtn = document.getElementById('generatePromptBtn');
  const applyBtn = document.getElementById('applyPromptBtn');
  const resultsEl = document.getElementById('promptLabResults');
  const reasoningEl = document.getElementById('generatedReasoning');
  const systemPromptEl = document.getElementById('generatedSystemPrompt');
  const userPromptEl = document.getElementById('generatedUserPrompt');
  const descriptionEl = document.getElementById('promptDescription');
  const strategyDirectivesEl = document.getElementById('generatedStrategyDirectives');
  const soulEl = document.getElementById('generatedSoul');
  const memoryEl = document.getElementById('generatedMemory');

  const loadActiveBtn = document.getElementById('loadActiveBtn');
  const refreshFeedbackBtn = document.getElementById('refreshFeedbackBtn');
  const feedbackRefreshStatusEl = document.getElementById('feedbackRefreshStatus');

  if (!agentSelect || !generateBtn || !applyBtn) return;
  let contractSequence = 0;
  let editorSequence = 0;
  let loadedAgent = null;
  let loadedVersion = null;
  const syncGenerateAvailability = () => {
    const company = agentSelect.value === 'CompanyExtractionAgent';
    generateBtn.disabled = company;
    generateBtn.title = company ? 'Company extraction supports viewing and manual editing; it is excluded from automatic prompt generation.' : '';
  };
  async function loadContract(agentType) {
    const sequence = ++contractSequence;
    const note = document.getElementById('promptRuntimeNote');
    const link = document.getElementById('promptRuntimeLink');
    document.querySelectorAll('[data-contract-field]').forEach(badge => {
      badge.textContent = 'Usage pending'; badge.classList.remove('is-runtime', 'is-reference');
    });
    document.querySelectorAll('[data-contract-note]').forEach(el => { el.textContent = ''; });
    if (note) note.textContent = 'Loading runtime field usage…';
    if (link) link.hidden = true;
    try {
      const contract = await apiJSON(`/api/prompt-contracts?agent=${encodeURIComponent(agentType)}`);
      if (sequence !== contractSequence || agentSelect.value !== agentType) return;
      if (note) note.textContent = contract.runtime_note || 'Runtime usage follows the agent’s assembly contract.';
      document.querySelectorAll('[data-contract-field]').forEach(badge => {
        const field = contract.fields?.[badge.dataset.contractField];
        const known = typeof field?.used === 'boolean';
        badge.textContent = known ? (field.used ? 'Used at runtime' : 'Reference only') : 'Usage unknown';
        badge.classList.toggle('is-runtime', known && field.used);
        badge.classList.toggle('is-reference', known && !field.used);
      });
      document.querySelectorAll('[data-contract-note]').forEach(el => { el.textContent = contract.fields?.[el.dataset.contractNote]?.note || ''; });
      if (link && typeof contract.compiled_runtime_url === 'string' && contract.compiled_runtime_url.startsWith('/api/policy-graph/compiled?')) {
        link.href = contract.compiled_runtime_url; link.hidden = false;
      }
    } catch (_) {
      if (sequence !== contractSequence || agentSelect.value !== agentType) return;
      if (note) note.textContent = 'Runtime usage could not be loaded. Editable fields are not necessarily all used by the automatic agent.';
      document.querySelectorAll('[data-contract-field]').forEach(badge => { badge.textContent = 'Usage unknown'; });
    }
  }
  agentSelect.addEventListener('change', () => {
    editorSequence++; loadedAgent = null; loadedVersion = null;
    setHidden(resultsEl, true);
    syncGenerateAvailability(); loadContract(agentSelect.value);
  });
  syncGenerateAvailability(); loadContract(agentSelect.value);

  // Refresh feedback on demand — runs the FeedbackAgent with the latest
  // trade outcomes. Does NOT mutate existing prompts (skip_auto_prompts=True
  // on the server). The next "Generate Improved Prompt" call will pick up
  // the freshly stored feedback row.
  if (refreshFeedbackBtn) {
    refreshFeedbackBtn.addEventListener('click', async () => {
      clearPromptLabAlerts();
      const originalLabel = refreshFeedbackBtn.textContent;
      refreshFeedbackBtn.disabled = true;
      refreshFeedbackBtn.textContent = 'Refreshing…';
      if (feedbackRefreshStatusEl) {
        feedbackRefreshStatusEl.textContent = 'Running FeedbackAgent against the latest trade outcomes…';
      }

      try {
        const data = await apiJSON('/api/prompt-evolution/refresh-feedback', {
          method: 'POST',
          body: JSON.stringify({})
        });

        if (data?.error) throw new Error(data.error);

        const ts = new Date().toLocaleString();
        if (data?.feedback_id) {
          const trades = data.total_trades ?? 0;
          const decisions = data.decisions_analyzed ?? 0;
          const sourceLabel = data.feedback_source || 'trade_outcomes';
          const detail = trades
            ? `${trades} trades analyzed`
            : `${decisions} decisions analyzed (no completed trades)`;
          const successRate = (typeof data.success_rate === 'number')
            ? ` · success ${(data.success_rate * 100).toFixed(1)}%`
            : '';
          const summary = `Feedback v#${data.feedback_id} written at ${ts} — source: ${sourceLabel} · ${detail}${successRate}`;
          if (feedbackRefreshStatusEl) {
            feedbackRefreshStatusEl.textContent = summary;
            feedbackRefreshStatusEl.style.color = '#2e7d32';
          }
          showPromptLabSuccess('Feedback refreshed. Click "Generate Improved Prompt" to evolve a candidate from this fresh feedback.');
        } else {
          const msg = data?.message || 'FeedbackAgent ran but produced no new record.';
          if (feedbackRefreshStatusEl) {
            feedbackRefreshStatusEl.textContent = `${ts} — ${msg}`;
            feedbackRefreshStatusEl.style.color = '#b26a00';
          }
          setPromptLabMessage(msg);
        }
      } catch (error) {
        if (feedbackRefreshStatusEl) {
          feedbackRefreshStatusEl.textContent = `Refresh failed: ${error.message}`;
          feedbackRefreshStatusEl.style.color = '#c62828';
        }
        showPromptLabError(`Failed to refresh feedback: ${error.message}`);
      } finally {
        refreshFeedbackBtn.disabled = false;
        refreshFeedbackBtn.textContent = originalLabel;
      }
    });
  }

  // Load active version into editing area
  if (loadActiveBtn) {
    loadActiveBtn.addEventListener('click', async () => {
      const agentType = agentSelect.value;
      const sequence = ++editorSequence;
      clearPromptLabAlerts();
      setPromptLabMessage('Loading active version...');
      const originalLabel = loadActiveBtn.textContent;
      loadActiveBtn.disabled = true;
      loadActiveBtn.textContent = 'Loading...';

      try {
        const data = await apiJSON(`/api/prompts/${encodeURIComponent(agentType)}/active`);
        if (sequence !== editorSequence || agentSelect.value !== agentType) return;
        if (!data || data.error) throw new Error(data?.error || 'No active prompt found');
        loadedAgent = agentType; loadedVersion = data.version;

        reasoningEl.textContent = `Loaded active v${data.version ?? '?'} for ${AGENT_LABELS[agentType]}. Edit any field and apply as a new version.`;
        systemPromptEl.value = data.system_prompt || '';
        userPromptEl.value = data.user_prompt_template || '';
        if (strategyDirectivesEl) strategyDirectivesEl.value = data.strategy_directives || '';
        if (soulEl) soulEl.value = data.soul || '';
        if (memoryEl) memoryEl.value = data.memory || '';
        descriptionEl.value = '';

        setHidden(resultsEl, false);
        setPromptLabMessage(`Active v${data.version ?? '?'} loaded. Edit and apply to create a new version.`);
      } catch (error) {
        if (sequence !== editorSequence || agentSelect.value !== agentType) return;
        showPromptLabError(`Failed to load active version: ${error.message}`);
        setPromptLabMessage('');
      } finally {
        loadActiveBtn.disabled = false;
        loadActiveBtn.textContent = originalLabel;
      }
    });
  }

  generateBtn.addEventListener('click', async () => {
    const agentType = agentSelect.value;
    if (agentType === 'CompanyExtractionAgent') return;
    const sequence = ++editorSequence;
    const generateSoul = true;
    const generateMemory = true;
    clearPromptLabAlerts();
    const genParts = ['prompt'];
    if (generateSoul) genParts.push('soul');
    if (generateMemory) genParts.push('memory');
    setPromptLabMessage(`Generating ${genParts.join(' + ')}...`);

    const originalLabel = generateBtn.textContent;
    generateBtn.disabled = true;
    generateBtn.textContent = 'Generating...';

    try {
      const data = await apiJSON('/api/prompt-evolution/generate', {
        method: 'POST',
        body: JSON.stringify({ agent_type: agentType, generate_soul: generateSoul, generate_memory: generateMemory })
      });
      if (sequence !== editorSequence || agentSelect.value !== agentType) return;
      if (data.no_change === true) {
        loadedAgent = null;
        loadedVersion = null;
        setHidden(resultsEl, true);
        setPromptLabMessage(`No change proposed for ${AGENT_LABELS[agentType]} v${data.current_version}.`);
        return;
      }
      loadedAgent = agentType; loadedVersion = data.current_version;

      reasoningEl.textContent = data.reasoning || 'No reasoning returned by API.';
      systemPromptEl.value = data.system_prompt || '';
      userPromptEl.value = data.user_prompt_template || '';
      if (strategyDirectivesEl) {
        strategyDirectivesEl.value = data.strategy_directives || '';
      }
      if (soulEl) {
        soulEl.value = data.soul || '';
      }
      if (memoryEl) {
        memoryEl.value = data.memory || '';
      }
      descriptionEl.value = `Refined ${AGENT_LABELS[agentType]} prompt (${new Date().toLocaleString()})`;

      setHidden(resultsEl, false);
      setPromptLabMessage('Generated candidate ready. Review and apply as a new version when ready.');
    } catch (error) {
      if (sequence !== editorSequence || agentSelect.value !== agentType) return;
      showPromptLabError(`Failed to generate prompt: ${error.message}`);
      setPromptLabMessage('');
    } finally {
      syncGenerateAvailability();
      generateBtn.textContent = originalLabel;
    }
  });

  applyBtn.addEventListener('click', async () => {
    const agentType = agentSelect.value;
    const sequence = editorSequence;
    const systemPrompt = systemPromptEl.value.trim();
    const userPromptTemplate = userPromptEl.value.trim();
    const strategyDirectives = strategyDirectivesEl ? strategyDirectivesEl.value.trim() : '';
    const soul = soulEl ? soulEl.value.trim() : '';
    const memory = memoryEl ? memoryEl.value.trim() : '';
    const description = descriptionEl.value.trim();

    clearPromptLabAlerts();

    if (loadedAgent !== agentType || loadedVersion === null || loadedVersion === undefined) {
      showPromptLabError('Load this agent’s active version or generate a fresh candidate before applying.');
      return;
    }

    if (!systemPrompt || !userPromptTemplate) {
      showPromptLabError('System prompt and user prompt template are required before applying.');
      return;
    }

    if (!description) {
      showPromptLabError('Please provide a version description before applying.');
      return;
    }

    const originalLabel = applyBtn.textContent;
    applyBtn.disabled = true;
    applyBtn.textContent = 'Applying...';
    setPromptLabMessage('Applying new version...');

    try {
      const payload = {
        agent_type: agentType,
        system_prompt: systemPrompt,
        user_prompt_template: userPromptTemplate,
        strategy_directives: strategyDirectives,
        soul: soul,
        memory: memory,
        description,
        base_version: loadedVersion
      };
      const data = await apiJSON('/api/prompt-evolution/apply', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (!data?.success) {
        throw new Error('API did not confirm success.');
      }
      if (data.no_change === true) {
        setPromptLabMessage(`No change to apply. v${data.version} is active.`);
        return;
      }

      showPromptLabSuccess(`Applied successfully as version v${data.version}.`);
      if (sequence === editorSequence && loadedAgent === agentType) loadedVersion = data.version;
      setPromptLabMessage('Prompt version applied. Timeline refreshed.');
      broadcastPromptApplied(agentType, data.version);
      await loadPromptHistory();
    } catch (error) {
      showPromptLabError(`Failed to apply new version: ${error.message}`);
      setPromptLabMessage('');
    } finally {
      applyBtn.disabled = false;
      applyBtn.textContent = originalLabel;
    }
  });
}

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

// =============================================================================
// Batch Prompt Lab — one-click "refresh feedback + generate for all 3 agents",
// per-agent tabs with GitHub-style diffs, approve/reject per agent.
// =============================================================================

function countDiffStats(diffLines) {
  let added = 0;
  let removed = 0;
  if (!Array.isArray(diffLines)) return { added, removed };
  const hasHeaders = typeof diffLines[0] === 'string' && diffLines[0].startsWith('--- ')
    && typeof diffLines[1] === 'string' && diffLines[1].startsWith('+++ ');
  for (const line of diffLines.slice(hasHeaders ? 2 : 0)) {
    if (typeof line !== 'string') continue;
    if (line.startsWith('+')) added++;
    else if (line.startsWith('-')) removed++;
  }
  return { added, removed };
}

function hasNoPromptChanges(candidate) {
  if (candidate.no_change === true) return true;
  const sections = Object.values(candidate.diffs || {});
  return sections.length > 0 && sections.every((lines) => Array.isArray(lines) && lines.length === 0);
}

function buildDiffSection(label, diffLines, openByDefault, sectionChanges, sectionToggle) {
  const wrap = document.createElement('details');
  wrap.className = 'pe-diff-section';
  if (openByDefault) wrap.open = true;

  const summary = document.createElement('summary');
  const { added, removed } = countDiffStats(diffLines);
  summary.innerHTML = `${label} <span class="pe-diff-badge"><span class="add">+${added}</span> / <span class="rem">−${removed}</span></span>`;

  // Per-section approval checkbox — only on sections the candidate actually
  // changes. Checked = ship this section; unchecked = keep the current text.
  if (sectionToggle) {
    const toggleWrap = document.createElement('label');
    toggleWrap.className = 'pe-section-toggle';
    toggleWrap.title = 'Checked = ship this section; unchecked = keep the current version of it';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = sectionToggle.initial !== false;
    toggleWrap.appendChild(cb);
    toggleWrap.appendChild(document.createTextNode(' include'));
    // Keep checkbox clicks from toggling the <details> open/closed state.
    toggleWrap.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => sectionToggle.onChange(cb.checked));
    summary.appendChild(toggleWrap);
  }
  wrap.appendChild(summary);

  // Justification chips — one per change the generator attributed to this
  // section. Clicking a chip opens a popup with the why + expected effect.
  if (Array.isArray(sectionChanges) && sectionChanges.length) {
    const chipRow = document.createElement('div');
    chipRow.className = 'pe-chip-row';
    sectionChanges.forEach((change) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `pe-change-chip ${change.kind === 'major' ? 'major' : 'minor'}`;
      const what = change.what || '(no description)';
      chip.innerHTML = `<span class="pe-chip-kind">${change.kind === 'major' ? 'MAJOR' : 'minor'}</span>${escapeHtml(truncate(what, 70))}`;
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        showChangePopup(change, chip);
      });
      chipRow.appendChild(chip);
    });
    wrap.appendChild(chipRow);
  }

  const view = document.createElement('div');
  view.className = 'pe-diff-view';
  renderDiff(diffLines, view);
  wrap.appendChild(view);
  return wrap;
}

function truncate(str, n) {
  if (typeof str !== 'string') return '';
  return str.length > n ? str.slice(0, n - 1) + '…' : str;
}

function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

let _changePopupEl = null;
function closeChangePopup() {
  if (_changePopupEl) {
    _changePopupEl.remove();
    _changePopupEl = null;
    document.removeEventListener('click', _onDocClickForPopup, true);
  }
}
function _onDocClickForPopup(e) {
  if (_changePopupEl && !_changePopupEl.contains(e.target)) closeChangePopup();
}
function showChangePopup(change, anchorEl) {
  closeChangePopup();
  const pop = document.createElement('div');
  pop.className = 'pe-change-popup';
  const kindLabel = change.kind === 'major' ? 'MAJOR' : 'minor';
  const behavioral = change.behavioral ? 'Behavioral' : 'Wording';
  pop.innerHTML = `
    <div class="pe-change-popup-head">
      <span class="pe-chip-kind ${change.kind === 'major' ? 'major' : 'minor'}">${kindLabel}</span>
      <span class="pe-change-popup-tag">${behavioral}</span>
      <button type="button" class="pe-change-popup-close" aria-label="Close">×</button>
    </div>
    <div class="pe-change-popup-body">
      <p class="pe-change-popup-what">${escapeHtml(change.what || '(no description)')}</p>
      ${change.why ? `<p><strong>Why:</strong> ${escapeHtml(change.why)}</p>` : ''}
      ${change.expected_effect ? `<p><strong>Expected effect:</strong> ${escapeHtml(change.expected_effect)}</p>` : ''}
    </div>`;
  document.body.appendChild(pop);

  // Position under the chip
  const r = anchorEl.getBoundingClientRect();
  pop.style.position = 'absolute';
  pop.style.top = `${window.scrollY + r.bottom + 6}px`;
  pop.style.left = `${window.scrollX + Math.min(r.left, window.innerWidth - 360)}px`;

  pop.querySelector('.pe-change-popup-close').addEventListener('click', closeChangePopup);
  _changePopupEl = pop;
  // Defer attaching the outside-click handler so this very click doesn't close it
  setTimeout(() => document.addEventListener('click', _onDocClickForPopup, true), 0);
}

function setupBatchPromptLab() {
  const btn = document.getElementById('batchGenerateBtn');
  const statusEl = document.getElementById('batchStatus');
  const errorEl = document.getElementById('batchError');
  const successEl = document.getElementById('batchSuccess');
  const fbBanner = document.getElementById('batchFeedbackSummary');
  const fbBannerText = document.getElementById('batchFeedbackSummaryText');
  const resultsEl = document.getElementById('batchResults');
  const tabsEl = document.getElementById('batchTabs');
  const panelsEl = document.getElementById('batchPanels');
  const hintEl = document.getElementById('batchGenerateHint');

  if (!btn || !tabsEl || !panelsEl) return;

  const clearBatchAlerts = () => {
    if (errorEl) { errorEl.textContent = ''; setHidden(errorEl, true); }
    if (successEl) { successEl.textContent = ''; setHidden(successEl, true); }
  };
  const showBatchError = (msg) => {
    if (!errorEl) return;
    errorEl.textContent = msg;
    setHidden(errorEl, false);
  };
  const showBatchSuccess = (msg) => {
    if (!successEl) return;
    successEl.textContent = msg;
    setHidden(successEl, false);
  };

  function activateTab(agentType) {
    tabsEl.querySelectorAll('.pe-tab-btn').forEach((b) => {
      const active = b.dataset.agent === agentType;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', String(active));
      b.tabIndex = active ? 0 : -1;
    });
    panelsEl.querySelectorAll('.pe-tab-panel').forEach((p) => {
      p.classList.toggle('active', p.dataset.agent === agentType);
    });
  }

  function renderTabsAndPanels(candidates, errors) {
    tabsEl.innerHTML = '';
    panelsEl.innerHTML = '';

    const errorByAgent = {};
    (errors || []).forEach((e) => { errorByAgent[e.agent_type] = e.error; });

    const order = ['SummarizerAgent', 'DeciderAgent', 'FeedbackAgent'];
    order.forEach((agentType, index) => {
      const candidate = candidates.find((c) => c.agent_type === agentType);
      const unchanged = candidate && hasNoPromptChanges(candidate);
      const errMsg = errorByAgent[agentType] || (candidate ? '' : 'No result returned.');

      // Tab button
      const tabBtn = document.createElement('button');
      tabBtn.type = 'button';
      tabBtn.className = 'pe-tab-btn';
      tabBtn.dataset.agent = agentType;
      tabBtn.id = `batch-tab-${agentType}`;
      tabBtn.setAttribute('role', 'tab');
      tabBtn.setAttribute('aria-controls', `batch-panel-${agentType}`);

      const label = AGENT_LABELS[agentType] || agentType;
      if (unchanged) {
        tabBtn.innerHTML = `${label} <span class="pe-diff-badge">No change</span>`;
      } else if (candidate) {
        // Total diff stats across all 5 fields
        let added = 0;
        let removed = 0;
        Object.values(candidate.diffs || {}).forEach((lines) => {
          const s = countDiffStats(lines);
          added += s.added;
          removed += s.removed;
        });
        const cs = candidate.change_summary || {};
        const impactDot = cs.is_substantive
          ? '<span class="pe-tab-impact substantive" title="Behavioral changes">●</span>'
          : '';
        const cv = candidate.critic?.auto ? null : candidate.critic?.verdict;
        const criticMark = cv === 'approve'
          ? '<span class="pe-critic-mark approve" title="critic approved">✓</span>'
          : (cv === 'reject' ? '<span class="pe-critic-mark reject" title="critic rejected">⊘</span>' : '');
        tabBtn.innerHTML = `${impactDot}${label}${criticMark} <span class="pe-diff-badge"><span class="add">+${added}</span> / <span class="rem">-${removed}</span></span>`;
      } else {
        tabBtn.classList.add('failed');
        tabBtn.innerHTML = `${label} <span class="pe-diff-badge">Failed</span>`;
      }
      tabBtn.addEventListener('click', () => activateTab(agentType));
      tabBtn.addEventListener('keydown', (event) => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % order.length;
        else if (event.key === 'ArrowLeft') next = (index + order.length - 1) % order.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = order.length - 1;
        else return;
        event.preventDefault();
        activateTab(order[next]);
        document.getElementById(`batch-tab-${order[next]}`)?.focus();
      });
      tabsEl.appendChild(tabBtn);

      // Tab panel
      const panel = document.createElement('div');
      panel.className = 'pe-tab-panel';
      panel.dataset.agent = agentType;
      panel.id = `batch-panel-${agentType}`;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', tabBtn.id);
      panel.tabIndex = 0;

      if (errMsg) {
        const errBox = document.createElement('div');
        errBox.className = 'pe-error';
        errBox.style.marginTop = '12px';
        errBox.textContent = `Generation failed for ${label}: ${errMsg}`;
        panel.appendChild(errBox);
        panelsEl.appendChild(panel);
        return;
      }

      if (unchanged) {
        const message = document.createElement('div');
        message.className = 'pe-no-change';
        message.innerHTML = `<h3>No change proposed</h3><p>Active version v${escapeHtml(String(candidate.current_version ?? '?'))}</p>`;
        if (candidate.reasoning) {
          const explanation = document.createElement('p');
          explanation.textContent = candidate.reasoning;
          message.appendChild(explanation);
        }
        panel.appendChild(message);
        panelsEl.appendChild(panel);
        return;
      }

      // Behavioral-impact summary — the headline for "is this change worth it?"
      const cs = candidate.change_summary || {};
      const summaryWrap = document.createElement('div');
      summaryWrap.className = 'pe-impact-summary';
      const substantive = cs.is_substantive;
      const wordingOnly = cs.wording_only ?? (!substantive && cs.total > 0 && cs.behavioral === 0);
      const impactLabel = substantive ? 'Behavioral changes' : wordingOnly ? 'Wording-only draft' : 'Impact unclassified';
      summaryWrap.innerHTML = `
        <span class="pe-impact-pill ${substantive ? 'substantive' : 'cosmetic'}">${impactLabel}</span>
        <span class="pe-impact-counts">Based on v${escapeHtml(String(candidate.current_version ?? '?'))}</span>`;
      panel.appendChild(summaryWrap);

      const reasoningWrap = document.createElement('div');
      reasoningWrap.className = 'pe-field';
      reasoningWrap.innerHTML = '<label>Draft rationale</label>';
      const reasoningBox = document.createElement('div');
      reasoningBox.className = 'pe-reasoning';
      reasoningBox.textContent = candidate.reasoning || 'No summary was returned.';
      reasoningWrap.appendChild(reasoningBox);
      panel.appendChild(reasoningWrap);

      const critic = candidate.critic || {};
      const criticRejected = critic.verdict === 'reject';
      if (critic.verdict && !critic.auto) {
        const criticBanner = document.createElement('div');
        criticBanner.className = `pe-critic-banner ${criticRejected ? 'reject' : 'approve'}`;
        const confPct = typeof critic.confidence === 'number' ? ` · ${Math.round(critic.confidence * 100)}% confidence` : '';
        criticBanner.innerHTML = `
          <span class="pe-critic-verdict">${criticRejected ? 'Critic recommends rejecting' : 'Critic recommends approval'}${confPct}</span>
          <span class="pe-critic-meta">${escapeHtml(critic.summary || critic.reason || '')}</span>`;
        if (critic.summary && critic.reason && critic.summary !== critic.reason) {
          const audit = document.createElement('details');
          audit.className = 'pe-critic-audit';
          audit.innerHTML = `<summary>Review details</summary><p>${escapeHtml(critic.reason)}</p>`;
          criticBanner.appendChild(audit);
        }
        panel.appendChild(criticBanner);
      }

      // Group the generator's changes by section so each diff block shows its chips.
      const changesBySection = {};
      (candidate.changes || []).forEach((ch) => {
        const sec = ch.section || 'strategy_directives';
        (changesBySection[sec] = changesBySection[sec] || []).push(ch);
      });

      // Five diff sections (Strategy Directives + Memory open by default — that's where evolution mostly lives)
      const diffMap = [
        { key: 'system_prompt_diff', section: 'system_prompt', label: 'System Prompt', open: false },
        { key: 'user_prompt_diff', section: 'user_prompt_template', label: 'User Prompt Template', open: false },
        { key: 'strategy_directives_diff', section: 'strategy_directives', label: 'Strategy Directives', open: true },
        { key: 'soul_diff', section: 'soul', label: 'Soul (mission + per-agent identity)', open: false },
        { key: 'memory_diff', section: 'memory', label: 'Memory (Obsidian-style log)', open: true },
      ];
      // Per-section approval state: every CHANGED section starts included; the
      // human can uncheck any of them to ship a partial version.
      const changedSections = [];
      const sectionApproval = {};
      diffMap.forEach(({ key, section: sec }) => {
        const s = countDiffStats(candidate.diffs?.[key] || []);
        if (s.added + s.removed > 0) {
          changedSections.push(sec);
          sectionApproval[sec] = true;
        }
      });
      diffMap.forEach(({ key, section: sec, label: lbl, open }) => {
        if (!changedSections.includes(sec)) return;
        const toggle = { initial: true, onChange: (on) => { sectionApproval[sec] = on; updateApproveState(); } };
        const section = buildDiffSection(lbl, candidate.diffs[key], open, changesBySection[sec] || [], toggle);
        panel.appendChild(section);
      });

      let overrideOn = !criticRejected; // critic-approved → human can act immediately
      if (criticRejected) {
        const overrideWrap = document.createElement('label');
        overrideWrap.className = 'pe-override';
        const label = critic.auto ? 'I reviewed the edits and their impact.' : 'I reviewed the critic’s recommendation and want to proceed.';
        overrideWrap.innerHTML = `<input type="checkbox" /> ${label}`;
        panel.appendChild(overrideWrap);
        overrideWrap.querySelector('input').addEventListener('change', (e) => {
          overrideOn = e.target.checked;
          updateApproveState();
        });
      }

      // Approve button reflects the section selection: full approval, partial
      // ("Approve 2/4 sections"), or disabled when nothing is selected.
      function selectedSections() {
        return changedSections.filter((s) => sectionApproval[s]);
      }
      function updateApproveState() {
        if (approveBtn.dataset.done) return; // decision already made
        const sel = selectedSections();
        const noneLeft = changedSections.length > 0 && sel.length === 0;
        approveBtn.disabled = !overrideOn || noneLeft;
        if (noneLeft) {
          approveBtn.textContent = '✅ Approve (select a section)';
        } else if (sel.length === changedSections.length) {
          approveBtn.textContent = '✅ Approve & Activate';
        } else {
          approveBtn.textContent = `✅ Approve ${sel.length}/${changedSections.length} Sections`;
        }
      }

      // Decision bar — editable description + approve/reject
      const decisionBar = document.createElement('div');
      decisionBar.className = 'pe-decision-bar';

      const descLabel = document.createElement('label');
      descLabel.textContent = 'Description:';
      descLabel.style.fontWeight = '600';
      decisionBar.appendChild(descLabel);

      const descInput = document.createElement('input');
      descInput.type = 'text';
      descInput.className = 'pe-input';
      descInput.style.flex = '1';
      descInput.style.minWidth = '300px';
      descInput.value = candidate.description || '';
      decisionBar.appendChild(descInput);

      const approveBtn = document.createElement('button');
      approveBtn.type = 'button';
      approveBtn.className = 'pe-btn approve';
      approveBtn.textContent = '✅ Approve & Activate';
      approveBtn.disabled = criticRejected; // gated until override when critic rejected
      decisionBar.appendChild(approveBtn);

      const rejectBtn = document.createElement('button');
      rejectBtn.type = 'button';
      rejectBtn.className = 'pe-btn reject';
      rejectBtn.textContent = '❌ Reject';
      decisionBar.appendChild(rejectBtn);

      const statusSpan = document.createElement('span');
      statusSpan.style.marginLeft = '8px';
      statusSpan.style.fontSize = '0.9em';
      decisionBar.appendChild(statusSpan);

      approveBtn.addEventListener('click', async () => {
        let description = (descInput.value || '').trim() || candidate.description;
        if (!description) {
          statusSpan.style.color = '#c62828';
          statusSpan.textContent = 'Description required.';
          return;
        }
        const approved = selectedSections();
        const rejected = changedSections.filter((s) => !sectionApproval[s]);
        const isPartial = rejected.length > 0;
        if (isPartial && !/partial:/.test(description)) {
          description += ` · partial: ${approved.join('+')}`;
        }
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        const origLabel = approveBtn.textContent;
        approveBtn.textContent = 'Applying…';
        statusSpan.style.color = '#888';
        statusSpan.textContent = '';

        try {
          const payload = {
            agent_type: candidate.agent_type,
            system_prompt: candidate.system_prompt,
            user_prompt_template: candidate.user_prompt_template,
            strategy_directives: candidate.strategy_directives,
            soul: candidate.soul,
            memory: candidate.memory,
            description,
            // Sections to take from the candidate; the server keeps the
            // current version's text for everything else.
            approved_sections: approved,
            // The version this candidate was drafted against — the server refuses the apply
            // when the active version moved meanwhile (e.g. a Policy Graph proposal shipped).
            base_version: candidate.current_version,
          };
          const data = await apiJSON('/api/prompt-evolution/apply', {
            method: 'POST',
            body: JSON.stringify(payload),
          });
          if (!data?.success) throw new Error('API did not confirm success.');

          approveBtn.dataset.done = '1';
          if (data.no_change === true) {
            approveBtn.textContent = `Active v${data.version}`;
            statusSpan.textContent = 'No change to apply.';
            descInput.disabled = true;
            return;
          }
          tabBtn.classList.add('approved');
          statusSpan.style.color = 'var(--success)';
          statusSpan.textContent = isPartial
            ? `✓ Activated as v${data.version} (partial: ${approved.join(', ')})`
            : `✓ Activated as v${data.version}`;
          approveBtn.textContent = `Active v${data.version}`;
          rejectBtn.disabled = true;
          descInput.disabled = true;
          showBatchSuccess(`${AGENT_LABELS[candidate.agent_type]} v${data.version} activated${isPartial ? ' (partial)' : ''}.`);
          broadcastPromptApplied(candidate.agent_type, data.version);
          // Record the human label (scores the critic; market outcome later).
          // Partial approvals carry the per-section detail for the RLHF loop.
          recordReviewDecision(
            candidate.review_id,
            isPartial ? 'partial' : 'approve',
            data.version,
            { approved, rejected },
          );
          await loadPromptHistory();
        } catch (err) {
          statusSpan.style.color = '#c62828';
          statusSpan.textContent = `Failed: ${err.message}`;
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
          approveBtn.textContent = origLabel;
        }
      });

      rejectBtn.addEventListener('click', () => {
        approveBtn.dataset.done = '1';
        tabBtn.classList.add('rejected');
        statusSpan.style.color = '#999';
        statusSpan.textContent = '✗ Rejected.';
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        descInput.disabled = true;
        recordReviewDecision(candidate.review_id, 'reject', null,
          { approved: [], rejected: changedSections });
      });

      panel.appendChild(decisionBar);
      panelsEl.appendChild(panel);
    });

    const drafts = candidates.filter((candidate) => !hasNoPromptChanges(candidate));
    const firstDraft = drafts.find((candidate) => candidate.change_summary?.is_substantive) || drafts[0];
    activateTab(firstDraft?.agent_type || errors?.[0]?.agent_type || candidates[0]?.agent_type || order[0]);
  }

  function renderFeedbackBanner(summary) {
    if (!fbBanner || !fbBannerText) return;
    const ts = new Date(summary.generated_at || Date.now()).toLocaleString();
    const bits = [];
    if (summary.feedback_id) bits.push(`#${summary.feedback_id}`);
    bits.push(`source: ${summary.feedback_source || 'trade_outcomes'}`);
    if (summary.total_trades) bits.push(`${summary.total_trades} trades`);
    if (summary.decisions_analyzed) bits.push(`${summary.decisions_analyzed} decisions`);
    if (typeof summary.success_rate === 'number') {
      bits.push(`success ${(summary.success_rate * 100).toFixed(1)}%`);
    }
    if (typeof summary.avg_profit === 'number') {
      bits.push(`avg ${summary.avg_profit.toFixed(2)}%`);
    }
    bits.push(ts);
    fbBannerText.textContent = bits.join(' · ');
    setHidden(fbBanner, false);
  }

  // ----- Persistence + polling (so a tab switch or reload doesn't lose state) -----
  const LS_JOB_KEY = 'pe.batchJobId';
  const LS_RESULT_KEY = 'pe.lastBatchResult';
  const POLL_INTERVAL_MS = 2000;
  const origBtnLabel = btn.textContent;
  let pollTimer = null;
  let activeJobId = null;
  let pollFailures = 0;

  const setRunningUI = (message) => {
    btn.disabled = true;
    btn.textContent = '⏳ Running…';
    if (statusEl) {
      statusEl.style.color = '#888';
      statusEl.textContent = message || 'Working…';
    }
    if (hintEl) hintEl.textContent = '';
  };
  const setIdleUI = () => {
    btn.disabled = false;
    btn.textContent = origBtnLabel;
  };

  const phaseMessage = (job) => {
    let phase = job.message || 'Working…';
    if (job.phase === 'feedback') {
      phase = 'Step 1/3 — Refreshing feedback';
    } else if (job.phase === 'generate') {
      const done = (job.completed_agents || []).length;
      phase = `Step 2/3 — Drafting prompts (${done}/3 complete)`;
    } else if (job.phase === 'critique') {
      phase = `Step 3/3 — Reviewing drafts (${job.reviewed_candidates ?? 0}/${job.total_candidates ?? 3} complete)`;
    }
    const details = [phase];
    if (job.model) details.push(job.model);
    if (job.reasoning_effort) details.push(`${job.reasoning_effort} reasoning requested`);
    if (Number.isFinite(job.started_at)) {
      const seconds = Math.max(0, Math.floor(Date.now() / 1000 - job.started_at));
      details.push(`${Math.floor(seconds / 60)}m ${seconds % 60}s elapsed`);
    }
    return details.join(' · ');
  };

  function renderFinishedJob(job) {
    if (job.feedback_summary) renderFeedbackBanner(job.feedback_summary);
    const candidates = job.candidates || [];
    const errors = job.errors || [];
    renderTabsAndPanels(candidates, errors);
    setHidden(resultsEl, false);

    const unchangedCount = candidates.filter(hasNoPromptChanges).length;
    const draftCount = candidates.length - unchangedCount;
    const failCount = errors.length;
    const ts = new Date(job.finished_at || Date.now()).toLocaleString();
    if (statusEl) {
      const results = [];
      if (draftCount) results.push(`${draftCount} ${draftCount === 1 ? 'draft' : 'drafts'} to review`);
      if (unchangedCount) results.push(unchangedCount === 3 ? 'No changes proposed for all three agents' : `${unchangedCount} with no change proposed`);
      if (failCount) results.push(`${failCount} failed`);
      statusEl.style.color = failCount ? 'var(--warning)' : 'var(--text)';
      statusEl.textContent = `${results.join(' · ') || 'No results returned'} · ${ts}`;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  async function pollOnce(jobId) {
    const controller = new AbortController();
    const requestTimeout = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(`/api/prompt-evolution/batch-status/${encodeURIComponent(jobId)}`, {
        signal: controller.signal, cache: 'no-store',
      });
      if (res.status === 404) {
        // Job is gone (server restart or TTL). Clear and surface a soft message.
        localStorage.removeItem(LS_JOB_KEY);
        activeJobId = null;
        stopPolling();
        setIdleUI();
        if (statusEl) {
          statusEl.style.color = '#b26a00';
          statusEl.textContent = 'Previous batch job is no longer available (server restart or expired). Click again to rerun.';
        }
        return;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const job = await res.json();
      if (!['running', 'done', 'failed'].includes(job.status)) {
        throw new Error('Unexpected batch status');
      }
      pollFailures = 0;

      if (job.status === 'running') {
        setRunningUI(phaseMessage(job));
        if (job.feedback_summary) renderFeedbackBanner(job.feedback_summary);
        pollTimer = setTimeout(() => pollOnce(jobId), POLL_INTERVAL_MS);
        return;
      }
      if (job.status === 'done') {
        stopPolling();
        activeJobId = null;
        localStorage.removeItem(LS_JOB_KEY);
        try {
          localStorage.setItem(LS_RESULT_KEY, JSON.stringify({
            feedback_summary: job.feedback_summary,
            candidates: job.candidates,
            errors: job.errors,
            finished_at: job.finished_at,
            stored_at: Date.now(),
          }));
        } catch (_) { /* localStorage quota — fine to drop */ }
        renderFinishedJob(job);
        setIdleUI();
        return;
      }
      if (job.status === 'failed') {
        stopPolling();
        activeJobId = null;
        localStorage.removeItem(LS_JOB_KEY);
        showBatchError(`Batch generation failed: ${job.error || 'unknown error'}`);
        if (statusEl) {
          statusEl.style.color = '#c62828';
          statusEl.textContent = '';
        }
        setIdleUI();
        return;
      }
    } catch (err) {
      console.warn('batch-status poll error:', err);
      pollFailures += 1;
      if (pollFailures >= 3) {
        setIdleUI();
        btn.textContent = 'Reconnect to batch';
        if (statusEl) statusEl.textContent = 'Batch status unavailable. Reconnect to check this run.';
      } else {
        setRunningUI('Connection interrupted. Reconnecting to this batch…');
        pollTimer = setTimeout(() => pollOnce(jobId), POLL_INTERVAL_MS * 2);
      }
    } finally {
      clearTimeout(requestTimeout);
    }
  }

  function startPolling(jobId) {
    activeJobId = jobId;
    pollFailures = 0;
    localStorage.setItem(LS_JOB_KEY, jobId);
    stopPolling();
    pollOnce(jobId);
  }

  // Resume any active job from a prior page load.
  function resumeFromLocalStorage() {
    const existingJobId = localStorage.getItem(LS_JOB_KEY);
    if (existingJobId) {
      setRunningUI('Reconnecting to in-flight batch job…');
      startPolling(existingJobId);
      return;
    }
    // No active job — but if we have a recent result, restore it so a hard
    // refresh after completion doesn't blank the page.
    try {
      const raw = localStorage.getItem(LS_RESULT_KEY);
      if (!raw) return;
      const cached = JSON.parse(raw);
      // Only restore if it's < 1 hour old; users probably don't want to see
      // candidates from a previous trading session.
      if (Date.now() - (cached.stored_at || 0) > 60 * 60 * 1000) {
        localStorage.removeItem(LS_RESULT_KEY);
        return;
      }
      renderFinishedJob({
        feedback_summary: cached.feedback_summary,
        candidates: cached.candidates || [],
        errors: cached.errors || [],
        finished_at: cached.finished_at,
      });
      if (statusEl) {
        statusEl.style.color = '#888';
        statusEl.textContent += ' (restored from previous session)';
      }
    } catch (_) {
      localStorage.removeItem(LS_RESULT_KEY);
    }
  }

  btn.addEventListener('click', async () => {
    clearBatchAlerts();
    if (activeJobId) {
      setRunningUI('Reconnecting to this batch…');
      startPolling(activeJobId);
      return;
    }
    setHidden(resultsEl, true);
    setRunningUI('Queuing batch job…');
    const controller = new AbortController();
    const requestTimeout = setTimeout(() => controller.abort(), 10000);
    try {
      const data = await apiJSON('/api/prompt-evolution/refresh-and-generate-all', {
        method: 'POST',
        body: JSON.stringify({}),
        signal: controller.signal,
      });
      if (data?.error || !data?.job_id) throw new Error(data?.error || 'No job_id returned.');
      startPolling(data.job_id);
    } catch (err) {
      showBatchError(`Failed to start batch: ${err.message}`);
      setIdleUI();
      if (statusEl) {
        statusEl.style.color = '#c62828';
        statusEl.textContent = '';
      }
    } finally {
      clearTimeout(requestTimeout);
    }
  });

  resumeFromLocalStorage();
}

document.addEventListener('DOMContentLoaded', () => {
  setupPromptLabViews();
  loadPerformanceContext();
  setupPromptLab();
  setupBatchPromptLab();

  // Auto-load active version into the Advanced section when it's opened and
  // when the agent dropdown changes. We don't auto-fire on page load anymore —
  // the Advanced section is collapsed by default.
  const loadActiveBtn = document.getElementById('loadActiveBtn');
  const advancedSection = document.getElementById('promptLabAdvanced');
  if (loadActiveBtn) {
    let loadedOnce = false;
    const loadIfFirstOpen = () => {
      if (!loadedOnce && advancedSection?.open) {
        loadedOnce = true;
        loadActiveBtn.click();
      }
    };
    if (advancedSection) {
      advancedSection.addEventListener('toggle', loadIfFirstOpen);
    }
    const agentSelect = document.getElementById('promptLabAgentType');
    if (agentSelect) {
      agentSelect.addEventListener('change', () => loadActiveBtn.click());
    }
  }

  // Auto-refresh performance context every 5 minutes
  setInterval(loadPerformanceContext, 5 * 60 * 1000);
});
