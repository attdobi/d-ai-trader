// Trades tab: pagination, filters, and the daily summary bar are all
// SERVER-side now (see the /trades route) — each page renders whole decision
// runs so trade rows and their RLHF feedback block can never separate.
// The only client behavior left is the Yahoo Finance chart popup.
document.addEventListener('DOMContentLoaded', () => {
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
});
