import * as api from './api.js';
import * as store from './store.js';
import { state } from './store.js';
import { showSwipe } from './swipe.js';
import {
  $, $$, confirmDialog, esc, formatDate, formatDateTime, formatRemaining, genreList, icon, initials, openDialog,
  plural, posterUrl, relativeTime, safeTrailer, score, setupDialog, signed, toast, withBusy,
} from './ui.js';

const ui = { sort: 'rank', genre: '', unvotedOnly: false, view: 'movies', detailId: null };
let watched = null; // list from /movies/watched, loaded lazily
let watchedTmdbIds = new Set();

// ── Boot ─────────────────────────────────────────────────────────────────
async function boot() {
  if (!api.getToken()) { window.location.replace('index.html'); return; }
  renderSkeleton();
  try {
    await store.init();
  } catch (e) {
    $('#movieGrid').innerHTML = emptyState('x', 'Laden fehlgeschlagen', e.message, '<button class="btn" id="retryBtn">Erneut versuchen</button>');
    $('#retryBtn').addEventListener('click', () => window.location.reload());
    return;
  }
  setupAccount();
  store.subscribe(render);
  render();
  loadWatched().catch(() => {});
  showView(viewFromHash(), { replace: true });
  setInterval(tickDeadline, 1000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') store.refresh().catch(() => {});
  });
}

// ── Rendering ────────────────────────────────────────────────────────────
function render() {
  renderHero();
  renderGrid();
  renderFab();
  renderSwipeBadge();
  if (ui.detailId !== null) renderDetailVotes();
}

function renderSkeleton() {
  $('#movieGrid').innerHTML = Array.from({ length: 6 }, () => '<div class="skeleton skeleton-card"></div>').join('');
}

function emptyState(iconName, title, text, extra = '') {
  return `<div class="empty"><div class="empty-icon">${icon(iconName)}</div><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ''}${extra}</div>`;
}

function deadlineInfo() {
  const r = state.round;
  if (!r || !r.vote_deadline) return null;
  const ms = new Date(r.vote_deadline).getTime() - Date.now();
  return { ms, closed: ms <= 0, urgent: ms > 0 && ms < 3600_000, at: formatDateTime(r.vote_deadline) };
}

function deadlineHtml() {
  const d = deadlineInfo();
  if (!d) return '<div class="hero-deadline"><span class="label">Abstimmung</span><strong>offen</strong><small>ohne Deadline</small></div>';
  if (d.closed) return `<div class="hero-deadline is-closed"><span class="label">Abstimmung</span><strong>geschlossen</strong><small>seit ${esc(d.at)}</small></div>`;
  return `<div class="hero-deadline${d.urgent ? ' is-urgent' : ''}"><span class="label">Abstimmung endet in</span><strong id="countdown">${formatRemaining(d.ms)}</strong><small>${esc(d.at)}</small></div>`;
}

let lastClosed = null;
function tickDeadline() {
  const d = deadlineInfo();
  if (!d) return;
  if (lastClosed !== null && d.closed !== lastClosed) store.emit(); // deadline just passed
  lastClosed = d.closed;
  const el = $('#countdown');
  if (el && !d.closed) {
    el.textContent = formatRemaining(d.ms);
    el.parentElement.classList.toggle('is-urgent', d.urgent);
  }
}

