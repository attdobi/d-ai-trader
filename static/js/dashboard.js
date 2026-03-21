let chart, performanceChart, breakdownChart;

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>'"]/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch] || ch));
}

Chart.defaults.color = '#7f8ca6';
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function createChartGradient(ctx, hex, height) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height || 380);
  gradient.addColorStop(0, hexToRgba(hex, 0.35));
  gradient.addColorStop(1, hexToRgba(hex, 0.0));
  return gradient;
}

const tooltipConfig = {
  backgroundColor: '#151f35',
  titleColor: '#e6ecff',
  bodyColor: '#e6ecff',
  borderColor: 'rgba(66,201,255,0.3)',
  borderWidth: 1,
  cornerRadius: 12,
  padding: 14,
  titleFont: { family: "'Inter', sans-serif", weight: '600', size: 13 },
  bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
  callbacks: {
    label: function(context) {
      return ' $' + context.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
  }
};

const crosshairPlugin = {
  id: 'crosshair',
  afterDraw(chartInstance) {
    if (chartInstance.tooltip && chartInstance.tooltip.getActiveElements().length > 0) {
      const activePoint = chartInstance.tooltip.getActiveElements()[0];
      const ctx = chartInstance.ctx;
      const x = activePoint.element.x;
      const topY = chartInstance.scales.y.top;
      const bottomY = chartInstance.scales.y.bottom;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, topY);
      ctx.lineTo(x, bottomY);
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(66,201,255,0.4)';
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.restore();
    }
  }
};

Chart.register(crosshairPlugin);

function renderChart(data, label = 'Portfolio Value') {
  const el = document.getElementById('historyChart');
  const canvas = el;

  // Handle empty data for new configs
  if (!data || data.length === 0) {
    if (chart) chart.destroy();
    const parent = canvas.parentElement;
    canvas.style.display = 'none';
    const msg = document.createElement('div');
    msg.id = 'historyChartNoData';
    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:200px;background:#151f35;border:1px solid rgba(255,255,255,0.06);border-radius:10px;margin:10px 0;';
    msg.innerHTML = '<div style="text-align:center;color:#7f8ca6;"><p>📊 No historical data yet for this configuration</p><p style="font-size:0.9em;">Data will appear after running the system</p></div>';
    const existing = parent.querySelector('#historyChartNoData');
    if (existing) existing.remove();
    parent.appendChild(msg);
    return;
  }

  // Remove no-data message if exists
  const noDataMsg = canvas.parentElement.querySelector('#historyChartNoData');
  if (noDataMsg) noDataMsg.remove();
  canvas.style.display = 'block';

  const ctx = canvas.getContext('2d');
  const labels = data.map(row => new Date(row.timestamp).toLocaleDateString());
  const values = data.map(row => row.total_portfolio_value);
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        borderColor: '#42c9ff',
        backgroundColor: createChartGradient(ctx, '#42c9ff', canvas.height),
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: '#42c9ff',
        fill: true,
        tension: 0.25
      }]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        tooltip: tooltipConfig,
        legend: { labels: { color: '#7f8ca6', usePointStyle: true } }
      },
      scales: {
        x: {
          display: true,
          title: { display: true, text: 'Date' },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#7f8ca6' }
        },
        y: {
          display: true,
          title: { display: true, text: 'Portfolio Value ($)' },
          beginAtZero: false,
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#7f8ca6' }
        }
      }
    }
  });
}

function renderPerformanceChart(data) {
  const el = document.getElementById('performanceChart');
  const ctx = el.getContext('2d');
  try {
    const labels = data.map(row => new Date(row.timestamp).toLocaleDateString());
    const netGainLoss = data.map(row => parseFloat(row.net_gain_loss) || 0);
    if (performanceChart) performanceChart.destroy();
    performanceChart = new Chart(el, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Net Gain/Loss ($)',
          data: netGainLoss,
          borderColor: '#29d697',
          segment: {
            borderColor: segmentCtx => segmentCtx.p0.parsed.y < 0 ? '#ff5f73' : '#29d697'
          },
          backgroundColor: createChartGradient(ctx, '#29d697', el.height),
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#29d697',
          fill: true,
          tension: 0.25
        }]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            display: true,
            title: { display: true, text: 'Date' },
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#7f8ca6' }
          },
          y: {
            display: true,
            title: { display: true, text: 'Net Gain/Loss ($)' },
            beginAtZero: false,
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#7f8ca6' }
          }
        },
        plugins: {
          tooltip: tooltipConfig,
          legend: { labels: { color: '#7f8ca6', usePointStyle: true } }
        }
      }
    });
  } catch (err) {
    el.style.display = 'flex';
    el.style.alignItems = 'center';
    el.style.justifyContent = 'center';
    el.style.height = '200px';
    el.style.backgroundColor = '#151f35';
    el.style.border = '1px solid rgba(255,255,255,0.06)';
    el.style.borderRadius = '10px';
    el.innerHTML = '<div style="text-align:center;color:#ff8a9a;"><p>Error rendering performance chart.</p></div>';
  }
}

