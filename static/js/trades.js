document.addEventListener('DOMContentLoaded', () => {
  const popupFeatures = () => {
    const width = Math.min(window.outerWidth - 120, 1200);
    const height = Math.min(window.outerHeight - 120, 800);
    const left = window.screenX + Math.max((window.outerWidth - width) / 2, 20);
    const top = window.screenY + Math.max((window.outerHeight - height) / 2, 20);
    return `popup=yes,resizable=yes,scrollbars=yes,width=${width},height=${height},left=${left},top=${top}`;
  };

  document.querySelectorAll('.chart-button').forEach(button => {
    button.addEventListener('click', () => {
      const ticker = button.dataset.ticker;
      if (!ticker) return;
      const chartUrl = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}/chart`;
      window.open(chartUrl, `${ticker}_chart`, popupFeatures());
    });
  });
});

