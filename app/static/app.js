// GLPI dashboard page. Renders /api/snapshot; every number links to #list=<key>,
// which opens the records behind it, each linked to GLPI.
// All GLPI text goes in with textContent - never innerHTML.
'use strict';

const POLL_MS = 60_000;
const PAGE = 10;
const RAG = { red: ['■', 'Act'], amber: ['▲', 'Watch'], green: ['●', 'OK'] };
const RAG_ORDER = { red: 0, amber: 1, green: 2 };
let snap = null;

/**
 * Creates an element. `text` sets textContent and `class` sets className; other attrs are attributes.
 * @param {string} tag
 * @param {Object<string, string>} attrs
 * @param {...(Node|string|null)} kids appended in order; null is skipped
 * @returns {HTMLElement}
 */
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) e.append(kid);
  return e;
}

/**
 * Guards every link: GLPI links are built server-side under GLPI_PUBLIC_URL, but only http(s) is followed.
 * @param {string} u
 * @returns {string} the normalised URL, or '#' for anything else
 */
function safeUrl(u) {
  try { const p = new URL(u); return p.protocol === 'https:' || p.protocol === 'http:' ? p.href : '#'; }
  catch { return '#'; }
}
const glpiLink = (url, text, cls) => el('a', { href: safeUrl(url), target: '_blank', rel: 'noopener', class: cls || '', text });
const listLink = (key, count, cls) => el('a', { href: '#list=' + encodeURIComponent(key), class: cls || '', 'aria-label': `${count} - show list` }, String(count));
const rag = (r) => el('span', { class: 'rag' },
  el('span', { class: 'rag-icon rag-' + r, 'aria-hidden': 'true', text: RAG[r][0] }), ' ' + RAG[r][1]);

const KINDS = new Set(['incident', 'request', 'problem', 'change', 'project', 'issue']);
/**
 * The class that colours an element by record kind (see --k-* in style.css); unknown kinds get none.
 * @param {string} kind e.g. 'Incident' or 'change'
 * @returns {string}
 */
const kindClass = (kind) => (KINDS.has(String(kind).toLowerCase()) ? ' kind-' + String(kind).toLowerCase() : '');
/** A count of one kind of record, linking to its list; zero is shown plain. */
const countLink = (key, count, kind, cls = '') =>
  listLink(key, count, `count${kindClass(kind)}${count ? '' : ' zero'}${cls ? ' ' + cls : ''}`);

/**
 * A stat tile: the short label shows, the full title names the link, and any `detail` is a tooltip
 * (shown by CSS after a short delay) that also describes the link to screen readers.
 */
function tile(t) {
  const a = el('a', { class: 'tile' + kindClass(t.kind) + (t.count ? '' : ' zero'),
    href: '#list=' + encodeURIComponent(t.key), 'aria-label': `${t.title}: ${t.count}` },
  el('span', { class: 'value', text: String(t.count) }),
  el('span', { class: 'label', text: t.label || t.title }));
  if (t.detail) {
    a.setAttribute('aria-describedby', 'tip-' + t.key);
    a.append(el('span', { class: 'tooltip', role: 'tooltip', id: 'tip-' + t.key, text: t.detail }));
  }
  return a;
}

function ciCell(ci) {
  const td = el('td');
  td.append(glpiLink(ci.url, ci.name));
  if (ci.internet) td.append(el('span', { class: 'net', title: 'Internet-facing', text: 'internet' }));
  return td;
}

/** Replaces a table body's rows, or shows one 'None' row spanning `cols` columns. */
function fill(tbody, rows, cols) {
  tbody.replaceChildren();
  if (!rows.length) {
    tbody.append(el('tr', {}, el('td', { class: 'empty', colspan: String(cols), text: 'None' })));
    return;
  }
  for (const r of rows) tbody.append(r);
}

function recordLink(rec) {
  return glpiLink(rec.url, rec.ref, 'ref chip' + kindClass(rec.kind));
}

function progress(percent) {
  const bar = el('span', { class: 'bar' }, el('span'));
  bar.firstChild.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  return el('td', { class: 'nowrap' }, bar, `${percent}%`);
}

// --- sortable, paged tables -------------------------------------------------------------------------------------

