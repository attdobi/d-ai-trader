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
  return Number.isFinite(v) ? `${v.toFixed(2)}%` : '—';
}
function feedbackEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function feedbackDate(value) {
  if (!value) return null;
  const source = String(value);
  // Flask can serialize datetimes as RFC 1123 GMT; ledger/API ISO values may
  // omit a zone. Preserve explicit RFC zones and interpret naive ISO as UTC.
  const raw = /(?:GMT|UTC)$/i.test(source) ? source : source.replace(' ', 'T');
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2}|GMT|UTC)$/i.test(raw) ? raw : `${raw}Z`);
  return Number.isFinite(date.getTime()) ? date : null;
}
function feedbackUTCLabel(value) {
  const date = feedbackDate(value);
  return date ? date.toISOString().slice(0,16).replace('T',' ') + ' UTC' : 'Not recorded';
}
function feedbackLocalLabel(value) {
  return feedbackDate(value)?.toLocaleString() || 'Not recorded';
}
function winRateInterval(wins, n) {
  if (!Number.isSafeInteger(n) || n <= 0 || !Number.isSafeInteger(wins) || wins < 0 || wins > n) return null;
  // Two-sided 95% Wilson binomial interval; nonzero uncertainty at 0/N and N/N.
  const z=1.959963984540054, z2=z*z, denominator=n+z2;
  const center=(wins+z2/2)/denominator;
  const half=z*Math.sqrt(wins*(1-wins/n)+z2/4)/denominator;
  return {lower:Math.max(0,center-half),upper:Math.min(1,center+half)};
}
function winRateIntervalLabel(row) {
  const interval=winRateInterval(row?.wins,row?.n);
  return interval ? `95% win-rate CI (Wilson): ${(interval.lower*100).toFixed(1)}%–${(interval.upper*100).toFixed(1)}%` : '95% win-rate CI: unavailable';
}
function performanceRows(periodData) {
  return Object.entries(periodData || {}).filter(([key]) => /^\d+d$/.test(key))
    .map(([key, value]) => {
      const metric = value || {}, n = Number.isInteger(metric.total_trades) && metric.total_trades >= 0 ? metric.total_trades : null;
      return {key, days:parseInt(key,10), label:`Last ${key}`, metric, n,
        wins:Number.isInteger(metric.wins) ? metric.wins : null,
        rate:n > 0 && Number.isFinite(metric.success_rate) ? metric.success_rate * 100 : null,
        mean:n > 0 && Number.isFinite(metric.avg_profit) ? metric.avg_profit * 100 : null};
    }).sort((a,b) => b.days - a.days);
}
function outcomeStreak(outcomes) {
  const sorted=[...(outcomes || [])].sort((a,b)=>(feedbackDate(b.sell_date)?.getTime() ?? -Infinity)-(feedbackDate(a.sell_date)?.getTime() ?? -Infinity) || (b.id ?? 0)-(a.id ?? 0));
  const kind=row=>!Number.isFinite(row.gain_loss_pct)?'unscored':row.gain_loss_pct>0?'winning':row.gain_loss_pct<0?'losing':'flat';
  const type=sorted.length?kind(sorted[0]):'none';
  let count=0;
  if(['winning','losing'].includes(type)) for(const row of sorted){if(kind(row)!==type)break;count++;}
  return {type,count,capped:count===50&&sorted.length===50};
}
let outcomeDonut=null;
function renderOutcomeOverview(outcomes) {
  const categories=[['significant_profit','Significant Profit','#29d697'],['moderate_profit','Moderate Profit','#42c9ff'],['break_even','Break Even','#fadb5f'],['moderate_loss','Moderate Loss','#ff8a5c'],['significant_loss','Significant Loss','#ff5f73'],['unclassified','Unclassified','#7f8ca6']];
  const counts=new Map(categories.map(([id])=>[id,0]));
  for(const row of outcomes){const id=counts.has(row.category)?row.category:'unclassified';counts.set(id,counts.get(id)+1);}
  const data=categories.map(([id])=>counts.get(id));
  if(outcomeDonut){outcomeDonut.data.datasets[0].data=data;outcomeDonut.update('none');}
  else if(document.getElementById('winLossDonut')) outcomeDonut=new Chart(document.getElementById('winLossDonut').getContext('2d'),{
    type:'doughnut',data:{labels:categories.map(([,label])=>label),datasets:[{data,backgroundColor:categories.map(([, ,color])=>color+'33'),borderColor:categories.map(([, ,color])=>color),borderWidth:2}]},
    options:{responsive:true,animation:false,cutout:'65%',plugins:{legend:{position:'bottom',labels:{color:'#7f8ca6',usePointStyle:true,padding:12,font:{size:10}}},tooltip:{backgroundColor:'#151f35',titleColor:'#e6ecff',bodyColor:'#e6ecff'}}}});
  const {type,count,capped}=outcomeStreak(outcomes), color=type==='winning'?'#29d697':type==='losing'?'#ff5f73':'#7f8ca6';
  const value=document.getElementById('streakValue'),label=document.getElementById('streakLabel');
  if(value){value.textContent=count?`${count}${capped?'+':''}`:'—';value.style.color=color;}
  if(label){label.textContent=count?`${count}${capped?'+':''} closure ${type} streak · latest 50`:type==='none'?'No recorded closures':`Latest closure: ${type}`;label.style.color=color;}
}
function formatFeedbackBlock(txt) {
  if (!txt || txt === 'null') return 'No specific guidance available';
  return (txt.startsWith('"') && txt.endsWith('"')) ? txt.slice(1, -1) : txt;
}
async function loadLatestFeedback() {
  const el = document.getElementById('latestFeedback');
  try {
    const data = await fetchJSON('/api/feedback');
    if(data.status !== 'success') throw new Error('Saved feedback metrics are unavailable');
    const p30 = data.period_analysis?.['30d'];
    if (p30) {
      setText('successRate', p30.total_trades > 0 && Number.isFinite(p30.success_rate) ? `${(p30.success_rate * 100).toFixed(1)}%` : '—');
      setText('avgProfit', p30.total_trades > 0 ? formatMaybePct(Number.isFinite(p30.avg_profit) ? p30.avg_profit * 100 : null) : '—');
      setText('tradeCount', p30.total_trades ?? '—');
    }
    if (selectedTrendPeriods === DEFAULT_TREND_PERIODS && data.period_analysis) {
      updatePerformanceChart(data.period_analysis);
    } else {
      refreshPerformanceChart(selectedTrendPeriods);
    }
    if (data.status === 'success' && data.latest_feedback) {
      const f = data.latest_feedback;
      const html = `
        <div class="feedback-history-item">
          <h4>📊 Analysis Summary (${f.total_trades_analyzed} trades)</h4>
          <div class="timestamp">${feedbackEscape(feedbackLocalLabel(f.analysis_timestamp))}${f.lookback_period_days ? ` · ${f.lookback_period_days}-day analysis` : ''}</div>
          <div style="margin-bottom: 15px;">
            <strong>Win Rate:</strong> ${f.total_trades_analyzed > 0 && Number.isFinite(f.success_rate) ? `${(f.success_rate * 100).toFixed(1)}%` : '— (no closed-trade sample)'}<br>
            <strong>Average Return:</strong> ${f.total_trades_analyzed > 0 ? formatMaybePct(Number.isFinite(f.avg_profit_percentage) ? f.avg_profit_percentage * 100 : null) : '—'}
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
    } else {
      el.innerHTML = '<p>No recent feedback analysis available</p>';
    }
  } catch (e) {
    el.innerHTML = `<p style="color:red;">Error loading feedback: ${e.message}</p>`;
  }
}
const DEFAULT_TREND_PERIODS = '7,14,30,60,90';
let selectedTrendPeriods = DEFAULT_TREND_PERIODS;
let trendRequestSequence = 0;

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
    if (!Number.isFinite(value)) return;
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

function buildTrendChart(canvasId, { color, labels, data, rows, fmt, guideValue, yOpts, tickOpts = {}, showXTicks, showWinInterval = false }) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data,
        borderColor: color,
        borderWidth: 2,
        backgroundColor: trendRgba(color, 0.32),
        borderRadius: 5, borderSkipped: false, maxBarThickness: 56,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { right: 12, top: 8 } },
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
          // The zero-return line is a financial baseline; 50% is a reference,
          // not a claim that win rate alone establishes profitability.
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
            title: items => items.length ? itemWindowTitle(items[0].chart.$trendRows?.[items[0].dataIndex]) : '',
            label: item => {
              const row = item.chart.$trendRows?.[item.dataIndex];
              return `${fmt(item.parsed.y)} · ${row?.wins ?? '—'} wins / ${row?.n ?? '—'} scored closures`;
            },
            afterBody: items => {
              const row=items[0]?.chart.$trendRows?.[items[0].dataIndex];
              if(!row) return [];
              return [...(showWinInterval?[winRateIntervalLabel(row),'Small samples give wide intervals.']:[]),`${feedbackUTCLabel(row.metric.window?.start)} →`,feedbackUTCLabel(row.metric.window?.end)];
            },
          },
        },
      },
    },
  });
  chart.$trendRows = rows;
  return chart;
}

function itemWindowTitle(row) {return row ? `${row.label} · N=${row.n ?? '—'}` : '';}
function renderPerformanceAudit(rows) {
  const latest = rows[rows.length-1], summary=document.getElementById('trendWindowSummary'), body=document.getElementById('trendCohortBody');
  if(summary) summary.textContent = !latest ? 'No lookback data is available.' : latest.n > 0
    ? `${latest.label}: ${latest.wins ?? '—'} wins / ${latest.n} scored closures (${formatMaybePct(latest.rate)}). ${Number.isFinite(latest.metric.net_gain_dollars) ? `Recorded P&L ${formatDollars(latest.metric.net_gain_dollars)}. ` : ''}Cutoff: ${feedbackUTCLabel(latest.metric.window?.end)}.`
    : `${latest.label}: no scored closed trades. Win rate and average return are unavailable.`;
  if(summary) summary.title=latest?`N=${latest.n ?? '—'} · ${latest.wins ?? '—'} wins / ${latest.n ?? '—'} scored closures\n${winRateIntervalLabel(latest)}\nAssumes independent closures; related trades can add uncertainty.`:'';
  if(body) body.innerHTML = rows.map(row=>`<tr><th scope="row">${feedbackEscape(row.label)}<small>${feedbackEscape(feedbackUTCLabel(row.metric.window?.start))}<br>to ${feedbackEscape(feedbackUTCLabel(row.metric.window?.end))}</small></th><td>${row.n ?? '—'}${row.metric.unscored_trades ? `<small>${row.metric.unscored_trades} unscored</small>` : ''}</td><td>${row.wins ?? '—'} / ${row.metric.losses ?? '—'} / ${row.metric.flat_trades ?? '—'}</td><td>${formatMaybePct(row.rate)}</td><td>${fmtPct(row.mean)}</td><td>${formatDollars(row.metric.net_gain_dollars)}</td></tr>`).join('');
}
function formatDollars(value) {return Number.isFinite(value) ? `${value < 0 ? '−' : '+'}$${Math.abs(value).toFixed(2)}` : '—';}

function updatePerformanceChart(periodData) {
  // Widest window first → most recent (7d) lands on the right.
  const rows = performanceRows(periodData);
  renderPerformanceAudit(rows);
  const labels = rows.map(row=>[row.label, `N = ${row.n ?? '—'}`]);
  const successRates = rows.map(row=>row.rate), avgProfits = rows.map(row=>row.mean);

  // Update in place when the panels exist and the x-axis still matches.
  // Destroying + recreating every 10s caused the visible flicker.
  if (feedbackTrendCharts
      && feedbackTrendCharts.labels.length === labels.length
      && feedbackTrendCharts.labels.every((l, i) => JSON.stringify(l) === JSON.stringify(labels[i]))) {
    for (const [chart, data] of [[feedbackTrendCharts.success, successRates], [feedbackTrendCharts.profit, avgProfits]]) {
      chart.data.datasets[0].data = data;
      chart.$trendRows = rows;
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
      color: TREND_SUCCESS_COLOR, labels, data: successRates, rows,
      fmt: v => `${v.toFixed(1)}%`,
      guideValue: 50,
      yOpts: { min: 0, max: 100 },
      tickOpts: { stepSize: 25 },

      showXTicks: true,
      showWinInterval: true,
    }),
    profit: buildTrendChart('avgProfitChart', {
      color: TREND_PROFIT_COLOR, labels, data: avgProfits, rows,
      fmt: v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
      guideValue: 0, // breakeven baseline
      yOpts: { beginAtZero: true },
      showXTicks: true,
    }),
  };
}

// Re-fetch the chart for a chosen set of lookback windows (range buttons + poll).
async function refreshPerformanceChart(periodsCsv) {
  const sequence=++trendRequestSequence;
  setText('trendWindowSummary','Loading the selected lookback samples…');
  try {
    const data = await fetchJSON(`/api/feedback?periods=${encodeURIComponent(periodsCsv)}`);
    if(sequence!==trendRequestSequence || periodsCsv!==selectedTrendPeriods) return;
    if (!data?.period_analysis) throw new Error('No saved lookback data');
    updatePerformanceChart(data.period_analysis);
  } catch (e) {
    if(sequence!==trendRequestSequence) return;
    setText('trendWindowSummary','Lookback data could not be refreshed. Previously loaded values may be stale.');
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
// --- System vs Market (benchmark-relative, TWR deposit-adjusted) ------------
// Fixed hue order, validated for CVD separation + contrast on the dark surface.
const BENCH_COLORS = {
  portfolio: '#42c9ff',
  'SPY': '#f2a35e',
  '^DJI': '#b28dff',
  '^IXIC': '#29d697',
  'VTI': '#9bb0cc',
};
let benchmarkChart = null;
let benchmarkRequestSequence = 0;

// Deposit / withdrawal markers from static/js/cash-flows.js (absent → charts render without them).
function transferPlugins() {
  return typeof transferMarkersPlugin !== 'undefined' ? [transferMarkersPlugin] : [];
}
function transferFooterLines(items) {
  return typeof transferTooltipFooter === 'function' ? transferTooltipFooter(items) : [];
}

// "gpt-5.6-terra" → "Terra", "gpt-5.5" → "GPT-5.5"
function shortModelName(m) {
  if (!m) return '?';
  const tier = m.match(/gpt-[\d.]+-(sol|terra|luna)/i);
  if (tier) return tier[1][0].toUpperCase() + tier[1].slice(1);
  return m.replace(/^gpt-/i, 'GPT-');
}

// Vertical dashed line + label wherever the decider's model was switched
// (model_transitions table). Dates snap to the next plotted trading day.
const benchModelLinePlugin = {
  id: 'benchModelLines',
  afterDatasetsDraw(chart) {
    const transitions = chart.$modelTransitions;
    if (!transitions || !transitions.length) return;
    const { ctx, chartArea, scales } = chart;
    const labels = chart.data.labels;
    ctx.save();
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    for (const t of transitions) {
      let idx = labels.findIndex(l => l >= t.date); // ISO dates: lexicographic works
      if (idx === -1) continue;
      const x = scales.x.getPixelForValue(idx);
      if (x < chartArea.left - 1 || x > chartArea.right + 1) continue;
      ctx.strokeStyle = 'rgba(255,255,255,0.30)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      const text = `▸ ${shortModelName(t.model)}`;
      const fitsRight = x + 6 + ctx.measureText(text).width < chartArea.right;
      ctx.fillStyle = TREND_INK.label;
      ctx.textAlign = fitsRight ? 'left' : 'right';
      ctx.textBaseline = 'top';
      ctx.fillText(text, fitsRight ? x + 6 : x - 6, chartArea.top + 2);
    }
    ctx.restore();
  }
};

function benchChip(k, v, sub, signed, unit = signed ? '%' : '') {
  const cls = signed && Number.isFinite(v) ? (v >= 0 ? ' pos' : ' neg') : '';
  const val = Number.isFinite(v) ? `${signed && v >= 0 ? '+' : ''}${v.toFixed(2)}${unit}` : '—';
  return `<div class="bench-chip"><div class="k">${k}</div><div class="v${cls}">${val}</div>` +
         (sub ? `<div class="s">${sub}</div>` : '') + `</div>`;
}

function renderBenchStats(stats) {
  const el = document.getElementById('benchStats');
  if (!el) return;
  const p = stats.portfolio || {};
  const spySym = stats.spy_symbol;
  const spy = (stats.benchmarks || {})[spySym] || {};
  const t = stats.trade || {};
  el.innerHTML = [
    benchChip(`Return spread vs ${feedbackEscape(spySym || 'benchmark')}`, stats.spy_alpha, `system ${fmtPct(p.return_pct)} vs ${feedbackEscape(spySym || 'benchmark')} ${fmtPct(spy.return_pct)}`, true, ' pp'),
    benchChip('System return', p.return_pct, `${stats.start} → ${stats.end}`, true),
    benchChip('Sharpe (annualized)', p.sharpe ?? NaN, `0% risk-free · ${feedbackEscape(spySym || 'benchmark')} ${spy.sharpe ?? '—'}`, false),
    benchChip('Max drawdown', p.max_drawdown_pct, `${feedbackEscape(spySym || 'benchmark')} ${fmtPct(spy.max_drawdown_pct)}`, true),
    benchChip('Profit factor', t.profit_factor ?? NaN, `$won / $lost · ${t.amount_scored_trades ?? t.trades ?? 0} scored closures`, false),
    benchChip('Mean trade return', t.expectancy_pct, `${t.scored_trades ?? t.trades ?? 0} scored closures · unweighted`, true),
    benchChip('Payoff ratio', t.payoff_ratio ?? NaN, `avg win ${fmtPct(t.avg_win_pct)} / loss ${fmtPct(t.avg_loss_pct)}`, false),
  ].join('');
}

function fmtPct(v) {
  return Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '—';
}

async function loadBenchmarkChart(days = 90) {
  const sequence=++benchmarkRequestSequence;
  const canvas = document.getElementById('benchmarkChart');
  if (!canvas) return;
  let payload;
  try {
    payload = await fetchJSON(`/api/feedback/benchmarks?days=${days}`);
  } catch (e) {
    if(sequence!==benchmarkRequestSequence) return;
    console.error('Error loading benchmark data:', e);
    return;
  }
  if(sequence!==benchmarkRequestSequence) return;
  const foot = document.getElementById('benchFootnote');
  if (payload?.error) {
    if (foot) foot.textContent = `Benchmark comparison unavailable: ${payload.error}`;
    return;
  }
  const { series, stats } = payload;
  renderBenchStats(stats);

  const labels = series.dates;
  const toPct = arr => arr.map(v => (v == null ? null : v - 100));
  const datasets = [{
    label: 'System (TWR)',
    data: toPct(series.portfolio),
    borderColor: BENCH_COLORS.portfolio,
    backgroundColor: trendRgba(BENCH_COLORS.portfolio, 0.06),
    borderWidth: 3, fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 5,
    pointBackgroundColor: BENCH_COLORS.portfolio, pointBorderColor: '#121c33',
  }];
  for (const b of payload.benchmark_order || []) {
    if (!series[b.symbol]) continue;
    datasets.push({
      label: b.label,
      data: toPct(series[b.symbol]),
      borderColor: BENCH_COLORS[b.symbol] || '#9bb0cc',
      borderWidth: 1.5, fill: false, tension: 0, pointRadius: 0, pointHoverRadius: 4,
      pointBackgroundColor: BENCH_COLORS[b.symbol] || '#9bb0cc', pointBorderColor: '#121c33',
      spanGaps: false,
    });
  }

  if (benchmarkChart) benchmarkChart.destroy();
  benchmarkChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { right: 62, top: 6 } },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          grid: { display: false },
          border: { color: TREND_INK.axis },
          ticks: { color: TREND_INK.muted, font: { size: 11 }, maxTicksLimit: 9, maxRotation: 0 },
        },
        y: {
          border: { display: false },
          grid: { color: c => c.tick.value === 0 ? TREND_INK.gridStrong : TREND_INK.grid },
          ticks: { color: TREND_INK.muted, font: { size: 11 }, maxTicksLimit: 7, callback: v => `${v > 0 ? '+' : ''}${v}%` },
          afterFit: axis => { axis.width = 58; },
        },
      },
      plugins: {
        legend: {
          display: true, position: 'top', align: 'end',
          labels: { color: TREND_INK.text, usePointStyle: true, pointStyle: 'line', boxWidth: 24, font: { size: 11 } },
        },
        tooltip: {
          backgroundColor: TREND_INK.tooltipBg, borderColor: TREND_INK.tooltipBorder,
          borderWidth: 1, titleColor: '#dfe8f7', bodyColor: TREND_INK.text,
          padding: 10, usePointStyle: true,
          itemSort: (a, b) => b.parsed.y - a.parsed.y,
          callbacks: {
            label: item => ` ${item.dataset.label}: ${fmtPct(item.parsed.y)}`,
            footer: transferFooterLines,
          },
        },
      },
    },
    plugins: [trendEndLabelPlugin, benchModelLinePlugin, ...transferPlugins()],
  });
  benchmarkChart.$trendFmt = fmtPct;
  benchmarkChart.$modelTransitions = stats.model_transitions || [];
  // Transfers inside the window (counted rows only — the same ones the TWR strips).
  if (typeof setTransferMarkers === 'function') {
    setTransferMarkers(benchmarkChart, (stats.external_flows || []).map(f => ({ ...f, counted: true })), labels);
  }
  benchmarkChart.draw();

  if (foot) {
    const flows = stats.external_flows || [];
    const artifacts = stats.artifact_days_filtered || [];
    const bits = [];
    bits.push(`${flows.length ? flows.length : 'No'} external transfer${flows.length === 1 ? '' : 's'} in window` +
      (flows.length ? ` (${flows.map(f => `${f.amount > 0 ? '+' : '−'}$${Math.abs(f.amount).toFixed(Math.abs(f.amount) % 1 ? 2 : 0)} ${f.date}${f.source === 'manual' ? ' manual' : ''}`).join(', ')}) stripped from returns via time-weighting and marked ▲/▼ on the chart` : ''));
    if (artifacts.length) bits.push(`${artifacts.length} bad snapshot day${artifacts.length === 1 ? '' : 's'} (${artifacts.join(', ')}) auto-filtered`);
    const trans = stats.model_transitions || [];
    if (stats.model_at_start || trans.length) {
      const chain = [shortModelName(stats.model_at_start), ...trans.map(t => `${shortModelName(t.model)} (${t.date})`)];
      bits.push(`Decider model: ${chain.join(' → ')}`);
    }
    bits.push('SPY/VTI use dividend-adjusted closes; DJIA/NASDAQ are price indexes.');
    if(stats.methodology) bits.push(stats.methodology);
    const coverage=stats.coverage || {};
    if(coverage.missing_portfolio_sessions?.length) bits.push(`${coverage.missing_portfolio_sessions.length} session(s) lack a portfolio valuation and appear as gaps; daily Sharpe is unavailable across gaps`);
    if(coverage.unavailable_benchmarks?.length) bits.push(`Common-date coverage unavailable for: ${coverage.unavailable_benchmarks.join(', ')}`);
    if(coverage.portfolio_last_snapshot) bits.push(`Last portfolio snapshot: ${coverage.portfolio_last_snapshot}`);
    foot.textContent = bits.join(' · ');
  }
}

function setupBenchRangeButtons() {
  const wrap = document.getElementById('benchRangeButtons');
  if (!wrap) return;
  wrap.querySelectorAll('.trend-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.trend-range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadBenchmarkChart(parseInt(btn.dataset.days, 10) || 90);
    });
  });
}

// --- Event Risk Landscape (regime + scheduled binary events) ------------------
// Regime bands, event verticals and fill markers share the palette of the benchmark chart.
const EVENT_INK = {
  score: '#ff7a59',
  projection: '#9bb0cc',
  regime: {
    'RISK-ON': 'rgba(41,214,151,0.10)', 'MIXED': 'rgba(242,163,94,0.13)',
    'RISK-OFF': 'rgba(255,99,132,0.16)', 'UNKNOWN': 'rgba(155,176,204,0.06)',
  },
  event: { fomc: '#ff6384', cpi: '#f2a35e', jobs: '#f2a35e', other: '#b28dff', earnings: '#42c9ff' },
  buy: '#29d697', sellWin: '#29d697', sellLoss: '#ff6384', sellFlat: '#fadb5f', sellUnscored: '#9bb0cc',
};
let eventRiskChart = null;
let eventRequestSequence = 0;

// Background: one band per plotted session coloured by its regime, plus the today divider.
const eventBandsPlugin = {
  id: 'eventBands',
  beforeDatasetsDraw(chart) {
    const rows = chart.$eventRows;
    if (!rows || !rows.length) return;
    const { ctx, chartArea, scales } = chart;
    const px = i => scales.x.getPixelForValue(i);
    ctx.save();
    for (let i = 0; i < rows.length; i++) {
      const x0 = i === 0 ? chartArea.left : (px(i - 1) + px(i)) / 2;
      const x1 = i === rows.length - 1 ? chartArea.right : (px(i) + px(i + 1)) / 2;
      ctx.fillStyle = EVENT_INK.regime[rows[i].regime] || EVENT_INK.regime.UNKNOWN;
      ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
    }
    const t = chart.$eventTodayIndex;
    if (t != null && t < rows.length - 1) {
      const x = (px(t) + px(t + 1)) / 2;
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = TREND_INK.label;
      ctx.font = '600 10px Inter, system-ui, sans-serif';
      ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
      ctx.fillText('today ▸ projected', x - 4, chartArea.bottom - 2);
    }
    ctx.restore();
  }
};

// Foreground: a vertical per scheduled event with its label (FOMC solid, prints dashed).
const eventMarkersPlugin = {
  id: 'eventMarkers',
  afterDatasetsDraw(chart) {
    const events = chart.$eventMarkers;
    const labels = chart.data.labels;
    if (!events || !events.length) return;
    const { ctx, chartArea, scales } = chart;
    ctx.save();
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    ctx.textBaseline = 'top';
    let lastX = -1e9, row = 0;
    for (const e of events) {
      const idx = labels.indexOf(e.date);
      if (idx === -1) continue;
      const x = scales.x.getPixelForValue(idx);
      const color = EVENT_INK.event[e.kind] || '#9bb0cc';
      ctx.strokeStyle = color;
      ctx.setLineDash(e.kind === 'fomc' ? [] : [4, 4]);
      ctx.lineWidth = e.kind === 'fomc' ? 1.5 : 1;
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.setLineDash([]);
      row = (x - lastX < 52) ? (row + 1) % 3 : 0;
      lastX = x;
      ctx.fillStyle = color;
      ctx.textAlign = 'left';
      ctx.fillText(e.label, Math.min(x + 4, chartArea.right - 44), chartArea.top + 2 + row * 12);
    }
    ctx.restore();
  }
};

function eventLevelClass(level) {
  return level === 'LOW' ? ' pos' : (level === 'HIGH' || level === 'EXTREME') ? ' neg' : '';
}

function renderEventStats(live, payload) {
  const el = document.getElementById('eventStats');
  if (!el) return;
  const m = live.macro || {};
  const whenOf = s => {
    if (!s || s.sessions_to == null) return 'not in calendar';
    if (s.sessions_to === 0) return `today ${s.release_et}${s.phase ? ` (${s.phase})` : ''}`;
    return `${s.next} · in ${s.sessions_to} session${s.sessions_to === 1 ? '' : 's'}`;
  };
  const nextPrint = [m.cpi, m.jobs].filter(s => s && s.sessions_to != null).sort((a, b) => a.sessions_to - b.sessions_to)[0];
  const reporting = (live.holdings_earnings || []).filter(h => h.flag);
  const holdings=live.holdings_earnings || [],dated=h=>Boolean(h.date)&&Number.isFinite(h.sessions_to),coverage=live.earnings_coverage?.holdings || {
    total:holdings.length,known:holdings.filter(dated).length,unknown:holdings.filter(h=>!dated(h)).length,
    unknown_tickers:holdings.filter(h=>!dated(h)).map(h=>h.ticker)};
  const earningsValue=reporting.length?reporting.map(h=>`${h.ticker} ${h.date}`).join(', '):!coverage.total?'No holdings':coverage.unknown?'No known releases ≤5 sessions':'None ≤5 sessions';
  const earningsCoverage=`${coverage.known}/${coverage.total} holdings dated${coverage.unknown?` · unknown: ${(coverage.unknown_tickers || []).join(', ')}`:''}`;
  const chip = (k, v, sub, cls) =>
    `<div class="bench-chip"><div class="k">${k}</div><div class="v${cls || ''}">${v}</div>` + (sub ? `<div class="s">${sub}</div>` : '') + `</div>`;
  el.innerHTML = [
    chip('Event/regime pressure', `${live.risk_score}/100`, `${live.risk_level} · regime ${live.regime || 'n/a'}`, eventLevelClass(live.risk_level)),
    chip('Macro window', live.macro_window ? 'YES' : 'no', live.macro_window ? live.macro_reason : 'no FOMC within 2 sessions, no print next session', live.macro_window ? ' neg' : ' pos'),
    chip('Next FOMC', m.fomc && m.fomc.next ? m.fomc.next : '—', whenOf(m.fomc), ''),
    chip('Next print', nextPrint ? nextPrint.label : '—', whenOf(nextPrint), ''),
    chip('Holdings reporting', feedbackEscape(earningsValue), feedbackEscape(earningsCoverage), reporting.length?' neg':coverage.unknown?'':' pos'),
    chip('Calendar buy guidance', live.macro_window ? 'Macro window' : 'Regime guidance', (live.allowance || {}).buys || '', ''),
  ].join('');
  const breakdown=document.getElementById('eventScoreBreakdown');
  if(breakdown) breakdown.innerHTML=(live.score_parts || []).map(part=>`<span class="event-score-part"><strong>+${feedbackEscape(part[2])}</strong>${feedbackEscape(String(part[0] || '').toUpperCase())} · ${feedbackEscape(part[1])}</span>`).join('')+(live.risk_score===100?'<span class="event-score-part">Total capped at 100</span>':'');
}

// Show the same bounded coverage warning the Decider sees when its loaded
// CPI/jobs calendars no longer reach the declared forward horizon.
function renderCalendarGap(gap) {
  const el = document.getElementById('eventCalendarGap');
  if (!el) return;
  const warning = gap && gap.warning ? String(gap.warning) : '';
  el.textContent = warning ? `⚠ ${warning}` : '';
  el.hidden = !warning;
}

async function loadEventRiskChart(days = 90) {
  const sequence=++eventRequestSequence;
  const canvas = document.getElementById('eventRiskChart');
  if (!canvas) return;
  let payload;
  try {
    payload = await fetchJSON(`/api/feedback/event-risk?days=${days}`);
  } catch (e) {
    if(sequence!==eventRequestSequence) return;
    console.error('Error loading event risk data:', e);
    return;
  }
  if(sequence!==eventRequestSequence) return;
  const foot = document.getElementById('eventFootnote');
  if (payload?.error) {
    if (foot) foot.textContent = `Event risk landscape unavailable: ${payload.error}`;
    return;
  }
  const history = payload.series || [];
  const projection = payload.projection || [];
  const rows = history.concat(projection);
  const labels = rows.map(r => r.date);
  const todayIndex = history.length - 1;
  if (payload.live) renderEventStats(payload.live, payload);
  renderCalendarGap(payload.calendar_gap);

  const scoreHist = rows.map((r, i) => (i <= todayIndex ? r.score : null));
  const scoreProj = rows.map((r, i) => (i >= todayIndex ? r.score : null));
  const byDate = new Map(rows.map((r, i) => [r.date, i]));
  const buys = new Array(rows.length).fill(null);
  const sellWins = new Array(rows.length).fill(null);
  const sellLosses = new Array(rows.length).fill(null);
  const sellFlat = new Array(rows.length).fill(null), sellUnscored = new Array(rows.length).fill(null);
  const tradeNotes = new Map();
  for (const t of payload.trades || []) {
    const i = byDate.get(t.date);
    if (i == null) continue;
    const y = rows[i].score;
    if (t.action === 'buy') buys[i] = y;
    else if (!Number.isFinite(t.pct)) sellUnscored[i] = y;
    else if (t.pct > 0) sellWins[i] = y;
    else if (t.pct < 0) sellLosses[i] = y;
    else sellFlat[i] = y;
    const note = t.action === 'buy' ? `▲ ${t.ticker}` : `▼ ${t.ticker} ${fmtPct(t.pct)}`;
    tradeNotes.set(t.date, (tradeNotes.get(t.date) || []).concat(note));
  }
  const eventsByDate = new Map();
  for (const e of payload.events || []) eventsByDate.set(e.date, (eventsByDate.get(e.date) || []).concat(e.label));

  const marker = (label, data, color, rotation) => ({
    label, data, showLine: false, pointStyle: 'triangle', rotation, pointRadius: 6, pointHoverRadius: 8,
    pointBackgroundColor: color, pointBorderColor: '#121c33', pointBorderWidth: 1, borderColor: color,
  });
  const datasets = [
    {
      label: 'Event risk', data: scoreHist, borderColor: EVENT_INK.score,
      backgroundColor: trendRgba(EVENT_INK.score, 0.12), borderWidth: 2.5, fill: true, tension: 0.15,
      pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: EVENT_INK.score, pointBorderColor: '#121c33',
    },
    {
      label: 'Projected', data: scoreProj, borderColor: EVENT_INK.projection, borderDash: [3, 4],
      borderWidth: 1.5, fill: false, tension: 0.15, pointRadius: 0, pointHoverRadius: 4,
      pointBackgroundColor: EVENT_INK.projection, pointBorderColor: '#121c33', spanGaps: false,
    },
    marker('Buy fill', buys, EVENT_INK.buy, 0),
    marker('Sell (win)', sellWins, EVENT_INK.sellWin, 180),
    marker('Sell (loss)', sellLosses, EVENT_INK.sellLoss, 180),
    marker('Sell (flat)', sellFlat, EVENT_INK.sellFlat, 180),
    marker('Sell (unscored)', sellUnscored, EVENT_INK.sellUnscored, 180),
  ];

  if (eventRiskChart) eventRiskChart.destroy();
  eventRiskChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { right: 62, top: 6 } },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          grid: { display: false },
          border: { color: TREND_INK.axis },
          ticks: { color: TREND_INK.muted, font: { size: 11 }, maxTicksLimit: 9, maxRotation: 0 },
        },
        y: {
          min: 0, max: 100,
          border: { display: false },
          grid: { color: c => (c.tick.value === 50 ? TREND_INK.gridStrong : TREND_INK.grid) },
          ticks: { color: TREND_INK.muted, font: { size: 11 }, stepSize: 25 },
          afterFit: axis => { axis.width = 58; },
        },
      },
      plugins: {
        legend: {
          display: true, position: 'top', align: 'end',
          labels: { color: TREND_INK.text, usePointStyle: true, boxWidth: 24, font: { size: 11 },
                    filter: item => item.text !== 'Projected' },
        },
        tooltip: {
          backgroundColor: TREND_INK.tooltipBg, borderColor: TREND_INK.tooltipBorder,
          borderWidth: 1, titleColor: '#dfe8f7', bodyColor: TREND_INK.text, padding: 10, usePointStyle: true,
          filter: item => item.datasetIndex === 0 || (item.datasetIndex === 1 && item.dataIndex > todayIndex),
          callbacks: {
            title: items => {
              const r = rows[items[0].dataIndex];
              return `${r.date} · ${r.regime}${items[0].dataIndex > todayIndex ? ' (projected)' : r.recorded ? ` (recorded daily maximum · ${r.snapshot_count ?? 1} snapshots)` : ' (reconstructed)'}`;
            },
            label: item => ` risk ${item.parsed.y}/100 · ${rows[item.dataIndex].level}${rows[item.dataIndex].macro_window ? ' · MACRO WINDOW' : ''}`,
            afterBody: items => {
              const d = rows[items[0].dataIndex].date;
              const lines = [];
              if (eventsByDate.has(d)) lines.push('events: ' + eventsByDate.get(d).join(', '));
              if (tradeNotes.has(d)) lines.push(tradeNotes.get(d).join('  '));
              return lines;
            },
            footer: transferFooterLines,
          },
        },
      },
    },
    plugins: [eventBandsPlugin, eventMarkersPlugin, ...transferPlugins()],
  });
  eventRiskChart.$eventRows = rows;
  eventRiskChart.$eventTodayIndex = todayIndex;
  eventRiskChart.$eventMarkers = payload.events || [];
  eventRiskChart.draw();
  // External transfers on the same session axis (history only; the projection has none).
  if (typeof loadCashFlows === 'function') {
    const chartAtRequest = eventRiskChart;
    loadCashFlows().then(cf => {
      if (!cf || !cf.flows || eventRiskChart !== chartAtRequest) return;
      setTransferMarkers(eventRiskChart, cf.flows, labels.slice(0, todayIndex + 1));
      eventRiskChart.draw();
    });
  }

  if (foot) {
    const rec = payload.snapshots_recorded || 0;
    foot.textContent = [
      'Score = regime base + FOMC proximity (35 / 30 / 20 points at 0 / 1 / 2 sessions, 8 at 3, 10 the session after) ' +
      '+ CPI / jobs (12 the session before, 6 day-of) + earnings (20 per holding reporting ≤2 sessions, 8 within 5; capped)',
      rec ? `${rec} Decider snapshot${rec === 1 ? '' : 's'} recorded in window; other days reconstructed from benchmark regimes + the calendars`
          : 'no Decider snapshots yet — the curve is reconstructed from benchmark regimes + the calendars until the next cycle runs',
      'FOMC dates from federalreserve.gov (2026–2027), CPI and jobs dates from bls.gov (2026–2027), earnings dates from yfinance',
    ].join(' · ');
  }
}

function setupEventRangeButtons() {
  const wrap = document.getElementById('eventRangeButtons');
  if (!wrap) return;
  wrap.querySelectorAll('.trend-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.trend-range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadEventRiskChart(parseInt(btn.dataset.days, 10) || 90);
    });
  });
}

async function loadFeedbackHistory() {
  const el = document.getElementById('feedbackHistory');
  try {
    const log = await fetchJSON('/api/feedback_log');
    const reviews=Array.isArray(log)?log.filter(entry=>entry.type==='feedback'||Number.isFinite(entry.success_rate)):[];
    document.getElementById('feedbackCount').textContent = reviews.length;
    if (!reviews.length) {
      el.innerHTML = '<p>No feedback history available</p>';
      return;
    }
    const lastTen = reviews.slice(0, 10);
    el.innerHTML = lastTen.map((entry, idx) => `
      <div class="feedback-history-item">
        <h4>📊 Feedback Analysis #${reviews.length - idx}</h4>
        <div class="timestamp">${feedbackLocalLabel(entry.timestamp)} (${entry.lookback_days} days lookback)</div>
        <div style="margin-bottom: 15px;">
          <strong>Trades Analyzed:</strong> ${entry.trades_analyzed}<br>
          <strong>Win Rate:</strong> ${entry.trades_analyzed>0?formatMaybePct(entry.success_rate):'— (no closed-trade sample)'}<br>
          <strong>Mean Return:</strong> ${entry.trades_analyzed>0?formatMaybePct(entry.avg_profit):'—'}
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
      renderOutcomeOverview(outcomes);
      sortOutcomes(currentSort.column,currentSort.direction);
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
    const netGainClass = Number.isFinite(outcome.net_gain_dollars) ? outcome.net_gain_dollars >= 0 ? 'text-success' : 'text-danger' : '';
    const netGainValue = formatDollars(outcome.net_gain_dollars);
    const percentageClass = Number.isFinite(outcome.gain_loss_pct) ? outcome.gain_loss_pct >= 0 ? 'text-success' : 'text-danger' : '';
    const percentageValue = fmtPct(outcome.gain_loss_pct);
    const category=String(outcome.category||'unscored').replace(/[^a-z_]/g,'');
    const price=value=>Number.isFinite(value)?`$${value.toFixed(2)}`:'—';
    return `
      <tr class="outcome-${category}">
        <td><strong>${feedbackEscape(outcome.ticker)}</strong></td>
        <td>${feedbackDate(outcome.sell_date)?.toLocaleDateString() || '—'}</td>
        <td>${Number.isFinite(outcome.shares) ? outcome.shares.toLocaleString(undefined,{maximumFractionDigits:4}) : '—'}</td>
        <td>${price(outcome.purchase_price)}</td>
        <td>${price(outcome.sell_price)}</td>
        <td class="${netGainClass}"><strong>${netGainValue}</strong></td>
        <td class="${percentageClass}"><strong>${percentageValue}</strong></td>
        <td>${category.replaceAll('_', ' ').toUpperCase()}</td>
        <td>${outcome.hold_days ?? '—'}</td>
      </tr>`;
  }).join('');
}
function setupTableSorting() {
  const headers = document.querySelectorAll('.outcomes-table th.sortable');
  headers.forEach(header => {
    if(header.dataset.sortBound) return;
    header.dataset.sortBound='true';
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
        if(!Number.isFinite(aVal)||!Number.isFinite(bVal))return Number.isFinite(aVal)?-1:Number.isFinite(bVal)?1:0;
        break;
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
  // 60s (was 10s): each poll re-renders sections, which yanked the page
  // around while users were exploring the charts.
  setInterval(refreshFeedbackData, 60000);
  setupTrendRangeButtons();
  setupBenchRangeButtons();
  loadBenchmarkChart(90); // fetched once per range click, not on the 10s poll
  setupEventRangeButtons();
  loadEventRiskChart(90);
  const resetBtn = document.getElementById('resetPromptsBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', resetPromptsToBaseline);
  }
  const undoBtn = document.getElementById('undoPromptChangeBtn');
  if (undoBtn) {
    undoBtn.addEventListener('click', undoLastPromptChange);
  }
});
