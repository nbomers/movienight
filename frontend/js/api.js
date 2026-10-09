// JSON API client. Browser and API share one origin (see README).

const TOKEN_KEY = 'token';
const LOGIN_PAGE = '/frontend/index.html';

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
};
export const setToken = (token) => {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* private mode */ }
};
export const clearToken = () => {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// FastAPI validation errors come as a list; show the first message.
function errorMessage(data, status) {
  const detail = data && data.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0] && detail[0].msg) return detail[0].msg;
  if (status === 429) return 'Zu viele Versuche, bitte später erneut probieren';
  if (status >= 500) return 'Serverfehler, bitte später erneut probieren';
  return `Fehler ${status}`;
}

async function request(method, path, body = null) {
  const token = getToken();
  const headers = { Accept: 'application/json' };
  if (body !== null) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(path, { method, headers, body: body !== null ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError('Keine Verbindung zum Server', 0);
  }

  // An expired session sends the user back to the login. A 401 without a
  // token (wrong password on the login form) is an ordinary error instead.
  if (res.status === 401 && token) {
    clearToken();
    window.location.replace(LOGIN_PAGE);
    // Never resolves: the page is navigating away.
    return new Promise(() => {});
  }

  if (res.status === 204) return null;

  // Empty or non-JSON bodies would make res.json() throw (Safari).
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status);
  return data;
}

const q = (params) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined));
  const str = s.toString();
  return str ? `?${str}` : '';
};

// Auth
export const login = (username, password) => request('POST', '/auth/login', { username, password });
export const register = (invite_token, username, password) =>
  request('POST', '/auth/register', { invite_token, username, password });
export const getMe = () => request('GET', '/auth/me');
export const changePassword = (current_password, new_password) =>
  request('POST', '/auth/change-password', { current_password, new_password });

export function logout() {
  clearToken();
  window.location.replace(LOGIN_PAGE);
}

// Movies, votes, comments
export const getConfig = () => request('GET', '/movies/config');
export const getMovies = () => request('GET', '/movies/');
export const getWatched = () => request('GET', '/movies/watched');
export const addMovie = (data) => request('POST', '/movies/', data);
export const removeMovie = (id) => request('DELETE', `/movies/${id}`);
export const vote = (id, vote_type) => request('POST', `/movies/${id}/vote`, { vote_type });
export const getComments = (movieId) => request('GET', `/movies/${movieId}/comments`);
export const addComment = (movieId, text) => request('POST', `/movies/${movieId}/comments`, { text });
export const deleteComment = (movieId, commentId) => request('DELETE', `/movies/${movieId}/comments/${commentId}`);

// Rounds
export const getRounds = () => request('GET', '/rounds/');
export const getActiveRound = () => request('GET', '/rounds/active');
export const createRound = (data) => request('POST', '/rounds/', data);
export const completeRound = (id, watched_movie_id = null) =>
  request('POST', `/rounds/${id}/complete${q({ watched_movie_id })}`);
export const setWatched = (id, watched_movie_id) =>
  request('PATCH', `/rounds/${id}/set-watched${q({ watched_movie_id })}`);
export const renameRound = (id, name) => request('PATCH', `/rounds/${id}/rename`, { name });
export const setDeadline = (id, vote_deadline) => request('PATCH', `/rounds/${id}/deadline`, { vote_deadline });
export const getRoundGuests = (id) => request('GET', `/rounds/${id}/guests`);
export const addRoundGuest = (id, user_id) => request('POST', `/rounds/${id}/guests`, { user_id });
export const removeRoundGuest = (id, userId) => request('DELETE', `/rounds/${id}/guests/${userId}`);

// TMDB
export const tmdbSearch = (query) => request('GET', `/tmdb/search${q({ q: query })}`);
export const tmdbDetail = (id) => request('GET', `/tmdb/movie/${id}`);
export const tmdbNowPlaying = () => request('GET', '/tmdb/now-playing');
export const tmdbPopular = () => request('GET', '/tmdb/popular');

// Admin
export const getInvites = () => request('GET', '/admin/invites');
export const createInvite = (data) => request('POST', '/admin/invites', data);
export const deleteInvite = (id) => request('DELETE', `/admin/invites/${id}`);
export const renameInvite = (id, label) => request('PATCH', `/admin/invites/${id}/label`, { label });
export const getUsers = () => request('GET', '/admin/users');
export const userAction = (id, action) => request('PATCH', `/admin/users/${id}/${action}`);
export const resetPassword = (id, password) => request('PATCH', `/admin/users/${id}/reset-password`, { password });
export const deleteUser = (id) => request('DELETE', `/admin/users/${id}`);