// Columns: `label`; `cell(row)` returns its <td>; `sort(row)` gives the value to sort by (a column without one
// can't be sorted); `num` right-aligns the header.
const RECORD_COLUMNS = [
  { label: 'Record', cell: (r) => el('td', {}, recordLink(r)), sort: (r) => r.ref },
  { label: 'Title', cell: (r) => el('td', {}, glpiLink(r.url, r.name)), sort: (r) => r.name },
  { label: 'Status', cell: (r) => el('td', { text: r.status }), sort: (r) => r.status },
  { label: 'Priority', cell: (r) => el('td', { class: 'nowrap', text: r.priority_name }), sort: (r) => r.priority },
  { label: 'Opened', cell: (r) => el('td', { class: 'nowrap', text: r.date }), sort: (r) => r.date },
  { label: 'Updated', cell: (r) => el('td', { class: 'nowrap', text: r.updated || '-' }), sort: (r) => r.updated },
  { label: 'Age', num: true, cell: (r) => el('td', { class: 'n', text: `${r.age_days} d` }), sort: (r) => r.age_days },
  { label: 'CIs', sort: (r) => r.cis.map((c) => c.name).join(', '), cell: (r) => {
    const td = el('td');
    r.cis.forEach((c, i) => { if (i) td.append(', '); td.append(glpiLink(c.url, c.name)); });
    return td;
  } },
];

const PROJECT_COLUMNS = [
  { label: 'Project', cell: (p) => el('td', {}, glpiLink(p.url, p.name)), sort: (p) => p.name },
  { label: 'State', cell: (p) => el('td', { text: p.state }), sort: (p) => p.state },
  { label: 'Progress', cell: (p) => progress(p.percent_done), sort: (p) => p.percent_done },
  { label: 'Open records', num: true, cell: (p) => el('td', { class: 'n' }, listLink(p.open_list, p.open)), sort: (p) => p.open },
  { label: 'All records', num: true, cell: (p) => el('td', { class: 'n' }, listLink(p.total_list, p.total)), sort: (p) => p.total },
];

const RECURRING_COLUMNS = [
  { label: 'Recurring change', cell: (r) => el('td', {}, glpiLink(r.url, r.name)), sort: (r) => r.name },
  { label: 'Every', cell: (r) => el('td', { text: r.periodicity }), sort: (r) => r.periodicity },
  { label: 'Next created', cell: (r) => el('td', { class: 'nowrap', text: r.next_creation || '-' }), sort: (r) => r.next_creation },
  { label: 'Due', cell: (r) => el('td', { class: 'nowrap', text: r.due || '-' }), sort: (r) => r.due },
  { label: 'Open changes', num: true, cell: (r) => el('td', { class: 'n' }, countLink(r.open_list, r.open, 'change')), sort: (r) => r.open },
];

const CI_COLUMNS = [
  { label: 'CI', cell: ciCell, sort: (c) => c.name },
  { label: 'State', cell: (c) => el('td', {}, rag(c.rag)), sort: (c) => RAG_ORDER[c.rag] },
  { label: 'Incidents', num: true, cell: (c) => el('td', { class: 'n' }, countLink(c.incidents_list, c.incidents, 'incident')), sort: (c) => c.incidents },
  { label: 'Problems', num: true, cell: (c) => el('td', { class: 'n' }, countLink(c.problems_list, c.problems, 'problem')), sort: (c) => c.problems },
  { label: 'Changes', num: true, cell: (c) => el('td', { class: 'n' }, countLink(c.changes_list, c.changes, 'change')), sort: (c) => c.changes },
];

// Rows are records with `risk` (rank, score, why), in score order.
const RISK_COLUMNS = [
  { label: '#', num: true, cell: (r) => el('td', { class: 'n', text: String(r.risk.rank) }), sort: (r) => r.risk.rank },
  { label: 'Record', cell: (r) => el('td', {}, recordLink(r), ' ', glpiLink(r.url, r.name)), sort: (r) => r.ref },
  { label: 'Priority', cell: (r) => el('td', { class: 'nowrap', text: r.priority_name }), sort: (r) => r.priority },
  { label: 'Area', cell: (r) => el('td', { text: r.area }), sort: (r) => r.area },
  { label: 'Opened', cell: (r) => el('td', { class: 'nowrap', text: r.date }), sort: (r) => r.date },
  { label: 'Score', num: true, cell: (r) => el('td', { class: 'n', text: String(r.risk.score) }), sort: (r) => r.risk.score },
  { label: 'Why', cell: (r) => el('td', { class: 'why', text: r.risk.why.join(' · ') }) },
];