function renderHero() {
  const hero = $('#roundHero');
  if (state.noAccess) { hero.innerHTML = ''; return; }
  if (!state.round) {
    hero.innerHTML = store.isArchive()
      ? `<div class="hero is-archive"><div class="hero-eyebrow">Gerade keine Runde</div>
           <div class="hero-title">Das war der letzte Filmabend</div>
           <div class="hero-stats"><span class="hero-stat">${icon('info')} Neue Vorschläge gibt es, sobald die nächste Runde startet.</span></div></div>`
      : '';
    return;
  }
  const movies = state.movies;
  const voted = movies.filter((m) => m.user_vote).length;
  const left = store.proposalsLeft();
  const max = state.config.max_movies_per_user;
  const quota = state.me.is_admin ? '' : `<span class="hero-stat"><span class="quota-dots" aria-hidden="true">${
    Array.from({ length: max }, (_, i) => `<i class="${i < max - left ? 'on' : ''}"></i>`).join('')
  }</span>${left > 0 ? `${left} von ${max} Vorschlägen frei` : 'Alle Vorschläge vergeben'}</span>`;
  const superStat = store.superlikeAvailable()
    ? `<span class="hero-stat">${icon('star')} Superlike frei</span>`
    : `<span class="hero-stat">${icon('star')} Superlike vergeben</span>`;
  const unvoted = store.unvotedMovies().length;
  const pct = movies.length ? Math.round((voted / movies.length) * 100) : 0;
  const cta = store.votingOpen() && unvoted > 0
    ? `<div class="hero-cta"><span>Noch ${plural(unvoted, 'Film', 'Filme')} ohne deine Stimme</span>
         <button class="btn btn-sm btn-primary" data-goto="swipe">${icon('cards')} Swipen</button></div>`
    : '';
  hero.innerHTML = `
    <div class="hero">
      <div class="hero-top">
        <div><div class="hero-eyebrow">Filmabend</div><div class="hero-title">${esc(state.round.name)}</div></div>
        ${deadlineHtml()}
      </div>
      <div class="hero-stats">
        <span class="hero-stat">${icon('film')} ${plural(movies.length, 'Film', 'Filme')}</span>
        <span class="hero-stat">${icon('check')} ${voted}/${movies.length} bewertet</span>
        ${superStat}${quota}
      </div>
      ${movies.length ? `<div class="hero-progress" aria-hidden="true"><span style="width:${pct}%"></span></div>` : ''}
      ${cta}
    </div>`;
  lastClosed = deadlineInfo()?.closed ?? null;
}

function visibleMovies() {
  let list = [...state.movies];
  if (ui.genre) list = list.filter((m) => genreList(m.genres).includes(ui.genre));
  if (ui.unvotedOnly) list = list.filter((m) => !m.user_vote);
  if (ui.sort === 'rank') {
    list.sort((a, b) => score(b) - score(a) || b.superlikes - a.superlikes || a.title.localeCompare(b.title, 'de'));
  } else if (ui.sort === 'new') {
    list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  } else {
    list.sort((a, b) => a.title.localeCompare(b.title, 'de'));
  }
  return list;
}

function rankMap() {
  // Ranks always follow the score, whatever the current sorting.
  const ranked = [...state.movies].sort((a, b) => score(b) - score(a) || b.superlikes - a.superlikes);
  const map = new Map();
  ranked.forEach((m, i) => { if (i < 3 && score(m) > 0) map.set(m.id, i + 1); });
  return map;
}

// Movies without poster get one of a few tinted placeholders, stable per title.
function fallbackTone(title = '') {
  let h = 0;
  for (const ch of title) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h % 5;
}

function posterBlock(m, size = 'w342', cls = 'mposter') {
  const url = posterUrl(m.poster_path, size);
  return `<div class="${cls}">${url
    ? `<img src="${url}" alt="" loading="lazy" decoding="async">`
    : `<div class="poster-fallback fb-${fallbackTone(m.title)}">${icon('film')}</div>`}</div>`;
}

function voteButtons(m, { large = false } = {}) {
  const disabled = !store.votingOpen() || m.read_only;
  const superBlocked = !store.superlikeAvailable() && m.user_vote !== 'superlike';
  const btn = (type, cls, iconName, count, label) => `
    <button class="vote ${cls}" data-vote="${type}" data-id="${m.id}" aria-pressed="${m.user_vote === type}"
      aria-label="${label} (${count})" ${disabled || (type === 'superlike' && superBlocked) ? 'disabled' : ''}
      ${type === 'superlike' && superBlocked && !disabled ? 'title="Superlike schon vergeben"' : ''}>
      ${icon(iconName)}<span>${count}</span></button>`;
  const s = score(m);
  return `${btn('up', 'like', 'heart', m.upvotes, 'Like')}${btn('down', 'nope', 'dislike', m.downvotes, 'Nope')}${btn('superlike', 'super', 'star', m.superlikes, 'Superlike')}
    <span class="score ${s > 0 ? 'pos' : s < 0 ? 'neg' : ''}" title="Punkte: Like +1, Superlike +3, Nope −1"${large ? '' : ' aria-hidden="true"'}>${signed(s)}</span>`;
}

