// Swipe tab: one card per unrated movie (ported from the old page as-is).
import * as store from './store.js';
import { esc, genreList, icon, posterUrl, toast } from './ui.js';

let root = null;
let queue = [];
let idx = 0;

export function showSwipe(container) {
  root = container;
  queue = store.unvotedMovies();
  idx = 0;
  render();
}

function render() {
  if (!store.state.round || idx >= queue.length) {
    root.innerHTML = `<div class="empty"><div class="empty-icon">${icon(store.state.round ? 'check' : 'calendar')}</div>
      <h3>${store.state.round ? 'Alle Filme bewertet!' : 'Gerade läuft keine Runde'}</h3></div>`;
    return;
  }
  const cards = queue.slice(idx, idx + 2).reverse();
  root.innerHTML = `<div class="old-deck">${cards.map((m, i) => `
    <div class="old-card" data-id="${m.id}" style="z-index:${i + 1}">
      ${posterUrl(m.poster_path, 'w500') ? `<img src="${posterUrl(m.poster_path, 'w500')}" alt="">` : ''}
      <div class="old-info"><strong>${esc(m.title)}</strong><span>${esc(genreList(m.genres).slice(0, 2).join(' · '))}</span></div>
    </div>`).join('')}</div>
    <div class="old-btns">
      <button class="btn btn-icon" data-v="down" aria-label="Nope">${icon('dislike')}</button>
      <button class="btn btn-icon" data-v="superlike" aria-label="Superlike">${icon('star')}</button>
      <button class="btn btn-icon" data-v="up" aria-label="Like">${icon('heart')}</button>
    </div>`;
  root.querySelectorAll('[data-v]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.v)));
  attachDrag(root.querySelector('.old-card:last-child'));
}

function attachDrag(card) {
  let sx = 0, sy = 0, dx = 0, dy = 0;
  card.addEventListener('pointerdown', (e) => {
    sx = e.clientX; sy = e.clientY; dx = dy = 0;
    card.setPointerCapture(e.pointerId);
    const move = (ev) => { dx = ev.clientX - sx; dy = ev.clientY - sy; card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx * 0.08}deg)`; };
    const up = () => {
      card.removeEventListener('pointermove', move);
      if (dy < -90 && Math.abs(dy) > Math.abs(dx)) decide('superlike');
      else if (dx > 90) decide('up');
      else if (dx < -90) decide('down');
      else card.style.transform = '';
    };
    card.addEventListener('pointermove', move);
    card.addEventListener('pointerup', up, { once: true });
  });
}

async function decide(type) {
  const movie = queue[idx];
  if (!movie) return;
  idx += 1;
  render();
  try { await store.castVote(movie.id, type); } catch (e) { toast(e.message, 'err'); }
}
