/* Presentation vocabulary for the policy explorer. Canonical graph data stays unchanged. */
(function (root, factory) {
  'use strict';
  const schema = factory();
  if (typeof module === 'object' && module.exports) module.exports = schema;
  else root.PolicyGraphSchema = schema;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const TYPES = Object.freeze({
    rule: Object.freeze({ label: 'Rule', token: 'R', color: '#fb7185' }),
    principle: Object.freeze({ label: 'Principle', token: 'P', color: '#a78bfa' }),
    lesson: Object.freeze({ label: 'Lesson', token: 'L', color: '#2dd4bf' }),
    diary: Object.freeze({ label: 'Diary', token: 'D', color: '#fbbf24' }),
    memory: Object.freeze({ label: 'Memory', token: 'M', color: '#60a5fa' }),
    context: Object.freeze({ label: 'Context', token: 'C', color: '#38bdf8' }),
    scaffold: Object.freeze({ label: 'Scaffold', token: 'S', color: '#94a3b8' }),
    group: Object.freeze({ label: 'Group', token: 'G', color: '#64748b' })
  });
  const GROUPS = Object.freeze([
    Object.freeze({ id: 'identity', label: 'Identity', description: 'Mission and guiding principles' }),
    Object.freeze({ id: 'rules', label: 'Trading rules', description: 'Strategy and decision gates' }),
    Object.freeze({ id: 'learning', label: 'Learned context', description: 'Lessons and dated experience' }),
    Object.freeze({ id: 'scaffold', label: 'Prompt scaffold', description: 'Templates and code-owned instructions' }),
    Object.freeze({ id: 'context', label: 'Cycle context', description: 'Memory, market factors and references' })
  ]);
  const EDGE_GROUPS = Object.freeze({
    hierarchy: Object.freeze({ label: 'Structure', color: '#64748b', dash: null }),
    flow: Object.freeze({ label: 'Flow', color: '#38bdf8', dash: null }),
    reference: Object.freeze({ label: 'Reference', color: '#a78bfa', dash: '3 4' })
  });
  const EDGE_TYPES = Object.freeze({
    subtype_of: Object.freeze({ group: 'hierarchy', label: 'Part of', directed: true }),
    includes: Object.freeze({ group: 'flow', label: 'Includes', directed: true }),
    constrains: Object.freeze({ group: 'flow', label: 'Constrains', directed: true }),
    enforced_by: Object.freeze({ group: 'flow', label: 'Enforced by', directed: true }),
    triggers: Object.freeze({ group: 'flow', label: 'Triggers', directed: true }),
    related_to: Object.freeze({ group: 'reference', label: 'Related to', directed: false }),
    overlaps: Object.freeze({ group: 'reference', label: 'Overlaps', directed: false }),
    cites: Object.freeze({ group: 'reference', label: 'Cites', directed: true }),
    exception_to: Object.freeze({ group: 'reference', label: 'Exception to', directed: true }),
    boundary_with: Object.freeze({ group: 'reference', label: 'Boundary with', directed: false }),
    confused_with: Object.freeze({ group: 'reference', label: 'Confused with', directed: false }),
    clarifies: Object.freeze({ group: 'reference', label: 'Clarifies', directed: true }),
    example_of: Object.freeze({ group: 'reference', label: 'Example of', directed: true }),
    negative_example_of: Object.freeze({ group: 'reference', label: 'Counterexample of', directed: true })
  });
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const ACRONYMS = new Set(['AI', 'API', 'CPI', 'ETF', 'FOMC', 'JSON', 'MA', 'P&L', 'RS20', 'RSI', 'SPY', 'QQQ', 'USD', 'VWAP']);

  function plainText(value) {
    return String(value == null ? '' : value)
      .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, target, alias) => alias || target)
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/<[^>]*>/g, '')
      .replace(/(?:\*\*|__|`)/g, '')
      .replace(/^\s{0,3}#{1,6}\s+/gm, '')
      .replace(/^\s*[-*]\s+/gm, '')
      .replace(/\s+/g, ' ').trim();
  }

  function sentenceCase(value) {
    return value.split(/\s+/).map((word, index) => {
      const bare = word.replace(/^[^\w]+|[^\w&]+$/g, '');
      if (ACRONYMS.has(bare.toUpperCase())) return word.replace(bare, bare.toUpperCase());
      if (!/[A-Za-z]/.test(word)) return word;
      const lower = word.toLowerCase();
      return index === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    }).join(' ');
  }

  function cleanTitle(value, id) {
    let title = plainText(value || String(id || '').split('.').pop() || 'Untitled guideline');
    title = title.replace(/^\d+\.\s*/, '').replace(/^#+/, '').trim();
    title = title.replace(/\s*\((?:shared across all agents|preserve verbatim)[^)]*\)/gi, '').trim();
    // Learned-rule titles often contain the entire rule. Keep its label on the
    // card; body text and the canonical title remain in the inspector.
    title = title.split(/\s+[—–]\s+|\s+-\s+/)[0].trim();
    if (/^\d{4}[-_]\d{2}[-_]\d{2}/.test(title)) {
      const match = /^(\d{4})[-_](\d{2})[-_](\d{2})(.*)$/.exec(title);
      const month = Number(match[2]), day = Number(match[3]);
      if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
        const suffix = plainText(match[4]).replace(/^\s*#/, '').replace(/[_-]/g, ' ').trim();
        return `${MONTHS[month - 1]} ${day}, ${match[1]}${suffix ? ' · ' + sentenceCase(suffix) : ''}`;
      }
    }
    title = title.replace(/[_-]/g, ' ').replace(/\s+/g, ' ').trim();
    return sentenceCase(title || 'Untitled guideline');
  }

  function snippet(value, limit) {
    const text = plainText(value);
    const size = Number.isFinite(Number(limit)) ? Math.max(1, Math.floor(Number(limit))) : 132;
    if (text.length <= size) return text;
    const head = text.slice(0, Math.max(1, size - 1));
    const space = head.lastIndexOf(' ');
    return (space > size * 0.55 ? head.slice(0, space) : head).trimEnd() + '…';
  }

  function layerOf(node) {
    if (['policy', 'scaffold', 'context'].includes(node.layer)) return node.layer;
    if (node.owner === 'world' || node.owner === 'decider_memory' || ['ltm', 'factor', 'ticker', 'concept'].includes(node.node_type)) return 'context';
    if (['db', 'default-file', 'proposal'].includes(node.owner) && ['soul', 'strategy_directives', 'memory'].includes(node.field)) return 'policy';
    return 'scaffold';
  }

  function structuralNode(node) {
    const type = String(node.node_type || '').toLowerCase();
    if (type === 'root' || type === 'field') return true;
    if (/\.(?:code|factor|ltm)$/.test(String(node.id || ''))) return true;
    if (type !== 'section') return false;
    // Soul sections often contain actual principles: do not hide them merely
    // because their storage node type is "section".
    const content = String(node.body || '').replace(/^\s*#{1,6}[^\n]*(?:\n|$)/gm, '').trim();
    return !content || (node.has_children === true && /^\*[^*]+\*$/.test(content));
  }

  function groupOf(node, layer) {
    if (layer === 'context') return 'context';
    if (layer === 'scaffold') return 'scaffold';
    return ({ soul: 'identity', strategy_directives: 'rules', memory: 'learning' })[node.field] || 'learning';
  }

  function typeOf(node, structural, layer) {
    if (structural) return 'group';
    const type = String(node.node_type || '').toLowerCase();
    if (type === 'ltm' || node.owner === 'decider_memory') return 'memory';
    if (['factor', 'ticker', 'concept'].includes(type) || node.owner === 'world') return 'context';
    if (layer === 'scaffold' || ['code', 'template', 'data'].includes(type)) return 'scaffold';
    if (type === 'entry') return 'diary';
    if (type === 'lesson' || (type === 'note' && node.field === 'memory')) return 'lesson';
    if (type === 'rule' || type === 'reminder') return 'rule';
    if (node.field === 'soul' || type === 'identity') return 'principle';
    if (node.field === 'strategy_directives') return 'rule';
    if (node.field === 'memory') return 'lesson';
    return 'context';
  }

  function count(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.floor(number)) : null;
  }

  function nodeView(value) {
    const node = value || {};
    const layer = layerOf(node), structural = structuralNode(node);
    const type = typeOf(node, structural, layer), definition = TYPES[type];
    const group = groupOf(node, layer), grouping = GROUPS.find(item => item.id === group);
    const sourceLabel = ({ db: 'Learned policy', 'default-file': 'Default file', code: 'Code', world: 'Market',
      decider_memory: 'Memory store', runtime: 'Runtime', generated: 'Generated', proposal: 'Proposal' })[node.owner] || 'Policy';
    const inactive = node.active === false || node.extra?.active === false || node.meta?.active === false || ['inactive', 'retired', 'archived'].includes(node.status);
    const retired = inactive && layer !== 'scaffold';
    const proposed = Boolean(node.ghost || node.proposed || node.owner === 'proposal');
    const statusLabel = proposed ? 'Proposed' : retired ? 'Retired' : inactive ? 'Not used' : node.status === 'inert' ? 'Historical' : 'Current';
    return {
      id: String(node.id || ''), type, typeLabel: definition.label, token: definition.token, color: definition.color,
      group, groupLabel: grouping.label, layer, structural,
      title: cleanTitle(node.title, node.id), subtitle: snippet(node.body, 132), sourceLabel, statusLabel,
      features: {
        source: node.owner || 'unknown', status: node.status || 'active', active: !inactive,
        editable: node.owner === 'db' && !node.locked && !structural && !proposed,
        locked: Boolean(node.locked), proposed,
        cited30d: count(node.hits?.cited_30d), served30d: count(node.hits?.served_30d),
        changed: ['added', 'changed', 'renamed', 'whitespace', 'source_changed'].includes(node.change),
        change: node.change || null, rawType: node.node_type || 'unknown', polarity: node.polarity || null
      }
    };
  }

  function endpoint(value) {
    return String(value && typeof value === 'object' ? value.id || '' : value || '');
  }

  function edgeView(value) {
    const edge = value || {};
    const type = String(edge.edge_type || edge.type || edge.kind || 'related_to');
    const definition = EDGE_TYPES[type] || { group: 'reference', label: 'Related to', directed: false };
    const group = definition.group, style = EDGE_GROUPS[group];
    return {
      type, group, groupLabel: style.label, label: definition.label, color: style.color,
      dash: style.dash, directed: definition.directed,
      sourceId: endpoint(edge.sourceId || edge.source || edge.source_node_id),
      targetId: endpoint(edge.targetId || edge.target || edge.target_node_id)
    };
  }

  function positive(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  function groupedLayout(nodes, width, options) {
    const opts = options || {}, w = positive(width, 900);
    const padding = Math.min(positive(opts.padding, 24), Math.max(0, (w - 1) / 2));
    const available = Math.max(1, w - padding * 2);
    const cardWidth = Math.min(positive(opts.cardWidth, 208), available);
    const cardHeight = positive(opts.cardHeight, 86), gap = positive(opts.gap, 20);
    const headerHeight = positive(opts.headerHeight, 34), groupGap = positive(opts.groupGap, 28);
    const columns = Math.max(1, Math.floor(Math.min(Math.floor((available + gap) / (cardWidth + gap)), positive(opts.maxColumns, Infinity))));
    const seen = new Set(), buckets = new Map(GROUPS.map(group => [group.id, []])), omittedIds = [];
    for (const node of Array.isArray(nodes) ? nodes : []) {
      if (!node || !node.id || seen.has(node.id)) continue;
      seen.add(node.id);
      const view = nodeView(node);
      if (view.structural && !opts.includeGroups) { omittedIds.push(node.id); continue; }
      buckets.get(view.group).push({ node, view });
    }
    const cards = [], groups = [];
    let y = padding;
    for (const group of GROUPS) {
      const members = buckets.get(group.id);
      if (!members.length) continue;
      const rows = Math.ceil(members.length / columns);
      const height = headerHeight + rows * cardHeight + Math.max(0, rows - 1) * gap;
      groups.push({ ...group, x: padding, y, width: available, height, count: members.length, columns });
      members.forEach((member, index) => cards.push({
        id: member.node.id, node: member.node, view: member.view,
        x: padding + (index % columns) * (cardWidth + gap),
        y: y + headerHeight + Math.floor(index / columns) * (cardHeight + gap),
        width: cardWidth, height: cardHeight
      }));
      y += height + groupGap;
    }
    return { width: w, height: Math.max(padding * 2, y - (groups.length ? groupGap : 0) + padding),
      cardWidth, cardHeight, columns, cards, groups, omittedIds };
  }

  return Object.freeze({ TYPES, GROUPS, EDGE_TYPES, EDGE_GROUPS, plainText, cleanTitle, snippet,
    nodeView, edgeView, groupedLayout });
}));
