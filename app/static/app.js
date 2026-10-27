// GLPI dashboard page. Renders /api/snapshot; every number links to #list=<key>,
// which opens the records behind it, each linked to GLPI.
// All GLPI text goes in with textContent - never innerHTML.
'use strict';

const POLL_MS = 60_000;
const RAG = { red: ['■', 'Act'], amber: ['▲', 'Watch'], green: ['●', 'OK'] };
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

function tile(t) {
  const a = el('a', { class: 'tile' + (t.count ? '' : ' zero'), href: '#list=' + encodeURIComponent(t.key) },
    el('span', { class: 'value', text: String(t.count) }),
    el('span', { class: 'label', text: t.title }));
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
  return glpiLink(rec.url, rec.ref, 'ref');
}

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

  document.getElementById('areas').replaceChildren(...snap.health.areas.map((a) =>
    el('div', { class: 'card' },
      el('h3', {}, el('span', { text: a.area }), rag(a.rag)),
      el('div', { class: 'counts' },
        el('span', {}, listLink(a.incidents_list, a.incidents, 'value'), el('span', { class: 'label', text: 'incidents' })),
        el('span', {}, listLink(a.problems_list, a.problems, 'value'), el('span', { class: 'label', text: 'problems' }))))));

  document.getElementById('cis-count').textContent = String(snap.health.cis.length);
  fill(document.querySelector('#cis tbody'), snap.health.cis.map((c) =>
    el('tr', {}, ciCell(c), el('td', {}, rag(c.rag)),
      el('td', { class: 'n' }, listLink(c.incidents_list, c.incidents)),
      el('td', { class: 'n' }, listLink(c.problems_list, c.problems)),
      el('td', { class: 'n' }, listLink(c.changes_list, c.changes)))), 5);

  const ra = document.getElementById('risks-all');
  ra.querySelector('span').textContent = String(snap.risks.total);
  fill(document.querySelector('#risks tbody'), snap.risks.top.map((s, i) => {
    const r = snap.records[s.key];
    return el('tr', {},
      el('td', { class: 'n', text: String(i + 1) }),
      el('td', {}, recordLink(r), document.createTextNode(' ' + r.name)),
      el('td', { class: 'nowrap', text: r.priority_name }),
      el('td', { text: r.area }),
      el('td', { class: 'n', text: String(s.score) }),
      el('td', { class: 'why', text: s.why.join(' · ') }));
  }), 6);

  document.getElementById('flight').replaceChildren(...snap.in_flight.tiles.map(tile));

  fill(document.querySelector('#projects tbody'), snap.in_flight.projects.map((p) => {
    const bar = el('span', { class: 'bar' }, el('span'));
    bar.firstChild.style.width = `${Math.max(0, Math.min(100, p.percent_done))}%`;
    return el('tr', {},
      el('td', {}, glpiLink(p.url, p.name)),
      el('td', { text: p.state }),
      el('td', {}, bar, document.createTextNode(`${p.percent_done}%`)),
      el('td', { class: 'n' }, listLink(p.open_list, p.open)),
      el('td', { class: 'n' }, listLink(p.total_list, p.total)));
  }), 5);

  fill(document.querySelector('#recurring tbody'), snap.in_flight.recurring.map((r) =>
    el('tr', {},
      el('td', {}, glpiLink(r.url, r.name)),
      el('td', { text: r.periodicity }),
      el('td', { text: r.next_creation || '-' }),
      el('td', { text: r.due || '-' }))), 4);

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
  if (!lst) { if (dlg.open) dlg.close(); return; }
  document.getElementById('list-title').textContent = lst.title;
  document.getElementById('list-count').textContent = `${lst.refs.length} record${lst.refs.length === 1 ? '' : 's'} - each opens in GLPI`;
  fill(document.getElementById('list-rows'), lst.refs.map((k) => {
    const r = snap.records[k];
    const cis = el('td');
    r.cis.forEach((c, i) => { if (i) cis.append(', '); cis.append(glpiLink(c.url, c.name)); });
    return el('tr', {},
      el('td', {}, recordLink(r)),
      el('td', {}, glpiLink(r.url, r.name)),
      el('td', { text: r.status }),
      el('td', { class: 'nowrap', text: r.priority_name }),
      el('td', { class: 'n', text: `${r.age_days} d` }),
      cis);
  }), 6);
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

document.getElementById('list').addEventListener('close', () => {
  if (location.hash.startsWith('#list=')) history.replaceState(null, '', location.pathname + location.search);
});
document.querySelector('#list .close').addEventListener('click', (e) => {
  e.preventDefault();
  document.getElementById('list').close();
});
document.getElementById('refresh').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = 'Refreshing…';
  await load(true);
  btn.disabled = false;
  btn.textContent = 'Refresh now';
});
window.addEventListener('hashchange', showList);
load();
setInterval(load, POLL_MS);
