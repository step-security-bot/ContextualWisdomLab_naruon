# Render.com Deployment

This runbook describes how to deploy Naruon on Render.com using the
`render.yaml` Blueprint at the repository root.

## Why a Blueprint instead of one Dockerfile

Render's single-service "New Web Service" form has one `Dockerfile Path`
field, which makes it look like only one Dockerfile per repo is supported.
That is a UI limitation, not a platform limitation. Render Blueprints
register many services from a single YAML file, and each service can point
at its own Dockerfile. The Naruon repo ships two Dockerfiles on purpose:

| Component | Dockerfile | Why split |
|---|---|---|
| Backend (FastAPI) | `./Dockerfile` | Python 3.14 toolchain, Alembic `migrate_db.py` + `start_backend.py` entrypoint, scaling on CPU/IO. |
| Frontend (Next.js) | `./frontend/Dockerfile` | Node 24 toolchain, Next.js build artifacts, scaling on memory. |

This is the same split used by `docker-compose.yml` and `k8s/*.yaml`,
and it preserves the AGENTS.md boundary that the browser never holds
backend secrets.

## What `render.yaml` declares

* **`naruon-postgres`** — managed Postgres 16 (`basic-256mb` plan).
  Required because the backend uses pgvector and managed Postgres on
  Render supports the `vector` extension.
* **`naruon-backend`** (`type: web`, `runtime: docker`) — builds from
  `./Dockerfile`. Overrides the container `CMD` so `start_backend.py`
  receives Render's injected `$PORT` and so the managed-Postgres URL
  is rewritten to the SQLAlchemy async-driver form
  (`postgresql+asyncpg://...`) that `backend/db/session.py` requires.
  Render Blueprints do not support variable interpolation, so the
  rewrite happens in the start command shell — no code default is
  added to the backend (AGENTS.md rule preserved). The boot path
  still runs through `scripts/start_backend.py`; we never call
  `uvicorn` directly.
* **`naruon-frontend`** (`type: web`, `runtime: docker`) — builds from
  `./frontend/Dockerfile`. Receives the backend's public URL via the
  `BACKEND_INTERNAL_URL` env var, populated from
  `naruon-backend`'s `RENDER_EXTERNAL_URL`. The frontend `/api/*`
  route handler reads that value at runtime and proxies same-origin
  browser requests to the backend, so the published Docker image is not
  permanently wired to one deployment environment and no public
  identity headers cross the browser boundary.

  When `BACKEND_INTERNAL_URL` is set explicitly, the route handler
  enforces SSRF guards before accepting it: the URL must use `https://`
  and the hostname must not fall into a private (RFC 1918), loopback,
  IPv4-mapped IPv6, IPv6 ULA/link-local, or cloud metadata
  (`169.254.0.0/16`) range. Render's `RENDER_EXTERNAL_URL` is an HTTPS
  `*.onrender.com` host and satisfies these checks. In production
  runtime, a missing value fails the request instead of falling back to
  loopback. The only non-HTTPS exception is the explicit Compose opt-in
  for exactly `http://backend:8000`.

## First-time setup

1. Push this branch (with `render.yaml`) to GitHub.
2. In the Render dashboard choose **New → Blueprint** and select the
   `naruon` repo. Render parses `render.yaml` and lists the resources
   it will create.
3. Render prompts for any `sync: false` values. Provide them now:
   * `OPENAI_API_KEY` — your real key, or a placeholder if running
     without OpenAI features.
   You will be able to update or rotate these later from the service's
   **Environment** tab.
4. Confirm the sync. Render provisions `naruon-postgres` first, then
   builds `naruon-backend` and `naruon-frontend` in parallel.
5. **pgvector extension.** The initial Alembic migration run by
   `backend/scripts/migrate_db.py` executes `CREATE EXTENSION IF NOT EXISTS
   vector`. If Render's
   application role has the privilege, the first deploy enables the
   extension automatically and there is nothing else to do. If the
   first backend deploy fails with
   `permission denied to create extension "vector"` (or
   `Must be superuser to create this extension`), open the
   database's **Connect** tab in the Render dashboard, click the
   `PSQL Command` button to start a privileged session, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   and trigger a redeploy of `naruon-backend`. Subsequent migration runs
   are a no-op for the extension because `CREATE EXTENSION IF NOT EXISTS
   vector` is idempotent.

## Verifying the deploy

1. Visit `https://naruon-backend.onrender.com/` — expect a JSON or HTML
   landing response from FastAPI (the exact body depends on the
   current `/` handler).
2. Visit `https://naruon-frontend.onrender.com/` — the Next.js app
   should render.
3. From the frontend service's URL, exercise a feature that calls
   `/api/...`. The request is proxied to the backend via
   `BACKEND_INTERNAL_URL`. If the frontend logs a 502 on `/api/*`,
   double-check that `BACKEND_INTERNAL_URL` resolves to the backend's
   `RENDER_EXTERNAL_URL` (visible in the frontend service's
   **Environment** tab).

## Optional: disable background workers on first boot

`backend/main.py` starts the IMAP sync worker in its lifespan. If you
deploy to Render before any tenant has configured IMAP credentials,
the worker logs harmless errors on its retry loop. To silence them
until you are ready, add the following to the **Environment** tab of
`naruon-backend`:

```bash
DISABLE_BACKGROUND_WORKERS=1
```

Remove the variable when you want IMAP sync to run.

## Rotating secrets

* `AUTH_SESSION_HMAC_SECRET` is generated automatically by Render
  (`generateValue: true`, base64-encoded 256-bit value, well over the
  32-byte minimum enforced by `backend/core/runtime_secrets.py`).
  Rotate by deleting the variable in the dashboard and triggering a
  redeploy; Render generates a fresh value. Rotating invalidates all
  in-flight signed sessions, so plan a maintenance window.

  Rare failure mode: the generated value happens to contain a banned
  substring (`change`, `example`, `password`, `secret`) and the
  backend refuses to boot with
  `AUTH_SESSION_HMAC_SECRET must not contain placeholder terms`.
  Delete the variable in the dashboard and redeploy to regenerate.
* `OPENAI_API_KEY` and any other `sync: false` value: edit in the
  service's **Environment** tab. The Blueprint never overrides
  user-supplied secret values on subsequent syncs.

## Local development is unaffected

`docker-compose up` continues to work with no Render-specific
environment variables. The Compose file passes
`BACKEND_INTERNAL_URL=http://backend:8000` plus the exact
`ALLOW_DOCKER_BACKEND_INTERNAL_URL=1` opt-in so the runtime route
handler can proxy to the Docker-network backend without weakening the
Render production guard. Plain local dev still falls back to
`http://127.0.0.1:8000` when `BACKEND_INTERNAL_URL` is unset and
`NODE_ENV` is not `production`.

## What this Blueprint deliberately does not do

* It does not bundle frontend and backend into one container with
  `supervisord` or `nginx` as a reverse proxy. That pattern violates
  the "one container, one process" principle that the rest of the
  repo (Compose, K8s) is built around, and Render does not require
  it.
* It does not modify the backend `Dockerfile` or `k8s/*.yaml`. It
  updates `frontend/Dockerfile` and `docker-compose.yml` only to keep
  the same runtime `/api/*` proxy contract in non-Render environments;
  those paths remain the source of truth for non-Render environments.
* It does not pin `OPENAI_MODEL` to anything other than the existing
  Compose default. Adjust in the dashboard if your account uses a
  different model.
