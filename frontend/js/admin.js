import * as api from './api.js';
import {
  $, $$, confirmDialog, esc, formatDate, formatDateTime, icon, initials, openDialog, plural, posterUrl, score,
  setupDialog, toast, withBusy,
} from './ui.js';

let me = null;
let rounds = [];
let invites = [];
let users = [];
let hideExpired = false;

// Deadlines are entered in Berlin time, which is what the server assumes for
// values without offset (see parse_deadline).
const berlinParts = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
});
const toBerlinInput = (date) => berlinParts.format(date).replace(' ', 'T');
const dayName = new Intl.DateTimeFormat('de-DE', { day: 'numeric', month: 'long', timeZone: 'Europe/Berlin' });

async function boot() {
  if (!api.getToken()) { window.location.replace('index.html'); return; }
  try {
    me = await api.getMe();
  } catch { return; }
  if (!me.is_admin) { window.location.replace('app.html'); return; }
  await Promise.all([loadRounds(), loadInvites(), loadUsers()]);
}

// Generic form dialog. `fields` is HTML; resolves with the form or null.
function formDialog({ title, body, confirmLabel = 'Speichern', danger = false, wide = false, onSubmit }) {
  const dlg = document.createElement('dialog');
  dlg.className = `sheet${wide ? ' sheet-wide' : ''}`;
  dlg.innerHTML = `
    <form class="sheet-inner" method="dialog" novalidate>
      <div class="sheet-head"><span class="sheet-grip"></span><h2>${esc(title)}</h2>
        <button type="button" class="close-btn" data-close aria-label="Schließen">${icon('x')}</button></div>
      <div class="sheet-body">${body}</div>
      <div class="sheet-foot">
        <button type="button" class="btn btn-ghost" data-close>${confirmLabel ? 'Abbrechen' : 'Fertig'}</button>
        ${confirmLabel ? `<button type="submit" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${esc(confirmLabel)}</button>` : ''}
      </div>
    </form>`;
  document.body.appendChild(dlg);
  setupDialog(dlg, { onClose: () => setTimeout(() => dlg.remove(), 300) });
  const form = $('form', dlg);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const done = await withBusy(e.submitter, () => onSubmit(form, dlg));
      if (done !== false) dlg.close();
    } catch (ex) { toast(ex.message, 'err'); }
  });
  openDialog(dlg);
  setTimeout(() => $('input:not([type=hidden])', dlg)?.focus(), 60);
  return dlg;
}

// ── Rounds ───────────────────────────────────────────────────────────────
async function loadRounds() {
  try {
    rounds = await api.getRounds();
  } catch (e) { toast(e.message, 'err'); return; }
  renderCurrentRound();
  renderRoundList();
}

