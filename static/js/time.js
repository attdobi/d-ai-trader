function utcStringToLocal(utc) {
  try {
    const iso = utc.includes('T') ? `${utc}Z` : `${utc.replace(' ', 'T')}Z`;
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return utc;
  }
}
function applyLocalTimestamps(selector = '.timestamp-utc') {
  document.querySelectorAll(selector).forEach(el => {
    const utc = el.getAttribute('data-timestamp') || el.textContent;
    el.textContent = utcStringToLocal(utc);
  });
}
document.addEventListener('DOMContentLoaded', () => applyLocalTimestamps());
