const AGENT_TYPES = ['SummarizerAgent', 'DeciderAgent', 'FeedbackAgent'];
const AGENT_LABELS = {
  SummarizerAgent: 'Summarizer',
  DeciderAgent: 'Decider',
  FeedbackAgent: 'Feedback'
};

const selectedVersions = {
  SummarizerAgent: [],
  DeciderAgent: [],
  FeedbackAgent: []
};

// Notify any other open dashboard page (e.g. the Feedback tab) that a new
// prompt version was activated, so it can refresh its version display
// instantly instead of waiting for its poll interval.
function broadcastPromptApplied(agentType, version) {
  try {
    const channel = new BroadcastChannel('dai-prompts');
    channel.postMessage({ type: 'prompt-applied', agent: agentType, version });
    channel.close();
  } catch (_) {
    // BroadcastChannel unsupported — other pages fall back to polling.
  }
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

    const statCards = [
      { label: 'Win Rate', value: formatPercent(stats.win_rate, 1) },
      { label: 'Avg Profit', value: formatPercent(stats.avg_profit_pct, 2, true) },
      { label: 'Total Trades', value: String(stats.total_trades ?? 0) },
      { label: 'Best Trade', value: formatTrade(stats.best_trade) },
      { label: 'Worst Trade', value: formatTrade(stats.worst_trade) }
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
  const loadingEl = document.getElementById('historyLoading');
  const columnsEl = document.getElementById('timelineColumns');
  const errorEl = document.getElementById('historyError');

  setHidden(loadingEl, false);
  setHidden(columnsEl, true);
  setHidden(errorEl, true);
  clearAllSelections();

  try {
    const data = await apiJSON('/api/prompt-evolution/history');

    AGENT_TYPES.forEach((agentType) => {
      const entries = Array.isArray(data?.[agentType]) ? data[agentType] : [];
      renderTimeline(agentType, entries);
    });

    setHidden(columnsEl, false);
  } catch (error) {
    errorEl.textContent = `Failed to load prompt history: ${error.message}`;
    setHidden(errorEl, false);
  } finally {
    setHidden(loadingEl, true);
  }
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
      clearPromptLabAlerts();
      setPromptLabMessage('Loading active version...');
      const originalLabel = loadActiveBtn.textContent;
      loadActiveBtn.disabled = true;
      loadActiveBtn.textContent = 'Loading...';

      try {
        const data = await apiJSON(`/api/prompts/${encodeURIComponent(agentType)}/active`);
        if (!data || data.error) throw new Error(data?.error || 'No active prompt found');

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
      showPromptLabError(`Failed to generate prompt: ${error.message}`);
      setPromptLabMessage('');
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = originalLabel;
    }
  });

  applyBtn.addEventListener('click', async () => {
    const agentType = agentSelect.value;
    const systemPrompt = systemPromptEl.value.trim();
    const userPromptTemplate = userPromptEl.value.trim();
    const strategyDirectives = strategyDirectivesEl ? strategyDirectivesEl.value.trim() : '';
    const soul = soulEl ? soulEl.value.trim() : '';
    const memory = memoryEl ? memoryEl.value.trim() : '';
    const description = descriptionEl.value.trim();

    clearPromptLabAlerts();

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
        description
      };
      const data = await apiJSON('/api/prompt-evolution/apply', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (!data?.success) {
        throw new Error('API did not confirm success.');
      }

      showPromptLabSuccess(`Applied successfully as version v${data.version}.`);
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
  for (const line of diffLines) {
    if (typeof line !== 'string') continue;
    if (line.startsWith('+') && !line.startsWith('+++')) added++;
    else if (line.startsWith('-') && !line.startsWith('---')) removed++;
  }
  return { added, removed };
}

function buildDiffSection(label, diffLines, openByDefault, sectionChanges) {
  const wrap = document.createElement('details');
  wrap.className = 'pe-diff-section';
  if (openByDefault) wrap.open = true;

  const summary = document.createElement('summary');
  const { added, removed } = countDiffStats(diffLines);
  const totalChanged = added + removed;
  summary.innerHTML = `${label} <span style="color:#888; font-weight:normal; font-size:0.9em;">— ${
    totalChanged
      ? `<span style="color:#2e7d32;">+${added}</span> / <span style="color:#c62828;">-${removed}</span>`
      : '<span style="color:#888;">no changes</span>'
  }</span>`;
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
  if (!totalChanged) {
    const empty = document.createElement('div');
    empty.className = 'pe-diff-empty';
    empty.textContent = 'No changes from active version.';
    view.appendChild(empty);
  } else {
    renderDiff(diffLines, view);
  }
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
  const behavioral = change.behavioral ? 'behavioral' : 'cosmetic';
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
      b.classList.toggle('active', b.dataset.agent === agentType);
    });
    panelsEl.querySelectorAll('.pe-tab-panel').forEach((p) => {
      p.classList.toggle('active', p.dataset.agent === agentType);
    });
  }

  function renderTabsAndPanels(candidates, errors) {
    tabsEl.innerHTML = '';
    panelsEl.innerHTML = '';

    // Failed-generation tabs first (so they're visible)
    const errorByAgent = {};
    (errors || []).forEach((e) => { errorByAgent[e.agent_type] = e.error; });

    const order = ['SummarizerAgent', 'DeciderAgent', 'FeedbackAgent'];
    order.forEach((agentType) => {
      const candidate = candidates.find((c) => c.agent_type === agentType);
      const errMsg = errorByAgent[agentType];

      // Tab button
      const tabBtn = document.createElement('button');
      tabBtn.type = 'button';
      tabBtn.className = 'pe-tab-btn';
      tabBtn.dataset.agent = agentType;
      tabBtn.setAttribute('role', 'tab');

      const label = AGENT_LABELS[agentType] || agentType;
      if (candidate) {
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
          ? '<span class="pe-tab-impact substantive" title="substantive: has behaviorally-major changes">●</span>'
          : '<span class="pe-tab-impact cosmetic" title="cosmetic only: reword/no behavior change">●</span>';
        tabBtn.innerHTML = `${impactDot}${label} <span class="pe-diff-badge"><span class="add">+${added}</span> / <span class="rem">-${removed}</span></span>`;
      } else {
        tabBtn.classList.add('failed');
        tabBtn.innerHTML = `${label} <span class="pe-diff-badge" style="color:#c62828;">⚠ failed</span>`;
      }
      tabBtn.addEventListener('click', () => activateTab(agentType));
      tabsEl.appendChild(tabBtn);

      // Tab panel
      const panel = document.createElement('div');
      panel.className = 'pe-tab-panel';
      panel.dataset.agent = agentType;
      panel.setAttribute('role', 'tabpanel');

      if (errMsg) {
        const errBox = document.createElement('div');
        errBox.className = 'pe-error';
        errBox.style.marginTop = '12px';
        errBox.textContent = `Generation failed for ${label}: ${errMsg}`;
        panel.appendChild(errBox);
        panelsEl.appendChild(panel);
        return;
      }

      // Behavioral-impact summary — the headline for "is this change worth it?"
      const cs = candidate.change_summary || {};
      const summaryWrap = document.createElement('div');
      summaryWrap.className = 'pe-impact-summary';
      const substantive = cs.is_substantive;
      summaryWrap.innerHTML = `
        <span class="pe-impact-pill ${substantive ? 'substantive' : 'cosmetic'}">${substantive ? 'SUBSTANTIVE' : 'COSMETIC ONLY'}</span>
        <span class="pe-impact-counts">${cs.major || 0} major · ${cs.minor || 0} minor · ${cs.behavioral || 0} behavioral</span>
        <span class="pe-impact-hint">— click a chip below to see why each change was made</span>`;
      panel.appendChild(summaryWrap);

      // Reasoning
      const reasoningWrap = document.createElement('div');
      reasoningWrap.className = 'pe-field';
      reasoningWrap.innerHTML = `<label>Reasoning <span style="color:#888; font-weight:normal;">— v${candidate.current_version} → v${candidate.current_version + 1}</span></label>`;
      const reasoningBox = document.createElement('div');
      reasoningBox.className = 'pe-reasoning';
      reasoningBox.textContent = candidate.reasoning || 'No reasoning returned by API.';
      reasoningWrap.appendChild(reasoningBox);
      panel.appendChild(reasoningWrap);

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
      diffMap.forEach(({ key, section: sec, label: lbl, open }) => {
        const section = buildDiffSection(lbl, candidate.diffs?.[key] || [], open, changesBySection[sec] || []);
        panel.appendChild(section);
      });

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
        const description = (descInput.value || '').trim() || candidate.description;
        if (!description) {
          statusSpan.style.color = '#c62828';
          statusSpan.textContent = 'Description required.';
          return;
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
          };
          const data = await apiJSON('/api/prompt-evolution/apply', {
            method: 'POST',
            body: JSON.stringify(payload),
          });
          if (!data?.success) throw new Error('API did not confirm success.');

          tabBtn.classList.add('approved');
          statusSpan.style.color = '#2e7d32';
          statusSpan.textContent = `✓ Activated as v${data.version}`;
          approveBtn.textContent = `Active v${data.version}`;
          rejectBtn.disabled = true;
          descInput.disabled = true;
          showBatchSuccess(`${AGENT_LABELS[candidate.agent_type]} v${data.version} activated.`);
          broadcastPromptApplied(candidate.agent_type, data.version);
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
        tabBtn.classList.add('rejected');
        statusSpan.style.color = '#999';
        statusSpan.textContent = '✗ Rejected (candidate discarded client-side).';
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        descInput.disabled = true;
      });

      panel.appendChild(decisionBar);
      panelsEl.appendChild(panel);
    });

    // Activate first successful candidate's tab (or first tab if all failed)
    const firstSuccessful = candidates[0]?.agent_type || order[0];
    activateTab(firstSuccessful);
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
    if (job.phase === 'feedback') {
      return job.message || 'Step 1/2 — Running FeedbackAgent…';
    }
    if (job.phase === 'generate') {
      const done = (job.completed_agents || []).length;
      return `Step 2/2 — Evolving prompts (${done}/3 complete)…`;
    }
    return job.message || 'Working…';
  };

  function renderFinishedJob(job) {
    if (job.feedback_summary) renderFeedbackBanner(job.feedback_summary);
    const candidates = job.candidates || [];
    const errors = job.errors || [];
    renderTabsAndPanels(candidates, errors);
    setHidden(resultsEl, false);

    const successCount = candidates.length;
    const failCount = errors.length;
    const ts = new Date(job.finished_at || Date.now()).toLocaleString();
    if (statusEl) {
      statusEl.style.color = failCount ? '#b26a00' : '#2e7d32';
      statusEl.textContent = `Generated ${successCount}/3 candidates at ${ts}${
        failCount ? ` (${failCount} failed — see tab)` : ''
      }. Review each tab and approve or reject.`;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  async function pollOnce(jobId) {
    try {
      const res = await fetch(`/api/prompt-evolution/batch-status/${encodeURIComponent(jobId)}`);
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
      // Unknown status — back off and try again.
      pollTimer = setTimeout(() => pollOnce(jobId), POLL_INTERVAL_MS);
    } catch (err) {
      // Transient network error — keep polling.
      console.warn('batch-status poll error:', err);
      pollTimer = setTimeout(() => pollOnce(jobId), POLL_INTERVAL_MS * 2);
    }
  }

  function startPolling(jobId) {
    activeJobId = jobId;
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
    setHidden(resultsEl, true);
    setRunningUI('Queuing batch job…');
    try {
      const data = await apiJSON('/api/prompt-evolution/refresh-and-generate-all', {
        method: 'POST',
        body: JSON.stringify({}),
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
    }
  });

  resumeFromLocalStorage();
}

document.addEventListener('DOMContentLoaded', () => {
  loadPerformanceContext();
  loadPromptHistory();
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