function renderBreakdownChart(data) {
  const el = document.getElementById('breakdownChart');
  const canvas = el;

  // Handle empty data for new configs
  if (!data || data.length === 0) {
    if (breakdownChart) breakdownChart.destroy();
    const parent = canvas.parentElement;
    canvas.style.display = 'none';
    const msg = document.createElement('div');
    msg.id = 'breakdownChartNoData';
    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:200px;background:#151f35;border:1px solid rgba(255,255,255,0.06);border-radius:10px;margin:10px 0;';
    msg.innerHTML = '<div style="text-align:center;color:#7f8ca6;"><p>📊 No breakdown data yet for this configuration</p><p style="font-size:0.9em;">Data will appear after running the system</p></div>';
    const existing = parent.querySelector('#breakdownChartNoData');
    if (existing) existing.remove();
    parent.appendChild(msg);
    return;
  }

  // Remove no-data message if exists
  const noDataMsg = canvas.parentElement.querySelector('#breakdownChartNoData');
  if (noDataMsg) noDataMsg.remove();
  canvas.style.display = 'block';

  const ctx = canvas.getContext('2d');
  const labels = data.map(row => new Date(row.timestamp).toLocaleDateString());
  const cashBalance = data.map(row => row.cash_balance);
  const totalInvested = data.map(row => row.total_invested);
  if (breakdownChart) breakdownChart.destroy();
  breakdownChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Cash Balance',
          data: cashBalance,
          borderColor: '#29d697',
          backgroundColor: createChartGradient(ctx, '#29d697', canvas.height),
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#29d697',
          fill: true,
          tension: 0.25
        },
        {
          label: 'Invested Amount',
          data: totalInvested,
          borderColor: '#42c9ff',
          backgroundColor: createChartGradient(ctx, '#42c9ff', canvas.height),
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#42c9ff',
          fill: true,
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        tooltip: tooltipConfig,
        legend: { labels: { color: '#7f8ca6', usePointStyle: true } }
      },
      scales: {
        x: {
          display: true,
          title: { display: true, text: 'Date' },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#7f8ca6' }
        },
        y: {
          display: true,
          title: { display: true, text: 'Amount ($)' },
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#7f8ca6' }
        }
      }
    }
  });
}

function loadChart(ticker = null) {
  if (ticker) {
    const url = `/api/history?ticker=${ticker}`;
    document.getElementById('chart-title').innerText = `History for ${ticker}`;
    fetch(url).then(r => r.json()).then(d => renderChart(d, ticker)).catch(console.error);
  } else {
    document.getElementById('chart-title').innerText = 'Portfolio Value Over Time';
    fetch('/api/portfolio-history').then(r => r.json()).then(d => renderChart(d, 'Portfolio Value')).catch(console.error);
  }
}

