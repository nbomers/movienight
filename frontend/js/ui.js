// Shared UI helpers. Every value from the API goes through esc() before it
// reaches innerHTML; URLs are only built from validated shapes.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (value) => {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
};

export const icon = (name, cls = '') =>
  `<svg class="ic ${cls}" aria-hidden="true"><use href="/frontend/img/icons.svg#${name}"/></svg>`;

const POSTER_PATH = /^\/[\w.-]+$/;
const TRAILER_URL = /^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{1,64}$/;

export const posterUrl = (path, size = 'w342') =>
  POSTER_PATH.test(path || '') ? `https://image.tmdb.org/t/p/${size}${path}` : '';
export const safeTrailer = (url) => (TRAILER_URL.test(url || '') ? url : '');

// One superlike counts like three likes. Used for ranking everywhere.
export const score = (m) => m.upvotes + m.superlikes * 3 - m.downvotes;
export const signed = (n) => (n > 0 ? `+${n}` : String(n));

export const initials = (name) => (name || '?').replace(/[^\p{L}\p{N}]/gu, '').slice(0, 2).toUpperCase() || '?';
export const genreList = (genres) => (genres ? genres.split(',').map((g) => g.trim()).filter(Boolean) : []);

export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

const dateFmt = new Intl.DateTimeFormat('de-DE', { day: 'numeric', month: 'long', year: 'numeric' });
const dateTimeFmt = new Intl.DateTimeFormat('de-DE', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
export const formatDate = (iso) => (iso ? dateFmt.format(new Date(iso)) : '');
export const formatDateTime = (iso) => (iso ? dateTimeFmt.format(new Date(iso)) : '');

export function formatRemaining(ms) {
  const totalMin = Math.max(0, Math.floor(ms / 60000));
  const d = Math.floor(totalMin / 1440);
  const h = Math.floor((totalMin % 1440) / 60);
  const m = totalMin % 60;
  if (d > 0) return `${d} T ${h} Std`;
  if (h > 0) return `${h} Std ${m} Min`;
  const s = Math.max(0, Math.floor((ms % 60000) / 1000));
  return `${m} Min ${String(s).padStart(2, '0')} s`;
}

export function relativeTime(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'gerade eben';
  if (diff < 3600) return `vor ${Math.floor(diff / 60)} Min`;
  if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std`;
  if (diff < 7 * 86400) return `vor ${Math.floor(diff / 86400)} T`;
  return formatDate(iso);
}

// ── Toasts ───────────────────────────────────────────────────────────────
let toastHost = null;

export function toast(message, type = '', { action = null, duration = 3200 } = {}) {
  if (!toastHost) {
    toastHost = document.createElement('div');
    toastHost.className = 'toasts';
    toastHost.setAttribute('role', 'status');
    toastHost.setAttribute('aria-live', 'polite');
    document.body.appendChild(toastHost);
  }
  const el = document.createElement('div');
  el.className = `toast${type ? ` toast-${type}` : ''}`;
  const iconName = type === 'err' ? 'x' : type === 'ok' ? 'check' : null;
  el.innerHTML = `${iconName ? icon(iconName) : ''}<span>${esc(message)}</span>`;
  if (action) {
    const btn = document.createElement('button');
    btn.className = 'toast-action';
    btn.textContent = action.label;
    btn.addEventListener('click', () => { action.onClick(); dismiss(); });
    el.appendChild(btn);
  }
  toastHost.appendChild(el);
  while (toastHost.children.length > 3) toastHost.firstElementChild.remove();

  let timer = setTimeout(dismiss, duration);
  function dismiss() {
    clearTimeout(timer);
    el.classList.add('is-leaving');
    setTimeout(() => el.remove(), 200);
  }
  return dismiss;
}

// ── Dialogs ──────────────────────────────────────────────────────────────
// <dialog class="sheet"> gives focus trapping and Escape for free. A click on
// the backdrop (the dialog element itself, outside .sheet-inner) closes it.
export function setupDialog(dialog, { onClose } = {}) {
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.documentElement.style.overflow = '';
    if (onClose) onClose();
  });
  $$('[data-close]', dialog).forEach((btn) => btn.addEventListener('click', () => dialog.close()));
  return dialog;
}

export function openDialog(dialog) {
  if (!dialog.open) dialog.showModal();
  document.documentElement.style.overflow = 'hidden';
}

// Small promise-based confirmation, styled like the rest of the app.
export function confirmDialog({ title, text = '', confirmLabel = 'OK', danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement('dialog');
    dlg.className = 'sheet';
    dlg.innerHTML = `
      <div class="sheet-inner">
        <div class="sheet-head"><h2>${esc(title)}</h2></div>
        ${text ? `<div class="sheet-body"><p style="color:var(--text-2)">${esc(text)}</p></div>` : ''}
        <div class="sheet-foot">
          <button class="btn btn-ghost" value="cancel">Abbrechen</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" value="ok">${esc(confirmLabel)}</button>
        </div>
      </div>`;
    document.body.appendChild(dlg);
    let result = false;
    $$('button', dlg).forEach((b) => b.addEventListener('click', () => { result = b.value === 'ok'; dlg.close(); }));
    setupDialog(dlg, { onClose: () => { setTimeout(() => dlg.remove(), 300); resolve(result); } });
    openDialog(dlg);
  });
}

// Busy state for buttons while a request runs.
export async function withBusy(button, fn) {
  if (!button) return fn();
  button.classList.add('is-loading');
  button.disabled = true;
  try {
    return await fn();
  } finally {
    button.classList.remove('is-loading');
    button.disabled = false;
  }
}

export function togglePasswordVisibility(button) {
  const input = button.closest('.input-wrap').querySelector('input');
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  button.setAttribute('aria-label', show ? 'Passwort verbergen' : 'Passwort anzeigen');
  button.innerHTML = icon(show ? 'eye-off' : 'eye');
}

export const vibrate = (pattern) => {
  if (navigator.vibrate) {
    try { navigator.vibrate(pattern); } catch { /* not allowed */ }
  }
};
