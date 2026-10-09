# movienight

**A self-hosted movie-night voting app for friend groups.**

Everyone proposes up to three films per round, the group votes until a deadline, and the admin closes the round with the film you actually watched. Films that lost come back next round, and anything nobody picks for too long drops out on its own.

<!-- Screenshots: add docs/swipe.png, docs/detail.png and docs/voting.png (taken with demo data) and uncomment.
<p align="center">
  <img src="docs/swipe.png" width="250" alt="Swipe tab">
  <img src="docs/detail.png" width="250" alt="Movie detail view">
  <img src="docs/voting.png" width="250" alt="Voting grid">
</p>
-->

## Features

- **Rounds with deadlines:** one active round at a time; no votes or new proposals once the deadline has passed
- **Voting:** like, nope and one superlike per person and round, in a ranked poster grid or in the swipe tab
- **Swipe mode:** a card deck with drag, flick and keyboard controls, undo, "later", and a summary at the end
- **Carry-over:** unwatched films move to the next round with their votes reset, and drop out after a configurable number of rounds
- **TMDB search:** posters, genres, overviews and German or English trailers from The Movie Database; without a key, films are added by hand
- **Invite-only accounts:** single- or multi-use invite links for regulars or one-off guests; guests only see the rounds they were invited to
- **Comments** per film and a history of what you watched
- **Accounts:** change your own password; admins reset passwords, grant or revoke admin rights, deactivate, reactivate or delete users
- **Admin panel** for rounds, invites, guests and users
- Mobile-first UI in plain HTML, CSS and JavaScript modules, with no build step

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2 |
| Database | SQLite |
| Auth | JWT (PyJWT, HS256), bcrypt password hashes |
| Frontend | Vanilla JS (ES modules), served by FastAPI |
| External API | TMDB |
| Tooling | pytest, ruff, GitHub Actions |

```
Browser ──HTTPS──▶ Caddy ──▶ uvicorn / FastAPI ──▶ SQLite
                                    │
                                    └──▶ TMDB API (search, details, trailers)
```

The FastAPI app serves both the JSON API and the static frontend, so browser and API share one origin. Caddy terminates TLS; in my setup a Cloudflare Tunnel sits in front of it, so the server needs no open inbound ports.

## Quickstart

Requires Python 3.12.

```bash
git clone https://github.com/nbomers/movienight.git
cd movienight
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Set SECRET_KEY (see the comment in .env.example). TMDB_API_KEY is optional.

python -m scripts.seed_demo        # made-up users, films and an active round
uvicorn app.main:app --reload
```

Open <http://localhost:8000> and log in as `demo_admin`, `alex`, `sam` or `robin` (a guest), all with password `demo-password`.

Without seed data the app creates the first admin from `FIRST_ADMIN_USERNAME` and `FIRST_ADMIN_PASSWORD` on first start, and refuses to start if no password is set. There is no default password.

Run the checks:

```bash
ruff check .
pytest
```

## Self-hosting

`deploy/` has examples for a typical single-server setup:

- [`deploy/movienight.service`](deploy/movienight.service): systemd unit. It binds uvicorn to localhost and enables `--proxy-headers`, so the login rate limit sees real client IPs.
- [`deploy/Caddyfile.example`](deploy/Caddyfile.example): reverse proxy with automatic HTTPS, plus a variant for use behind Cloudflare Tunnel.

Back up the SQLite file (`movienight.db` with the example `.env`) the same way as any other data directory. The app runs SQLite in WAL mode, so copy the `-wal` file too, or use `sqlite3 movienight.db ".backup backup.db"`.

Installs that predate the rename and have no `DATABASE_URL` set keep using `filmabend.db`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | (required) | Signs login tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Token lifetime (7 days) |
| `DATABASE_URL` | `sqlite:///./filmabend.db` | SQLite file |
| `TMDB_API_KEY` | empty | Enables search; without it films are added by hand |
| `MAX_MOVIES_PER_USER` | `3` | Proposals per person and round |
| `FIRST_ADMIN_USERNAME` / `FIRST_ADMIN_PASSWORD` | `admin` / empty | Initial admin, first start only |
| `CORS_ORIGINS` | `[]` | Only for a frontend on another origin |
| `AUTH_RATE_LIMIT` / `AUTH_RATE_WINDOW_SECONDS` | `10` / `300` | Failed logins per IP and window |

### Upgrading

Login tokens are now bound to the user id and a per-user token version. Tokens issued by earlier versions are rejected, so everyone logs in once after the update. The new database column is added automatically at startup.

## Design decisions

**SQLite instead of Postgres.** A friend group produces a few hundred rows a year, and there is one writer most of the time. SQLite means no extra service, backups are one file copy, and the test suite runs against the same engine as production. If this ever needed several app servers, the database would be the first thing to change.

**No frontend framework.** The UI is a handful of views over a small JSON API. Plain ES modules load directly in the browser, there is no build step and no `node_modules`, and deploying is copying files. The cost is manual DOM updates and manual escaping: every value from the API goes through one `esc()` helper before it reaches `innerHTML`, and the backend additionally only accepts poster paths and trailer links in the exact shape TMDB produces.

**Round logic.** Exactly one round is active at a time. When the admin closes a round, they can mark the film that was watched; it leaves the pool. When the next round starts, all other films from the last round move over, their votes are cleared, and their `rounds_survived` counter goes up. Once it reaches the configured limit (default 4), the film is retired. This keeps the list fresh without anyone cleaning it up by hand.

**Superlikes are derived, not stored.** Whether someone has used their superlike is a query over the current round's votes. Earlier versions kept a separate list, which could drift from the votes (for example when a superliked film was removed). Deriving it removes that class of bugs.

**Auth and access.** Accounts exist only through invite links (`secrets.token_urlsafe(32)`), which carry the token in the URL fragment so it never reaches server logs. Tokens are signed JWTs bound to the user id and a per-user token version; changing or resetting a password raises the version and logs out every other session. Every request re-reads the user, so deactivating someone takes effect immediately. Login answers unknown users and wrong passwords with the same error in the same time, usernames are unique ignoring case, and failed logins and registrations are rate-limited per IP. Guests are checked against the active round on every round-scoped endpoint, including comments and TMDB search.

**Defense in depth for the frontend.** The login token lives in `localStorage`, so the frontend has no inline scripts or event handlers and the server sends a strict Content-Security-Policy (`script-src 'self'`). Even if an escaping mistake slipped through, injected markup could not run code. A test keeps inline scripts from coming back.

**Time zones.** Deadlines are entered as local time (Europe/Berlin), converted to UTC before storage, and sent to the browser with an explicit offset. SQLite does not store offsets, so the API attaches UTC when reading.

## TMDB attribution

<!-- Add the official TMDB logo from https://www.themoviedb.org/about/logos-attribution as docs/tmdb-logo.svg:
<img src="docs/tmdb-logo.svg" width="120" alt="TMDB logo">
-->

This product uses the TMDB API but is not endorsed or certified by TMDB.

## License

[MIT](LICENSE). The bundled Inter font is licensed under the [SIL Open Font License](frontend/fonts/OFL.txt).
