#!/usr/bin/env bash
# `make deploy-server`, or `make deploy` with DEPLOY = server (docs/11 §2b): ship this
# working tree to the home server over Tailscale SSH and restart it (docs/16 sets the
# server up). Run from Git Bash (Windows) or any POSIX shell with tar, ssh and curl.
#
#   1. build the SPA here (the server has no Node)
#   2. stream the tree into a fresh /srv/hb/app.new, minus this checkout's .env, its
#      data and the dev-only folders
#   3. move the server's own .env and backend/.venv into app.new, swap it into place:
#      a file deleted or renamed here never lingers there (a stale migration
#      would give alembic two heads)
#   4. uv sync, restart hb, then poll the health endpoint through the
#      `tailscale serve` front door (APP_BASE_URL in the server's .env) for up to 20 s
#
# HB_SSH overrides the target (default hb@hb, the MagicDNS name): set it in config.mk,
# which the Makefile exports, or in the environment.
set -euo pipefail

cd "$(dirname "$0")/.."
target="${HB_SSH:-hb@hb}"

(cd frontend && npm run build)

ssh "$target" 'rm -rf /srv/hb/app.new && mkdir /srv/hb/app.new'
tar --exclude=node_modules --exclude=.venv --exclude=__pycache__ \
    --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.git --exclude=.env \
    --exclude=./backend/data --exclude=./data --exclude=./.claude \
    --exclude=./home-server.local.md --exclude=./CLAUDE.local.md --exclude=./config.mk -cf - . \
  | ssh "$target" 'tar -xf - -C /srv/hb/app.new'

ssh "$target" 'bash -s' <<'REMOTE'
set -euo pipefail
cd /srv/hb
[ -f app/.env ] || { echo "deploy failed: /srv/hb/app/.env is missing on the server (docs/16 section 6)" >&2; exit 1; }
mv app/.env app.new/.env
if [ -d app/backend/.venv ]; then mv app/backend/.venv app.new/backend/.venv; fi
rm -rf app.old
mv app app.old
mv app.new app
rm -rf app.old
cd app/backend
"$HOME/.local/bin/uv" sync
sudo -n systemctl restart hb
REMOTE

url="$(ssh "$target" "sed -n 's/^APP_BASE_URL=//p' /srv/hb/app/.env" | tr -d '\r')"
[ -n "$url" ] || { echo "deploy failed: no APP_BASE_URL in the server's .env" >&2; exit 1; }
for _ in $(seq 20); do
    sleep 1
    if curl -fsS -m 5 "$url/api/ops/health" >/dev/null 2>&1; then
        echo "deployed: $url"
        exit 0
    fi
done
echo "deploy failed: nothing healthy at $url - check 'ssh $target journalctl -u hb -n 50'" >&2
exit 1
