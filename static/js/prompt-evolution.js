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

  if (!agentSelect || !generateBtn || !applyBtn) return;

  generateBtn.addEventListener('click', async () => {
    const agentType = agentSelect.value;
    clearPromptLabAlerts();
    setPromptLabMessage('Generating prompt candidate...');

    const originalLabel = generateBtn.textContent;
    generateBtn.disabled = true;
    generateBtn.textContent = 'Generating...';

    try {
      const data = await apiJSON('/api/prompt-evolution/generate', {
        method: 'POST',
        body: JSON.stringify({ agent_type: agentType })
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

document.addEventListener('DOMContentLoaded', () => {
  loadPerformanceContext();
  loadPromptHistory();
  setupPromptLab();

  // Auto-refresh performance context every 5 minutes
  setInterval(loadPerformanceContext, 5 * 60 * 1000);
});
