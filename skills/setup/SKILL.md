---
name: setup
description: "Verify and auto-fix the project's development environment. Checks Python 3.13+, uv virtualenvs, Docker + OpenSearch, Node, and .env files, then auto-fixes everything project-level. Use when setting up the project, getting it running, or verifying the environment. Triggers on: set up the project, setup environment, get this running, verify my environment, /setup."
user-invocable: true
---

# Project Setup

Verifies every prerequisite needed to run this repo and auto-fixes everything
that can be safely fixed at the project level.

---

## The Job

Get the project into a runnable state by running `skills/setup/setup.sh`.

---

## Flow

1. **Check.** Run:

   ```bash
   bash skills/setup/setup.sh check
   ```

   This prints a pass/fail summary table and exits non-zero if anything fails.

2. **If everything passed**, report that the environment is ready and stop.

3. **If anything failed**, run the auto-fixer:

   ```bash
   bash skills/setup/setup.sh fix
   ```

4. **Re-check** to confirm:

   ```bash
   bash skills/setup/setup.sh check
   ```

5. **If checks still fail**, the remaining failures are system-level
   prerequisites the script will not auto-install. Surface the exact
   instructions to the user:

   - **`uv` not installed** — https://docs.astral.sh/uv/getting-started/installation/
   - **Docker daemon not running** — start Docker Desktop
   - **Node not installed / too old** — https://nodejs.org/ (need >=20)
   - **`.env` placeholder values** — the user must fill in real API keys in
     `agent/.env` and `index/.env`

---

## Notes

- `check` is read-only and safe to run anytime.
- `fix` is idempotent — safe to run repeatedly.
- The script auto-detects `docker compose` vs `docker-compose`.
- `fix` only handles project-level items (dependency syncs, Python install via
  uv, image pull, container start, `.env` creation, `npm install`). System-level
  prerequisites (`uv`, Docker, Node) are reported, never auto-installed.