function renderGrid() {
  const grid = $('#movieGrid');
  $('#toolbar').hidden = state.noAccess || state.movies.length < 2;
  populateGenres();

  if (state.noAccess) {
    grid.innerHTML = emptyState('ticket', 'Noch keine Einladung', 'Für die aktuelle Runde bist du nicht eingeladen. Sobald dich jemand einlädt, siehst du hier die Vorschläge.');
    return;
  }
  if (!state.movies.length) {
    grid.innerHTML = state.round
      ? emptyState('film', 'Noch keine Vorschläge', 'Schlag den ersten Film für diese Runde vor.',
        store.votingOpen() && store.proposalsLeft() > 0 ? `<button class="btn btn-primary" data-action="add">${icon('plus')} Film vorschlagen</button>` : '')
      : emptyState('calendar', 'Gerade läuft keine Runde', 'Sobald die nächste Runde startet, kannst du hier Filme vorschlagen und abstimmen.');
    return;
  }

  const ranks = rankMap();
  const list = visibleMovies();
  const archive = store.isArchive() ? `<div class="notice">${icon('clock')} Letzte Runde, nur zur Ansicht</div>` : '';
  if (!list.length) {
    grid.innerHTML = archive + emptyState('check', 'Alles bewertet', 'Für diesen Filter gibt es keine Filme mehr.');
    return;
  }
  grid.innerHTML = archive + list.map((m) => {
    const rank = ranks.get(m.id);
    const meta = [m.release_year, genreList(m.genres)[0]].filter(Boolean).join(' · ');
    const isNew = !m.read_only && Date.now() - new Date(m.created_at).getTime() < 24 * 3600_000 && m.rounds_survived === 0;
    return `
      <article class="mcard${m.superlikes > 0 ? ' is-super' : ''}">
        <button class="mcard-open" data-open="${m.id}" aria-label="${esc(m.title)} – Details">
          ${posterBlock(m)}
          ${rank ? `<span class="rank rank-${rank}" aria-label="Platz ${rank}">${rank}</span>` : ''}
          <span class="badges">
            ${m.superlikes > 0 ? `<span class="badge badge-super">${icon('star')}${m.superlikes}</span>` : ''}
            ${m.comment_count > 0 ? `<span class="badge">${icon('msg')}${m.comment_count}</span>` : ''}
            ${isNew ? '<span class="badge badge-new">Neu</span>' : ''}
            ${m.rounds_survived > 0 ? `<span class="badge" title="Aus früheren Runden übernommen">${icon('refresh')}${m.rounds_survived}</span>` : ''}
          </span>
          <span class="mcard-meta">
            <span class="mcard-title">${esc(m.title)}</span>
            <span class="mcard-sub">${esc(meta || `von ${m.submitted_by_username}`)}</span>
          </span>
        </button>
        <div class="mcard-foot">${voteButtons(m)}</div>
      </article>`;
  }).join('');
}

function populateGenres() {
  const select = $('#genreSelect');
  const genres = [...new Set(state.movies.flatMap((m) => genreList(m.genres)))].sort((a, b) => a.localeCompare(b, 'de'));
  const html = '<option value="">Alle Genres</option>' + genres.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
  if (select.dataset.html !== html) {
    select.innerHTML = html;
    select.dataset.html = html;
    if (!genres.includes(ui.genre)) ui.genre = '';
    select.value = ui.genre;
  }
}

function fabState() {
  if (state.noAccess || !state.round) return { show: false };
  if (!store.votingOpen()) return { show: true, disabled: 'Die Abstimmung ist geschlossen' };
  if (store.proposalsLeft() <= 0) return { show: true, disabled: `Du hast schon ${state.config.max_movies_per_user} Filme vorgeschlagen` };
  return { show: true };
}

