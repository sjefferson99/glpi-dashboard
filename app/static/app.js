// GLPI dashboard page. Renders /api/snapshot; every number links to #list=<key>,
// which opens the records behind it, each linked to GLPI.
// All GLPI text goes in with textContent - never innerHTML.
'use strict';

const POLL_MS = 60_000;
const PAGE = 10;
const RAG = { red: ['■', 'Act'], amber: ['▲', 'Watch'], green: ['●', 'OK'] };
const RAG_ORDER = { red: 0, amber: 1, green: 2 };
// The server fills in <html lang> from its LOCALE setting; a tag Intl can't read would throw on every date.
const LOCALE = (() => {
  try {
    return Intl.getCanonicalLocales(document.documentElement.lang)[0] || 'en-GB';
  } catch {
    return 'en-GB';
  }
})();
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

const KINDS = new Set(['incident', 'request', 'problem', 'change', 'project', 'issue', 'ci']);
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

/**
 * Text with each search word marked, built from text nodes and <mark>s, never HTML.
 * @param {string} text
 * @param {Array<string>} words lower case
 * @returns {DocumentFragment}
 */
function marked(text, words) {
  const frag = document.createDocumentFragment();
  if (!words.length) { frag.append(text); return frag; }
  // Longest first: the regex takes the first alternative that matches, so `db` would hide `db1`.
  const longest = [...words].sort((a, b) => b.length - a.length);
  // An #id word marks only that whole number, as the server matches it: #12, not the start of #123.
  const re = new RegExp(longest.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + (ID_WORD.test(w) ? '(?!\\d)' : ''))
    .join('|'), 'gi');
  let at = 0;
  for (const m of text.matchAll(re)) {
    frag.append(text.slice(at, m.index), el('mark', { text: m[0] }));
    at = m.index + m[0].length;
  }
  frag.append(text.slice(at));
  return frag;
}

// The words of the search being shown, for marking them in its results.
let searchWords = [];

