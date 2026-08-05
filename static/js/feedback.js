let feedbackTrendCharts = null; // { success: Chart, profit: Chart, labels: [] }
const promptFallbackDescriptions = {
  summarizer: 'Latest summarizer template in use.',
  decider: 'Latest decision-making template in use.',
  feedback: 'Default system analysis prompt - comprehensive system-wide feedback.'
};
const promptElementMap = {
  summarizer: {
    version: 'summarizerVersion',
    label: 'summarizerVersionLabel',
    shortDescription: 'summarizerDescriptionShort',
    fullDescription: 'summarizerDescriptionFull',
    system: 'summarizerSystemPrompt',
    user: 'summarizerUserTemplate'
  },
  decider: {
    version: 'deciderVersion',
    label: 'deciderVersionLabel',
    shortDescription: 'deciderDescriptionShort',
    fullDescription: 'deciderDescriptionFull',
    system: 'deciderSystemPrompt',
    user: 'deciderUserTemplate'
  },
  feedback: {
    version: 'feedbackVersion',
    label: 'feedbackVersionLabel',
    shortDescription: 'feedbackDescriptionShort',
    fullDescription: 'feedbackDescriptionFull',
    system: 'feedbackSystemPrompt',
    user: 'feedbackUserTemplate'
  }
};

function setText(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
}

function updatePromptCard(prefix, prompt) {
  const mapping = promptElementMap[prefix];
  if (!mapping) return;

  const version = (prompt && prompt.version !== undefined && prompt.version !== null)
    ? `v${prompt.version}`
    : '--';
  const versionLabel = (prompt && prompt.version !== undefined && prompt.version !== null)
    ? `v${prompt.version}`
    : 'No active version';

  const description = (prompt && typeof prompt.description === 'string' && prompt.description.trim().length)
    ? prompt.description.trim()
    : promptFallbackDescriptions[prefix] || 'Active template.';

  const rawSystem = prompt && typeof prompt.system_prompt === 'string' ? prompt.system_prompt : '';
  const renderedSystem = prompt && typeof prompt.rendered_system_prompt === 'string' ? prompt.rendered_system_prompt : '';
  const systemPrompt = (renderedSystem || rawSystem || '').trim() || 'Not configured.';

  const rawUser = prompt && typeof prompt.user_prompt === 'string' ? prompt.user_prompt : '';
  const renderedUser = prompt && typeof prompt.rendered_user_prompt === 'string' ? prompt.rendered_user_prompt : '';
  const userTemplate = (renderedUser || rawUser || '').trim() || 'Not configured.';

  setText(mapping.version, version);
  setText(mapping.label, versionLabel);
  setText(mapping.shortDescription, description);
  setText(mapping.fullDescription, description);
  setText(mapping.system, systemPrompt);
  setText(mapping.user, userTemplate);
}

async function loadPromptDetails() {
  try {
    const data = await fetchJSON('/api/prompts/active');
    const prompts = data.prompts || {};
    updatePromptCard('summarizer', prompts.summarizer);
    updatePromptCard('decider', prompts.decider);
    updatePromptCard('feedback', prompts.feedback);
  } catch (e) {
    console.error('Error loading prompt templates:', e);
  }
}

async function resetPromptsToBaseline() {
  const status = document.getElementById('promptResetStatus');
  if (status) {
    status.textContent = 'Resetting prompts to baseline...';
    status.style.color = '#555';
  }
  try {
    const response = await fetch('/api/prompts/reset', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok || payload.status !== 'success') {
      throw new Error(payload.message || 'Reset failed');
    }
    if (status) {
      status.textContent = 'Prompts reset to baseline (v0). Use "Undo Last Prompt Change" to revert.';
      status.style.color = '#2e7d32';
    }
    await loadPromptDetails();
  } catch (err) {
    console.error('Prompt reset failed:', err);
    if (status) {
      status.textContent = `Reset failed: ${err.message}`;
      status.style.color = '#c62828';
    }
  }
}

