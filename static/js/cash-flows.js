/* ========== Cash transfers: shared fetch + chart markers ==========
 * Deposits and withdrawals are not performance. Every gain on the Dashboard and the Feedback tab
 * already excludes them (cash_flows.py); these markers explain the jumps they leave in value charts.
 * Each counted transfer becomes a dotted vertical line with a ▲ green (deposit) / ▼ red (withdrawal)
 * head, a "+$700 deposit" pill near the x-axis and a hover card (date, source, description).
 * Transfers a few pixels apart share one pill ("4 transfers · net +$439.50"); zooming splits them.
 *
 * Usage (any Chart.js line chart on a category x-axis):
 *   plugins: [transferMarkersPlugin]                 // or Chart.register(transferMarkersPlugin)
 *   setTransferMarkers(chart, flows, isoDatePerPoint); chart.draw();
 *   tooltip.callbacks.footer: items => transferTooltipFooter(items)
 * A transfer snaps to the first plotted point dated on/after it (weekend transfers land on the next
 * session); transfers before the first or after the last plotted date are not drawn.
 */
const TRANSFER_INK = {
  deposit: '#29d697',
  withdrawal: '#ff5f73',
  cardBg: 'rgba(21,31,53,0.96)',
  cardBorder: '#3a4a63',
  text: '#dfe8f7',
  muted: '#9bb0cc',
};

let _cashFlowsPromise = null;

