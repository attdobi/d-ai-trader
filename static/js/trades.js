document.addEventListener('DOMContentLoaded', () => {
  const PAGE_SIZE = 25;
  let currentPage = 1;
  let activeFilter = 'all';
  const allRows = Array.from(document.querySelectorAll('.trade-row'));
  
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

  function getFilteredRows() {
    return allRows.filter(row => {
      const action = (row.dataset.action || '').toLowerCase();
      if (activeFilter === 'all') return true;
      if (activeFilter === 'today') {
        const cells = row.querySelectorAll('td');
        const tsText = cells[cells.length - 1]?.textContent?.trim() || '';
        const today = new Date().toLocaleDateString();
        try {
          const rowDate = new Date(tsText).toLocaleDateString();
          return rowDate === today;
        } catch { return false; }
      }
      if (activeFilter === 'market_closed') {
        return action.includes('market_closed') || action.includes('market closed');
      }
      return action.includes(activeFilter);
    });
  }

  function renderPage() {
    const filtered = getFilteredRows();
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;
    const start = (currentPage - 1) * PAGE_SIZE;
    const end = start + PAGE_SIZE;

    // Hide all, show only current page
    allRows.forEach(r => r.style.display = 'none');
    filtered.forEach((row, i) => {
      row.style.display = (i >= start && i < end) ? '' : 'none';
    });

    // Update pagination controls
    const pageInfo = document.getElementById('pageInfo');
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');
    if (pageInfo) pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${filtered.length} trades)`;
    if (prevBtn) prevBtn.disabled = currentPage <= 1;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
  }

  // Filter chips
  const chips = document.querySelectorAll('.chip[data-filter]');
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeFilter = chip.dataset.filter;
      currentPage = 1;
      renderPage();
      updateDailySummary();
    });
  });

  window.changePage = function(delta) {
    currentPage += delta;
    renderPage();
  };

  function updateDailySummary() {
    const today = new Date().toLocaleDateString();
    let buyCount = 0, sellCount = 0;
    allRows.forEach(row => {
      const cells = row.querySelectorAll('td');
      const tsText = cells[cells.length - 1]?.textContent?.trim() || '';
      let isToday = false;
      try { isToday = new Date(tsText).toLocaleDateString() === today; } catch {}
      if (!isToday) return;
      const action = (row.dataset.action || '').toLowerCase();
      if (action.includes('buy')) buyCount++;
      if (action.includes('sell')) sellCount++;
    });
    const buysEl = document.getElementById('todayBuys');
    const sellsEl = document.getElementById('todaySells');
    const netEl = document.getElementById('todayNet');
    if (buysEl) buysEl.textContent = buyCount;
    if (sellsEl) sellsEl.textContent = sellCount;
    if (netEl) netEl.textContent = `${buyCount + sellCount} trades`;
  }

  // Add "Today" chip if not present
  const filterContainer = document.getElementById('filterChips');
  if (filterContainer && !filterContainer.querySelector('[data-filter="today"]')) {
    const todayChip = document.createElement('button');
    todayChip.className = 'chip';
    todayChip.dataset.filter = 'today';
    todayChip.textContent = '📅 Today';
    // Insert after "All" chip
    const allChip = filterContainer.querySelector('[data-filter="all"]');
    if (allChip && allChip.nextSibling) {
      filterContainer.insertBefore(todayChip, allChip.nextSibling);
    } else {
      filterContainer.appendChild(todayChip);
    }
    todayChip.addEventListener('click', () => {
      chips.forEach(c => c.classList.remove('active'));
      todayChip.classList.add('active');
      activeFilter = 'today';
      currentPage = 1;
      renderPage();
      updateDailySummary();
    });
  }

  updateDailySummary();
  renderPage();
});