async function undoLastPromptChange() {
  const status = document.getElementById('promptResetStatus');
  if (status) {
    status.textContent = 'Undoing last prompt change...';
    status.style.color = '#555';
  }
  try {
    const response = await fetch('/api/prompts/undo', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok || !payload.undone) {
      throw new Error(payload.message || 'Nothing to undo');
    }
    const restored = (payload.reverted || [])
      .filter((r) => r.changed)
      .map((r) => `${r.agent_type} → ${r.to_version === null ? 'none' : `v${r.to_version}`}`)
      .join(', ');
    if (status) {
      status.textContent = restored
        ? `Undid "${payload.undid_action}": ${restored}. Undo again to re-apply.`
        : 'Undo recorded, but no versions changed.';
      status.style.color = '#2e7d32';
    }
    await loadPromptDetails();
  } catch (err) {
    console.error('Prompt undo failed:', err);
    if (status) {
      status.textContent = `Undo failed: ${err.message}`;
      status.style.color = '#c62828';
    }
  }
}

function formatMaybePct(v) {
  const n = Number(v || 0);
  return `${n.toFixed(2)}%`;
}
function formatFeedbackBlock(txt) {
  if (!txt || txt === 'null') return 'No specific guidance available';
  return (txt.startsWith('"') && txt.endsWith('"')) ? txt.slice(1, -1) : txt;
}
async function loadLatestFeedback() {
  const el = document.getElementById('latestFeedback');
  try {
    const data = await fetchJSON('/api/feedback');
    if (data.status === 'success' && data.latest_feedback) {
      const f = data.latest_feedback;
      const html = `
        <div class="feedback-history-item">
          <h4>📊 Analysis Summary (${f.total_trades_analyzed} trades)</h4>
          <div class="timestamp">${new Date().toLocaleString()}</div>
          <div style="margin-bottom: 15px;">
            <strong>Success Rate:</strong> ${(f.success_rate * 100).toFixed(1)}%<br>
            <strong>Average Profit:</strong> ${formatMaybePct(f.avg_profit_percentage)}
          </div>
          <h4>📝 Summarizer Guidance:</h4>
          <div class="content">${formatFeedbackBlock(f.summarizer_feedback)}</div>
          <h4>🎯 Decider Guidance:</h4>
          <div class="content">${formatFeedbackBlock(f.decider_feedback)}</div>
          ${f.recommended_adjustments?.key_insights?.length ? `
            <h4>💡 Key Insights:</h4>
            <ul style="margin-top:10px;">
              ${f.recommended_adjustments.key_insights.map(x => `<li>${x}</li>`).join('')}
            </ul>` : '' }
        </div>`;
      el.innerHTML = html;
      const p30 = data.period_analysis?.['30d'];
      if (p30) {
        document.getElementById('successRate').textContent = `${(p30.success_rate * 100).toFixed(1)}%`;
        document.getElementById('avgProfit').textContent = `${(p30.avg_profit * 100).toFixed(2)}%`;
        document.getElementById('tradeCount').textContent = p30.total_trades;
      }
      // Drive the chart from the user's selected range. When it's the default
      // set, reuse the data we just fetched; otherwise fetch the chosen windows.
      if (selectedTrendPeriods === DEFAULT_TREND_PERIODS && data.period_analysis) {
        updatePerformanceChart(data.period_analysis);
      } else {
        refreshPerformanceChart(selectedTrendPeriods);
      }
    } else {
      el.innerHTML = '<p>No recent feedback analysis available</p>';
    }
  } catch (e) {
    el.innerHTML = `<p style="color:red;">Error loading feedback: ${e.message}</p>`;
  }
}
const DEFAULT_TREND_PERIODS = '7,14,30,60,90';
let selectedTrendPeriods = DEFAULT_TREND_PERIODS;

// --- Performance trend panels (small multiples, one axis each) --------------
// Windows are trailing and NESTED (30d includes 14d includes 7d). Plotted
// widest-first so the x-axis reads left → right as history narrowing toward
// now: the rightmost point is always the freshest window.
const TREND_INK = {
  text: '#9bb0cc', muted: '#7f8ca6', label: '#c9d6ee',
  grid: 'rgba(255,255,255,0.05)', gridStrong: 'rgba(255,255,255,0.22)',
  axis: 'rgba(255,255,255,0.12)', tooltipBg: '#151f35', tooltipBorder: '#3a4a63',
};
const TREND_SUCCESS_COLOR = '#29d697';
const TREND_PROFIT_COLOR = '#42c9ff';

function trendRgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Direct-label only the rightmost (most recent) point of the series.
// Reads the formatter off the chart instance ($trendFmt) — options-level
// custom keys don't survive Chart.js v4's config resolver.
const trendEndLabelPlugin = {
  id: 'trendEndLabel',
  afterDatasetsDraw(chart) {
    const fmt = chart.$trendFmt;
    if (!fmt) return;
    const meta = chart.getDatasetMeta(0);
    const pt = meta.data[meta.data.length - 1];
    if (!pt) return;
    const value = chart.data.datasets[0].data[chart.data.datasets[0].data.length - 1];
    const { ctx } = chart;
    ctx.save();
    ctx.font = '600 11px Inter, system-ui, sans-serif';
    ctx.fillStyle = TREND_INK.label;
    ctx.textBaseline = 'middle';
    const text = fmt(value);
    // Right of the point unless that would clip at the canvas edge.
    const fitsRight = pt.x + 9 + ctx.measureText(text).width < chart.width - 4;
    ctx.textAlign = fitsRight ? 'left' : 'right';
    ctx.fillText(text, fitsRight ? pt.x + 9 : pt.x - 9, pt.y);
    ctx.restore();
  }
};

function buildTrendChart(canvasId, { color, labels, data, trades, fmt, guideValue, yOpts, tickOpts = {}, showXTicks }) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        borderColor: color,
        borderWidth: 2,
        backgroundColor: trendRgba(color, 0.07),
        fill: true,
        tension: 0,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: color,
        pointBorderColor: '#121c33',
        pointBorderWidth: 1.5,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { right: 56, top: 8 } },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          grid: { display: false },
          border: { color: TREND_INK.axis },
          ticks: { display: showXTicks, color: TREND_INK.muted, font: { size: 11 } },
        },
        y: {
          ...yOpts,
          border: { display: false },
          // Emphasize the interpretive baseline (50% coin-flip / 0% breakeven).
          grid: { color: c => c.tick.value === guideValue ? TREND_INK.gridStrong : TREND_INK.grid },
          ticks: { color: TREND_INK.muted, font: { size: 11 }, maxTicksLimit: 6, callback: v => `${v}%`, ...tickOpts },
          // Fixed axis width keeps both panels' plot areas x-aligned.
          afterFit: axis => { axis.width = 58; },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: TREND_INK.tooltipBg, borderColor: TREND_INK.tooltipBorder,
          borderWidth: 1, titleColor: '#dfe8f7', bodyColor: TREND_INK.text,
          padding: 10, displayColors: false,
          callbacks: {
            title: items => items.length ? items[0].label : '',
            label: item => {
              const n = item.chart.$trendTrades?.[item.dataIndex];
              return `${fmt(item.parsed.y)}${Number.isFinite(n) ? ` across ${n} closed trades` : ''}`;
            },
          },
        },
      },
    },
    plugins: [trendEndLabelPlugin],
  });
  chart.$trendTrades = trades;
  chart.$trendFmt = fmt;
  chart.draw(); // re-draw so the end label (which needs $trendFmt) appears
  return chart;
}

function updatePerformanceChart(periodData) {
  // Widest window first → most recent (7d) lands on the right.
  const periods = Object.keys(periodData || {})
    .map(k => ({ key: k, days: parseInt(k, 10) }))
    .filter(p => !Number.isNaN(p.days))
    .sort((a, b) => b.days - a.days);
  if (!periods.length) return;
  const labels = periods.map(p => p.days >= 365 ? `Last ${Math.round(p.days / 365)}y` : `Last ${p.days}d`);
  const successRates = periods.map(p => (periodData[p.key]?.success_rate || 0) * 100);
  const avgProfits = periods.map(p => (periodData[p.key]?.avg_profit || 0) * 100);
  const trades = periods.map(p => periodData[p.key]?.total_trades);

  // Update in place when the panels exist and the x-axis still matches.
  // Destroying + recreating every 10s caused the visible flicker.
  if (feedbackTrendCharts
      && feedbackTrendCharts.labels.length === labels.length
      && feedbackTrendCharts.labels.every((l, i) => l === labels[i])) {
    for (const [chart, data] of [[feedbackTrendCharts.success, successRates], [feedbackTrendCharts.profit, avgProfits]]) {
      chart.data.datasets[0].data = data;
      chart.$trendTrades = trades;
      chart.update('none'); // no animation, no re-create
    }
    return;
  }

  if (feedbackTrendCharts) {
    feedbackTrendCharts.success.destroy();
    feedbackTrendCharts.profit.destroy();
  }
  feedbackTrendCharts = {
    labels,
    success: buildTrendChart('successRateChart', {
      color: TREND_SUCCESS_COLOR, labels, data: successRates, trades,
      fmt: v => `${v.toFixed(1)}%`,
      guideValue: 50, // coin-flip baseline
      yOpts: { suggestedMin: 40, suggestedMax: 80 },
      tickOpts: { stepSize: 10 }, // guarantees a tick (and guide line) at 50

      showXTicks: false, // shared x — labels live on the bottom panel
    }),
    profit: buildTrendChart('avgProfitChart', {
      color: TREND_PROFIT_COLOR, labels, data: avgProfits, trades,
      fmt: v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
      guideValue: 0, // breakeven baseline
      yOpts: { beginAtZero: true },
      showXTicks: true,
    }),
  };
}