const LIST_KINDS = {
  records: { columns: RECORD_COLUMNS, noun: ['record', 'records'] },
  projects: { columns: PROJECT_COLUMNS, noun: ['project', 'projects'] },
  risks: { columns: RISK_COLUMNS, noun: ['record', 'records'] },
};

// Sort column, direction and rows shown, by table id, so the 60 s re-render keeps them.
const views = new Map();
// What each table shows now; the header is only rebuilt when the columns change, so focus stays on it.
const grids = new WeakMap();

/**
 * Sorts rows by a column's value, keeping the default order for ties. Blank values sort last either way.
 * @param {Array<Object>} rows
 * @param {Function} key the column's `sort`
 * @param {number} dir 1 ascending, -1 descending
 * @returns {Array<Object>} a sorted copy
 */
function sortRows(rows, key, dir) {
  const blank = (v) => v == null || v === '';
  return rows.map((r, i) => [key(r), i, r]).sort(([a, i], [b, j]) => {
    if (blank(a) || blank(b)) return blank(a) - blank(b) || i - j;
    const c = typeof a === 'number' && typeof b === 'number'
      ? a - b : String(a).localeCompare(String(b), 'en-GB', { numeric: true, sensitivity: 'base' });
    return c * dir || i - j;
  }).map(([, , r]) => r);
}

/**
 * Shows rows in a table whose headers sort it, PAGE rows at a time with Show more / Show all below.
 * @param {HTMLTableElement} table
 * @param {string} id keeps this table's sort and length; each drill-down list has its own
 * @param {Array<Object>} columns
 * @param {Array<Object>} rows in their default order
 */
function grid(table, id, columns, rows) {
  if (grids.get(table)?.columns !== columns) {
    const head = table.tHead || table.createTHead();
    head.replaceChildren(el('tr', {}, ...columns.map((c, i) => {
      const th = el('th', { scope: 'col', class: c.num ? 'n' : '' });
      if (!c.sort) { th.textContent = c.label; return th; }
      const btn = el('button', { type: 'button', class: 'sort' }, c.label, el('span', { class: 'sort-icon', 'aria-hidden': 'true' }));
      btn.addEventListener('click', () => {
        const view = views.get(grids.get(table).id);
        view.dir = view.col === i ? -view.dir : 1;
        view.col = i;
        draw(table);
      });
      th.append(btn);
      return th;
    })));
  }
  grids.set(table, { id, columns, rows });
  if (!views.has(id)) views.set(id, { col: -1, dir: 1, shown: PAGE });
  draw(table);
}