function loadPerformanceChart() {
  fetch('/api/portfolio-performance').then(r => r.json()).then(data => {
    if (Array.isArray(data) && data.length > 0) {
      const hasData = data.some(row => Math.abs(parseFloat(row.net_gain_loss || 0)) > 0.01 || Math.abs(parseFloat(row.total_portfolio_value || 0)) > 0.01);
      if (hasData) {
        renderPerformanceChart(data);
      } else {
        showNoDataMessage();
      }
    } else {
      showNoDataMessage();
    }
  }).catch(() => showErrorMessage());
}
function showNoDataMessage() {
  const el = document.getElementById('performanceChart');
  el.style.display = 'flex';
  el.style.alignItems = 'center';
  el.style.justifyContent = 'center';
  el.style.height = '200px';
  el.style.backgroundColor = '#151f35';
  el.style.border = '1px solid rgba(255,255,255,0.06)';
  el.style.borderRadius = '10px';
  el.innerHTML = '<div style="text-align:center;color:#7f8ca6;"><p>No performance data available yet.</p><p>Start trading to see performance metrics.</p></div>';
}
function showErrorMessage() {
  const el = document.getElementById('performanceChart');
  el.style.display = 'flex';
  el.style.alignItems = 'center';
  el.style.justifyContent = 'center';
  el.style.height = '200px';
  el.style.backgroundColor = '#151f35';
  el.style.border = '1px solid rgba(255,95,115,0.35)';
  el.style.borderRadius = '10px';
  el.innerHTML = '<div style="text-align:center;color:#ff8a9a;"><p>Error loading performance data.</p></div>';
}
function loadBreakdownChart() {
  fetch('/api/portfolio-history').then(r => r.json()).then(renderBreakdownChart).catch(console.error);
}

function loadSparklines() {
  fetch('/api/sparklines')
    .then(r => r.json())
    .then(data => {
      const container = document.getElementById('sparklineRow');
      if (!container) return;

      if (!data || Object.keys(data).length === 0) {
        container.innerHTML = '<p style="color: var(--muted); font-size: 13px;">No active holdings for sparklines.</p>';
        return;
      }

      container.innerHTML = '';
      Object.entries(data).forEach(([ticker, prices]) => {
        if (!Array.isArray(prices) || prices.length === 0) return;

        const card = document.createElement('div');
        card.className = 'sparkline-card';
        const last = prices[prices.length - 1];
        const first = prices[0];
        const change = first > 0 ? ((last - first) / first * 100).toFixed(2) : '0.00';
        const isUp = parseFloat(change) >= 0;
        card.innerHTML = `
          <span class="sparkline-ticker">${ticker}</span>
          <canvas id="spark-${ticker}" width="120" height="40"></canvas>
          <span class="sparkline-price">$${last.toFixed(2)}</span>
          <span class="sparkline-change ${isUp ? 'up' : 'down'}">${isUp ? '+' : ''}${change}%</span>
        `;
        container.appendChild(card);

        const sparkCanvas = document.getElementById(`spark-${ticker}`);
        if (!sparkCanvas) return;
        const ctx = sparkCanvas.getContext('2d');

        new Chart(ctx, {
          type: 'line',
          data: {
            labels: prices.map((_, i) => i),
            datasets: [{
              data: prices,
              borderColor: isUp ? '#29d697' : '#ff5f73',
              borderWidth: 2,
              pointRadius: 0,
              fill: false,
              tension: 0.3
            }]
          },
          options: {
            responsive: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } },
            animation: false
          }
        });
      });
    })
    .catch(err => {
      console.error('Sparkline error:', err);
      const container = document.getElementById('sparklineRow');
      if (container) {
        container.innerHTML = '<p style="color: var(--muted);">Failed to load sparklines.</p>';
      }
    });
}