function renderFab() {
  const fab = $('#fab');
  const s = fabState();
  fab.hidden = !s.show || ui.view !== 'movies';
  fab.setAttribute('aria-disabled', s.disabled ? 'true' : 'false');
  fab.title = s.disabled || '';
}

function renderSwipeBadge() {
  const n = store.votingOpen() ? store.unvotedMovies().length : 0;
  const badge = $('#swipeBadge');
  badge.hidden = n === 0;
  badge.textContent = n > 9 ? '9+' : String(n);
}

// ── Interactions: grid ───────────────────────────────────────────────────
$('#movieGrid').addEventListener('click', (e) => {
  const voteBtn = e.target.closest('[data-vote]');
  if (voteBtn) { handleVote(+voteBtn.dataset.id, voteBtn.dataset.vote, voteBtn); return; }
  const open = e.target.closest('[data-open]');
  if (open) { openDetail(+open.dataset.open); return; }
  if (e.target.closest('[data-action="add"]')) openAdd();
});
$('#roundHero').addEventListener('click', (e) => {
  const go = e.target.closest('[data-goto]');
  if (go) showView(go.dataset.goto);
});

async function handleVote(id, type, button = null) {
  try {
    await store.castVote(id, type);
    if (button) {
      const fresh = $(`[data-vote="${type}"][data-id="${id}"]`, button.closest('.mcard-foot, .detail-votes') || document);
      fresh?.classList.add('is-pop');
    }
  } catch (e) {
    toast(e.message, 'err');
    store.refresh().catch(() => {});
  }
}

$$('[data-sort]').forEach((b) => b.addEventListener('click', () => {
  ui.sort = b.dataset.sort;
  $$('[data-sort]').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
  renderGrid();
}));
$('#genreSelect').addEventListener('change', (e) => { ui.genre = e.target.value; renderGrid(); });
$('#unvotedOnly').addEventListener('click', (e) => {
  ui.unvotedOnly = !ui.unvotedOnly;
  e.currentTarget.setAttribute('aria-pressed', String(ui.unvotedOnly));
  renderGrid();
});

// ── Views and tabs ───────────────────────────────────────────────────────
const VIEWS = ['movies', 'swipe', 'watched'];
const viewFromHash = () => (VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'movies');