/** Redraws a table from `grids` and `views`: header sort marks, the visible rows, and the Show more row. */
function draw(table) {
  const { id, columns, rows } = grids.get(table);
  const view = views.get(id);
  table.tHead.querySelectorAll('th').forEach((th, i) => {
    const on = i === view.col;
    if (on) th.setAttribute('aria-sort', view.dir > 0 ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
    const icon = th.querySelector('.sort-icon');
    if (icon) icon.textContent = on ? (view.dir > 0 ? '▲' : '▼') : '↕';
  });
  const sorted = view.col < 0 ? rows : sortRows(rows, columns[view.col].sort, view.dir);
  fill(table.tBodies[0], sorted.slice(0, view.shown).map((r) => el('tr', {}, ...columns.map((c) => c.cell(r)))), columns.length);

  const foot = table.tFoot || table.createTFoot();
  foot.replaceChildren();
  const hidden = rows.length - view.shown;
  if (rows.length <= PAGE) return;
  /** Shows `n` more rows, then keeps focus on the same button, or on the first new row once all show. */
  const showMore = (n, cls) => () => {
    const first = view.shown;
    view.shown += n;
    draw(table);
    (table.tFoot.querySelector('.' + cls) || table.tBodies[0].rows[first]?.querySelector('a, button'))?.focus();
  };
  const buttons = [];
  if (hidden > 0) {
    const more = el('button', { type: 'button', class: 'btn more', text: `Show ${Math.min(PAGE, hidden)} more` });
    more.addEventListener('click', showMore(PAGE, 'more'));
    const all = el('button', { type: 'button', class: 'btn all', text: `Show all ${rows.length}` });
    all.addEventListener('click', showMore(hidden, 'all'));
    buttons.push(more, all);
  }
  if (view.shown > PAGE) {
    const less = el('button', { type: 'button', class: 'btn less', text: 'Show less' });
    // Focus goes to Show more, which is now just below the last row shown, so the table stays in view.
    less.addEventListener('click', () => { view.shown = PAGE; draw(table); table.tFoot.querySelector('.more').focus(); });
    buttons.push(less);
  }
  foot.append(el('tr', {}, el('td', { colspan: String(columns.length) },
    el('span', { class: 'shown', text: `Showing ${Math.min(view.shown, rows.length)} of ${rows.length}` }), ...buttons)));
}

// --- risks: a sunburst (inner ring one grouping, outer ring split by the other) and the same counts as a table ---

const SVG_NS = 'http://www.w3.org/2000/svg';
const RISK_KINDS = ['Problem', 'Change'];
const RING = { size: 240, hole: 44, inner: 82, outer: 116 };
// The chart's two toggles; each choice is remembered in localStorage as risk-<name>.
const RISK_CHOICES = { inner: ['priority', 'kind'], colours: ['traffic', 'heat'] };
const riskView = { inner: 'priority', colours: 'traffic' };
for (const [name, values] of Object.entries(RISK_CHOICES)) {
  try {
    const saved = localStorage.getItem('risk-' + name);
    if (values.includes(saved)) riskView[name] = saved;
  } catch { /* storage blocked: the defaults */ }
}
// What the risks section last drew, so an unchanged re-render leaves it (and the focus in it) alone.
let risksDrawn = null;

/** Like el(), for SVG: `text` sets textContent; everything else, `class` included, is an attribute. */
function svgEl(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) e.append(kid);
  return e;
}

/** The colour class for a priority (1-6, see --pt* and --ph* in style.css); any other value gets a neutral fill. */
const prioClass = (p) => (Number.isInteger(p) && p >= 1 && p <= 6 ? 'prio-' + p : 'prio-none');

/**
 * The outline of one ring segment, clockwise from 12 o'clock.
 * @param {number} r0 inner radius
 * @param {number} r1 outer radius
 * @param {number} a0 start, as a fraction of the circle
 * @param {number} a1 end, as a fraction of the circle
 * @returns {string} an SVG path; a whole ring is two circles, to be filled even-odd
 */
function ringPath(r0, r1, a0, a1) {
  const c = RING.size / 2;
  if (a1 - a0 >= 1 - 1e-9) {
    const circle = (r) => `M${c - r},${c}A${r},${r} 0 1 1 ${c + r},${c}A${r},${r} 0 1 1 ${c - r},${c}Z`;
    return circle(r1) + circle(r0);
  }
  const pt = (r, a) => {
    const t = 2 * Math.PI * a - Math.PI / 2;
    return `${(c + r * Math.cos(t)).toFixed(2)},${(c + r * Math.sin(t)).toFixed(2)}`;
  };
  const large = a1 - a0 > 0.5 ? 1 : 0;
  return `M${pt(r1, a0)}A${r1},${r1} 0 ${large} 1 ${pt(r1, a1)}L${pt(r0, a1)}A${r0},${r0} 0 ${large} 0 ${pt(r0, a0)}Z`;
}

/**
 * Draws the risks section: the sunburst with the chosen inner ring and colours, and the priority-by-kind table.
 * Skipped when nothing changed, so the 60 s re-render doesn't take focus off a segment.
 */
