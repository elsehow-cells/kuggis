'use strict';
// Shared theme, authentication, and safe text rendering for both pages.

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private window */ } },
};

// BigBrain's themes (theme.css; ids and names from its lib/theme.ts). No
// data-theme is Ink following the system; a pair follows it too.
const THEMES = [
  ['', 'Ink · follows the system'],
  ['pair:kind-of-blue', 'Kind of Blue · follows the system'],
  ['pair:somethings-gotta-give', "Something's Gotta Give · follows the system"],
  ['default', 'Ink, light'], ['dusk', 'Ink, dark'],
  ['kind-of-blue-light', 'Kind of Blue, light'], ['kind-of-blue-dark', 'Kind of Blue, dark'],
  ['somethings-gotta-give', "Something's Gotta Give, light"], ['hamptons-nights', "Hampton's Nights"],
  ['web', 'OG Web Blue'], ['moegiiro', 'Spring'], ['adzukiiro', 'Fall'], ['asagiiro', 'Winter'],
  ['jodie-foster-in-contact', 'Jodie Foster in Contact'], ['a-love-supreme', 'A Love Supreme'],
];
const PAIRS = { 'kind-of-blue': ['kind-of-blue-light', 'kind-of-blue-dark'], 'somethings-gotta-give': ['somethings-gotta-give', 'hamptons-nights'] };
const darkMode = matchMedia('(prefers-color-scheme: dark)');
let themeChoice = store.get('kuggis.theme') || '';
function applyTheme() {
  const pair = themeChoice.startsWith('pair:') && PAIRS[themeChoice.slice(5)];
  const id = pair ? pair[darkMode.matches ? 1 : 0] : themeChoice;
  if (id) document.documentElement.dataset.theme = id;
  else delete document.documentElement.dataset.theme;
}
applyTheme(); // before first paint: this script loads in <head>
darkMode.addEventListener('change', applyTheme);

// The token arrives once in the #fragment (kuggis web opens that link) and is
// kept here, out of the address bar.
const token = (() => {
  const h = location.hash.slice(1);
  if (/^[0-9a-f]{32,}$/.test(h)) {
    store.set('kuggis.token', h);
    history.replaceState(null, '', location.pathname);
    return h;
  }
  return store.get('kuggis.token') || '';
})();

const PLAIN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/; // what a session or project name may be
const HIDDEN = /[­​-‏‪-‮⁠-⁤﻿]/g;

function el(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const k of kids) if (k != null && k !== false) e.append(k);
  return e;
}

// Text, with invisible and direction-changing characters made visible.
function visible(s) {
  const f = document.createDocumentFragment();
  let last = 0;
  for (const m of String(s).matchAll(HIDDEN)) {
    f.append(s.slice(last, m.index));
    f.append(el('span', 'hidden-char', 'U+' + m[0].codePointAt(0).toString(16).toUpperCase().padStart(4, '0')));
    last = m.index + m[0].length;
  }
  f.append(String(s).slice(last));
  return f;
}


async function api(path, body) {
  const headers = { 'X-Kuggis-Token': token };
  const r = await fetch(path, body
    ? { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : { headers });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

let toastTimer;
function toast(msg, bad) {
  const t = document.getElementById('toast');
  t.replaceChildren(visible(msg));
  t.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = 'toast'), bad ? 9000 : 5000);
}


async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  const t = el('textarea');
  t.value = text;
  document.body.append(t);
  t.select();
  const ok = document.execCommand('copy');
  t.remove();
  return ok;
}


function setupThemes() {
  const sel = document.getElementById('theme');
  for (const [id, name] of THEMES) {
    const o = el('option', null, name);
    o.value = id;
    sel.append(o);
  }
  sel.value = themeChoice;
  sel.addEventListener('change', () => {
    themeChoice = sel.value;
    store.set('kuggis.theme', themeChoice || null);
    applyTheme();
    sel.blur();
  });
}

