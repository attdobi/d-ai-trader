/* ========== Schwab Live Dashboard ========== */

let schwabLoading = false;
let allocationChartInstance = null;
let historyChartInstance = null;

function setSchwabLoading(on) {
  schwabLoading = on;
  const refreshBtn = document.getElementById('refresh-btn');
  refreshBtn && (refreshBtn.disabled = on);
}

function updateStatus(icon, text, color = '#007bff') {
  const statusIcon = document.getElementById('status-icon');
  const statusText = document.getElementById('status-text');
  const wrapper = document.querySelector('.connection-status');
  if (statusIcon) statusIcon.textContent = icon;
  if (statusText) statusText.textContent = text;
  if (wrapper) wrapper.style.borderLeftColor = color;
}

function showSchwabError(message) {
  updateStatus('❌', 'Connection Error', '#dc3545');
  const errMsg = document.getElementById('error-message');
  const errSec = document.getElementById('error-section');
  if (errMsg) errMsg.textContent = message;
  if (errSec) errSec.style.display = 'block';
}

function hideSchwabSections() {
  ['schwab-hero', 'schwab-summary', 'schwab-charts-row', 'holdings-section',
   'error-section', 'simulation-warning', 'recent-trades-section']
    .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
}

/* ========== Hero + Account Details ========== */

