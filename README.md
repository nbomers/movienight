# Filmabend

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
- **Voting:** upvote, downvote and one superlike per person and round; a ranked grid plus a Tinder-style swipe tab
- **Carry-over:** unwatched films move to the next round with their votes reset, and drop out after a configurable number of rounds
- **TMDB search:** posters, genres, overviews and trailer links come from The Movie Database
- **Invite-only accounts:** single- or multi-use invite links for regulars or one-off guests; guests only see the rounds they were invited to
- **Comments** per film and a history of what you watched
- **Admin panel** for rounds, invites, guests and users
- Mobile-first UI in plain HTML, CSS and JavaScript, with no build step

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
git clone https://github.com/nbomers/filmabend.git
cd filmabend
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

- [`deploy/filmabend.service`](deploy/filmabend.service): systemd unit. It binds uvicorn to localhost and enables `--proxy-headers`, so the login rate limit sees real client IPs.
- [`deploy/Caddyfile.example`](deploy/Caddyfile.example): reverse proxy with automatic HTTPS, plus a variant for use behind Cloudflare Tunnel.

Back up the SQLite file (`filmabend.db` by default) the same way as any other data directory.

## Design decisions

**SQLite instead of Postgres.** A friend group produces a few hundred rows a year, and there is one writer most of the time. SQLite means no extra service, backups are one file copy, and the test suite runs against the same engine as production. If this ever needed several app servers, the database would be the first thing to change.

**No frontend framework.** The UI is a handful of views over a small JSON API. Plain ES modules load directly in the browser, there is no build step and no `node_modules`, and deploying is copying files. The cost is manual DOM updates and manual escaping: every value from the API goes through one `esc()` helper before it reaches `innerHTML`, and the backend additionally only accepts poster paths and trailer links in the exact shape TMDB produces.

**Round logic.** Exactly one round is active at a time. When the admin closes a round, they can mark the film that was watched; it leaves the pool. When the next round starts, all other films from the last round move over, their votes are cleared, and their `rounds_survived` counter goes up. Once it reaches the configured limit (default 4), the film is retired. This keeps the list fresh without anyone cleaning it up by hand.

**Superlikes are derived, not stored.** Whether someone has used their superlike is a query over the current round's votes. Earlier versions kept a separate list, which could drift from the votes (for example when a superliked film was removed). Deriving it removes that class of bugs.

**Auth and access.** Accounts exist only through invite links (`secrets.token_urlsafe(32)`). Tokens are signed JWTs with a configurable lifetime, and every request re-reads the user from the database, so deactivating someone takes effect immediately. Login returns the same error for unknown users and wrong passwords, and failed logins and registrations are rate-limited per IP. Guests are checked against the active round on every round-scoped endpoint.

**Time zones.** Deadlines are entered as local time (Europe/Berlin), converted to UTC before storage, and sent to the browser with an explicit offset. SQLite does not store offsets, so the API attaches UTC when reading.

## TMDB attribution

<!-- Add the official TMDB logo from https://www.themoviedb.org/about/logos-attribution as docs/tmdb-logo.svg:
<img src="docs/tmdb-logo.svg" width="120" alt="TMDB logo">
-->

This product uses the TMDB API but is not endorsed or certified by TMDB.

## License

[MIT](LICENSE). The bundled Inter font is licensed under the [SIL Open Font License](frontend/fonts/OFL.txt).
