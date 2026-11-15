#!/usr/bin/env bash
# `make deploy` (PROMPT.md §12): copy the project to the Vultr VM over SSH, build and start the stack there, run
# the migrations, and smoke-check the public URL. Settings come from .env.deploy (see .env.deploy.example) or the
# environment. DRY_RUN=1 prints every command instead of running it.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.deploy ]; then set -a; . ./.env.deploy; set +a; fi
: "${DEPLOY_HOST:?Set DEPLOY_HOST (the VM IP) in .env.deploy}"
: "${DOMAIN:?Set DOMAIN (the public host name) in .env.deploy}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_DIR="${DEPLOY_DIR:-hospital-twin}"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [ -n "${DEPLOY_KEY:-}" ]; then SSH_OPTS+=(-i "$DEPLOY_KEY"); fi
TARGET="$DEPLOY_USER@$DEPLOY_HOST"
COMPOSE="docker compose -f infra/docker-compose.prod.yml --env-file .env"

run() { if [ "${DRY_RUN:-0}" = 1 ]; then echo "+ $*"; else "$@"; fi; }
remote() { run ssh "${SSH_OPTS[@]}" "$TARGET" "cd $DEPLOY_DIR && $*"; }

echo "==> Checking the VM ($TARGET)"
run ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p $DEPLOY_DIR && docker --version"

echo "==> Secrets: the VM keeps its own .env (never copied from git)"
if [ "${DRY_RUN:-0}" != 1 ] && ! ssh "${SSH_OPTS[@]}" "$TARGET" "test -f $DEPLOY_DIR/.env"; then
  if [ -f .env.prod ]; then
    scp "${SSH_OPTS[@]}" .env.prod "$TARGET:$DEPLOY_DIR/.env"
    ssh "${SSH_OPTS[@]}" "$TARGET" "chmod 600 $DEPLOY_DIR/.env"
  else
    echo "No $DEPLOY_DIR/.env on the VM and no local .env.prod. Create one (DATABASE_URL, DOMAIN, GEMINI_*)." >&2
    exit 1
  fi
fi

echo "==> Copying the project"
run rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --include='data/' --include='data/ml/' --include='data/ml/***' \
  --exclude='.git/' --exclude='.github/' --exclude='node_modules/' --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='.mypy_cache/' --exclude='.ruff_cache/' --exclude='.pytest_cache/' --exclude='data/*' \
  --exclude='.env' --exclude='.env.*' --exclude='reference/' --exclude='docs/evidence/' --exclude='frontend/dist/' \
  --exclude='frontend/test-results/' --exclude='frontend/playwright-report/' --exclude='docs/demo.webm' \
  ./ "$TARGET:$DEPLOY_DIR/"

echo "==> Building and starting the stack"
remote "$COMPOSE up -d --build"

echo "==> Migrations"
remote "$COMPOSE run --rm --no-deps backend python -m twin.db.migrate"

echo "==> Patients in the database"
COUNT_PATIENTS="import asyncio,asyncpg,os
async def n():
    c=await asyncpg.connect(os.environ['DATABASE_URL']); print(await c.fetchval('select count(*) from patients'))
asyncio.run(n())"
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "+ (count patients on the VM)"
else
  COUNT="$(ssh "${SSH_OPTS[@]}" "$TARGET" "cd $DEPLOY_DIR && $COMPOSE run --rm --no-deps backend python -c \"$COUNT_PATIENTS\"" | tail -1)"
  if [ "${COUNT:-0}" = 0 ]; then
    echo "The database has no patients: run make seed-prod (from your Mac), then make deploy again." >&2
    exit 1
  fi
  echo "$COUNT patients"
fi

echo "==> Smoke check of https://$DOMAIN (certificates can take a minute)"
if [ "${DRY_RUN:-0}" = 1 ]; then echo "+ python -m twin.ops.smoke https://$DOMAIN"; exit 0; fi
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if env -u VIRTUAL_ENV uv run --directory backend python -m twin.ops.smoke "https://$DOMAIN"; then
    echo "Deployed: https://$DOMAIN"
    exit 0
  fi
  echo "Not ready yet (attempt $attempt of 10); waiting 15 s"
  sleep 15
done
echo "The smoke check did not pass. Look at: ssh $TARGET 'cd $DEPLOY_DIR && $COMPOSE logs --tail=100'" >&2
exit 1