function showView(view, { replace = false } = {}) {
  ui.view = view;
  $$('.tabbar [role="tab"]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.view === view)));
  $$('.view').forEach((v) => v.classList.toggle('is-active', v.id === `view${view[0].toUpperCase()}${view.slice(1)}`));
  const hash = view === 'movies' ? location.pathname : `#${view}`;
  if (replace) history.replaceState(null, '', hash); else history.pushState(null, '', hash);
  renderFab();
  if (view === 'swipe') showSwipe($('#swipe'), { openDetail });
  if (view === 'watched') renderWatched();
  window.scrollTo({ top: 0 });
}
$$('.tabbar [role="tab"]').forEach((t) => t.addEventListener('click', () => showView(t.dataset.view)));
window.addEventListener('popstate', () => showView(viewFromHash(), { replace: true }));

// ── Detail sheet ─────────────────────────────────────────────────────────
const detailDialog = setupDialog($('#detailDialog'), { onClose: () => { ui.detailId = null; } });

function openDetail(id) {
  const m = store.findMovie(id);
  if (!m) return;
  ui.detailId = id;
  const backdrop = posterUrl(m.poster_path, 'w500');
  const trailer = safeTrailer(m.trailer_url);
  const canRemove = state.me.is_admin || (m.submitted_by === state.me.id && !m.read_only);
  const superBy = m.superlike_usernames.length
    ? `<span class="chip chip-super">${icon('star')} ${esc(m.superlike_usernames.join(', '))}</span>` : '';

  $('#detailContent').innerHTML = `
    <button class="close-btn detail-close" data-close aria-label="Schließen">${icon('x')}</button>
    <div class="detail-scroll">
      <div class="detail-hero">
        ${backdrop ? `<div class="detail-backdrop" style="background-image:url('${backdrop}')"></div>` : ''}
        ${posterBlock(m, 'w342', 'detail-poster')}
        <div class="detail-head">
          <h2 id="detailTitle">${esc(m.title)}</h2>
          <div class="chips">
            ${m.release_year ? `<span class="chip">${m.release_year}</span>` : ''}
            ${genreList(m.genres).map((g) => `<span class="chip">${esc(g)}</span>`).join('')}
            ${superBy}
          </div>
        </div>
      </div>
      <div class="detail-body">
        <div class="detail-votes" id="detailVotes"></div>
        ${m.overview ? `<p class="detail-overview">${esc(m.overview)}</p>` : ''}
        <div class="detail-facts">
          <span>Vorgeschlagen von <strong>${esc(m.submitted_by_username)}</strong></span>
          ${m.rounds_survived > 0 ? `<span>Seit <strong>${plural(m.rounds_survived + 1, 'Runde', 'Runden')}</strong> dabei</span>` : ''}
        </div>
        ${trailer || canRemove ? `<div class="detail-actions">
          ${trailer ? `<a class="btn btn-trailer" href="${esc(trailer)}" target="_blank" rel="noopener noreferrer">${icon('play')} Trailer</a>` : ''}
          ${canRemove ? `<button class="btn btn-danger" id="removeBtn">${icon('trash')} Entfernen</button>` : ''}
        </div>` : ''}
        <section class="comments" aria-labelledby="commentsTitle">
          <h3 id="commentsTitle">Kommentare</h3>
          <div class="comment-list" id="commentList"><div class="skeleton" style="height:44px"></div></div>
          <form class="comment-form" id="commentForm">
            <label class="sr-only" for="commentInput">Kommentar</label>
            <textarea class="input" id="commentInput" rows="1" maxlength="1000" placeholder="Was denkst du über den Film?"></textarea>
            <button class="btn btn-primary" type="submit" aria-label="Senden">${icon('send')}</button>
          </form>
        </section>
      </div>
    </div>`;

  $$('[data-close]', detailDialog).forEach((b) => b.addEventListener('click', () => detailDialog.close()));
  $('#detailVotes').addEventListener('click', (e) => {
    const b = e.target.closest('[data-vote]');
    if (b) handleVote(id, b.dataset.vote, b);
  });
  $('#removeBtn')?.addEventListener('click', async () => {
    const ok = await confirmDialog({ title: `„${m.title}“ entfernen?`, text: 'Alle Stimmen und Kommentare zu diesem Film gehen verloren.', confirmLabel: 'Entfernen', danger: true });
    if (!ok) return;
    try {
      await store.removeMovie(id);
      detailDialog.close();
      toast('Film entfernt', 'ok');
    } catch (e) { toast(e.message, 'err'); }
  });
  const input = $('#commentInput');
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = `${input.scrollHeight}px`; });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#commentForm').requestSubmit(); }
  });
  $('#commentForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    try {
      await withBusy(e.submitter, () => api.addComment(id, text));
      input.value = '';
      input.style.height = '';
      m.comment_count += 1;
      await loadComments(id);
      renderGrid();
    } catch (ex) { toast(ex.message, 'err'); }
  });

  renderDetailVotes();
  openDialog(detailDialog);
  loadComments(id);
}

function renderDetailVotes() {
  const m = store.findMovie(ui.detailId);
  const box = $('#detailVotes');
  if (!m || !box) return;
  box.innerHTML = voteButtons(m, { large: true });
}

