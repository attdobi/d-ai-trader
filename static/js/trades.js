document.addEventListener('DOMContentLoaded', () => {
  // Chart button popup
  const popupFeatures = () => {
    const width = Math.min(window.outerWidth - 120, 1200);
    const height = Math.min(window.outerHeight - 120, 800);
    const left = window.screenX + Math.max((window.outerWidth - width) / 2, 20);
    const top = window.screenY + Math.max((window.outerHeight - height) / 2, 20);
    return `popup=yes,resizable=yes,scrollbars=yes,width=${width},height=${height},left=${left},top=${top}`;
  };

  document.querySelectorAll('.chart-button').forEach(button => {
    button.addEventListener('click', (e) => {
      e.stopPropagation();
      const ticker = button.dataset.ticker;
      if (!ticker) return;
      window.open(`https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}/chart`, `${ticker}_chart`, popupFeatures());
    });
  });

  // Filter chips
  const chips = document.querySelectorAll('.chip[data-filter]');
  const rows = document.querySelectorAll('.trade-row');

  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      const filter = chip.dataset.filter;
      rows.forEach(row => {
        const action = (row.dataset.action || '').toLowerCase();
        if (filter === 'all') {
          row.style.display = '';
        } else if (filter === 'market_closed') {
          row.style.display = action.includes('market_closed') || action.includes('market closed') ? '' : 'none';
        } else {
          row.style.display = action.includes(filter) ? '' : 'none';
        }
      });
    });
  });

  // Daily summary calculation
  let buyCount = 0, sellCount = 0, buyTotal = 0, sellTotal = 0;
  const today = new Date().toLocaleDateString();
  rows.forEach(row => {
    const cells = row.querySelectorAll('td');
    const timestamp = cells[cells.length - 1]?.textContent?.trim() || '';
    // Check if trade is from today (rough match)
    const action = (row.dataset.action || '').toLowerCase();
    if (action.includes('buy')) { buyCount++; }
    if (action.includes('sell')) { sellCount++; }
  });

  const buysEl = document.getElementById('todayBuys');
  const sellsEl = document.getElementById('todaySells');
  const netEl = document.getElementById('todayNet');
  if (buysEl) buysEl.textContent = buyCount;
  if (sellsEl) sellsEl.textContent = sellCount;
  if (netEl) netEl.textContent = `${buyCount + sellCount} trades`;
});
