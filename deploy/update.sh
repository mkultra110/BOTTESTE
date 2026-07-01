#!/usr/bin/env bash
# Pull the latest code and restart the bot service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "==> Pulling latest changes ..."
git pull --ff-only

echo "==> Updating dependencies ..."
.venv/bin/pip install -r requirements.txt

echo "==> Restarting service ..."
sudo systemctl restart pss-bot
sudo systemctl status pss-bot --no-pager