function renderCurrentRound() {
  const box = $('#currentRound');
  const active = rounds.find((r) => r.status === 'active');
  if (active) {
    const closed = active.vote_deadline && new Date(active.vote_deadline) < new Date();
    box.innerHTML = `
      <div class="round-card">
        <span class="chip chip-accent">Läuft</span>
        <h3 style="margin-top:.5rem">${esc(active.name)}</h3>
        <div class="meta">
          <span>${icon('calendar')} seit ${esc(formatDate(active.starts_at))}</span>
          <span>${icon('clock')} ${active.vote_deadline ? `${closed ? 'Abstimmung beendet' : 'Deadline'} ${esc(formatDateTime(active.vote_deadline))}` : 'ohne Deadline'}</span>
        </div>
        <div class="round-actions">
          <button class="btn btn-primary btn-sm" data-round="complete" data-id="${active.id}">${icon('check')} Abschließen</button>
          <button class="btn btn-sm" data-round="deadline" data-id="${active.id}">${icon('clock')} Deadline</button>
          <button class="btn btn-sm" data-round="guests" data-id="${active.id}">${icon('users')} Gäste</button>
          <button class="btn btn-sm btn-ghost" data-round="rename" data-id="${active.id}">${icon('edit')} Umbenennen</button>
        </div>
      </div>`;
    return;
  }
  const deadline = new Date(Date.now() + 3 * 86400_000);
  const value = `${toBerlinInput(deadline).slice(0, 10)}T20:00`;
  box.innerHTML = `
    <p class="hint" style="margin-bottom:1rem">Gerade läuft keine Runde. Nicht geschaute Filme der letzten Runde werden übernommen.</p>
    <form class="round-form" id="roundForm" novalidate>
      <div class="field"><label for="roundName">Name</label><input class="input" id="roundName" maxlength="100" required></div>
      <div class="field"><label for="roundDeadline">Abstimmung bis (Berliner Zeit)</label><input class="input" type="datetime-local" id="roundDeadline" value="${value}"></div>
      <div class="field"><label for="roundMax">Film fliegt raus nach</label>
        <select class="input" id="roundMax">${[2, 3, 4, 5, 6, 8].map((n) => `<option value="${n}"${n === 4 ? ' selected' : ''}>${n} Runden</option>`).join('')}</select></div>
      <button class="btn btn-primary" type="submit">${icon('plus')} Runde starten</button>
    </form>`;
  const nameInput = $('#roundName');
  const suggestName = () => {
    if (nameInput.dataset.edited) return;
    const v = $('#roundDeadline').value;
    nameInput.value = v ? `Filmabend ${dayName.format(new Date(`${v.slice(0, 10)}T12:00:00Z`))}` : 'Filmabend';
  };
  suggestName();
  nameInput.addEventListener('input', () => { nameInput.dataset.edited = '1'; });
  $('#roundDeadline').addEventListener('change', suggestName);
  $('#roundForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = nameInput.value.trim();
    if (!name) { toast('Bitte einen Namen eingeben', 'err'); return; }
    const deadlineValue = $('#roundDeadline').value;
    if (deadlineValue && deadlineValue < toBerlinInput(new Date())) { toast('Die Deadline liegt in der Vergangenheit', 'err'); return; }
    try {
      await withBusy(e.submitter, () => api.createRound({
        name,
        starts_at: new Date().toISOString(),
        vote_deadline: deadlineValue ? `${deadlineValue}:00` : null,
        max_rounds_before_removal: +$('#roundMax').value,
      }));
      toast('Runde gestartet', 'ok');
      await loadRounds();
    } catch (ex) { toast(ex.message, 'err'); }
  });
}

function renderRoundList() {
  const past = rounds.filter((r) => r.status !== 'active');
  $('#roundList').innerHTML = past.length ? past.map((r) => `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${esc(r.name)}
          ${r.status === 'cancelled' ? '<span class="chip chip-danger">Abgebrochen</span>' : ''}
          ${r.watched_movie_id ? `<span class="chip chip-ok">${icon('check')} Film markiert</span>` : ''}</div>
        <div class="row-sub">${esc(formatDate(r.starts_at))}${r.ends_at ? ` – ${esc(formatDate(r.ends_at))}` : ''}</div>
      </div>
      <div class="row-actions">
        ${r.status === 'completed' && !r.watched_movie_id ? `<button class="btn btn-sm" data-round="watched" data-id="${r.id}">${icon('film')} Film markieren</button>` : ''}
        <button class="btn btn-sm btn-ghost btn-icon" data-round="rename" data-id="${r.id}" aria-label="Umbenennen">${icon('edit')}</button>
      </div>
    </div>`).join('') : '<div class="empty-row">Noch keine abgeschlossenen Runden.</div>';
}

$('#rounds').addEventListener('click', (e) => {
  const b = e.target.closest('[data-round]');
  if (!b) return;
  const round = rounds.find((r) => r.id === +b.dataset.id);
  ({ complete: completeRound, deadline: editDeadline, guests: editGuests, rename: renameRound, watched: markWatched })[b.dataset.round](round);
});

function moviePicker(movies) {
  const sorted = [...movies].sort((a, b) => score(b) - score(a));
  return sorted.length ? `<div class="pick-list">${sorted.map((m) => `
    <button type="button" class="pick" data-pick="${m.id}" aria-pressed="false">
      <span class="pick-poster">${posterUrl(m.poster_path, 'w92') ? `<img src="${posterUrl(m.poster_path, 'w92')}" alt="">` : ''}</span>
      <span class="pick-main"><span class="pick-title">${esc(m.title)}</span>
        <span class="pick-sub">${score(m) > 0 ? '+' : ''}${score(m)} Punkte · ${m.upvotes} ♥ · ${m.superlikes} ★ · ${m.downvotes} ✕</span></span>
      <span class="pick-check">${icon('check')}</span>
    </button>`).join('')}</div>` : '<p class="hint">Keine Filme in dieser Runde.</p>';
}

function bindPicker(dlg) {
  let selected = null;
  $$('[data-pick]', dlg).forEach((p) => p.addEventListener('click', () => {
    const id = +p.dataset.pick;
    selected = selected === id ? null : id;
    $$('[data-pick]', dlg).forEach((x) => x.setAttribute('aria-pressed', String(+x.dataset.pick === selected)));
  }));
  return () => selected;
}

