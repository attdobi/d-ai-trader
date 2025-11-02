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
    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:200px;background:#f8f9fa;border:1px solid #dee2e6;border-radius:4px;margin:10px 0;';
    msg.innerHTML = '<div style="text-align:center;color:#6c757d;"><p>📊 No historical data yet for this configuration</p><p style="font-size:0.9em;">Data will appear after running the system</p></div>';
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
    data: { labels, datasets: [{
      label, data: values, borderColor: '#007bff', backgroundColor: 'rgba(0, 123, 255, 0.1)', fill: true, tension: 0.1
    }]},
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { display: true, title: { display: true, text: 'Date' } },
        y: { display: true, title: { display: true, text: 'Portfolio Value ($)' }, beginAtZero: false }
      }
    }
  });
}

function renderPerformanceChart(data) {
  const el = document.getElementById('performanceChart');
  try {
    const labels = data.map(row => new Date(row.timestamp).toLocaleDateString());
    const netGainLoss = data.map(row => parseFloat(row.net_gain_loss) || 0);
    if (performanceChart) performanceChart.destroy();
    performanceChart = new Chart(el, {
      type: 'line',
      data: { labels, datasets: [{
        label: 'Net Gain/Loss ($)',
        data: netGainLoss,
        borderColor: '#007bff',
        backgroundColor: 'rgba(0, 123, 255, 0.1)',
        fill: true, tension: 0.1
      }]},
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { display: true, title: { display: true, text: 'Date' } },
          y: { display: true, title: { display: true, text: 'Net Gain/Loss ($)' }, beginAtZero: false }
        },
        plugins: { legend: { display: true } }
      }
    });
  } catch (err) {
    el.style.display = 'flex';
    el.style.alignItems = 'center';
    el.style.justifyContent = 'center';
    el.style.height = '200px';
    el.style.backgroundColor = '#f8d7da';
    el.style.border = '1px solid #f5c6cb';
    el.style.borderRadius = '4px';
    el.innerHTML = '<div style="text-align:center;color:#721c24;"><p>Error rendering performance chart.</p></div>';
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
    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:200px;background:#f8f9fa;border:1px solid #dee2e6;border-radius:4px;margin:10px 0;';
    msg.innerHTML = '<div style="text-align:center;color:#6c757d;"><p>📊 No breakdown data yet for this configuration</p><p style="font-size:0.9em;">Data will appear after running the system</p></div>';
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
    data: { labels, datasets: [
      { label: 'Cash Balance', data: cashBalance, borderColor: '#28a745', backgroundColor: 'rgba(40,167,69,0.1)', fill: true, tension: 0.1 },
      { label: 'Invested Amount', data: totalInvested, borderColor: '#007bff', backgroundColor: 'rgba(0,123,255,0.1)', fill: true, tension: 0.1 }
    ]},
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: { x: { display: true, title: { display: true, text: 'Date' } }, y: { display: true, title: { display: true, text: 'Amount ($)' } } }
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
  el.style.display = 'flex'; el.style.alignItems = 'center'; el.style.justifyContent = 'center';
  el.style.height = '200px'; el.style.backgroundColor = '#f8f9fa'; el.style.border = '1px solid #dee2e6'; el.style.borderRadius = '4px';
  el.innerHTML = '<div style="text-align:center;color:#6c757d;"><p>No performance data available yet.</p><p>Start trading to see performance metrics.</p></div>';
}
function showErrorMessage() {
  const el = document.getElementById('performanceChart');
  el.style.display = 'flex'; el.style.alignItems = 'center'; el.style.justifyContent = 'center';
  el.style.height = '200px'; el.style.backgroundColor = '#f8d7da'; el.style.border = '1px solid #f5c6cb'; el.style.borderRadius = '4px';
  el.innerHTML = '<div style="text-align:center;color:#721c24;"><p>Error loading performance data.</p></div>';
}
function loadBreakdownChart() {
  fetch('/api/portfolio-history').then(r => r.json()).then(renderBreakdownChart).catch(console.error);
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
  loadChart(); loadPerformanceChart(); loadBreakdownChart();
});
