// Swipe tab: rate the movies of the round one card at a time.
//
// Right = like, left = nope, up = superlike. Cards can be skipped (they come
// back at the end) and every decision can be undone. Votes go through the
// shared store, so the grid stays in sync.
import * as store from './store.js';
import { state } from './store.js';
import { $, $$, esc, genreList, icon, plural, posterUrl, safeTrailer, toast, vibrate } from './ui.js';

const STACK = 3; // cards rendered at once
const FLY_MS = 280;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

const s = {
  root: null,
  openDetail: null,
  queue: [], // movie ids
  idx: 0,
  history: [], // {id, kind: 'vote'|'skip', type, prev}
  stats: { up: 0, down: 0, superlike: 0 },
  replay: false, // going through already rated movies again
  busy: false,
  expanded: false,
  mounted: false,
};

export function showSwipe(root, { openDetail }) {
  s.root = root;
  s.openDetail = openDetail;
  if (!s.mounted) {
    s.mounted = true;
    store.subscribe(onStoreChange);
    document.addEventListener('keydown', onKey);
  }
  start(false);
}

function start(replay) {
  s.replay = replay;
  s.queue = (replay ? state.movies.filter((m) => !m.read_only) : store.unvotedMovies()).map((m) => m.id);
  s.idx = 0;
  s.history = [];
  s.stats = { up: 0, down: 0, superlike: 0 };
  s.expanded = false;
  render();
}

const isActive = () => s.root && s.root.closest('.view')?.classList.contains('is-active');
const current = () => store.findMovie(s.queue[s.idx]);

// New proposals that arrive while swiping are added to the end of the deck.
function onStoreChange() {
  if (!isActive() || s.busy) return;
  const known = new Set(s.queue);
  const fresh = store.unvotedMovies().filter((m) => !known.has(m.id)).map((m) => m.id);
  // Drop cards whose movie was removed in the meantime.
  const before = s.queue.length;
  s.queue = s.queue.filter((id, i) => i < s.idx || store.findMovie(id));
  if (fresh.length || s.queue.length !== before) {
    s.queue.push(...fresh);
    render();
  } else {
    renderControls();
  }
}

// ── Rendering ────────────────────────────────────────────────────────────
function render() {
  const root = s.root;
  if (!root) return;

  if (state.noAccess) return renderEmpty('ticket', 'Noch keine Einladung', 'Für die aktuelle Runde bist du nicht eingeladen.');
  if (!state.round) return renderEmpty('calendar', 'Gerade läuft keine Runde', 'Sobald die nächste Runde startet, kannst du hier swipen.');
  if (!store.votingOpen()) return renderEmpty('clock', 'Abstimmung geschlossen', 'Die Deadline ist vorbei. Das Ergebnis siehst du im Ranking.', true);
  if (!state.movies.length) return renderEmpty('film', 'Noch keine Vorschläge', 'Sobald jemand einen Film vorschlägt, kannst du hier abstimmen.');
  if (s.idx >= s.queue.length) return renderDone();

  const total = s.queue.length;
  root.innerHTML = `
    <div class="swipe-head">
      <div class="swipe-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${s.idx}"
        aria-label="Fortschritt"><span style="width:${(s.idx / total) * 100}%"></span></div>
      <div class="swipe-count"><strong>${s.idx + 1}</strong> / ${total}${s.replay ? ' · Nochmal' : ''}</div>
    </div>
    <div class="deck" id="deck" aria-live="polite">${deckCards()}</div>
    <div class="swipe-controls" id="swipeControls">
      <button class="sbtn sbtn-sm" data-act="undo" aria-label="Rückgängig (Rücktaste)" title="Rückgängig">${icon('undo')}</button>
      <button class="sbtn sbtn-lg sbtn-nope" data-act="down" aria-label="Nope (Pfeil links)" title="Nope">${icon('x')}</button>
      <button class="sbtn sbtn-md sbtn-super" data-act="superlike" aria-label="Superlike (Pfeil hoch)" title="Superlike">${icon('star')}</button>
      <button class="sbtn sbtn-lg sbtn-like" data-act="up" aria-label="Like (Pfeil rechts)" title="Like">${icon('heart')}</button>
      <button class="sbtn sbtn-sm" data-act="skip" aria-label="Später (Pfeil runter)" title="Später">${icon('skip')}</button>
    </div>
    <p class="swipe-hint hide-touch">Pfeiltasten zum Abstimmen · ↓ später · ⌫ rückgängig · Leertaste Infos</p>`;

  $$('[data-act]', root).forEach((b) => b.addEventListener('click', () => onControl(b.dataset.act)));
  renderControls();
  attachDrag($('.card.is-top', root));
}