function renderRisks() {
  const risks = snap.risks;
  for (const name of Object.keys(RISK_CHOICES)) {
    for (const b of document.querySelectorAll(`[data-${name}]`)) b.setAttribute('aria-pressed', String(b.dataset[name] === riskView[name]));
  }
  const box = document.getElementById('risks');
  box.classList.toggle('colours-heat', riskView.colours === 'heat');
  const drawn = JSON.stringify([riskView.inner, risks]);
  if (drawn === risksDrawn) return;
  risksDrawn = drawn;
  if (!risks.total) {
    box.replaceChildren(el('p', { class: 'empty', text: 'No open risks.' }));
    return;
  }
  const prioName = Object.fromEntries(risks.priorities.map((p) => [p.priority, p.name]));
  const kindRank = (k) => RISK_KINDS.indexOf(k);
  const kindCls = (k) => kindClass(k).trim();
  const byPrio = riskView.inner === 'priority';
  // Outer segments follow the inner ring's order, so each sits inside its own inner segment.
  const inner = byPrio
    ? risks.priorities.map((p) => ({ ...p, label: `${p.name} priority`, cls: prioClass(p.priority) }))
    : risks.kinds.map((k) => ({ ...k, label: `${k.kind}s`, cls: kindCls(k.kind) }));
  const outer = [...risks.cells]
    .sort((a, b) => (byPrio ? b.priority - a.priority || kindRank(a.kind) - kindRank(b.kind)
      : kindRank(a.kind) - kindRank(b.kind) || b.priority - a.priority))
    .map((c) => ({ ...c, label: `${c.kind}s at ${prioName[c.priority]} priority`,
      cls: byPrio ? kindCls(c.kind) : prioClass(c.priority) }));

  /** The sunburst, as a <figure>: each segment links to its list, and the middle shows the total. */
  const sunburst = () => {
    const mid = RING.size / 2;
    const centreN = svgEl('text', { class: 'centre-n', x: String(mid), y: String(mid + 4) });
    const centreLabel = svgEl('text', { class: 'centre-label', x: String(mid), y: String(mid + 20) });
    // Screen readers get the same from each segment's name, so this is for sighted users only.
    const caption = el('p', { class: 'risk-caption', 'aria-hidden': 'true' });
    /** Shows a segment's count in the middle and its name below, or the total when `seg` is null. */
    const show = (seg) => {
      centreN.textContent = String(seg ? seg.count : risks.total);
      centreLabel.textContent = seg ? 'records' : 'open risks';
      caption.textContent = seg ? `${seg.label}: ${seg.count} of ${risks.total}` : 'Pick a segment to list its records.';
    };
    /** One ring: each segment is a link to its list, sized by its share of the total. */
    const ring = (segs, r0, r1) => {
      let at = 0;
      return segs.map((seg) => {
        const a0 = at / risks.total;
        at += seg.count;
        const a = svgEl('a', { href: '#list=' + encodeURIComponent(seg.list), 'aria-label': `${seg.label}: ${seg.count} - show list` },
          svgEl('path', { class: 'seg ' + seg.cls, d: ringPath(r0, r1, a0, at / risks.total), 'fill-rule': 'evenodd' }));
        for (const [type, shown] of [['pointerenter', seg], ['focus', seg], ['pointerleave', null], ['blur', null]]) {
          a.addEventListener(type, () => show(shown));
        }
        return a;
      });
    };
    const svg = svgEl('svg', { class: 'sunburst', viewBox: `0 0 ${RING.size} ${RING.size}`, role: 'group',
      'aria-label': `Risks by ${byPrio ? 'priority, then record type' : 'record type, then priority'}` },
    ...ring(inner, RING.hole, RING.inner), ...ring(outer, RING.inner, RING.outer), centreN, centreLabel);
    show(null);
    return el('figure', { class: 'risk-chart' }, svg, caption);
  };

  // The table holds every count the chart does, as text: it's the legend and the non-visual view in one.
  const swatch = (cls) => el('span', { class: 'swatch ' + cls, 'aria-hidden': 'true' });
  const num = (g, kind) => el('td', { class: 'n' },
    g ? countLink(g.list, g.count, kind) : el('span', { class: 'count zero', text: '0' }));
  const cell = (p, kind) => risks.cells.find((c) => c.priority === p && c.kind === kind);
  const table = el('table', { class: 'grid risk-table', 'aria-labelledby': 'h-risks' },
    el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: 'Priority' }),
      ...RISK_KINDS.map((k) => el('th', { scope: 'col', class: 'n' }, swatch(kindCls(k)), `${k}s`)),
      el('th', { scope: 'col', class: 'n', text: 'All' }))),
    el('tbody', {}, ...risks.priorities.map((p) => el('tr', {},
      el('th', { scope: 'row' }, swatch(prioClass(p.priority)), p.name),
      ...RISK_KINDS.map((k) => num(cell(p.priority, k), k)),
      el('td', { class: 'n' }, listLink(p.list, p.count, 'count'))))),
    el('tfoot', {}, el('tr', {}, el('th', { scope: 'row', text: 'All' }),
      ...RISK_KINDS.map((k) => num(risks.kinds.find((g) => g.kind === k), k)),
      el('td', { class: 'n' }, listLink(risks.list, risks.total, 'count')))));
  box.replaceChildren(sunburst(), el('div', { class: 'scroll risk-table-box' }, table));
}

