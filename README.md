# 🚀 Pixel Starships Discord Bot

An unofficial companion **Discord bot** for [Pixel Starships](https://www.pixelstarships.com)
(by Savy Soda). It reads live data from the public PSS API and exposes it
through clean Discord slash commands: player search, fleet rankings, crew
stats & prestige recipes, item lookups and the daily offers.

> Not affiliated with or endorsed by Savy Soda. This bot only **reads**
> public game data — it does **not** automate gameplay.

---

## ✨ Commands

| Command | What it does |
|---|---|
| `/player <name>` | Search a player: trophies, fleet, last seen, PvP record. |
| `/fleet-top [count]` | Top fleets ranked by trophies. |
| `/crew <name>` | Crew stats, ability, rarity. |
| `/prestige <crew1> <crew2>` | What two crew members prestige into. |
| `/prestige-recipes <crew>` | Every recipe that produces a crew. |
| `/item <name>` | Item details, bonus and catalogue price. |
| `/price <name>` | 30-day market price trend with a sparkline. |
| `/crew-top <stat>` | Best crew ranked by a chosen stat. |
| `/collection [name]` | Collection combo bonus and member crew. |
| `/room <name>` | Ship room stats across its levels. |
| `/daily` | Today's sale, shop offer, daily reward and news. |
| `/top-players [count]` | Global player leaderboard *(needs auth — see below)*. |
| `/help`, `/about`, `/ping` | Meta commands. |

Most commands work out of the box. A few endpoints (global player ladder,
fleet member lists, ship inspection, marketplace) require an authenticated
device token — see [Authenticated features](#-authenticated-features).

---

## 🛠️ Quick start (local)

```bash
git clone https://github.com/mkultra110/botteste.git BOTTESTE
cd BOTTESTE
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env and add your DISCORD_TOKEN
python bot.py
```

### Getting a Discord bot token
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → **Bot** → **Reset Token** → copy it into `.env`.
3. Under **OAuth2 → URL Generator**, tick `bot` + `applications.commands`,
   then invite the bot to your server with the generated URL.

No privileged intents are required — the bot only uses slash commands.

For instant command updates while developing, set `DISCORD_GUILD_ID` to your
test server's ID (right-click the server → *Copy Server ID*). Leave it empty
for global commands in production.

---

## 🖥️ Deploy on a VPS (Ubuntu — e.g. OVH)

SSH into your server, then:

```bash
git clone https://github.com/mkultra110/botteste.git BOTTESTE
cd BOTTESTE
bash deploy/install.sh          # installs Python, venv & dependencies
nano .env                       # paste your DISCORD_TOKEN
```

Run it once to check it connects (`Ctrl+C` to stop):

```bash
.venv/bin/python bot.py
```

Then install it as a **systemd service** so it runs 24/7 and restarts on reboot:

```bash
sudo cp deploy/pss-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pss-bot
sudo systemctl status pss-bot          # check it's running
journalctl -u pss-bot -f               # follow the logs
```

> The unit file assumes the repo lives at `/home/ubuntu/BOTTESTE`. Edit
> `deploy/pss-bot.service` if you cloned it elsewhere or use another user.

To update later:

```bash
bash deploy/update.sh
```

### Or run with Docker

```bash
cp .env.example .env     # add your DISCORD_TOKEN
docker compose up -d --build
docker compose logs -f
```

---

## 🧪 Tests

Pure-logic unit tests (no network) cover the formatting helpers, cache
indexing and the LiveOps/item parsing:

```bash
pip install pytest
pytest -q
```

CI runs them on Python 3.10–3.12 (`.github/workflows/ci.yml`).

To verify the whole data path against the **live** PSS API (no Discord
connection needed) before deploying:

```bash
python tests/smoke_live.py
```

---

## 🔐 Authenticated features

The public PSS API serves almost everything anonymously. A small set of
endpoints (`/top-players`, fleet member lists, marketplace, ship inspection)
require an authenticated **device token**, which is derived from a checksum
key. If you have that community key, put it in `.env`:

```
PSS_DEVICE_CHECKSUM_KEY=...
```

The bot then unlocks those commands automatically. Without it, everything
else keeps working and the locked commands simply report that they're
disabled.

---

## 🔒 Security notes

- **Never commit your `.env`** — it holds your bot token. It's already in
  `.gitignore`.
- If a token ever leaks, reset it in the Discord Developer Portal.

---

## 📁 Project layout

```
bot.py               # entry point, loads cogs, syncs slash commands
config.py            # env-based configuration
pss/
  api.py             # async PSS API client (XML), optional auth
  cache.py           # crew/item/room catalogue with name<->id lookup
  formatting.py      # markup cleaning & embed helpers
cogs/
  general.py         # /help /about /ping
  players.py         # /player
  fleets.py          # /fleet-top
  crew.py            # /crew /prestige /prestige-recipes
  items.py           # /item
  daily.py           # /daily /top-players
deploy/
  install.sh         # VPS installer
  update.sh          # pull + restart
  pss-bot.service    # systemd unit
```

---

*Made for the Pixel Starships community. 🛸*