// One fetch per page (force=true after an edit). Resolves to the /api/cash-flows payload or null.
function loadCashFlows(force = false, query = '') {
  if (force || !_cashFlowsPromise) {
    _cashFlowsPromise = fetch(`/api/cash-flows${query ? `?${query}` : ''}`)
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _cashFlowsPromise;
}

// 'YYYY-MM-DD' in the browser's local day (date-only strings are returned as-is, never shifted by UTC).
function isoLocalDate(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function transferMoney(amount) {
  const a = Math.abs(Number(amount) || 0);
  const whole = Math.abs(a - Math.round(a)) < 0.005;
  return '$' + a.toLocaleString('en-US', { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 });
}

function transferLabel(amount) {
  const dep = Number(amount) >= 0;
  return `${dep ? '+' : '−'}${transferMoney(amount)} ${dep ? 'deposit' : 'withdrawal'}`;
}

function transferIndexFor(dates, isoDate) {
  if (!dates || !dates.length || !isoDate) return -1;
  if (!dates[0] || isoDate < dates[0]) return -1;
  for (let i = 0; i < dates.length; i++) {
    if (dates[i] && dates[i] >= isoDate) return i;
  }
  return -1;
}

// Attach the counted transfers of `flows` to `chart` against its per-point ISO dates.
function setTransferMarkers(chart, flows, dates) {
  if (!chart) return;
  const markers = [];
  for (const f of flows || []) {
    if (!f || f.counted === false) continue;
    const index = transferIndexFor(dates, f.date);
    if (index >= 0) markers.push({ index, flow: f });
  }
  chart.$transferMarkers = markers;
  chart.$transferDates = dates || [];
  chart.$transferHover = null;
}

// Tooltip footer lines for the transfers that snapped to the hovered point's date.
function transferTooltipFooter(items) {
  const item = items && items[0];
  if (!item) return [];
  const chart = item.chart;
  const markers = chart && chart.$transferMarkers;
  if (!markers || !markers.length) return [];
  const dates = chart.$transferDates || [];
  const day = dates[item.dataIndex];
  if (!day) return [];
  return markers
    .filter(m => dates[m.index] === day)
    .map(m => `${m.flow.amount >= 0 ? '▲' : '▼'} ${transferLabel(m.flow.amount)} (${m.flow.date}) — transfer, not a gain`);
}

function _transferRoundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (typeof ctx.roundRect === 'function') ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
}


// Markers closer than this many pixels share one pill ("4 transfers · net +$439.50"); zooming in
// splits them again.
const TRANSFER_GROUP_PX = 28;

function _transferGroups(chart) {
  const markers = chart.$transferMarkers;
  const { chartArea } = chart;
  const xScale = chart.scales && chart.scales.x;
  if (!markers || !markers.length || !xScale || !chartArea) return [];
  const visible = [];
  for (const m of markers) {
    const x = xScale.getPixelForValue(m.index);
    if (Number.isFinite(x) && x >= chartArea.left - 1 && x <= chartArea.right + 1) visible.push({ x, m });
  }
  visible.sort((a, b) => a.x - b.x);
  const groups = [];
  for (const v of visible) {
    const g = groups[groups.length - 1];
    if (g && v.x - g.members[g.members.length - 1].x <= TRANSFER_GROUP_PX) g.members.push(v);
    else groups.push({ members: [v] });
  }
  for (const g of groups) {
    g.net = g.members.reduce((s, v) => s + (Number(v.m.flow.amount) || 0), 0);
    g.label = g.members.length === 1
      ? (g.members[0].m.flow.label || transferLabel(g.members[0].m.flow.amount))
      : `${g.members.length} transfers · net ${g.net >= 0 ? '+' : '−'}${transferMoney(g.net)}`;
  }
  return groups;
}

const transferMarkersPlugin = {
  id: 'transferMarkers',
  afterDatasetsDraw(chart) {
    chart.$transferHit = [];
    const groups = _transferGroups(chart);
    if (!groups.length) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    const pillH = 15;
    const maxRows = Math.max(1, Math.floor((chartArea.bottom - chartArea.top - 30) / (pillH + 3)));
    for (const g of groups) {
      for (const { x, m } of g.members) {
        const dep = Number(m.flow.amount) >= 0;
        const color = dep ? TRANSFER_INK.deposit : TRANSFER_INK.withdrawal;
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.8;
        ctx.lineWidth = 1.25;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
        // Arrow head on the x-axis: ▲ money in, ▼ money out.
        const yb = chartArea.bottom - 1;
        ctx.fillStyle = color;
        ctx.beginPath();
        if (dep) { ctx.moveTo(x, yb - 9); ctx.lineTo(x - 5, yb); ctx.lineTo(x + 5, yb); }
        else { ctx.moveTo(x, yb); ctx.lineTo(x - 5, yb - 9); ctx.lineTo(x + 5, yb - 9); }
        ctx.closePath();
        ctx.fill();
      }
    }

    // One pill per group just above the arrows, stacking upward when pills would overlap. When the
    // full labels do not all fit (small or crowded chart), every pill switches to the bare net amount
    // rounded ("+$440"); a pill that still has no room is skipped (its lines and hover card remain).
    const layout = textOf => {
      const placed = [];
      let missing = 0;
      const out = groups.map(g => {
        const text = textOf(g);
        const x0 = g.members[0].x;
        const xN = g.members[g.members.length - 1].x;
        const w = ctx.measureText(text).width + 12;
        let lx = xN + 6;
        if (lx + w > chartArea.right) lx = x0 - 6 - w;
        lx = Math.max(chartArea.left, lx);
        let row = 0;
        while (row < maxRows && placed.some(p => p.row === row && lx < p.x1 + 2 && lx + w > p.x0 - 2)) row++;
        if (row >= maxRows) { missing += 1; return null; }
        placed.push({ row, x0: lx, x1: lx + w });
        return { text, lx, w, ly: chartArea.bottom - 14 - pillH - row * (pillH + 3) };
      });
      return { out, missing };
    };
    const compactOf = g => `${g.net >= 0 ? '+' : '−'}$${Math.round(Math.abs(g.net)).toLocaleString('en-US')}`;
    let pills = layout(g => g.label);
    if (pills.missing) {
      const compact = layout(compactOf);
      if (compact.missing <= pills.missing) pills = compact;
    }

    groups.forEach((g, i) => {
      const hit = { x0: g.members[0].x - 5, x1: g.members[g.members.length - 1].x + 5,
                    xs: g.members.map(v => v.x), group: g, y0: null, y1: null };
      const p = pills.out[i];
      if (p) {
        const color = g.net >= 0 ? TRANSFER_INK.deposit : TRANSFER_INK.withdrawal;
        ctx.fillStyle = TRANSFER_INK.cardBg;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        _transferRoundRect(ctx, p.lx, p.ly, p.w, pillH, 7);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.textAlign = 'left';
        ctx.fillText(p.text, p.lx + 6, p.ly + pillH / 2 + 0.5);
        Object.assign(hit, { x0: Math.min(hit.x0, p.lx), x1: Math.max(hit.x1, p.lx + p.w), y0: p.ly, y1: p.ly + pillH });
      }
      chart.$transferHit.push(hit);
    });
    ctx.restore();
  },
  afterEvent(chart, args) {
    const hits = chart.$transferHit;
    if (!hits || !hits.length) return;
    const e = args.event;
    const area = chart.chartArea;
    let hover = null;
    if (e && e.type !== 'mouseout' && e.x != null && area) {
      hover = hits.find(h => h.y0 != null && e.x >= h.x0 && e.x <= h.x1 && e.y >= h.y0 - 2 && e.y <= h.y1 + 2)
        || hits.find(h => h.xs.some(x => Math.abs(e.x - x) <= 3) && e.y >= area.top && e.y <= area.bottom)
        || null;
    }
    const before = chart.$transferHover ? chart.$transferHover.group : null;
    const after = hover ? hover.group : null;
    if (before !== after) {
      chart.$transferHover = hover;
      _showTransferCard(chart, hover);
    }
  },
  afterDestroy(chart) {
    if (chart.$transferHover) _showTransferCard(chart, null);
  },
};

// Hover card: a fixed-position DOM element (never clipped by a small canvas), one per page.
function _transferEsc(value) {
  return String(value == null ? '' : value).replace(/[&<>'"]/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function _transferCardEl() {
  let el = document.getElementById('transferHoverCard');
  if (!el) {
    el = document.createElement('div');
    el.id = 'transferHoverCard';
    el.className = 'transfer-hover-card';
    el.setAttribute('role', 'tooltip');
    el.hidden = true;
    document.body.appendChild(el);
    window.addEventListener('scroll', () => { el.hidden = true; }, { passive: true });
  }
  return el;
}

function _showTransferCard(chart, hit) {
  const el = _transferCardEl();
  if (!hit) { el.hidden = true; return; }
  const members = hit.group.members.map(v => v.m.flow);
  const rows = [];
  if (members.length > 1) {
    rows.push(`<div class="thc-title ${hit.group.net >= 0 ? 'dep' : 'wd'}">${_transferEsc(hit.group.label)}</div>`);
  }
  for (const f of members.slice(0, 8)) {
    const dep = Number(f.amount) >= 0;
    const desc = String(f.note || f.description || '').trim();
    rows.push(`<div class="thc-row"><span class="thc-amt ${dep ? 'dep' : 'wd'}">${dep ? '▲' : '▼'} ${_transferEsc(transferLabel(f.amount))}</span>` +
      `<span class="thc-meta">${_transferEsc(f.date)} · ${f.source === 'manual' ? 'manual entry' : 'Schwab'}` +
      `${desc ? ` · ${_transferEsc(desc.length > 60 ? `${desc.slice(0, 59)}…` : desc)}` : ''}</span></div>`);
  }
  if (members.length > 8) rows.push(`<div class="thc-meta">… ${members.length - 8} more (zoom in to separate)</div>`);
  rows.push('<div class="thc-foot">Not performance — excluded from gains</div>');
  el.innerHTML = rows.join('');
  el.hidden = false;

  const rect = chart.canvas.getBoundingClientRect();
  const cw = el.offsetWidth;
  const chh = el.offsetHeight;
  const xs = hit.xs;
  let left = rect.left + xs[xs.length - 1] + 12;
  if (left + cw > window.innerWidth - 8) left = rect.left + xs[0] - 12 - cw;
  left = Math.max(8, Math.min(left, window.innerWidth - cw - 8));
  const anchorY = hit.y0 != null ? hit.y0 : chart.chartArea.top;
  let top = rect.top + anchorY - chh - 8;
  if (top < 8) top = rect.top + anchorY + 24;
  el.style.left = `${Math.round(left)}px`;
  el.style.top = `${Math.round(top)}px`;
}