async function loadComments(movieId) {
  const list = $('#commentList');
  try {
    const comments = await api.getComments(movieId);
    if (ui.detailId !== movieId) return;
    list.innerHTML = comments.length ? comments.map((c) => `
      <div class="comment">
        <span class="avatar">${esc(initials(c.username))}</span>
        <div class="comment-body">
          <div class="comment-meta">
            <strong>${esc(c.username)}</strong><time datetime="${esc(c.created_at)}">${esc(relativeTime(c.created_at))}</time>
            ${c.user_id === state.me.id || state.me.is_admin ? `<button class="comment-del" data-cid="${c.id}" aria-label="Kommentar löschen">${icon('trash')}</button>` : ''}
          </div>
          <div class="comment-text">${esc(c.text)}</div>
        </div>
      </div>`).join('') : '<p class="hint">Noch keine Kommentare. Fang an!</p>';
    $$('.comment-del', list).forEach((b) => b.addEventListener('click', async () => {
      try {
        await api.deleteComment(movieId, +b.dataset.cid);
        const m = store.findMovie(movieId);
        if (m) m.comment_count = Math.max(0, m.comment_count - 1);
        await loadComments(movieId);
        renderGrid();
      } catch (e) { toast(e.message, 'err'); }
    }));
  } catch (e) {
    list.innerHTML = `<p class="hint">${esc(e.message)}</p>`;
  }
}

// ── Propose a movie ──────────────────────────────────────────────────────
const addDialog = setupDialog($('#addDialog'), { onClose: () => { $('#searchInput').value = ''; } });
const add = { src: 'search', seq: 0, results: [], timer: null, cache: {} };

$('#fab').addEventListener('click', () => {
  const s = fabState();
  if (s.disabled) { toast(s.disabled, 'err'); return; }
  openAdd();
});

function openAdd() {
  const tmdb = state.config.tmdb_enabled;
  $$('#addTabs [data-src]').forEach((t) => { t.hidden = !tmdb && t.dataset.src !== 'manual'; });
  const left = store.proposalsLeft();
  $('#addQuota').textContent = Number.isFinite(left) ? `${left} frei` : '';
  openDialog(addDialog);
  setAddSource(tmdb ? 'search' : 'manual');
}

