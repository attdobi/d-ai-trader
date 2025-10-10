async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
function formatCurrency(n) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(n || 0));
}
function formatPercent(x, digits = 2, withSign = true) {
  const v = Number(x || 0);
  const sign = withSign ? (v >= 0 ? '+' : '') : '';
  return `${sign}${v.toFixed(digits)}%`;
}