// Rows are search results: records, projects and CIs, best match first.
const SEARCH_COLUMNS = [
  { label: 'Record', cell: (r) => el('td', {}, recordLink(r)), sort: (r) => r.ref },
  { label: 'Title', sort: (r) => r.name, cell: (r) => {
    const a = glpiLink(r.url, '');
    a.append(marked(r.name, searchWords));
    return el('td', {}, a);
  } },
  { label: 'Status', cell: (r) => el('td', { class: 'nowrap', text: r.status || '-' }), sort: (r) => r.status },
  { label: 'Category / type', cell: (r) => el('td', { text: r.category || '-' }), sort: (r) => r.category },
  { label: 'Updated', cell: (r) => el('td', { class: 'nowrap', text: r.updated || r.date || '-' }), sort: (r) => r.updated || r.date },
  { label: 'Found in description', cell: (r) => el('td', { class: 'snippet' }, marked(r.snippet, searchWords)) },
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
      ? a - b : String(a).localeCompare(String(b), LOCALE, { numeric: true, sensitivity: 'base' });
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

// --- record explorer: every record as a treemap, up to three groupings deep; a box lists its records beside it ---

const OPENED_BANDS = [[7, 'Last week'], [30, 'Last month'], [90, 'Last 3 months'], [365, 'Last year'],
  [Infinity, 'Over a year ago']];
// What records can be grouped by. `cls` colours a box whose records all share the value; only these can colour.
// A `value` that's a list puts the record in a box for each (a record linked to two CIs is in both).
const DIMS = {
  kind: { label: 'Record type', value: (r) => r.kind, cls: (r) => kindClass(r.kind).trim() },
  priority: { label: 'Priority', value: (r) => r.priority_name, cls: (r) => prioClass(r.priority) },
  area: { label: 'Area', value: (r) => r.area },
  category: { label: 'Category', value: (r) => r.category || 'Uncategorised' },
  status: { label: 'Status', value: (r) => r.status },
  open: { label: 'Open or closed', value: (r) => (r.open ? 'Open' : 'Closed'), cls: (r) => (r.open ? 'state-open' : 'state-closed') },
  assigned: { label: 'Assigned', value: (r) => (r.assigned ? 'Assigned' : 'Unassigned') },
  ci: { label: 'Has a CI', value: (r) => (r.cis.length ? 'Linked to a CI' : 'No CI') },
  cis: { label: 'Linked CI', value: (r) => (r.cis.length ? r.cis : 'No CI') },
  family: { label: 'Linked records', value: (r) => r.family || 'Not linked' },
  opened: { label: 'Opened', value: (r) => OPENED_BANDS.find(([days]) => r.age_days <= days)[1] },
  year: { label: 'Year opened', value: (r) => r.date.slice(0, 4) },
};
const COLOURS = ['kind', 'priority', 'open', 'none'];
const EXPLORE_DEFAULT = { tiers: ['kind', 'priority', 'area'], colour: 'kind', closed: false, zoom: [], sel: [] };
// Treemap sizes in px: a group's header and padding, and the smallest box that gets a label.
const TM = { head: 18, headW: 48, pad: 2, inner: 6, labelW: 44, labelH: 16 };

/**
 * The explorer's view from a `#explore=` hash: groupings, colour, Include closed, and the zoomed and selected
 * groups as paths of group names. Anything unknown falls back to the defaults.
 * @param {string} hash
 * @returns {Object|null} null if it isn't an explorer hash
 */
function parseExplore(hash) {
  if (!hash.startsWith('#explore=')) return null;
  const parts = Object.fromEntries(hash.slice(1).split('&').map((p) => {
    const i = p.indexOf('=');
    return i < 0 ? [p, ''] : [p.slice(0, i), p.slice(i + 1)];
  }));
  const path = (s) => { try { return s ? s.split('/').map(decodeURIComponent) : []; } catch { return []; } };
  const tiers = [...new Set(parts.explore.split(',').filter((d) => Object.hasOwn(DIMS, d)))].slice(0, 3);
  return { tiers: tiers.length ? tiers : EXPLORE_DEFAULT.tiers, colour: COLOURS.includes(parts.colour) ? parts.colour : 'kind',
    closed: parts.closed === '1', zoom: path(parts.zoom), sel: path(parts.sel) };
}

/** The hash for an explorer view; each group name in a path is encoded, so `/` only ever separates them. */
function exploreHash(v) {
  const path = (p) => p.map(encodeURIComponent).join('/');
  return `#explore=${v.tiers.join(',')}&colour=${v.colour}${v.closed ? '&closed=1' : ''}`
    + (v.zoom.length ? '&zoom=' + path(v.zoom) : '') + (v.sel.length ? '&sel=' + path(v.sel) : '');
}

let exploreView = { ...EXPLORE_DEFAULT };
try { exploreView = parseExplore(localStorage.getItem('explore') || '') || exploreView; } catch { /* storage blocked: the defaults */ }
// The records from /api/explorer, and the refresh they were last asked for, so each refresh is fetched once.
let explorerData = null;
let explorerAsked = null;
// What the explorer last drew, so the 60 s re-render leaves it (and the focus in it) alone.
let explorerDrawn = null;
let exploreListKey = null;
let exploreSelPath = [];

const pathText = (p) => (p.length ? p.join(' › ') : 'All records');
const samePath = (a, b) => a.length === b.length && a.every((s, i) => s === b[i]);
const recordsText = (n) => `${n} ${n === 1 ? 'record' : 'records'}`;

/**
 * Groups records into a tree, one level per dimension, biggest group first. A box's `size` is its records, or
 * the sum of its children's: more than its records when a record is in several of them (e.g. two CIs).
 * @param {Array<Object>} records
 * @param {Array<string>} dims keys of DIMS
 * @returns {{label: string, path: Array<string>, records: Array<Object>, children: Array<Object>, size: number}}
 *   the root
 */
function groupTree(records, dims) {
  const node = (label, path, recs) => {
    const n = { label, path, records: recs, children: [], size: recs.length };
    if (path.length < dims.length) {
      const by = new Map();
      for (const r of recs) {
        const v = DIMS[dims[path.length]].value(r);
        for (const one of new Set((Array.isArray(v) ? v : [v]).map((x) => String(x ?? '') || '(blank)'))) {
          if (!by.has(one)) by.set(one, []);
          by.get(one).push(r);
        }
      }
      n.children = [...by].map(([v, rs]) => node(v, [...path, v], rs))
        .sort((a, b) => b.size - a.size || a.label.localeCompare(b.label, LOCALE, { numeric: true }));
      n.size = n.children.reduce((s, c) => s + c.size, 0);
    }
    return n;
  };
  return node('All records', [], records);
}

/** The group at `path` under `root`, or null if there's none (say, after a refresh emptied it). */
function findGroup(root, path) {
  let n = root;
  for (const label of path) {
    n = n.children.find((c) => c.label === label);
    if (!n) return null;
  }
  return n;
}

/**
 * Lays out boxes whose areas are in proportion to `sizes` (largest first) as squarely as it can: the squarified
 * treemap of Bruls, Huizing and van Wijk. Each row of boxes runs along the short side of what's left.
 * @param {Array<number>} sizes
 * @returns {Array<{x: number, y: number, w: number, h: number}>} one box per size, in the same order
 */
function squarify(sizes, x, y, w, h) {
  const total = sizes.reduce((a, b) => a + b, 0);
  if (!total || w <= 0 || h <= 0) return sizes.map(() => ({ x, y, w: 0, h: 0 }));
  const areas = sizes.map((s) => (s * w * h) / total);
  // The row's worst aspect ratio: adding a box to it is kept only while this doesn't get worse.
  const worst = (sum, min, max, side) => Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  const out = [];
  let i = 0;
  while (i < areas.length) {
    const side = Math.min(w, h);
    let j = i + 1;
    let sum = areas[i], min = areas[i], max = areas[i];
    let ratio = worst(sum, min, max, side);
    while (j < areas.length) {
      const a = areas[j];
      const next = worst(sum + a, Math.min(min, a), Math.max(max, a), side);
      if (next > ratio) break;
      sum += a; min = Math.min(min, a); max = Math.max(max, a); ratio = next; j++;
    }
    const thick = sum / side;
    let at = 0;
    for (let k = i; k < j; k++) {
      const len = areas[k] / thick;
      out.push(w >= h ? { x, y: y + at, w: thick, h: len } : { x: x + at, y, w: len, h: thick });
      at += len;
    }
    if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
    i = j;
  }
  return out;
}

/**
 * The relative luminance of a computed colour, `rgb(...)` or `color(srgb ...)` (what color-mix() computes to).
 * @param {string} css
 * @returns {number} 0 (black) to 1 (white)
 */
function luminance(css) {
  const n = (css.match(/[\d.]+/g) || []).map(Number);
  const c = (css.startsWith('color(') ? n.slice(0, 3) : n.slice(0, 3).map((v) => v / 255))
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return c.length === 3 ? 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] : 1;
}