for (const name of Object.keys(RISK_CHOICES)) {
  for (const b of document.querySelectorAll(`[data-${name}]`)) {
    b.addEventListener('click', () => {
      riskView[name] = b.dataset[name];
      try { localStorage.setItem('risk-' + name, riskView[name]); } catch { /* storage blocked: the choice just isn't kept */ }
      if (snap) renderRisks();
    });
  }
}

// --- page -------------------------------------------------------------------------------------------------------

/** Draws every section from `snap`, then reopens the list in the URL hash, if any. */
function render() {
  document.getElementById('glpi-link').href = safeUrl(snap.glpi_url);
  const at = new Date(snap.refreshed_at);
  document.getElementById('updated').textContent =
    `Updated ${at.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })} (refreshed every ${Math.round(snap.refresh_seconds / 60)} min)`;
  const err = document.getElementById('error');
  err.hidden = !snap.error;
  err.textContent = snap.error ? `Last refresh from GLPI failed - showing the data from ${at.toLocaleTimeString('en-GB')}. ${snap.error}` : '';

  document.getElementById('summary').replaceChildren(...snap.summary.map(tile));
  document.getElementById('quality').replaceChildren(...snap.quality.map(tile));

  document.getElementById('areas').replaceChildren(...snap.health.areas.map((a) =>
    el('div', { class: 'card' },
      el('h3', {}, el('span', { text: a.area }), rag(a.rag)),
      el('div', { class: 'counts' },
        el('span', {}, countLink(a.incidents_list, a.incidents, 'incident', 'value'), el('span', { class: 'label', text: 'incidents' })),
        el('span', {}, countLink(a.problems_list, a.problems, 'problem', 'value'), el('span', { class: 'label', text: 'problems' }))))));

  const recurring = snap.health.recurring;
  document.getElementById('recurring-cards').replaceChildren(...recurring.map((r) =>
    el('div', { class: 'card kind-change' },
      el('h3', {}, glpiLink(r.url, r.name)),
      el('div', { class: 'counts' },
        el('span', {}, countLink(r.open_list, r.open, 'change', 'value'), el('span', { class: 'label', text: 'open changes' }))),
      el('p', { class: 'card-meta', text: r.next_creation ? `Next created ${r.next_creation}` : 'Not scheduled' }))));
  grid(document.getElementById('recurring'), 'recurring', RECURRING_COLUMNS, recurring);

  document.getElementById('cis-count').textContent = String(snap.health.cis.length);
  grid(document.getElementById('cis'), 'cis', CI_COLUMNS, snap.health.cis);

  document.getElementById('flight').replaceChildren(...snap.in_flight.groups.map((g) =>
    el('div', { class: 'flight-group' + kindClass(g.kind) }, el('h3', { text: g.title }), el('div', { class: 'tiles' }, ...g.tiles.map(tile)))));

  renderRisks();

  showList();
}

/**
 * Drill-down: #list=<key> opens the dialog; closing it clears the hash, so Back works too.
 * Unknown or malformed keys close it.
 */