function renderSchwabData(data) {
  const total = document.getElementById('total-value');
  const cash = document.getElementById('cash-balance');
  const unsettled = document.getElementById('unsettled-cash');
  const funds = document.getElementById('funds-available');
  const orderReserve = document.getElementById('order-reserve');
  const bp = document.getElementById('buying-power');
  const dtbp = document.getElementById('day-trading-power');
  const openOrders = document.getElementById('open-orders');
  const componentsCard = document.getElementById('funds-components-card');
  const componentsText = document.getElementById('funds-components');
  const acctHashEl = document.getElementById('account-hash');
  const acctNumberEl = document.getElementById('account-number');
  const acctTypeEl = document.getElementById('account-type');
  const acctModeEl = document.getElementById('account-mode');
  const lastUpdatedEl = document.getElementById('last-updated');
  const readonlyNoteEl = document.getElementById('readonly-note');
  const readonlyDescription = readonlyNoteEl ? readonlyNoteEl.querySelector('p') : null;
  const accountMetaEl = document.getElementById('account-meta');

  const isMarginAccount = Boolean(
    data.is_margin_account
    ?? data.account_info?.is_margin_account
    ?? false
  );
  const baseFundsAvailable = Number(
    data.funds_available_effective
    ?? data.funds_available_for_trading
    ?? data.account_info?.funds_available_for_trading
    ?? data.account_info?.funds_available_effective
    ?? data.cash_balance
    ?? 0
  );
  const rawSettledCash = Number(
    data.cash_balance_settled
    ?? data.cash_balance
    ?? data.account_info?.cash_balance
    ?? 0
  );
  const unsettledCash = Number(
    data.unsettled_cash
    ?? data.account_info?.unsettled_cash
    ?? 0
  );
  let settledUsable = data.settled_funds_available
    ?? data.account_info?.settled_funds_available;
  if (settledUsable == null) {
    settledUsable = Math.max(rawSettledCash - unsettledCash, 0);
  }
  settledUsable = Math.max(0, Number(settledUsable));
  let fundsDisplay = data.funds_available_display
    ?? data.account_info?.funds_available_display;
  if (fundsDisplay == null) {
    fundsDisplay = isMarginAccount
      ? baseFundsAvailable
      : Math.min(baseFundsAvailable, settledUsable);
  }
  fundsDisplay = Math.max(0, Number(fundsDisplay));

  const portfolioValue = Number(data.total_portfolio_value || 0);
  if (total) total.textContent = formatCurrency(portfolioValue);
  if (funds) funds.textContent = formatCurrency(fundsDisplay);
  if (cash) cash.textContent = formatCurrency(settledUsable);
  if (unsettled) unsettled.textContent = formatCurrency(unsettledCash);

  const reserveValue = data.order_reserve
    ?? data.account_info?.order_reserve
    ?? data.funds_available_components?.order_reserve
    ?? 0;
  if (orderReserve) orderReserve.textContent = formatCurrency(reserveValue);

  const openCount = data.open_orders_count
    ?? data.account_info?.open_orders_count
    ?? 0;
  if (openOrders) openOrders.textContent = openCount;

  const components = data.funds_available_components
    ?? data.account_info?.funds_available_components;
  if (componentsCard && componentsText) {
    if (components || Number.isFinite(fundsDisplay)) {
      const lines = [
        `Usable ${formatCurrency(fundsDisplay)}`,
        `Eff ${formatCurrency(components?.effective ?? baseFundsAvailable)}`,
        `Exp ${formatCurrency(components?.explicit ?? 0)}`,
        `Der ${formatCurrency(components?.derived_cash ?? 0)}`,
        `Sett ${formatCurrency(components?.settled_cash_guardrail ?? settledUsable)}`,
        `Raw ${formatCurrency(components?.settled_cash ?? rawSettledCash)}`,
        `Unsett ${formatCurrency(components?.unsettled_cash ?? unsettledCash)}`,
      ];
      if (typeof components?.order_reserve === 'number') {
        lines.push(`Orders ${formatCurrency(components.order_reserve)}`);
      }
      if (typeof data.open_orders_count === 'number') {
        lines.push(`Open ${data.open_orders_count}`);
      } else if (typeof data.account_info?.open_orders_count === 'number') {
        lines.push(`Open ${data.account_info.open_orders_count}`);
      }
      if (typeof components?.same_day_net === 'number') {
        lines.push(`Same-day ${formatCurrency(components.same_day_net)}`);
      }
      componentsText.textContent = lines.join(' · ');
      componentsCard.style.display = 'block';
    } else {
      componentsCard.style.display = 'none';
    }
  }

  if (data.account_info) {
    if (bp) bp.textContent = formatCurrency(data.account_info.buying_power || 0);
    if (dtbp) dtbp.textContent = formatCurrency(data.account_info.day_trading_buying_power || 0);
    if (acctHashEl) acctHashEl.textContent = data.account_info.account_hash || '—';
    if (acctNumberEl) acctNumberEl.textContent = data.account_info.account_number || '—';
    if (acctTypeEl) acctTypeEl.textContent = data.account_info.account_type || '—';
  }
  if (acctModeEl) acctModeEl.textContent = data.readonly_mode ? 'Read-Only' : (data.live_trading_enabled ? 'Live Trading' : 'Simulation');
  if (lastUpdatedEl) {
    const parsed = data.last_updated ? new Date(data.last_updated) : null;
    lastUpdatedEl.textContent = (parsed && !Number.isNaN(parsed.valueOf()))
      ? parsed.toLocaleString()
      : (data.last_updated || new Date().toLocaleString());
  }
  if (accountMetaEl) accountMetaEl.style.display = 'grid';
  if (readonlyNoteEl) readonlyNoteEl.style.display = data.readonly_mode ? 'block' : 'none';
  if (data.warning && readonlyDescription) readonlyDescription.textContent = data.warning;

  /* ---- Hero P&L ---- */
  let totalPnl = 0;
  let totalCost = 0;
  if (Array.isArray(data.positions)) {
    data.positions.forEach(p => {
      totalPnl += Number(p.gain_loss || 0);
      totalCost += Number(p.total_value || 0);
    });
  }
  const pnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const heroPnl = document.getElementById('hero-pnl');
  const pnlValEl = document.getElementById('total-pnl-value');
  const pnlPctEl = document.getElementById('total-pnl-pct');
  if (pnlValEl) pnlValEl.textContent = formatCurrency(totalPnl);
  if (pnlPctEl) pnlPctEl.textContent = formatPercent(pnlPct);
  if (heroPnl) {
    heroPnl.classList.remove('gain', 'loss');
    heroPnl.classList.add(totalPnl >= 0 ? 'gain' : 'loss');
  }

  /* ---- Cash / Invested subtitle ---- */
  const invested = Math.max(portfolioValue - fundsDisplay, 0);
  const subtitleEl = document.getElementById('cash-invested-subtitle');
  if (subtitleEl) {
    subtitleEl.textContent = `Invested: ${formatCurrency(invested)}`;
  }

  /* ---- Show hero ---- */
  const heroEl = document.getElementById('schwab-hero');
  if (heroEl) heroEl.style.display = 'grid';

  /* ---- Show account details ---- */
  const sum = document.getElementById('schwab-summary');
  if (sum) sum.style.display = 'grid';

  /* ---- Holdings table ---- */
  const tbody = document.getElementById('holdings-body');
  const tfoot = document.getElementById('holdings-foot');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (tfoot) tfoot.innerHTML = '';

  if (Array.isArray(data.positions) && data.positions.length) {
    // Sort by market_value descending
    const sorted = [...data.positions].sort((a, b) => (b.market_value || 0) - (a.market_value || 0));

    let sumMarketValue = 0;
    let sumTotalCost = 0;
    let sumGainLoss = 0;

    sorted.forEach(p => {
      const mv = Number(p.market_value || 0);
      const tc = Number(p.total_value || 0);
      const gl = Number(p.gain_loss || 0);
      sumMarketValue += mv;
      sumTotalCost += tc;
      sumGainLoss += gl;

      const cls = gl >= 0 ? 'gain' : 'loss';
      const rowCls = gl >= 0 ? 'row-gain' : 'row-loss';
      const pctOfPortfolio = portfolioValue > 0 ? (mv / portfolioValue) * 100 : 0;

      const tr = document.createElement('tr');
      tr.className = rowCls;
      tr.innerHTML = `
        <td><strong>${p.symbol}</strong></td>
        <td>${Number(p.shares || 0).toFixed(0)}</td>
        <td>${formatCurrency(p.average_price)}</td>
        <td>${formatCurrency(p.current_price)}</td>
        <td><strong>${formatCurrency(mv)}</strong></td>
        <td>${formatCurrency(tc)}</td>
        <td class="${cls}"><strong>${formatCurrency(gl)}</strong></td>
        <td class="${cls}"><strong>${formatPercent(p.gain_loss_percentage)}</strong></td>
        <td>${pctOfPortfolio.toFixed(1)}%</td>`;
      tbody.appendChild(tr);
    });

    // Totals footer
    if (tfoot) {
      const totalGlPct = sumTotalCost > 0 ? (sumGainLoss / sumTotalCost) * 100 : 0;
      const footCls = sumGainLoss >= 0 ? 'gain' : 'loss';
      const footRow = document.createElement('tr');
      footRow.innerHTML = `
        <td><strong>Total</strong></td>
        <td></td><td></td><td></td>
        <td><strong>${formatCurrency(sumMarketValue)}</strong></td>
        <td><strong>${formatCurrency(sumTotalCost)}</strong></td>
        <td class="${footCls}"><strong>${formatCurrency(sumGainLoss)}</strong></td>
        <td class="${footCls}"><strong>${formatPercent(totalGlPct)}</strong></td>
        <td></td>`;
      tfoot.appendChild(footRow);
    }

    // Render allocation chart
    renderAllocationChart(sorted, fundsDisplay);
  } else {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="9" style="text-align:center;color:#666;padding:40px;">No positions found</td>`;
    tbody.appendChild(tr);
  }

  const hs = document.getElementById('holdings-section');
  if (hs) hs.style.display = 'block';

  // Show charts row
  const chartsRow = document.getElementById('schwab-charts-row');
  if (chartsRow) chartsRow.style.display = 'grid';

  // Fetch additional data
  loadPortfolioHistory();
  loadRecentTrades();
}

/* ========== Allocation Donut Chart ========== */

function renderAllocationChart(positions, cashAmount) {
  const canvas = document.getElementById('allocationChart');
  if (!canvas) return;

  const colors = ['#42c9ff','#36b37e','#6554c0','#ff5f73','#ffab00','#00b8d9','#8777d9','#57d9a3','#ff8b00','#4c9aff'];
  const labels = positions.map(p => p.symbol);
  const values = positions.map(p => Number(p.market_value || 0));

  if (cashAmount > 0) {
    labels.push('Cash');
    values.push(cashAmount);
  }

  const total = values.reduce((s, v) => s + v, 0);

  if (allocationChartInstance) {
    allocationChartInstance.destroy();
  }

  allocationChartInstance = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderWidth: 0,
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#b0b8c9', padding: 12, usePointStyle: true, pointStyleWidth: 10 }
        },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const val = ctx.parsed;
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0';
              return `${ctx.label}: ${formatCurrency(val)} (${pct}%)`;
            }
          }
        }
      }
    }
  });
}

/* ========== Portfolio History Line Chart ========== */

async function loadPortfolioHistory() {
  try {
    const data = await fetchJSON('/api/portfolio-history');
    if (!Array.isArray(data) || data.length === 0) return;

    const canvas = document.getElementById('schwabHistoryChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 300);
    gradient.addColorStop(0, 'rgba(66,201,255,0.15)');
    gradient.addColorStop(1, 'transparent');

    const labels = data.map(d => {
      const dt = new Date(d.timestamp);
      return dt.toLocaleDateString();
    });
    const values = data.map(d => Number(d.total_portfolio_value || 0));

    if (historyChartInstance) {
      historyChartInstance.destroy();
    }

    historyChartInstance = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Portfolio Value',
          data: values,
          borderColor: '#42c9ff',
          backgroundColor: gradient,
          fill: true,
          pointRadius: 0,
          tension: 0.3,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function(items) { return items[0]?.label || ''; },
              label: function(ctx) { return formatCurrency(ctx.parsed.y); }
            }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#6b7a90', maxTicksLimit: 8 }
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: {
              color: '#6b7a90',
              callback: function(val) { return formatCurrency(val); }
            }
          }
        }
      }
    });
  } catch (e) {
    console.warn('Failed to load portfolio history:', e.message);
  }
}

/* ========== Recent Trades ========== */

async function loadRecentTrades() {
  try {
    const data = await fetchJSON('/api/trade_outcomes');
    if (!Array.isArray(data) || data.length === 0) return;

    const section = document.getElementById('recent-trades-section');
    const tbody = document.getElementById('recent-trades-body');
    if (!section || !tbody) return;

    tbody.innerHTML = '';
    const trades = data.slice(0, 10);

    trades.forEach(t => {
      const gl = Number(t.net_gain_dollars || 0);
      const glPct = Number(t.gain_loss_pct || 0);
      const cls = gl >= 0 ? 'gain' : 'loss';
      const rowCls = gl >= 0 ? 'row-gain' : 'row-loss';
      const holdDays = t.hold_days != null ? `${t.hold_days}d` : '—';
      const sellDate = t.sell_date ? new Date(t.sell_date).toLocaleDateString() : '—';

      const tr = document.createElement('tr');
      tr.className = rowCls;
      tr.innerHTML = `
        <td><strong>${t.ticker || '—'}</strong></td>
        <td>${sellDate}</td>
        <td class="${cls}"><strong>${formatCurrency(gl)}</strong></td>
        <td class="${cls}"><strong>${formatPercent(glPct)}</strong></td>
        <td>${holdDays}</td>
        <td>${t.category || '—'}</td>`;
      tbody.appendChild(tr);
    });

    section.style.display = 'block';
  } catch (e) {
    console.warn('Failed to load recent trades:', e.message);
  }
}

/* ========== Main Refresh ========== */

async function refreshSchwabData() {
  if (schwabLoading) return;
  setSchwabLoading(true);
  hideSchwabSections();
  updateStatus('🔄', 'Loading...', '#ffc107');
  try {
    const data = await fetchJSON('/api/schwab/holdings');
    setSchwabLoading(false);
    if (!data.enabled) return showSchwabError('Schwab integration is not available. Please check your configuration.');
    if (data.status === 'error') return showSchwabError(data.message || 'Failed to retrieve Schwab data');
    if (data.status === 'disabled') {
      updateStatus('ℹ️', 'Schwab API disabled', '#ffc107');
      const w = document.getElementById('simulation-warning');
      if (w) w.style.display = 'block';
      return;
    }
    if (data.status === 'success') {
      updateStatus('✅', 'Connected to Schwab', '#28a745');
      if (data.raw_snapshot) {
        console.log('📡 Schwab snapshot:', data.raw_snapshot);
      }
      renderSchwabData(data);
      return;
    }
    showSchwabError('Unexpected response from Schwab API');
  } catch (e) {
    setSchwabLoading(false);
    showSchwabError(`Connection failed: ${e.message}`);
  }
}

/* ========== Init ========== */

document.addEventListener('DOMContentLoaded', () => {
  refreshSchwabData();
  // Poll Schwab every 2 minutes
  setInterval(() => { if (!schwabLoading) refreshSchwabData(); }, 120000);

  // Collapsible account details persistence
  const details = document.getElementById('schwab-account-details');
  if (details) {
    if (localStorage.getItem('schwab-details-open') === 'true') details.open = true;
    details.addEventListener('toggle', () => localStorage.setItem('schwab-details-open', details.open));
  }
});