function deckCards() {
  const ids = s.queue.slice(s.idx, s.idx + STACK);
  // Last in DOM order is on top.
  return ids.map((id, depth) => cardHtml(store.findMovie(id), depth)).reverse().join('');
}

function cardHtml(m, depth) {
  if (!m) return '';
  const poster = posterUrl(m.poster_path, 'w780');
  const genres = genreList(m.genres).slice(0, 3);
  const trailer = safeTrailer(m.trailer_url);
  const prev = s.replay && m.user_vote ? { up: 'Like', down: 'Nope', superlike: 'Superlike' }[m.user_vote] : '';
  return `
    <article class="card${depth === 0 ? ' is-top' : ''}${depth === 0 && s.expanded ? ' is-expanded' : ''}" data-id="${m.id}" data-depth="${depth}"
      ${depth === 0 ? `tabindex="0" aria-label="${esc(m.title)}"` : 'aria-hidden="true"'}>
      ${poster
        ? `<img class="card-poster" src="${poster}" alt="" draggable="false" ${depth > 1 ? 'loading="lazy"' : ''}>`
        : `<div class="card-poster card-poster-fallback">${icon('film')}</div>`}
      <div class="card-shade"></div>
      <div class="stamp stamp-like" aria-hidden="true">${icon('heart')} Dabei</div>
      <div class="stamp stamp-nope" aria-hidden="true">${icon('x')} Nö</div>
      <div class="stamp stamp-super" aria-hidden="true">${icon('star')} Super</div>
      <div class="card-info">
        <div class="card-tags">
          ${m.release_year ? `<span class="chip">${m.release_year}</span>` : ''}
          ${genres.map((g) => `<span class="chip">${esc(g)}</span>`).join('')}
          ${m.superlikes > 0 ? `<span class="chip chip-super">${icon('star')} ${m.superlikes}</span>` : ''}
        </div>
        <h2 class="card-title">${esc(m.title)}</h2>
        <div class="card-by">${icon('user')} ${esc(m.submitted_by_username)}${prev ? ` · deine Stimme: ${prev}` : ''}</div>
        ${m.overview ? `<p class="card-overview">${esc(m.overview)}</p>` : ''}
        <div class="card-actions">
          <button class="card-btn" data-card="info">${icon('info')} <span>${s.expanded && depth === 0 ? 'Weniger' : 'Mehr'}</span></button>
          <button class="card-btn" data-card="detail">${icon('msg')} ${m.comment_count || ''}</button>
          ${trailer ? `<a class="card-btn card-btn-trailer" href="${esc(trailer)}" target="_blank" rel="noopener noreferrer">${icon('play')} Trailer</a>` : ''}
        </div>
      </div>
    </article>`;
}

function renderControls() {
  const box = $('#swipeControls', s.root || document);
  if (!box) return;
  const m = current();
  const superBlocked = !store.superlikeAvailable() && m?.user_vote !== 'superlike';
  const sup = $('[data-act="superlike"]', box);
  sup.disabled = superBlocked;
  sup.title = superBlocked ? 'Superlike schon vergeben' : 'Superlike';
  $('[data-act="undo"]', box).disabled = s.history.length === 0;
  $('[data-act="skip"]', box).disabled = s.queue.length - s.idx < 2;
}

function renderEmpty(iconName, title, text, toRanking = false) {
  s.root.innerHTML = `<div class="empty swipe-empty"><div class="empty-icon">${icon(iconName)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>
    ${toRanking ? `<a class="btn" href="app.html">${icon('trophy')} Zum Ranking</a>` : ''}</div>`;
}

