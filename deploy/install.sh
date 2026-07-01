#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-shot installer for the Pixel Starships Discord bot on an Ubuntu VPS.
# Run it from the repository root:  bash deploy/install.sh
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "==> Installing system packages (python3, venv, git) ..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip git
fi

echo "==> Creating virtual environment ..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
    echo "==> Creating .env from template (edit it and add your DISCORD_TOKEN!)"
    cp .env.example .env
fi

echo
echo "==> Done. Next steps:"
echo "    1. Edit .env and paste your DISCORD_TOKEN"
echo "         nano $REPO_DIR/.env"
echo "    2. Test it runs:"
echo "         .venv/bin/python bot.py"
echo "    3. (Optional) install as a service so it runs 24/7:"
echo "         sudo cp deploy/pss-bot.service /etc/systemd/system/"
echo "         sudo systemctl daemon-reload"
echo "         sudo systemctl enable --now pss-bot"
echo "         sudo systemctl status pss-bot"