/**
 * Gives each element black or white text, whichever reads better on its background: boxes are filled with the full
 * kind or priority colour, light for some and dark for others, and differently in each theme. Black and white
 * meet each other at a luminance of 0.179, where either has 4.58:1, so the better one always passes WCAG AA.
 * @param {Array<HTMLElement>} els elements with the same classes (theirs and their parent's: a group's header takes
 *   its colour from the group) share one answer, so it's worked out once each
 */
function setInk(els) {
  const ink = new Map();
  for (const e of els) {
    const key = `${e.className}|${e.parentElement?.className}`;
    if (!ink.has(key)) ink.set(key, luminance(getComputedStyle(e).backgroundColor) > 0.179 ? 'ink-dark' : 'ink-light');
    e.classList.add(ink.get(key));
  }
}

const EXPLORE_COLUMNS = [
  { label: 'Record', cell: (r) => el('td', {}, recordLink(r)), sort: (r) => r.ref },
  // Titles are cut to the column with an ellipsis; the whole title shows on hover, and is the link's name.
  { label: 'Title', cell: (r) => el('td', { class: 'clip' }, el('a', { href: safeUrl(r.url), target: '_blank', rel: 'noopener', title: r.name, text: r.name })),
    sort: (r) => r.name },
  { label: 'Status', cell: (r) => el('td', { class: 'nowrap', text: r.status }), sort: (r) => r.status },
  { label: 'Priority', cell: (r) => el('td', { class: 'nowrap', text: r.priority_name }), sort: (r) => r.priority },
  { label: 'Updated', cell: (r) => el('td', { class: 'nowrap', text: r.updated || r.date }), sort: (r) => r.updated || r.date },
];

/**
 * Fetches every record for the explorer, once per refresh, then draws it. A failure says so in the explorer's
 * own alert (the page banner shows the snapshot's state) and keeps the last records on screen.
 */