function renderDone() {
  const { up, down, superlike } = s.stats;
  const rated = up + down + superlike;
  const unvoted = store.unvotedMovies().length;
  s.root.innerHTML = `
    <div class="swipe-done">
      <div class="done-burst" aria-hidden="true">${icon(rated ? 'sparkles' : 'check')}</div>
      <h2>${rated ? 'Stapel geschafft!' : 'Alles bewertet'}</h2>
      <p>${rated ? `Du hast ${plural(rated, 'Film', 'Filme')} bewertet.` : 'Für alle Filme dieser Runde hast du schon abgestimmt.'}
        ${unvoted ? ` ${plural(unvoted, 'Film ist', 'Filme sind')} noch offen.` : ''}</p>
      ${rated ? `<div class="done-stats">
        <span class="done-stat like">${icon('heart')}<strong>${up}</strong>Likes</span>
        <span class="done-stat super">${icon('star')}<strong>${superlike}</strong>Super</span>
        <span class="done-stat nope">${icon('x')}<strong>${down}</strong>Nope</span>
      </div>` : ''}
      <div class="done-actions">
        <a class="btn btn-primary" href="app.html">${icon('trophy')} Zum Ranking</a>
        ${unvoted ? `<button class="btn" data-done="unvoted">${icon('cards')} Offene swipen</button>` : ''}
        <button class="btn btn-ghost" data-done="replay">${icon('refresh')} Alle nochmal</button>
        ${s.history.length ? `<button class="btn btn-ghost" data-done="undo">${icon('undo')} Letzte rückgängig</button>` : ''}
      </div>
    </div>`;
  $('[data-done="replay"]', s.root).addEventListener('click', () => start(true));
  $('[data-done="unvoted"]', s.root)?.addEventListener('click', () => start(false));
  $('[data-done="undo"]', s.root)?.addEventListener('click', undo);
}

// ── Input ────────────────────────────────────────────────────────────────
function onControl(act) {
  if (act === 'undo') return undo();
  if (act === 'skip') return skip();
  decide(act);
}

function onKey(e) {
  if (!isActive() || document.querySelector('dialog[open]')) return;
  if (e.target.closest('input, textarea, select')) return;
  const map = { ArrowRight: 'up', ArrowLeft: 'down', ArrowUp: 'superlike' };
  if (map[e.key]) { e.preventDefault(); decide(map[e.key]); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); skip(); }
  else if (e.key === 'Backspace' || (e.key === 'z' && (e.ctrlKey || e.metaKey))) { e.preventDefault(); undo(); }
  else if (e.key === ' ') { e.preventDefault(); toggleExpanded(); }
  else if (e.key === 'Enter') { const m = current(); if (m) s.openDetail(m.id); }
}

function toggleExpanded() {
  const card = $('.card.is-top', s.root);
  if (!card) return;
  s.expanded = !s.expanded;
  card.classList.toggle('is-expanded', s.expanded);
  const label = $('[data-card="info"] span', card);
  if (label) label.textContent = s.expanded ? 'Weniger' : 'Mehr';
}

