function buildLineChart(ctx, labels, datasets, options = {}) {
  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: Object.assign({
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: { x: { display: true }, y: { display: true } }
    }, options)
  });
}