function showList() {
  const dlg = document.getElementById('list');
  const m = location.hash.match(/^#list=(.+)$/);
  let key = null;
  try { key = m && decodeURIComponent(m[1]); } catch { key = null; }
  const lst = key && snap && Object.hasOwn(snap.lists, key) ? snap.lists[key] : null;
  const kindName = lst?.kind || 'records';
  const kind = lst && Object.hasOwn(LIST_KINDS, kindName) ? LIST_KINDS[kindName] : null;
  if (!kind) { if (dlg.open) dlg.close(); return; }
  const rows = lst.rows || lst.refs.map((k) => snap.records[k]);
  document.getElementById('list-title').textContent = lst.title;
  document.getElementById('list-count').textContent =
    `${rows.length} ${kind.noun[rows.length === 1 ? 0 : 1]} - each opens in GLPI`;
  // A freshly opened list starts unsorted and short; a re-render while it's open keeps its state.
  if (!dlg.open) views.delete('list:' + key);
  grid(dlg.querySelector('table'), 'list:' + key, kind.columns, rows);
  if (!dlg.open) dlg.showModal();
}

/**
 * Loads the current snapshot and renders it; failures show in the banner and keep the old data.
 * @param {boolean} refresh POST /api/refresh, so the backend re-reads GLPI first
 */
async function load(refresh = false) {
  try {
    const res = await fetch(refresh ? 'api/refresh' : 'api/snapshot', { method: refresh ? 'POST' : 'GET', cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    snap = body;
    render();
  } catch (e) {
    const err = document.getElementById('error');
    err.hidden = false;
    err.textContent = `Could not load the dashboard data: ${e.message}`;
  }
}

// --- tabs: arrow keys move between them (roving tabindex); the last one chosen is remembered ---------------------

const TABS = [...document.querySelectorAll('[role="tab"]')];

/**
 * Shows one tab's panel and hides the rest.
 * @param {HTMLElement} tab
 * @param {boolean} focus move focus to the tab too (keyboard navigation)
 */
function selectTab(tab, focus = false) {
  for (const t of TABS) {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
  }
  if (focus) tab.focus();
  try { localStorage.setItem('tab', tab.id); } catch { /* storage blocked: the choice just isn't kept */ }
}

TABS.forEach((t, i) => {
  t.addEventListener('click', () => selectTab(t));
  t.addEventListener('keydown', (e) => {
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    selectTab(TABS[(next + TABS.length) % TABS.length], true);
  });
});
let savedTab = null;
try { savedTab = localStorage.getItem('tab'); } catch { savedTab = null; }
selectTab(TABS.find((t) => t.id === savedTab) || TABS[0]);

// Escape hides a showing tooltip without moving the pointer (WCAG 1.4.13); it can show again once the pointer
// or focus leaves that tile.
let tipDismissedOn = null;
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  tipDismissedOn = document.querySelector('.tile:hover, .tile:focus-visible');
  document.body.classList.toggle('tips-off', tipDismissedOn !== null);
});
for (const type of ['pointerover', 'focusin']) {
  document.addEventListener(type, (e) => {
    if (tipDismissedOn && e.target.closest?.('.tile') !== tipDismissedOn) {
      tipDismissedOn = null;
      document.body.classList.remove('tips-off');
    }
  });
}

const dialog = document.getElementById('list');
dialog.addEventListener('close', () => {
  if (location.hash.startsWith('#list=')) history.replaceState(null, '', location.pathname + location.search);
});
// A click on the backdrop targets the dialog itself, but so does one on its padding, and so does a drag (a text
// selection) that starts inside and ends on the backdrop. Close only when the press and the release were both
// outside the box.
const outsideDialog = (e) => {
  const box = dialog.getBoundingClientRect();
  return e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom;
};
let pressedOutside = false;
dialog.addEventListener('pointerdown', (e) => { pressedOutside = e.target === dialog && outsideDialog(e); });
dialog.addEventListener('click', (e) => {
  if (e.target === dialog && pressedOutside && outsideDialog(e)) dialog.close();
  pressedOutside = false;
});
document.querySelector('#list .close').addEventListener('click', (e) => {
  e.preventDefault();
  dialog.close();
});
document.getElementById('refresh').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  // An icon button: its name is the label, so that's what says it's busy (the icon spins too).
  btn.disabled = true;
  btn.setAttribute('aria-label', 'Refreshing…');
  btn.title = 'Refreshing…';
  await load(true);
  btn.disabled = false;
  btn.setAttribute('aria-label', 'Refresh now');
  btn.title = 'Refresh now';
});
window.addEventListener('hashchange', showList);
load();
setInterval(load, POLL_MS);
