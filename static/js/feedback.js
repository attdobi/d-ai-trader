let feedbackPerformanceChart = null;

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
      if (data.period_analysis) updatePerformanceChart(data.period_analysis);
    } else {
      el.innerHTML = '<p>No recent feedback analysis available</p>';
    }
  } catch (e) {
    el.innerHTML = `<p style="color:red;">Error loading feedback: ${e.message}</p>`;
  }
}
function updatePerformanceChart(periodData) {
  const ctx = document.getElementById('performanceChart').getContext('2d');
  if (feedbackPerformanceChart) feedbackPerformanceChart.destroy();
  const periods = ['7d','14d','30d'];
  const successRates = periods.map(p => (periodData[p]?.success_rate || 0) * 100);
  const avgProfits = periods.map(p => (periodData[p]?.avg_profit || 0) * 100);
  feedbackPerformanceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['7 Days','14 Days','30 Days'],
      datasets: [
        { label: 'Success Rate (%)', data: successRates, borderColor: '#4CAF50', backgroundColor: 'rgba(76,175,80,0.1)', yAxisID: 'y' },
        { label: 'Average Profit (%)', data: avgProfits, borderColor: '#2196F3', backgroundColor: 'rgba(33,150,243,0.1)', yAxisID: 'y1' }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { y: { position: 'left' }, y1: { position: 'right', grid: { drawOnChartArea: false } } },
      plugins: { title: { display: true, text: 'Performance Trends' } }
    }
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
}
document.addEventListener('DOMContentLoaded', () => {
  refreshFeedbackData();
  setInterval(refreshFeedbackData, 10000);
});