async function completeRound(round) {
  let movies = [];
  try { movies = await api.getMovies(); } catch (e) { toast(e.message, 'err'); return; }
  let getSelected = () => null;
  const dlg = formDialog({
    title: `„${round.name}“ abschließen`,
    body: `<p class="hint" style="margin-bottom:.9rem">Welchen Film habt ihr geschaut? Er kommt in die Gesehen-Liste. Alle anderen wandern in die nächste Runde, die Stimmen werden zurückgesetzt.</p>${moviePicker(movies)}`,
    confirmLabel: 'Abschließen',
    onSubmit: async () => {
      const id = getSelected();
      if (!id) {
        const ok = await confirmDialog({ title: 'Ohne Film abschließen?', text: 'Du kannst den Film später noch markieren.', confirmLabel: 'Ohne Film abschließen' });
        if (!ok) return false;
      }
      await api.completeRound(round.id, id);
      toast('Runde abgeschlossen', 'ok');
      await loadRounds();
    },
  });
  getSelected = bindPicker(dlg);
}

async function markWatched(round) {
  let movies = [];
  try { movies = await api.getMovies(); } catch (e) { toast(e.message, 'err'); return; }
  let getSelected = () => null;
  const dlg = formDialog({
    title: 'Film nachträglich markieren',
    body: `<p class="hint" style="margin-bottom:.9rem">Welcher Film lief bei „${esc(round.name)}“?</p>${moviePicker(movies)}`,
    confirmLabel: 'Markieren',
    onSubmit: async () => {
      const id = getSelected();
      if (!id) { toast('Bitte einen Film auswählen', 'err'); return false; }
      await api.setWatched(round.id, id);
      toast('Film markiert', 'ok');
      await loadRounds();
    },
  });
  getSelected = bindPicker(dlg);
}

function editDeadline(round) {
  const value = round.vote_deadline ? toBerlinInput(new Date(round.vote_deadline)) : '';
  formDialog({
    title: 'Deadline ändern',
    body: `<div class="field"><label for="dlInput">Abstimmung bis (Berliner Zeit)</label>
      <input class="input" type="datetime-local" id="dlInput" value="${value}"><span class="hint">Leer lassen für keine Deadline.</span></div>`,
    onSubmit: async (form) => {
      const v = $('#dlInput', form).value;
      await api.setDeadline(round.id, v ? `${v}:00` : null);
      toast('Deadline gespeichert', 'ok');
      await loadRounds();
    },
  });
}

function renameRound(round) {
  formDialog({
    title: 'Runde umbenennen',
    body: `<div class="field"><label for="rnInput">Name</label><input class="input" id="rnInput" maxlength="100" value="${esc(round.name)}"></div>`,
    onSubmit: async (form) => {
      const name = $('#rnInput', form).value.trim();
      if (!name) { toast('Name darf nicht leer sein', 'err'); return false; }
      await api.renameRound(round.id, name);
      await loadRounds();
    },
  });
}

async function editGuests(round) {
  let current;
  try { [users, current] = await Promise.all([api.getUsers(), api.getRoundGuests(round.id)]); } catch (e) { toast(e.message, 'err'); return; }
  const invited = new Set(current.map((g) => g.user_id));
  const guests = users.filter((u) => !u.is_regular && !u.is_admin && u.is_active);
  const dlg = formDialog({
    title: 'Gäste dieser Runde',
    confirmLabel: '',
    body: guests.length ? `<p class="hint" style="margin-bottom:.9rem">Stammgäste sind immer dabei. Gäste sehen nur Runden, zu denen sie eingeladen sind. Änderungen gelten sofort.</p>
      <div class="pick-list">${guests.map((u) => `
        <button type="button" class="pick" data-guest="${u.id}" aria-pressed="${invited.has(u.id)}">
          <span class="avatar">${esc(initials(u.username))}</span>
          <span class="pick-main"><span class="pick-title">${esc(u.username)}</span></span>
          <span class="pick-check">${icon('check')}</span>
        </button>`).join('')}</div>`
      : '<p class="hint">Es gibt keine Gäste. Erstelle einen Einladungslink vom Typ „Gast“.</p>',
    onSubmit: async () => {},
  });
  $$('[data-guest]', dlg).forEach((b) => b.addEventListener('click', async () => {
    const uid = +b.dataset.guest;
    const on = b.getAttribute('aria-pressed') === 'true';
    try {
      if (on) await api.removeRoundGuest(round.id, uid); else await api.addRoundGuest(round.id, uid);
      b.setAttribute('aria-pressed', String(!on));
    } catch (e) { toast(e.message, 'err'); }
  }));
}