function setAddSource(src) {
  add.src = src;
  $$('#addTabs [data-src]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.src === src)));
  $('#searchWrap').hidden = src !== 'search';
  $('#addBack').hidden = true;
  $('#addControls').hidden = false;
  if (src === 'search') {
    const q = $('#searchInput').value.trim();
    if (q.length >= 2) runSearch(q); else $('#addBody').innerHTML = '<p class="state-msg">Gib mindestens 2 Zeichen ein.</p>';
    setTimeout(() => $('#searchInput').focus(), 50);
  } else if (src === 'manual') {
    renderManualForm();
  } else {
    loadList(src);
  }
}
$$('#addTabs [data-src]').forEach((t) => t.addEventListener('click', () => setAddSource(t.dataset.src)));

$('#searchInput').addEventListener('input', () => {
  clearTimeout(add.timer);
  const q = $('#searchInput').value.trim();
  if (q.length < 2) { $('#addBody').innerHTML = '<p class="state-msg">Gib mindestens 2 Zeichen ein.</p>'; return; }
  add.timer = setTimeout(() => runSearch(q), 300);
});

async function runSearch(q) {
  const seq = ++add.seq;
  $('#addBody').innerHTML = '<p class="state-msg">Suche …</p>';
  try {
    const results = await api.tmdbSearch(q);
    if (seq === add.seq && add.src === 'search') renderResults(results);
  } catch (e) {
    if (seq === add.seq) $('#addBody').innerHTML = `<p class="state-msg">${esc(e.message)}</p>`;
  }
}

async function loadList(src) {
  const seq = ++add.seq;
  if (add.cache[src]) { renderResults(add.cache[src]); return; }
  $('#addBody').innerHTML = '<p class="state-msg">Lade …</p>';
  try {
    const results = src === 'popular' ? await api.tmdbPopular() : await api.tmdbNowPlaying();
    add.cache[src] = results;
    if (seq === add.seq && add.src === src) renderResults(results);
  } catch (e) {
    if (seq === add.seq) $('#addBody').innerHTML = `<p class="state-msg">${esc(e.message)}</p>`;
  }
}

const isProposed = (tmdbId) => state.movies.some((m) => m.tmdb_id === tmdbId && !m.read_only);

function resultBadges(r) {
  return `${isProposed(r.tmdb_id) ? `<span class="chip chip-ok">${icon('check')} Vorgeschlagen</span>` : ''}${
    watchedTmdbIds.has(r.tmdb_id) ? `<span class="chip chip-accent">${icon('eye')} Schon gesehen</span>` : ''}`;
}

function renderResults(results) {
  add.results = results;
  if (!results.length) { $('#addBody').innerHTML = '<p class="state-msg">Nichts gefunden.</p>'; return; }
  $('#addBody').innerHTML = results.map((r, i) => `
    <button class="result" data-idx="${i}">
      ${posterBlock({ ...r, title: '' }, 'w154', 'result-poster')}
      <span class="result-info">
        <span class="result-title">${esc(r.title)}</span>
        <span class="result-meta">${[r.release_year, r.vote_average ? `★ ${r.vote_average.toFixed(1)}` : ''].filter(Boolean).join(' · ')}</span>
        ${resultBadges(r)}
        ${r.overview ? `<span class="result-overview">${esc(r.overview)}</span>` : ''}
      </span>
    </button>`).join('');
}

$('#addBody').addEventListener('click', async (e) => {
  const row = e.target.closest('[data-idx]');
  if (!row) return;
  const r = add.results[+row.dataset.idx];
  row.style.opacity = '0.5';
  try {
    renderPreview(await api.tmdbDetail(r.tmdb_id));
  } catch (ex) {
    row.style.opacity = '';
    toast(ex.message, 'err');
  }
});

function renderPreview(d) {
  $('#addControls').hidden = true;
  $('#addBack').hidden = false;
  const trailer = safeTrailer(d.trailer_url);
  const proposed = isProposed(d.tmdb_id);
  const facts = [d.release_year, d.runtime ? `${d.runtime} Min` : '', d.vote_average ? `★ ${d.vote_average.toFixed(1)}` : ''].filter(Boolean);
  $('#addBody').innerHTML = `
    <div class="preview">
      <div class="preview-top">
        ${posterBlock(d, 'w342', 'detail-poster')}
        <div>
          <h3>${esc(d.title)}</h3>
          <div class="chips">${facts.map((f) => `<span class="chip">${esc(f)}</span>`).join('')}
            ${genreList(d.genres).map((g) => `<span class="chip">${esc(g)}</span>`).join('')}</div>
          <div class="chips">${resultBadges(d)}</div>
        </div>
      </div>
      ${d.overview ? `<p class="detail-overview">${esc(d.overview)}</p>` : ''}
      <div class="detail-actions">
        <button class="btn btn-primary" id="proposeBtn" ${proposed ? 'disabled' : ''}>${icon('plus')} ${proposed ? 'Schon vorgeschlagen' : 'Vorschlagen'}</button>
        ${trailer ? `<a class="btn btn-trailer" href="${esc(trailer)}" target="_blank" rel="noopener noreferrer">${icon('play')} Trailer</a>` : ''}
      </div>
    </div>`;
  $('#proposeBtn').addEventListener('click', (e) => propose(e.currentTarget, {
    title: d.title, tmdb_id: d.tmdb_id, overview: d.overview, poster_path: d.poster_path,
    release_year: d.release_year, genres: d.genres, trailer_url: trailer || null,
  }));
}

$('#addBack').addEventListener('click', () => {
  $('#addControls').hidden = false;
  $('#addBack').hidden = true;
  renderResults(add.results);
});

function renderManualForm() {
  $('#addBody').innerHTML = `
    <form class="manual-form" id="manualForm" novalidate>
      ${state.config.tmdb_enabled ? '' : '<div class="alert alert-info">Die Filmsuche ist nicht eingerichtet. Trag den Film von Hand ein.</div>'}
      <div class="field"><label for="mTitle">Titel</label><input class="input" id="mTitle" maxlength="255" required></div>
      <div class="field"><label for="mYear">Jahr (optional)</label><input class="input" id="mYear" type="number" inputmode="numeric" min="1870" max="2100"></div>
      <div class="field"><label for="mGenres">Genres (optional)</label><input class="input" id="mGenres" maxlength="255" placeholder="z. B. Komödie, Drama"></div>
      <button class="btn btn-primary btn-block" type="submit">${icon('plus')} Vorschlagen</button>
    </form>`;
  $('#manualForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const title = $('#mTitle').value.trim();
    if (!title) { toast('Bitte einen Titel eingeben', 'err'); return; }
    const year = parseInt($('#mYear').value, 10);
    propose(e.submitter, { title, release_year: Number.isFinite(year) ? year : null, genres: $('#mGenres').value.trim() || null });
  });
  setTimeout(() => $('#mTitle')?.focus(), 50);
}