function triggerAgent(agentType) {
  const statusDiv = document.getElementById('trigger-status');
  const buttons = document.querySelectorAll('.trigger-btn');
  statusDiv.innerHTML = `🔄 Triggering ${agentType} agent...`; statusDiv.className = 'trigger-status loading';
  buttons.forEach(b => b.disabled = true);
  fetch(`/api/trigger/${agentType}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(r => r.json())
    .then(data => {
      if (data.success) { statusDiv.innerHTML = `✅ ${data.message}`; statusDiv.className = 'trigger-status success'; setTimeout(() => location.reload(), 2000); }
      else { statusDiv.innerHTML = `❌ Error: ${data.error}`; statusDiv.className = 'trigger-status error'; }
    })
    .catch(err => { statusDiv.innerHTML = `❌ Network error: ${err.message}`; statusDiv.className = 'trigger-status error'; })
    .finally(() => { buttons.forEach(b => b.disabled = false); });
}
function runSummaryAnalyzer() {
  const statusDiv = document.getElementById('summary-analyzer-output');
  const triggerButton = document.getElementById('summary-analyzer-btn');
  if (!statusDiv) return;

  statusDiv.innerHTML = '🔄 Running summary analyzer and momentum recap...';
  statusDiv.className = 'trigger-status loading';
  if (triggerButton) triggerButton.disabled = true;

  fetch('/api/run-summary-analyzer', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(response => response.json())
    .then(data => {
      if (!data.success) {
        statusDiv.innerHTML = `❌ ${escapeHtml(data.error || 'Analyzer failed.')}`;
        statusDiv.className = 'trigger-status error';
        return;
      }

      const summariesCount = data.summary_count || 0;
      const companies = Array.isArray(data.companies) ? data.companies : [];
      const momentumRecap = escapeHtml(data.momentum_recap || data.momentum_summary || '').replace(/\n/g, '<br>');
      const summariesPreview = escapeHtml(data.summaries_preview || '').replace(/\n/g, '<br>');

      let companiesHtml = 'No companies detected.';
      if (companies.length) {
        companiesHtml = '<ul class="analyzer-company-list">' + companies.map(entry => {
          const name = escapeHtml(entry.company || entry.symbol || 'Unknown');
          const symbol = escapeHtml(entry.symbol || '–');
          return `<li><strong>${name}</strong> <span class="ticker">(${symbol})</span></li>`;
        }).join('') + '</ul>';
      }

      statusDiv.innerHTML = [
        '✅ Summary analyzer complete.',
        `<strong>Summaries Processed:</strong> ${summariesCount}`,
        `<strong>Detected Companies:</strong><br>${companiesHtml}`,
        `<strong>Momentum Recap:</strong><br>${momentumRecap || 'N/A'}`,
        `<details class="analyzer-summaries"><summary>Summary Preview</summary><div>${summariesPreview || 'N/A'}</div></details>`
      ].join('<br><br>');
      statusDiv.className = 'trigger-status success';
    })
    .catch(err => {
      statusDiv.innerHTML = `❌ Network error: ${escapeHtml(err.message)}`;
      statusDiv.className = 'trigger-status error';
    })
    .finally(() => {
      if (triggerButton) triggerButton.disabled = false;
    });
}
function resetPortfolio() {
  if (!confirm('Are you sure you want to reset the portfolio? This will:\n\n• Sell all current holdings\n• Reset cash balance to $10,000\n• Clear all trading history\n\nThis action cannot be undone.')) return;
  const statusDiv = document.getElementById('reset-status'); const button = document.querySelector('.reset-btn-small');
  statusDiv.innerHTML = '🔄 Resetting portfolio...'; statusDiv.className = 'reset-status-small loading'; if (button) button.disabled = true;
  fetch('/api/reset-portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(r => r.json())
    .then(data => {
      if (data.success) { statusDiv.innerHTML = `✅ ${data.message}`; statusDiv.className = 'reset-status-small success'; setTimeout(() => location.reload(), 2000); }
      else { statusDiv.innerHTML = `❌ Error: ${data.error}`; statusDiv.className = 'reset-status-small error'; }
    })
    .catch(err => { statusDiv.innerHTML = `❌ Network error: ${err.message}`; statusDiv.className = 'reset-status-small error'; })
    .finally(() => { if (button) button.disabled = false; });
}
function updatePrices() {
  const statusDiv = document.getElementById('price-update-status');
  const button = document.querySelector('.price-update-btn');
  statusDiv.innerHTML = '🔄 Fetching latest stock prices...'; statusDiv.className = 'price-update-status loading'; if (button) button.disabled = true;
  fetch('/api/trigger/price-update', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(r => r.json())
    .then(data => {
      if (data.success) { statusDiv.innerHTML = `✅ ${data.message}`; statusDiv.className = 'price-update-status success'; setTimeout(() => location.reload(), 3000); }
      else { statusDiv.innerHTML = `❌ Error: ${data.error}`; statusDiv.className = 'price-update-status error'; }
    })
    .catch(err => { statusDiv.innerHTML = `❌ Network error: ${err.message}`; statusDiv.className = 'price-update-status error'; })
    .finally(() => { if (button) button.disabled = false; });
}
window.addEventListener('load', () => {
  loadChart();
  loadPerformanceChart();
  loadBreakdownChart();
  loadSparklines();
});