async function loadExplorer() {
  if (!snap || explorerAsked === snap.refreshed_at || (explorerData && explorerData.refreshed_at >= snap.refreshed_at)) return;
  explorerAsked = snap.refreshed_at;
  const err = document.getElementById('explore-error');
  try {
    const res = await fetch('api/explorer', { cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    explorerData = body;
    err.hidden = true;
  } catch (e) {
    // explorerAsked stays set, so the redraw below doesn't ask again at once; load() clears it, so the next poll does.
    err.hidden = false;
    err.textContent = `Could not load the records for the explorer: ${e.message}${explorerData ? ' - showing the last ones read.' : ''}`;
  }
  renderExplorer();
}

/** Sets the explorer's controls to `exploreView`; a grouping already used above can't be picked again. */
function syncExploreForm() {
  [1, 2, 3].forEach((i) => {
    const select = document.getElementById('explore-tier-' + i);
    select.value = exploreView.tiers[i - 1] || '';
    for (const o of select.options) o.disabled = Boolean(o.value) && exploreView.tiers.slice(0, i - 1).includes(o.value);
  });
  document.getElementById('explore-colour').value = exploreView.colour;
  document.getElementById('explore-closed').checked = exploreView.closed;
}

/**
 * Shows a new explorer view: remembers its groupings and colour, and puts it in the hash while the tab shows, so
 * the link can be shared. Picking a box is a link instead, so Back goes back through what was picked.
 */
function setExplore(v) {
  exploreView = v;
  try { localStorage.setItem('explore', exploreHash({ ...v, zoom: [], sel: [] })); } catch { /* storage blocked: not kept */ }
  if (!document.getElementById('panel-explorer').hidden) history.replaceState(null, '', exploreHash(v));
  renderExplorer();
}

/**
 * Draws the explorer from `explorerData` and `exploreView`: the treemap, the list of the picked box's records,
 * the zoom path and the table of groups. Skipped when nothing changed, or while the tab is hidden.
 */
function renderExplorer() {
  syncExploreForm();
  const box = document.getElementById('treemap');
  if (document.getElementById('panel-explorer').hidden) return;
  loadExplorer();
  if (!explorerData) {
    if (!box.childElementCount) box.append(el('p', { class: 'empty', text: 'Loading records…' }));
    return;
  }
  const v = exploreView;
  const drawn = JSON.stringify([explorerData.refreshed_at, exploreHash(v), box.clientWidth, box.clientHeight]);
  if (drawn === explorerDrawn) return;
  explorerDrawn = drawn;

  // The colour is the innermost grouping when it isn't already one, so every smallest box has a single colour.
  const dims = [...v.tiers];
  if (v.colour !== 'none' && !dims.includes(v.colour)) dims.push(v.colour);
  const colourAt = dims.indexOf(v.colour);
  const colourCls = (n) => (colourAt >= 0 && n.path.length > colourAt ? DIMS[v.colour].cls(n.records[0]) : '');
  const tree = groupTree(v.closed ? explorerData.records : explorerData.records.filter((r) => r.open), dims);
  const root = findGroup(tree, v.zoom) || tree;
  const inRoot = v.sel.length >= root.path.length && samePath(v.sel.slice(0, root.path.length), root.path);
  const sel = (inRoot && findGroup(tree, v.sel)) || root;
  const total = root.records.length;
  const share = (n) => `${total ? Math.round((n.records.length * 1000) / total) / 10 : 0}%`;
  const href = (path) => exploreHash({ ...v, sel: path });
  const zoomHref = (path) => exploreHash({ ...v, zoom: path, sel: [] });

  // The treemap: boxes are links, absolutely placed side by side (never nested, so no link holds another); a group
  // comes before its children, which sit on top of it.
  const focused = box.contains(document.activeElement) ? document.activeElement.dataset.path : null;
  const caption = document.getElementById('treemap-caption');
  const show = (n) => {
    caption.textContent = n ? `${pathText(n.path)}: ${recordsText(n.records.length)}, ${share(n)} of ${total}`
      : 'Pick a box to list its records; double-click a group to zoom into it.';
  };
  const items = [];
  const link = (n, cls, x, y, w, h, label) => {
    const c = colourCls(n);
    const a = el('a', { class: cls + (c ? ' ' + c : ''), href: href(n.path), 'data-path': JSON.stringify(n.path),
      'aria-label': `${pathText(n.path)}: ${recordsText(n.records.length)} - show list` },
    label ? el('span', { class: 'tm-label' }, el('span', { class: 'tm-name', text: n.label }),
      el('span', { class: 'tm-n', text: String(n.records.length) })) : null);
    Object.assign(a.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
    if (n === sel && sel !== root) a.setAttribute('aria-current', 'true');
    for (const [type, shown] of [['pointerenter', n], ['focus', n], ['pointerleave', null], ['blur', null]]) {
      a.addEventListener(type, () => show(shown));
    }
    items.push(a);
    return a;
  };
  const place = (n, x, y, w, h) => {
    const top = n === root;
    const pad = top ? 0 : TM.pad;
    const head = !top && w >= TM.headW && h >= 2 * TM.head ? TM.head : 0;
    const iw = w - 2 * pad, ih = h - head - 2 * pad;
    if (!n.children.length || iw < TM.inner || ih < TM.inner) {
      link(n, 'tm-leaf', x, y, w, h, w >= TM.labelW && h >= TM.labelH);
      return;
    }
    if (!top) {
      link(n, 'tm-group', x, y, w, h, head > 0).addEventListener('dblclick', (e) => {
        e.preventDefault();
        location.hash = zoomHref(n.path);
      });
    }
    const rects = squarify(n.children.map((c) => c.size), x + pad, y + head + pad, iw, ih);
    n.children.forEach((c, i) => place(c, rects[i].x, rects[i].y, rects[i].w, rects[i].h));
  };
  if (total) place(root, 0, 0, box.clientWidth, box.clientHeight);
  else items.push(el('p', { class: 'empty', text: v.closed ? 'No records.' : 'No open records.' }));
  box.replaceChildren(...items);
  setInk([...box.querySelectorAll('.tm-leaf, .tm-group > .tm-label')]);
  if (focused) items.find((a) => a.dataset?.path === focused)?.focus();
  document.getElementById('explore-note').hidden = !dims.includes('cis');
  show(null);

  // Zoomed in, the path back out: each group above is a link that zooms out to it.
  const crumbs = document.getElementById('explore-crumbs');
  crumbs.hidden = !root.path.length;
  const steps = [el('a', { href: zoomHref([]), text: 'All records' })];
  root.path.forEach((label, i) => {
    steps.push(el('span', { class: 'sep', 'aria-hidden': 'true', text: ' › ' }));
    steps.push(i === root.path.length - 1 ? el('span', { 'aria-current': 'location', text: label })
      : el('a', { href: zoomHref(root.path.slice(0, i + 1)), text: label }));
  });
  crumbs.replaceChildren(...(root.path.length ? steps : []));

  // The picked box's records, or everything shown when none is picked.
  exploreSelPath = sel.path;
  document.getElementById('explore-title').textContent = pathText(sel.path);
  document.getElementById('explore-count').textContent =
    `${recordsText(sel.records.length)}${v.closed ? '' : ' (open only)'} - each opens in GLPI`;
  document.getElementById('explore-zoom').hidden = !(sel !== root && sel.children.length);
  const key = 'explore:' + JSON.stringify([sel.path, v.closed]);
  if (key !== exploreListKey) { views.delete(key); exploreListKey = key; }
  grid(document.getElementById('explore-rows'), key, EXPLORE_COLUMNS, sel.records);

  // The same groups and counts as a table: the legend, and the view for anyone not using the map.
  const table = document.getElementById('explore-table');
  (table.tHead || table.createTHead()).replaceChildren(el('tr', {}, el('th', { scope: 'col', text: 'Group' }),
    el('th', { scope: 'col', class: 'n', text: 'Records' }), el('th', { scope: 'col', class: 'n', text: 'Share' })));
  const rows = [];
  const walk = (n, depth) => {
    for (const c of n.children) {
      const cls = colourCls(c);
      const th = el('th', { scope: 'row' }, cls ? el('span', { class: 'swatch ' + cls, 'aria-hidden': 'true' }) : null, c.label);
      th.style.paddingLeft = `${10 + 18 * depth}px`;
      rows.push(el('tr', {}, th, el('td', { class: 'n' },
        el('a', { href: href(c.path), 'aria-label': `${pathText(c.path)}: ${recordsText(c.records.length)} - show list`,
          text: String(c.records.length) })),
      el('td', { class: 'n', text: share(c) })));
      walk(c, depth + 1);
    }
  };
  walk(root, 0);
  fill(table.tBodies[0], rows, 3);
}

{
  const tierOptions = (none) => [...(none ? [el('option', { value: '', text: '(nothing)' })] : []),
    ...Object.entries(DIMS).map(([k, d]) => el('option', { value: k, text: d.label }))];
  document.getElementById('explore-tier-1').append(...tierOptions(false));
  document.getElementById('explore-tier-2').append(...tierOptions(true));
  document.getElementById('explore-tier-3').append(...tierOptions(true));
  document.getElementById('explore-colour').append(...COLOURS.map((k) =>
    el('option', { value: k, text: k === 'none' ? 'Nothing' : DIMS[k].label })));
  const form = document.getElementById('explore-form');
  form.addEventListener('submit', (e) => e.preventDefault());
  form.addEventListener('change', () => {
    // "(nothing)" ends the groupings there; one picked again lower down (the top one changed to it) is dropped.
    const picked = [1, 2, 3].map((i) => document.getElementById('explore-tier-' + i).value);
    const end = picked.indexOf('');
    const tiers = [...new Set(end < 0 ? picked : picked.slice(0, end))];
    const colour = document.getElementById('explore-colour').value;
    // Only Include closed changed: stay on the same groups, if they're still there.
    const same = tiers.join() === exploreView.tiers.join() && colour === exploreView.colour;
    setExplore({ tiers, colour, closed: document.getElementById('explore-closed').checked,
      zoom: same ? exploreView.zoom : [], sel: same ? exploreView.sel : [] });
  });
  document.getElementById('explore-zoom').addEventListener('click', () => {
    location.hash = exploreHash({ ...exploreView, zoom: exploreSelPath, sel: [] });
  });
  // Drawn to fit: a new size (the tab shown, the window resized) lays it out again.
  new ResizeObserver(() => requestAnimationFrame(renderExplorer)).observe(document.getElementById('treemap'));
  // The box colours, and so the text on them, change with the theme.
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { explorerDrawn = null; renderExplorer(); });
}

// --- theme: System (the default), Light or Dark; theme.js applies the saved one before the page is first drawn ---

const themeButtons = [...document.querySelectorAll('[data-theme-choice]')];

/**
 * Applies a theme and marks its button as the one picked.
 * @param {string} theme 'system', 'light' or 'dark'
 */
function setTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  for (const b of themeButtons) b.setAttribute('aria-pressed', String(b.dataset.themeChoice === theme));
}

setTheme(document.documentElement.dataset.theme || 'system');
for (const b of themeButtons) {
  b.addEventListener('click', () => {
    const theme = b.dataset.themeChoice;
    setTheme(theme);
    try {
      if (theme === 'system') localStorage.removeItem('theme');
      else localStorage.setItem('theme', theme);
    } catch { /* storage blocked: the choice just isn't kept */ }
    // The explorer's box text is picked for the colours it was drawn on.
    explorerDrawn = null;
    renderExplorer();
  });
}

// --- page -------------------------------------------------------------------------------------------------------

/** Draws every section from `snap`, then reopens the list in the URL hash, if any. */
function render() {
  document.getElementById('glpi-link').href = safeUrl(snap.glpi_url);
  const at = new Date(snap.refreshed_at);
  document.getElementById('updated').textContent =
    `Updated ${at.toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' })} (refreshed every ${Math.round(snap.refresh_seconds / 60)} min)`;
  const err = document.getElementById('error');
  err.hidden = !snap.error;
  err.textContent = snap.error ? `Last refresh from GLPI failed - showing the data from ${at.toLocaleTimeString(LOCALE)}. ${snap.error}` : '';

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
  renderExplorer();

  showList();
}

/**
 * Drill-down: #list=<key> opens the dialog; closing it clears the hash, so Back works too.
 * Unknown or malformed keys close it.
 */
function showList() {
  const dlg = document.getElementById('list');
  const s = location.hash.match(/^#search=([^&]*)(&closed=1)?$/);
  if (s) {
    let q = null;
    try { q = decodeURIComponent(s[1]); } catch { q = null; }
    // The boxes stop at SEARCH_MAX characters and so does the server; a longer link is cut to fit.
    if (q !== null) { showSearch(q.slice(0, SEARCH_MAX), Boolean(s[2])); return; }
  }
  setSearchMode(false);
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
  grid(document.getElementById('list-table'), 'list:' + key, kind.columns, rows);
  if (!dlg.open) dlg.showModal();
}

// --- search: the header box opens #search=<query> in the list dialog, which has its own box to refine it ---------

const SEARCH_MIN = 2;
const SEARCH_MAX = 100;
const SEARCH_DELAY_MS = 500;
// A search word naming a record's id, e.g. #12; the server finds that id in every type.
const ID_WORD = /^#\d+$/;
const searchBox = document.getElementById('search');
const listSearch = document.getElementById('list-search');
// Include closed, beside each box; the two always agree. Off by default: a search over open records only is
// what's usually wanted, and quicker.
const closedBoxes = [document.getElementById('search-closed'), document.getElementById('list-closed')];
let searchTimer = null;
// The query and snapshot the results were last fetched for, so the 60 s re-render doesn't fetch them again.
let searchDrawn = null;
// Only the latest request draws its results: answers can come back out of order.
let searchSeq = 0;

/** Shows or hides the dialog's search box; the dialog is wider for search results, to keep each on one line. */
function setSearchMode(on) {
  document.getElementById('list-search-form').hidden = !on;
  document.getElementById('search-data').hidden = !on;
  document.getElementById('list').classList.toggle('searching', on);
  if (!on) {
    showIdParts(false);
    searchDrawn = null;
    ++searchSeq;      // a search still on its way must not draw over the list that replaced it
  }
}

/**
 * Splits the results in two for a search with an #id in it: the records with that id above, headed ID matches,
 * and the rest below, headed Text matches. Without one, the dialog has its usual single table.
 * @param {boolean} on
 */
function showIdParts(on) {
  document.getElementById('search-ids').hidden = !on;
  document.getElementById('search-text-title').hidden = !on;
  document.getElementById('list-table').setAttribute('aria-labelledby', on ? 'search-text-title' : 'list-title');
}

/** The hash for a search: `#search=<query>`, plus `&closed=1` to include closed records. */
const searchHash = (q, closed) => '#search=' + encodeURIComponent(q) + (closed ? '&closed=1' : '');

/** Says, in the dialog, which data a search looks through: the last refresh, which Refresh now updates. */
function showSearchData() {
  const text = document.getElementById('search-data-text');
  if (!snap) { text.textContent = 'Searching the data from the last refresh of GLPI.'; return; }
  const at = new Date(snap.refreshed_at).toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' });
  text.textContent = snap.error
    ? `Searching the data read from GLPI at ${at}: the last refresh failed.`
    : `Searching the data read from GLPI at ${at}.`;
}

/**
 * Opens (or updates) the search results for `q` in the dialog. The server searches what it read at the last
 * refresh, so this asks it again only when the query, Include closed or the snapshot changes.
 * @param {string} q
 * @param {boolean} closed include closed records
 */
async function showSearch(q, closed) {
  const dlg = document.getElementById('list');
  const count = document.getElementById('list-count');
  const table = document.getElementById('list-table');
  setSearchMode(true);
  document.getElementById('list-title').textContent = 'Search';
  for (const b of closedBoxes) b.checked = closed;
  showSearchData();
  // Leave a box being typed in alone: it may already hold more than this query.
  if (document.activeElement !== listSearch) listSearch.value = q;
  if (document.activeElement !== searchBox) searchBox.value = q;
  if (!dlg.open) {
    dlg.showModal();
    listSearch.focus();
    listSearch.setSelectionRange(listSearch.value.length, listSearch.value.length);
  }
  const asked = `${q}\n${closed}`;
  const drawn = `${asked}\n${snap?.refreshed_at}`;
  if (drawn === searchDrawn) return;
  searchDrawn = drawn;
  const seq = ++searchSeq;
  if (q.trim().length < SEARCH_MIN) {
    count.textContent = `Type at least ${SEARCH_MIN} characters to search.`;
    searchWords = [];
    showIdParts(false);
    grid(table, 'search', SEARCH_COLUMNS, []);
    return;
  }
  count.textContent = 'Searching…';
  try {
    const res = await fetch('api/search?q=' + encodeURIComponent(q) + (closed ? '&closed=true' : ''), { cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    if (seq !== searchSeq) return;
    // A new query starts unsorted and short; the same one, re-fetched after a refresh, keeps its state.
    for (const id of ['search', 'search-ids']) {
      if (views.get(id)?.asked !== asked) views.set(id, { col: -1, dir: 1, shown: PAGE, asked });
    }
    searchWords = q.toLowerCase().split(/\s+/).filter(Boolean);
    const byId = searchWords.some((w) => ID_WORD.test(w));
    showIdParts(byId);
    grid(document.getElementById('search-ids').querySelector('table'), 'search-ids', SEARCH_COLUMNS, body.ids);
    grid(table, 'search', SEARCH_COLUMNS, body.results);
    /** `n matches`, with `what` (e.g. 'ID ') before the noun. */
    const matches = (k, what) => `${k} ${what}${k === 1 ? 'match' : 'matches'}`;
    const n = body.results.length;
    const found = matches(body.total, byId ? 'text ' : '')
      + (body.total > n ? ` - showing the best ${n}; add words to narrow it` : '');
    count.textContent = body.total + body.ids.length === 0 ? 'No matches.'
      : `${byId ? matches(body.ids.length, 'ID ') + ', ' : ''}${found} - each opens in GLPI`;
  } catch (e) {
    if (seq !== searchSeq) return;
    searchDrawn = null;
    searchWords = [];
    showIdParts(false);
    grid(table, 'search', SEARCH_COLUMNS, []);     // not the last query's results under this one
    count.textContent = `Search failed: ${e.message}`;
  }
}

/**
 * Searches for what's in a box: the header box opens the dialog (a history entry, so Back closes it), and the
 * dialog's box updates it in place. A query too short to search opens nothing from the header.
 * @param {HTMLInputElement} input
 */
function search(input) {
  clearTimeout(searchTimer);
  const q = input.value.trim();
  const closed = closedBoxes[0].checked;
  const hash = searchHash(q, closed);
  if (input === listSearch) {
    if (location.hash !== hash) history.replaceState(null, '', hash);
    showSearch(q, closed);
  } else if (q.length >= SEARCH_MIN) {
    if (location.hash === hash) showSearch(q, closed);
    else location.hash = hash;
  }
}

for (const input of [searchBox, listSearch]) {
  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search(input), SEARCH_DELAY_MS);
  });
  // Enter searches at once. The CSP's form-action 'none' would block a real submit anyway.
  input.form.addEventListener('submit', (e) => { e.preventDefault(); search(input); });
}
// In a search box, Escape would only clear it (✕ does that); in the dialog's, it closes the dialog as anywhere else.
listSearch.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  e.preventDefault();
  document.getElementById('list').close();
});
// Include closed changes the results at once when they're showing; in the header it applies to the next search.
for (const box of closedBoxes) {
  box.addEventListener('change', () => {
    for (const other of closedBoxes) other.checked = box.checked;
    const dlg = document.getElementById('list');
    if (dlg.open && dlg.classList.contains('searching')) search(listSearch);
  });
}