// ── Invites ──────────────────────────────────────────────────────────────
// The token goes into the fragment, so it never shows up in server logs.
const inviteUrl = (token) => `${window.location.origin}/frontend/register.html#token=${encodeURIComponent(token)}`;

async function loadInvites() {
  try { invites = await api.getInvites(); } catch (e) { toast(e.message, 'err'); return; }
  renderInvites();
}

function renderInvites() {
  const list = invites.filter((i) => !hideExpired || (!i.is_used && !i.is_expired));
  $('#inviteList').innerHTML = list.length ? list.map((inv) => {
    const valid = !inv.is_used && !inv.is_expired;
    const status = inv.is_used ? '<span class="chip">Verbraucht</span>' : inv.is_expired ? '<span class="chip chip-danger">Abgelaufen</span>' : '<span class="chip chip-ok">Gültig</span>';
    const uses = inv.max_uses === 0 ? `${inv.use_count} genutzt` : `${inv.use_count}/${inv.max_uses} genutzt`;
    return `
      <div class="row${valid ? '' : ' is-muted'}">
        <div class="row-main">
          <div class="row-title">${inv.label ? esc(inv.label) : `<span class="mono">${esc(inv.token.slice(0, 10))}…</span>`}
            <span class="chip ${inv.invite_type === 'regular' ? 'chip-accent' : ''}">${inv.invite_type === 'regular' ? 'Stammgast' : 'Gast'}</span>${status}</div>
          <div class="row-sub">${uses} · ${valid ? 'gültig bis' : 'lief ab'} ${esc(formatDateTime(inv.expires_at))}</div>
        </div>
        <div class="row-actions">
          ${valid ? `<button class="btn btn-sm" data-inv="copy" data-id="${inv.id}">${icon('copy')} Link</button>` : ''}
          <button class="btn btn-sm btn-ghost btn-icon" data-inv="label" data-id="${inv.id}" aria-label="Label ändern">${icon('edit')}</button>
          <button class="btn btn-sm btn-ghost btn-icon" data-inv="delete" data-id="${inv.id}" aria-label="Löschen">${icon('trash')}</button>
        </div>
      </div>`;
  }).join('') : '<div class="empty-row">Keine Einladungen.</div>';
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Link kopiert', 'ok');
  } catch {
    // Clipboard API needs HTTPS; fall back to selecting the text.
    const input = $('#newLinkInput');
    input.value = text;
    $('#newLink').hidden = false;
    input.select();
    toast('Link markiert – jetzt kopieren', '');
  }
  button?.focus();
}

$('#inviteForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const inv = await withBusy(e.submitter, () => api.createInvite({
      expires_in_hours: +$('#inviteExpiry').value,
      max_uses: +$('#inviteMaxUses').value,
      invite_type: $('#inviteType').value,
      label: $('#inviteLabel').value.trim() || null,
    }));
    $('#inviteLabel').value = '';
    $('#newLinkInput').value = inviteUrl(inv.token);
    $('#newLink').hidden = false;
    $('#newLinkShare').hidden = !navigator.share;
    await loadInvites();
  } catch (ex) { toast(ex.message, 'err'); }
});
$('#newLinkCopy').addEventListener('click', (e) => copyText($('#newLinkInput').value, e.currentTarget));
$('#newLinkShare').addEventListener('click', () => {
  navigator.share({ title: 'Einladung zu movienight', url: $('#newLinkInput').value }).catch(() => {});
});
$('#toggleExpired').addEventListener('click', (e) => {
  hideExpired = !hideExpired;
  e.currentTarget.setAttribute('aria-pressed', String(hideExpired));
  renderInvites();
});

$('#inviteList').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-inv]');
  if (!b) return;
  const inv = invites.find((i) => i.id === +b.dataset.id);
  if (b.dataset.inv === 'copy') return copyText(inviteUrl(inv.token), b);
  if (b.dataset.inv === 'label') {
    formDialog({
      title: 'Label ändern',
      body: `<div class="field"><label for="lbInput">Für wen?</label><input class="input" id="lbInput" maxlength="100" value="${esc(inv.label || '')}"></div>`,
      onSubmit: async (form) => { await api.renameInvite(inv.id, $('#lbInput', form).value.trim() || null); await loadInvites(); },
    });
    return;
  }
  if (b.dataset.inv === 'delete') {
    const ok = await confirmDialog({ title: 'Einladung löschen?', text: 'Der Link funktioniert danach nicht mehr. Bereits angelegte Accounts bleiben.', confirmLabel: 'Löschen', danger: true });
    if (!ok) return;
    try { await api.deleteInvite(inv.id); await loadInvites(); } catch (ex) { toast(ex.message, 'err'); }
  }
});