function attachDrag(card) {
  if (!card) return;
  const deck = $('#deck', s.root);
  let start = null;
  let last = null;
  let dx = 0;
  let dy = 0;

  $('[data-card="info"]', card).addEventListener('click', (e) => { e.stopPropagation(); toggleExpanded(); });
  $('[data-card="detail"]', card).addEventListener('click', (e) => { e.stopPropagation(); s.openDetail(+card.dataset.id); });

  card.addEventListener('pointerdown', (e) => {
    if (s.busy || e.button > 0 || e.target.closest('a, button')) return;
    const rect = card.getBoundingClientRect();
    start = { x: e.clientX, y: e.clientY, t: performance.now(), fromTop: e.clientY - rect.top < rect.height / 2 };
    last = { x: e.clientX, y: e.clientY, t: start.t, vx: 0, vy: 0 };
    dx = dy = 0;
    card.setPointerCapture(e.pointerId);
    card.classList.add('is-dragging');
  });

  card.addEventListener('pointermove', (e) => {
    if (!start) return;
    const now = performance.now();
    const dt = Math.max(1, now - last.t);
    last = { x: e.clientX, y: e.clientY, t: now, vx: (e.clientX - last.x) / dt, vy: (e.clientY - last.y) / dt };
    dx = e.clientX - start.x;
    dy = e.clientY - start.y;
    // Grabbing the lower half tilts the other way, like a real card.
    const rot = (dx / card.offsetWidth) * 18 * (start.fromTop ? 1 : -1);
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${rot}deg)`;
    showIntent(card, deck, intentFor(card, dx, dy, 0, 0));
  });

  const end = () => {
    if (!start) return;
    const moved = Math.hypot(dx, dy);
    const quickTap = moved < 6 && performance.now() - start.t < 350;
    const decision = intentFor(card, dx, dy, last.vx, last.vy, true);
    start = null;
    card.classList.remove('is-dragging');
    if (quickTap) { resetCard(card, deck); toggleExpanded(); return; }
    if (decision) decide(decision, { fromDrag: true });
    else resetCard(card, deck);
  };
  card.addEventListener('pointerup', end);
  card.addEventListener('pointercancel', () => { start = null; card.classList.remove('is-dragging'); resetCard(card, deck); });
}

// Which way the card is heading: distance or a quick flick both count.
function intentFor(card, dx, dy, vx, vy, final = false) {
  const w = card.offsetWidth;
  const h = card.offsetHeight;
  const flick = final ? 0.55 : Infinity;
  if (-dy > Math.abs(dx) && (-dy > h * 0.22 || (-vy > flick && -dy > 30))) return 'superlike';
  if (dx > w * 0.3 || (vx > flick && dx > 30)) return 'up';
  if (-dx > w * 0.3 || (-vx > flick && -dx > 30)) return 'down';
  if (!final) {
    // Preview direction before the threshold is reached.
    if (-dy > Math.abs(dx) && -dy > 20) return { hint: 'superlike', p: Math.min(1, -dy / (h * 0.22)) };
    if (Math.abs(dx) > 20) return { hint: dx > 0 ? 'up' : 'down', p: Math.min(1, Math.abs(dx) / (w * 0.3)) };
  }
  return null;
}

function showIntent(card, deck, intent) {
  const kind = typeof intent === 'string' ? intent : intent?.hint;
  const p = typeof intent === 'string' ? 1 : intent?.p || 0;
  $('.stamp-like', card).style.opacity = kind === 'up' ? p : 0;
  $('.stamp-nope', card).style.opacity = kind === 'down' ? p : 0;
  $('.stamp-super', card).style.opacity = kind === 'superlike' ? p : 0;
  card.dataset.intent = p >= 1 ? kind : '';
  $$('[data-act]', s.root).forEach((b) => b.classList.toggle('is-hot', p >= 1 && b.dataset.act === kind));
  // The next card rises as the top card leaves.
  const next = $('.card[data-depth="1"]', deck);
  if (next) next.style.setProperty('--lift', String(kind ? p : 0));
}

function resetCard(card, deck) {
  card.style.transform = '';
  showIntent(card, deck, null);
}

// ── Actions ──────────────────────────────────────────────────────────────
async function decide(type, { fromDrag = false } = {}) {
  const m = current();
  if (!m || s.busy) return;
  const card = $('.card.is-top', s.root);
  const deck = $('#deck', s.root);

  if (type === 'superlike' && m.user_vote !== 'superlike' && !store.superlikeAvailable()) {
    if (card) {
      resetCard(card, deck);
      card.classList.remove('is-shaking');
      void card.offsetWidth;
      card.classList.add('is-shaking');
    }
    vibrate([30, 40, 30]);
    toast('Dein Superlike ist schon vergeben. Nimm ihn erst woanders zurück.', 'err');
    return;
  }

  s.busy = true;
  vibrate(type === 'superlike' ? [15, 30, 15] : 12);
  if (card) {
    if (!fromDrag) showIntent(card, deck, type);
    card.classList.add('is-leaving', `leave-${type}`);
    card.style.transform = '';
  }

  const prev = m.user_vote;
  // Re-rating with the same vote changes nothing (sending it would remove it).
  const request = prev === type ? Promise.resolve(true) : store.castVote(m.id, type);
  const advance = new Promise((r) => setTimeout(r, reducedMotion.matches ? 0 : FLY_MS));

  try {
    await Promise.all([request, advance]);
    s.history.push({ id: m.id, kind: 'vote', type, prev });
    s.stats[type] += 1;
    s.idx += 1;
  } catch (e) {
    await advance;
    toast(e.message, 'err');
  } finally {
    s.busy = false;
    s.expanded = false;
    render();
  }
}

function skip() {
  if (s.busy || s.queue.length - s.idx < 2) return;
  const id = s.queue[s.idx];
  const card = $('.card.is-top', s.root);
  s.busy = true;
  card?.classList.add('is-leaving', 'leave-skip');
  setTimeout(() => {
    s.queue.push(id);
    s.history.push({ id, kind: 'skip' });
    s.idx += 1;
    s.busy = false;
    s.expanded = false;
    render();
  }, reducedMotion.matches ? 0 : FLY_MS);
}

async function undo() {
  const last = s.history.at(-1);
  if (!last || s.busy) return;
  s.busy = true;
  try {
    if (last.kind === 'vote') {
      const m = store.findMovie(last.id);
      if (m && m.user_vote !== last.prev) {
        // Same type again removes the vote; otherwise restore the previous one.
        await store.castVote(last.id, last.prev || last.type);
      }
      s.stats[last.type] -= 1;
    } else {
      s.queue.pop();
    }
    s.history.pop();
    s.idx -= 1;
    vibrate(8);
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    s.busy = false;
    render();
    $('.card.is-top', s.root)?.classList.add('is-returning');
  }
}