/**
 * Loads the current snapshot and renders it; failures show in the banner and keep the old data.
 * @param {boolean} refresh POST /api/refresh, so the backend re-reads GLPI first
 * @returns {Promise<string|null>} the banner's message if it failed, else null
 */
async function load(refresh = false) {
  try {
    const res = await fetch(refresh ? 'api/refresh' : 'api/snapshot', { method: refresh ? 'POST' : 'GET', cache: 'no-store' });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    snap = body;
    explorerAsked = null;     // the explorer may ask again: once per poll if it failed, else only for a new refresh
    render();
    return null;
  } catch (e) {
    const err = document.getElementById('error');
    err.hidden = false;
    err.textContent = `Could not load the dashboard data: ${e.message}`;
    return err.textContent;
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
  // The explorer's view lives in the hash while it shows, so the address can be shared; other tabs don't keep it.
  // A #list= or #search= link is left alone: it opens over whichever tab shows.
  if (tab.id === 'tab-explorer') {
    if (location.hash.length <= 1) history.replaceState(null, '', exploreHash(exploreView));
    renderExplorer();
  } else if (parseExplore(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search);
  }
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
const explorerTab = document.getElementById('tab-explorer');
const linkedView = parseExplore(location.hash);
if (linkedView) exploreView = linkedView;
selectTab(linkedView ? explorerTab : TABS.find((t) => t.id === savedTab) || TABS[0]);
// An explorer link (a box picked, Back, a shared address) shows the explorer at that view.
window.addEventListener('hashchange', () => {
  const v = parseExplore(location.hash);
  if (!v) return;
  exploreView = v;
  if (explorerTab.getAttribute('aria-selected') === 'true') renderExplorer();
  else selectTab(explorerTab);
});

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
  clearTimeout(searchTimer);
  if (/^#(list|search)=/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
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
/**
 * Refresh now, from the header or the search results. Both buttons show it's busy until the new data is in, and
 * a failure the banner can't show (it's behind the dialog) is said in the dialog too.
 * @param {MouseEvent} e
 */
async function refreshNow(e) {
  const clicked = e.currentTarget;
  const buttons = document.querySelectorAll('.refresh');
  // Icon buttons: the name is the label, so that's what says it's busy (the icon spins too).
  for (const b of buttons) { b.disabled = true; b.setAttribute('aria-label', 'Refreshing…'); b.title = 'Refreshing…'; }
  const failed = await load(true);
  for (const b of buttons) { b.disabled = false; b.setAttribute('aria-label', 'Refresh now'); b.title = 'Refresh now'; }
  // A disabled button loses focus; give it back so the keyboard user carries on from where they were.
  if (document.activeElement === document.body || document.activeElement === dialog) clicked.focus();
  if (failed && clicked.id === 'list-refresh') document.getElementById('search-data-text').textContent = failed;
}
for (const b of document.querySelectorAll('.refresh')) b.addEventListener('click', refreshNow);
window.addEventListener('hashchange', showList);
load();
setInterval(load, POLL_MS);