async function propose(button, data) {
  try {
    const movie = await withBusy(button, () => store.addMovie(data));
    addDialog.close();
    toast(`„${movie.title}“ ist dabei`, 'ok');
    showView('movies');
  } catch (e) { toast(e.message, 'err'); }
}

// ── Watched ──────────────────────────────────────────────────────────────
async function loadWatched() {
  watched = await api.getWatched();
  watchedTmdbIds = new Set(watched.map((w) => w.movie_tmdb_id).filter(Boolean));
}

async function renderWatched() {
  const list = $('#watchedList');
  if (!watched) list.innerHTML = '<div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:96px"></div>';
  try {
    await loadWatched();
  } catch (e) {
    list.innerHTML = emptyState('x', 'Laden fehlgeschlagen', e.message);
    return;
  }
  $('#watchedSummary').textContent = watched.length ? `${plural(watched.length, 'Filmabend', 'Filmabende')} bisher` : 'Alle bisherigen Filmabende';
  if (!watched.length) {
    list.innerHTML = emptyState('eye', 'Noch nichts gesehen', 'Nach dem ersten Filmabend taucht der Film hier auf.');
    return;
  }
  list.innerHTML = watched.map((w, i) => `
    <article class="watched">
      <span class="watched-num" aria-hidden="true">${watched.length - i}</span>
      ${posterBlock({ poster_path: w.movie_poster_path, title: '' }, 'w154', 'watched-poster')}
      <div class="watched-info">
        <div class="watched-title">${esc(w.movie_title)}</div>
        <div class="watched-meta">${esc([w.movie_release_year, genreList(w.movie_genres)[0], `von ${w.submitted_by_username}`].filter(Boolean).join(' · '))}</div>
        <div class="watched-date">${icon('calendar')} ${esc(formatDate(w.watched_at))} · ${esc(w.round_name)}</div>
      </div>
    </article>`).join('');
}

// ── Account ──────────────────────────────────────────────────────────────
function setupAccount() {
  const me = state.me;
  $('#avatar').textContent = initials(me.username);
  $('#accountAvatar').textContent = initials(me.username);
  $('#accountName').textContent = me.username;
  $('#accountRole').textContent = me.is_admin ? 'Admin' : me.is_regular ? 'Stammgast' : 'Gast';
  $('#adminLink').hidden = !me.is_admin;
}

const accountDialog = setupDialog($('#accountDialog'));
$('#accountBtn').addEventListener('click', () => openDialog(accountDialog));
$('#logoutBtn').addEventListener('click', () => api.logout());
$('#passwordForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = $('#passwordMsg');
  const cur = $('#curPassword').value;
  const next = $('#newPassword').value;
  msg.hidden = true;
  if (next.length < 8) { msg.className = 'alert alert-error'; msg.textContent = 'Das neue Passwort braucht mindestens 8 Zeichen'; msg.hidden = false; return; }
  try {
    const data = await withBusy($('#passwordBtn'), () => api.changePassword(cur, next));
    api.setToken(data.access_token);
    e.target.reset();
    msg.className = 'alert alert-ok';
    msg.textContent = 'Passwort geändert. Andere Geräte sind jetzt abgemeldet.';
  } catch (ex) {
    msg.className = 'alert alert-error';
    msg.textContent = ex.message;
  }
  msg.hidden = false;
});

boot();
