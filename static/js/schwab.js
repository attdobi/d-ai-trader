let schwabLoading = false;
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
  ['schwab-summary','holdings-section','error-section','simulation-warning']
    .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
}
function renderSchwabData(data) {
  const total = document.getElementById('total-value');
  const cash = document.getElementById('cash-balance');
  const bp = document.getElementById('buying-power');
  const dtbp = document.getElementById('day-trading-power');
  const acctHashEl = document.getElementById('account-hash');
  const acctNumberEl = document.getElementById('account-number');
  const acctTypeEl = document.getElementById('account-type');
  const acctModeEl = document.getElementById('account-mode');
  const lastUpdatedEl = document.getElementById('last-updated');
  const readonlyNoteEl = document.getElementById('readonly-note');
  const readonlyDescription = readonlyNoteEl ? readonlyNoteEl.querySelector('p') : null;
  const accountMetaEl = document.getElementById('account-meta');

  if (total) total.textContent = formatCurrency(data.total_portfolio_value || 0);
  if (cash) cash.textContent = formatCurrency(data.cash_balance || 0);
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

  const sum = document.getElementById('schwab-summary');
  if (sum) sum.style.display = 'grid';
  const tbody = document.getElementById('holdings-body');
  if (!tbody) return;
  tbody.innerHTML = '';
  if (Array.isArray(data.positions) && data.positions.length) {
    data.positions.forEach(p => {
      const tr = document.createElement('tr');
      const cls = (p.gain_loss >= 0) ? 'gain' : 'loss';
      tr.innerHTML = `
        <td><strong>${p.symbol}</strong></td>
        <td>${Number(p.shares || 0).toFixed(0)}</td>
        <td>${formatCurrency(p.average_price)}</td>
        <td>${formatCurrency(p.current_price)}</td>
        <td><strong>${formatCurrency(p.market_value)}</strong></td>
        <td>${formatCurrency(p.total_value)}</td>
        <td class="${cls}"><strong>${formatCurrency(p.gain_loss)}</strong></td>
        <td class="${cls}"><strong>${formatPercent(p.gain_loss_percentage)}</strong></td>`;
      tbody.appendChild(tr);
    });
  } else {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="8" style="text-align:center;color:#666;padding:40px;">No positions found</td>`;
    tbody.appendChild(tr);
  }
  const hs = document.getElementById('holdings-section');
  if (hs) hs.style.display = 'block';
}
async function refreshSchwabData() {
  if (schwabLoading) return;
  setSchwabLoading(true); hideSchwabSections(); updateStatus('🔄','Loading...','#ffc107');
  try {
    const data = await fetchJSON('/api/schwab/holdings');
    setSchwabLoading(false);
    if (!data.enabled) return showSchwabError('Schwab integration is not available. Please check your configuration.');
    if (data.status === 'error') return showSchwabError(data.message || 'Failed to retrieve Schwab data');
    if (data.status === 'disabled') {
      updateStatus('ℹ️','Schwab API disabled','#ffc107');
      const w = document.getElementById('simulation-warning');
      if (w) w.style.display = 'block';
      return;
    }
    if (data.status === 'success') {
      updateStatus('✅','Connected to Schwab','#28a745');
      renderSchwabData(data);
      return;
    }
    showSchwabError('Unexpected response from Schwab API');
  } catch (e) {
    setSchwabLoading(false);
    showSchwabError(`Connection failed: ${e.message}`);
  }
}
document.addEventListener('DOMContentLoaded', () => {
  refreshSchwabData();
  setInterval(() => { if (!schwabLoading) refreshSchwabData(); }, 30000);
});
