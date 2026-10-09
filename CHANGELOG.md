# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-10

A complete overhaul of security, backend and design.

### Upgrade notes

- **Everyone has to log in once.** Login tokens are now bound to the user id
  and a per-user token version; tokens from earlier versions are rejected.
  Passwords and all other data stay as they are.
- The new `users.token_version` column is added automatically at startup.
- SQLite now runs in WAL mode. Back up with `sqlite3 <db> ".backup <file>"`
  instead of copying the file.
- Installs without `DATABASE_URL` keep using `filmabend.db`. Do not replace
  an existing `.env` with the new `.env.example`.

### Security

- Tokens of a deleted user no longer work for a new account registered with
  the same name; password changes and resets log out all other sessions.
- Votes are only accepted for films of the active round; guests only see
  comments of the round they were invited to; TMDB search requires round
  access.
- Login timing no longer reveals which usernames exist; usernames are unique
  ignoring case; single-use invite links cannot be redeemed twice in parallel.
- Strict Content-Security-Policy, Permissions-Policy and cache headers; the
  frontend has no inline scripts anymore.
- Invite links carry the token in the URL fragment instead of the query
  string.
- The login rate limiter no longer grows without bound.

### Added

- Redesigned interface with a shared design system, native dialogs and
  empty states for every situation.
- Rebuilt swipe mode: card deck, drag and flick gestures, undo, "later",
  keyboard shortcuts and a summary.
- Optimistic voting shared by grid, detail view and swipe deck.
- Manual proposals when no TMDB key is configured.
- Password change for everyone; admins can reactivate users and grant or
  revoke admin rights.
- `MAX_MOVIES_PER_USER` setting and `GET /movies/config`.

### Fixed

- A wrong password reloaded the login page instead of showing an error.
- Most films had no trailer because only German videos were searched.
- "Mark watched" in the admin panel also tried to complete the round.
- Deleting a user removed watched films from the history.
- Invite expiry times were shown one or two hours off.
- New rounds used a removal limit of 3 instead of the documented 4.
- Comment delete buttons were invisible on touch screens.

## [0.2.0] - 2026-10-09

Initial public release.

[1.0.0]: https://github.com/nbomers/movienight/compare/338a55d...v1.0.0
[0.2.0]: https://github.com/nbomers/movienight/commit/338a55d