// ── Users ────────────────────────────────────────────────────────────────
async function loadUsers() {
  try { users = await api.getUsers(); } catch (e) { toast(e.message, 'err'); return; }
  renderUsers();
}

function renderUsers() {
  $('#userCount').textContent = plural(users.length, 'Account', 'Accounts');
  $('#userList').innerHTML = users.map((u) => {
    const self = u.id === me.id;
    const role = u.is_admin ? '<span class="chip chip-accent">Admin</span>' : u.is_regular ? '<span class="chip">Stammgast</span>' : '<span class="chip">Gast</span>';
    return `
      <div class="row${u.is_active ? '' : ' is-muted'}">
        <span class="avatar">${esc(initials(u.username))}</span>
        <div class="row-main">
          <div class="row-title">${esc(u.username)} ${role}${u.is_active ? '' : '<span class="chip chip-danger">Deaktiviert</span>'}${self ? '<span class="chip chip-plain">du</span>' : ''}</div>
          <div class="row-sub">dabei seit ${esc(formatDate(u.created_at))}</div>
        </div>
        ${self ? '' : `<div class="row-actions">
          <select class="input btn-sm" data-user="${u.id}" aria-label="Aktion für ${esc(u.username)}" style="min-height:34px;width:auto">
            <option value="">Aktion …</option>
            ${u.is_admin ? '' : `<option value="toggle-regular">${u.is_regular ? 'Zum Gast machen' : 'Zum Stammgast machen'}</option>`}
            <option value="${u.is_admin ? 'revoke-admin' : 'make-admin'}">${u.is_admin ? 'Adminrechte entziehen' : 'Zum Admin machen'}</option>
            <option value="password">Passwort zurücksetzen</option>
            <option value="${u.is_active ? 'deactivate' : 'activate'}">${u.is_active ? 'Deaktivieren' : 'Wieder aktivieren'}</option>
            <option value="delete">Löschen …</option>
          </select>
        </div>`}
      </div>`;
  }).join('');
}

$('#userList').addEventListener('change', async (e) => {
  const select = e.target.closest('[data-user]');
  if (!select || !select.value) return;
  const action = select.value;
  select.value = '';
  const user = users.find((u) => u.id === +select.dataset.user);
  try {
    if (action === 'password') {
      formDialog({
        title: `Passwort für ${user.username}`,
        body: `<div class="field"><label for="pwInput">Neues Passwort</label><input class="input" id="pwInput" type="text" minlength="8" maxlength="72" autocomplete="off">
          <span class="hint">Mindestens 8 Zeichen. ${esc(user.username)} wird auf allen Geräten abgemeldet.</span></div>`,
        onSubmit: async (form) => {
          const pw = $('#pwInput', form).value;
          if (pw.length < 8) { toast('Mindestens 8 Zeichen', 'err'); return false; }
          await api.resetPassword(user.id, pw);
          toast('Passwort geändert', 'ok');
        },
      });
      return;
    }
    if (action === 'delete') {
      const ok = await confirmDialog({
        title: `${user.username} löschen?`,
        text: 'Vorschläge, Stimmen und Kommentare werden entfernt. Bereits geschaute Filme bleiben in der Historie.',
        confirmLabel: 'Endgültig löschen', danger: true,
      });
      if (!ok) return;
      await api.deleteUser(user.id);
      toast(`${user.username} gelöscht`, 'ok');
    } else {
      if (action === 'deactivate' || action === 'make-admin') {
        const ok = await confirmDialog({
          title: action === 'deactivate' ? `${user.username} deaktivieren?` : `${user.username} zum Admin machen?`,
          text: action === 'deactivate' ? 'Der Account wird sofort abgemeldet und kann sich nicht mehr anmelden.' : 'Admins können Runden, Einladungen und alle Accounts verwalten.',
          confirmLabel: action === 'deactivate' ? 'Deaktivieren' : 'Zum Admin machen',
          danger: action === 'deactivate',
        });
        if (!ok) return;
      }
      await api.userAction(user.id, action);
    }
    await loadUsers();
  } catch (ex) { toast(ex.message, 'err'); }
});

boot();