// Re-fetch the chart for a chosen set of lookback windows (range buttons + poll).
async function refreshPerformanceChart(periodsCsv) {
  try {
    const data = await fetchJSON(`/api/feedback?periods=${encodeURIComponent(periodsCsv)}`);
    if (data?.period_analysis) updatePerformanceChart(data.period_analysis);
  } catch (e) {
    console.error('Error loading performance chart:', e);
  }
}

function setupTrendRangeButtons() {
  const wrap = document.getElementById('trendRangeButtons');
  if (!wrap) return;
  wrap.querySelectorAll('.trend-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.trend-range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedTrendPeriods = btn.dataset.periods;
      refreshPerformanceChart(selectedTrendPeriods);
    });
  });
}
async function loadFeedbackHistory() {
  const el = document.getElementById('feedbackHistory');
  try {
    const log = await fetchJSON('/api/feedback_log');
    document.getElementById('feedbackCount').textContent = Array.isArray(log) ? log.length : 0;
    if (!Array.isArray(log) || !log.length) {
      el.innerHTML = '<p>No feedback history available</p>';
      return;
    }
    const lastTen = log.slice(0, 10);
    el.innerHTML = lastTen.map((entry, idx) => `
      <div class="feedback-history-item">
        <h4>📊 Feedback Analysis #${log.length - idx}</h4>
        <div class="timestamp">${new Date(entry.timestamp).toLocaleString()} (${entry.lookback_days} days lookback)</div>
        <div style="margin-bottom: 15px;">
          <strong>Trades Analyzed:</strong> ${entry.trades_analyzed}<br>
          <strong>Success Rate:</strong> ${entry.success_rate.toFixed(1)}%<br>
          <strong>Average Profit:</strong> ${entry.avg_profit.toFixed(2)}%
        </div>
        <h4>📝 Summarizer Guidance:</h4>
        <div class="content">${formatFeedbackBlock(entry.summarizer_feedback)}</div>
        <h4>🎯 Decider Guidance:</h4>
        <div class="content">${formatFeedbackBlock(entry.decider_feedback)}</div>
      </div>`).join('');
  } catch (e) {
    el.innerHTML = `<p style="color:red;">Error loading feedback history: ${e.message}</p>`;
  }
}
let currentOutcomes = [];
let currentSort = { column: 'sell_date', direction: 'desc' };
async function loadTradeOutcomes() {
  try {
    const outcomes = await fetchJSON('/api/trade_outcomes');
    if (Array.isArray(outcomes)) {
      currentOutcomes = outcomes;
      updateOutcomesTable(currentOutcomes);
      setupTableSorting();
    }
  } catch (e) {
    console.error('Error loading trade outcomes:', e);
  }
}
function updateOutcomesTable(outcomes) {
  const tbody = document.getElementById('outcomesBody');
  if (outcomes.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9">No trade outcomes recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = outcomes.map(outcome => {
    const netGainClass = outcome.net_gain_dollars >= 0 ? 'text-success' : 'text-danger';
    const netGainValue = outcome.net_gain_dollars >= 0 ? 
      `$${outcome.net_gain_dollars.toFixed(2)}` : 
      `-$${Math.abs(outcome.net_gain_dollars).toFixed(2)}`;
    const percentageClass = outcome.gain_loss_pct >= 0 ? 'text-success' : 'text-danger';
    const percentageValue = outcome.gain_loss_pct >= 0 ? 
      `${outcome.gain_loss_pct.toFixed(2)}%` : 
      `-${Math.abs(outcome.gain_loss_pct).toFixed(2)}%`;
    return `
      <tr class="outcome-${outcome.category}">
        <td><strong>${outcome.ticker}</strong></td>
        <td>${new Date(outcome.sell_date).toLocaleDateString()}</td>
        <td>${outcome.shares.toFixed(0)}</td>
        <td>$${outcome.purchase_price.toFixed(2)}</td>
        <td>$${outcome.sell_price.toFixed(2)}</td>
        <td class="${netGainClass}"><strong>${netGainValue}</strong></td>
        <td class="${percentageClass}"><strong>${percentageValue}</strong></td>
        <td>${outcome.category.replace('_', ' ').toUpperCase()}</td>
        <td>${outcome.hold_days || 'N/A'}</td>
      </tr>`;
  }).join('');
}
function setupTableSorting() {
  const headers = document.querySelectorAll('.outcomes-table th.sortable');
  headers.forEach(header => {
    header.addEventListener('click', () => {
      const column = header.dataset.column;
      if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
      } else {
        currentSort = { column, direction: 'asc' };
      }
      headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
      header.classList.add(currentSort.direction === 'asc' ? 'sort-asc' : 'sort-desc');
      sortOutcomes(column, currentSort.direction);
    });
  });
  const defaultHeader = document.querySelector(`[data-column="${currentSort.column}"]`);
  if (defaultHeader) defaultHeader.classList.add(`sort-${currentSort.direction}`);
}
function sortOutcomes(column, direction) {
  const sorted = [...currentOutcomes].sort((a, b) => {
    let aVal = a[column], bVal = b[column];
    switch (column) {
      case 'sell_date': aVal = new Date(aVal); bVal = new Date(bVal); break;
      case 'shares':
      case 'purchase_price':
      case 'sell_price':
      case 'net_gain_dollars':
      case 'gain_loss_pct':
      case 'hold_days':
        aVal = parseFloat(aVal) || 0; bVal = parseFloat(bVal) || 0; break;
      case 'ticker':
      case 'category':
        aVal = String(aVal).toLowerCase(); bVal = String(bVal).toLowerCase(); break;
    }
    if (aVal < bVal) return direction === 'asc' ? -1 : 1;
    if (aVal > bVal) return direction === 'asc' ?  1 : -1;
    return 0;
  });
  updateOutcomesTable(sorted);
}
function refreshFeedbackData() {
  loadLatestFeedback();
  loadFeedbackHistory();
  loadTradeOutcomes();
  // Keep the active-prompt version card in sync with approvals made in the
  // Prompt Lab. Previously this only ran once on page load, so the Feedback
  // page showed a stale version until a hard reload.
  loadPromptDetails();
}

// Instant cross-page sync: the Prompt Lab broadcasts on the 'dai-prompts'
// channel whenever a new version is approved/activated. Refresh immediately
// so the Feedback page never lags behind the Prompt Lab.
try {
  const promptSyncChannel = new BroadcastChannel('dai-prompts');
  promptSyncChannel.onmessage = (event) => {
    if (event?.data?.type === 'prompt-applied') {
      loadPromptDetails();
    }
  };
} catch (_) {
  // BroadcastChannel unsupported — the 10s poll above still keeps us in sync.
}

// Back/forward navigation restores pages from the bfcache without re-running
// DOMContentLoaded, which would otherwise show stale prompt versions. Force a
// refresh when the page is shown from cache.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    loadPromptDetails();
    refreshFeedbackData();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  loadPromptDetails();
  refreshFeedbackData();
  setInterval(refreshFeedbackData, 10000);
  setupTrendRangeButtons();
  const resetBtn = document.getElementById('resetPromptsBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', resetPromptsToBaseline);
  }
  const undoBtn = document.getElementById('undoPromptChangeBtn');
  if (undoBtn) {
    undoBtn.addEventListener('click', undoLastPromptChange);
  }
});
