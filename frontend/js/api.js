// Basis-URL — im Dev leer lassen (same origin), in Prod ggf. anpassen
const API = '';

async function request(method, path, body = null) {
  const token = localStorage.getItem('token');
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (token) opts.headers['Authorization'] = `Bearer ${token}`;
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(API + path, opts);

  // An expired session sends the user back to the login. A 401 without a
  // token (wrong password on the login form) is an ordinary error instead.
  if (res.status === 401 && token) {
    localStorage.removeItem('token');
    window.location.href = '/frontend/index.html';
    return;
  }

  // 204 No Content
  if (res.status === 204) return null;

  // Safari-safe parsing: empty bodies would throw on res.json()
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
  if (!res.ok) throw new Error((data && data.detail) || `Fehler ${res.status}`);
  return data;
}

// Auth
export const login = (username, password) =>
  request('POST', '/auth/login', { username, password });

export const register = (invite_token, username, password) =>
  request('POST', '/auth/register', { invite_token, username, password });

export const getMe = () => request('GET', '/auth/me');

// Movies
export const getMovies = () => request('GET', '/movies/');
export const addMovie = (data) => request('POST', '/movies/', data);
export const removeMovie = (id) => request('DELETE', `/movies/${id}`);
export const vote = (id, vote_type) =>
  request('POST', `/movies/${id}/vote`, { vote_type });

// Rounds
export const getRounds = () => request('GET', '/rounds/');
export const getActiveRound = () => request('GET', '/rounds/active');
export const createRound = (data) => request('POST', '/rounds/', data);
export const completeRound = (id, watched_movie_id = null) => {
  const params = watched_movie_id ? `?watched_movie_id=${watched_movie_id}` : '';
  return request('POST', `/rounds/${id}/complete${params}`);
};

// TMDB
export const tmdbSearch = (q) =>
  request('GET', `/tmdb/search?q=${encodeURIComponent(q)}`);
export const tmdbDetail = (id) => request('GET', `/tmdb/movie/${id}`);

// Admin
export const createInvite = (expires_in_hours = 72) =>
  request('POST', '/admin/invites', { expires_in_hours });
export const getInvites = () => request('GET', '/admin/invites');
export const getUsers = () => request('GET', '/admin/users');
export const deactivateUser = (id) =>
  request('PATCH', `/admin/users/${id}/deactivate`);
export const makeAdmin = (id) =>
  request('PATCH', `/admin/users/${id}/make-admin`);

export const tmdbNowPlaying = () => request('GET', '/tmdb/now-playing');
