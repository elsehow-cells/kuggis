'use strict';
let snapshot, timer, request;
const rowsById = new Map();

function age(since, now) {
  const seconds = Math.max(0, now - since);
  if (seconds < 60) return '<1m';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function showDefinition(cell) {
  const dialog = document.getElementById('definition');
  document.getElementById('definition-title').textContent = cell.name;
  const d = cell.definition;
  document.getElementById('definition-meta').replaceChildren(visible(d
    ? `Read-only ${d.contract ? "development contract · isolation not certified" : "display definition · not enforced"} · SHA256 ${d.sha256}\n${d.source}`
    : 'Inferred display grouping · no enforced cell definition'));
  document.getElementById('definition-text').replaceChildren(visible(d?.text || JSON.stringify({
    cell: cell.name, projects: cell.projects, enforced: false,
  }, null, 2)));
  dialog.showModal();
}

// Only copy the existing CLI's small command vocabulary, never arbitrary
// commands supplied by a VM or a display definition.
function validCommand(command) {
  return typeof command === 'string' && /^(kuggis (think|dispatch)|kuggis sh [A-Za-z0-9][A-Za-z0-9_-]*( --project [A-Za-z0-9][A-Za-z0-9_-]*)?|kuggis [A-Za-z0-9][A-Za-z0-9_-]* [A-Za-z0-9][A-Za-z0-9_-]*( --project [A-Za-z0-9][A-Za-z0-9_-]*)?)$/.test(command);
}

async function copyRow(id) {
  const row = rowsById.get(id);
  if (!row || !validCommand(row.command)) return toast('No command available for this row.');
  const ok = await copy(row.command);
  toast(ok ? `Copied: ${row.command}` : `Copy manually: ${row.command}`);
}

function render() {
  const focused = document.activeElement?.dataset.focus;
  const frag = document.createDocumentFragment();
  rowsById.clear();
  let needs = 0;
  for (const cell of snapshot.cells) {
    needs += cell.needs_you;
    const name = el('button', 'cell-name', visible(cell.name));
    name.type = 'button';
    name.dataset.focus = `cell:${cell.name}`;
    name.title = `View ${cell.name} definition`;
    name.addEventListener('click', () => showDefinition(cell));
    const heading = el('h2', null, name);
    if (cell.name === 'operator') heading.append(el('span', 'outside', 'outside cells'));
    const section = el('section', 'cell', el('div', 'cell-header', heading, el('span', 'cell-state', `${cell.status} · ${cell.readiness || 'setup unverified'}`)));
    for (const row of cell.rows) {
      rowsById.set(row.id, row);
      const elapsed = row.since ? age(row.since, snapshot.now) : row.age;
      const dot = el('span', 'dot');
      dot.setAttribute('aria-hidden', 'true');
      const button = el('button', `row${row.needs_you ? ' needs-you' : ''}`, dot,
        el('span', 'row-name', el('span', 'name', visible(row.name)), row.project && el('span', 'project', visible(row.project))),
        el('span', 'state', visible(row.state)), el('span', 'age', visible(elapsed || '')));
      button.type = 'button';
      button.dataset.focus = row.id;
      button.title = validCommand(row.command) ? `Copy ${row.command}` : 'Command unavailable';
      button.setAttribute('aria-label', `${row.name}, ${row.state}${row.needs_you ? ', needs you' : ''}. ${button.title}`);
      button.addEventListener('click', () => copyRow(row.id));
      section.append(button);
    }
    if (!cell.rows.length) section.append(el('p', 'empty', 'No sessions'));
    frag.append(section);
  }
  if (!snapshot.cells.length) frag.append(el('p', 'empty', 'No configured projects'));
  document.getElementById('cells').replaceChildren(frag);
  // Polls must not move keyboard focus or reorder rows by urgency.
  if (focused) [...document.querySelectorAll('[data-focus]')].find(e => e.dataset.focus === focused)?.focus({ preventScroll: true });
  document.getElementById('summary').textContent = needs ? `${needs} need${needs === 1 ? 's' : ''} you` : 'Nothing waiting';
}

async function refresh() {
  if (request) return request;
  clearTimeout(timer);
  document.getElementById('refresh').disabled = true;
  request = (async () => {
    try {
      snapshot = await api('/api/cells');
      render();
      document.getElementById('error').hidden = true;
      document.getElementById('status').textContent = `Updated ${new Date(snapshot.now * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    } catch (e) {
      const error = document.getElementById('error');
      error.replaceChildren(visible(e.message));
      error.hidden = false;
      document.getElementById('status').textContent = snapshot ? 'Updates unavailable · showing last snapshot' : 'Updates unavailable';
      if (!snapshot) document.getElementById('cells').replaceChildren();
    } finally {
      document.getElementById('refresh').disabled = false;
      timer = setTimeout(refresh, 15000);
    }
  })();
  try { await request; } finally { request = null; }
}

setupThemes();
document.getElementById('refresh').addEventListener('click', refresh);
document.getElementById('close-definition').addEventListener('click', () => document.getElementById('definition').close());
document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey || document.getElementById('definition').open || e.target.closest?.('select, input, textarea')) return;
  if (e.key === 'r') { e.preventDefault(); refresh(); }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && token) refresh(); });
if (token) refresh();
else {
  document.getElementById('cells').replaceChildren();
  document.getElementById('error').textContent = 'Run kuggis web to open an authenticated dashboard.';
  document.getElementById('error').hidden = false;
}
