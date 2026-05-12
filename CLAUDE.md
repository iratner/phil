# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a multi-project workspace (not a Bazel/Turborepo monorepo — each project has its own `package.json` / `requirements.txt` and is built independently) for the **phil** game. The pieces:

- `phil-game/` — Phaser 4 + Vite + TypeScript game client. Wrapped with Capacitor (`capacitor.config.ts`, `android/`, `ios/`) for native iOS/Android builds. Game scenes live in `src/game/scenes/` and are wired up in `src/game/main.ts`.
- `phil-server-nest/` — NestJS 11 (TypeScript) server. Currently scaffolding: `src/modules/{levels,users,game-state}/` each hold a single controller. The root `AppController` uses host-based routing (`@Controller({ host: ':truck.localhost' })`), which means hitting `localhost:3000` directly won't match — requests must use a `*.truck.localhost` host header.
- `phil-server-fapi-leveler/` — FastAPI (Python 3.8) service that owns the `Level` model and `/levels` routes. Deployed as a container to Google Cloud Run via `gcr.io/twa-developer-ilya-test/bosun-service`. The Pydantic `Level` model in `app/models/level.py` is the de-facto schema source today (`BlockType` enum: `ICE`, `SPIKE`, `BOUNCE`, `MOVE_ONE`, `STATIC`; `board_top` / `board_bottom` are 2D arrays of `BlockType`). `gen-openapi.py` dumps the OpenAPI spec to `openapi.json`.
- `next-app-level-editor/` — Next.js 15 (React 19, Tailwind v4, Turbopack) level-editor UI. The real app is the nested `base-next-app/` directory; the outer `package.json` only pulls in `prettier`.
- `postgres-fun/` — `docker-compose.yml` for a local Postgres (port 5435, user `ilya`). No app code; used for ad-hoc dev.

`project.todo` is the planning doc — it spells out the intended `Level` / `User` / `GameState` entities and the `Block` types. It also flags the open question of whether to define game rules in a shared JSON file consumable by both the Python server and the JS clients; the Python model has so far gotten there first.

## Tooling baseline

- Node: **v22.9.0** (see `.nvmrc`).
- Python: **3.8.20** (see `.python-version`). The FastAPI service's Dockerfile pins `python:3.8.10-slim`.
- Package manager: **pnpm 10.8.0** for every JS project (declared in each `package.json`).

## Common commands

Run these from the relevant subdirectory (each project is self-contained).

### phil-game (Phaser client)
```bash
pnpm install
pnpm dev           # vite dev server (port 8080); pings gryzor.co via log.js
pnpm dev-nolog     # same, without the analytics ping
pnpm build         # production bundle to dist/
pnpm build-nolog
```
Capacitor wraps `dist/` for iOS/Android — rebuild the web bundle before syncing to native projects.

### phil-server-nest (NestJS)
```bash
pnpm install
pnpm start:dev     # nest start --watch
pnpm start         # one-shot
pnpm start:prod    # node dist/main (after pnpm build)
pnpm build         # nest build → dist/
pnpm lint          # eslint --fix on src/, apps/, libs/, test/
pnpm format        # prettier --write
pnpm test          # jest (testRegex: *.spec.ts, rootDir: src)
pnpm test -- path/to/file.spec.ts     # run a single spec
pnpm test:e2e      # jest --config test/jest-e2e.json
pnpm test:cov
```

### phil-server-fapi-leveler (FastAPI)
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080         # local dev
python gen-openapi.py                              # regenerate openapi.json

# Container build/deploy (target is Cloud Run, linux/amd64):
docker build --platform linux/amd64 -t gcr.io/twa-developer-ilya-test/bosun-service:<tag> .
docker push gcr.io/twa-developer-ilya-test/bosun-service:<tag>
gcloud run deploy bosun-service --image gcr.io/twa-developer-ilya-test/bosun-service:<tag> \
  --platform managed --region us-east1 --timeout 200s --port 8080
```
CORS is hard-coded to `http://localhost:3003` in `app/main.py` — if the level editor moves ports, update this.

### next-app-level-editor (Next.js)
The actual app lives in `base-next-app/`, not the outer directory.
```bash
cd next-app-level-editor/base-next-app
pnpm install
pnpm dev           # next dev --turbopack
pnpm build
pnpm start
pnpm lint
```

### postgres-fun
```bash
cd postgres-fun
docker compose up -d    # Postgres on localhost:5435, user=ilya, pw=postgres
```

## Release / CI

Workflows live in `.github/workflows/`:

- `conventional-commits.yml` — path-scoped to `phil-game/**`. **Requires PRs touching `phil-game/` to contain exactly one non-merge commit with a conventional-commit subject.** The single-commit rule exists because the repo's squash-merge title source is `COMMIT_OR_PR_TITLE`, which only uses the source commit's subject when there is exactly one; with 2+ commits, GitHub falls back to the unvalidated PR title. To fix a failing check: `git rebase -i main` to squash, then `git push --force-with-lease`.
- `release-please.yml` and `release-on-tag.yml` — both **scaffolded but inert** (`workflow_dispatch` only). They are named "Armada" — that's a placeholder copied from a template, not a real product name. Don't be confused; they're meant to manage versioning for `phil-game/`. The companion files `release-please-config.json` and `.release-please-manifest.json` referenced by the workflow are not yet in the repo.
- `docker-image.yml` — builds `./Dockerfile` on every push/PR to `main`. Note: there is no `Dockerfile` at the repo root (only at `phil-server-fapi-leveler/Dockerfile`), so this workflow is currently broken until either moved or pointed at a real path.

Only `feat:`, `fix:`, and `!` / `BREAKING CHANGE` bump the version under release-please.

## NestJS gotchas (from `phil-server-nest/notes.md`)

When a controller method uses `@Res()` / `@Response()` to inject the response object, you take over response handling — Nest's automatic serialization is disabled, and you must call methods on the underlying platform (Express by default, Fastify if swapped) to send the response.
