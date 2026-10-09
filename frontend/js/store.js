// App state shared by the grid, the detail sheet and the swipe deck.
import * as api from './api.js';

export const state = {
  me: null,
  config: { max_movies_per_user: 3, tmdb_enabled: true },
  round: null, // active round or null
  movies: [],
  noAccess: false, // guest without an invitation for the running round
  loaded: false,
};

const listeners = new Set();
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const emit = () => listeners.forEach((fn) => fn(state));

export const findMovie = (id) => state.movies.find((m) => m.id === id);
export const isArchive = () => !state.round && state.movies.length > 0;
export const deadlinePassed = () =>
  !!(state.round && state.round.vote_deadline && Date.now() > new Date(state.round.vote_deadline).getTime());
export const votingOpen = () => !!state.round && !deadlinePassed();
export const superlikeAvailable = () => !state.movies.some((m) => m.user_vote === 'superlike');
export const myProposalCount = () =>
  state.round ? state.movies.filter((m) => m.submitted_by === state.me.id && m.round_id === state.round.id).length : 0;
export const proposalsLeft = () =>
  state.me && state.me.is_admin ? Infinity : Math.max(0, state.config.max_movies_per_user - myProposalCount());
export const unvotedMovies = () => state.movies.filter((m) => !m.user_vote && !m.read_only);

export async function init() {
  const [me, config] = await Promise.all([api.getMe(), api.getConfig()]);
  state.me = me;
  state.config = config;
  await refresh();
}

export async function refresh() {
  try {
    const [movies, round] = await Promise.all([api.getMovies(), api.getActiveRound()]);
    // Keep optimistic votes that are still in flight.
    state.movies = movies.map((m) => (pending.has(m.id) ? findMovie(m.id) || m : m));
    state.round = round;
    state.noAccess = false;
  } catch (e) {
    if (e.status === 403 && e.message === 'GUEST_NO_ACCESS') {
      state.noAccess = true;
      state.movies = [];
      state.round = null;
    } else {
      throw e;
    }
  } finally {
    state.loaded = true;
    emit();
  }
}

// ── Voting ───────────────────────────────────────────────────────────────
const pending = new Set();
const COUNT = { up: 'upvotes', down: 'downvotes', superlike: 'superlikes' };

function applyVote(movie, type) {
  const prev = movie.user_vote;
  if (prev) movie[COUNT[prev]] -= 1;
  if (prev === 'superlike') movie.superlike_usernames = movie.superlike_usernames.filter((n) => n !== state.me.username);
  // Sending the same type again removes the vote (server toggles).
  movie.user_vote = prev === type ? null : type;
  if (movie.user_vote) movie[COUNT[movie.user_vote]] += 1;
  if (movie.user_vote === 'superlike') movie.superlike_usernames = [...movie.superlike_usernames, state.me.username];
}

/**
 * Optimistic vote. Returns true on success. `type` equal to the current vote
 * removes it, like the server does.
 */
export async function castVote(movieId, type) {
  const movie = findMovie(movieId);
  if (!movie || pending.has(movieId)) return false;
  if (!votingOpen()) throw new Error('Die Abstimmung ist geschlossen');
  if (type === 'superlike' && movie.user_vote !== 'superlike' && !superlikeAvailable()) {
    throw new Error('Du hast deinen Superlike in dieser Runde schon vergeben');
  }

  const snapshot = structuredClone(movie);
  applyVote(movie, type);
  pending.add(movieId);
  emit();
  try {
    await api.vote(movieId, type);
    return true;
  } catch (e) {
    Object.assign(movie, snapshot);
    throw e;
  } finally {
    pending.delete(movieId);
    emit();
  }
}

export async function removeMovie(movieId) {
  await api.removeMovie(movieId);
  state.movies = state.movies.filter((m) => m.id !== movieId);
  emit();
}

export async function addMovie(data) {
  const movie = await api.addMovie(data);
  state.movies = [...state.movies, movie];
  emit();
  return movie;
}
