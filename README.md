# Running Coach

An AI-powered running coach that connects to your Strava account and gives data-driven training advice via a Telegram bot or CLI. Powered by Claude (Anthropic) and the Strava API.

## Features

- Analyses your actual Strava training history before giving advice
- Flags injury risk patterns (volume spikes, too many hard days, no recovery)
- Suggests specific workouts with targets (pace, distance, rest intervals)
- Tracks conversation history within a session for follow-up questions
- Available via Telegram bot (hosted) or CLI (local)

## Architecture

```
bot.py / cli.py          ← entry points
coach/session.py         ← Claude agent + agentic tool loop
strava_mcp/server.py     ← MCP server exposing Strava as tools (subprocess)
strava_mcp/strava_client.py  ← Strava API HTTP client
config.py                ← credentials + token management
auth.py                  ← one-time Strava OAuth flow
```

Claude calls Strava tools via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). The MCP server runs as a subprocess communicating over stdio.

## Prerequisites

- Python 3.11+
- A [Strava account](https://www.strava.com) with activities logged
- An [Anthropic API key](https://console.anthropic.com)
- A Telegram bot token (for the bot; optional for CLI-only use)

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd running-coach
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create a Strava app

1. Go to [strava.com/settings/api](https://www.strava.com/settings/api)
2. Create a new application
3. Set **Authorization Callback Domain** to `localhost`
4. Note your **Client ID** and **Client Secret**

### 3. Create a Telegram bot (optional — skip if using CLI only)

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token
4. Message [@userinfobot](https://t.me/userinfobot) to get your Telegram user ID

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in all values:

```env
ANTHROPIC_API_KEY=""         # console.anthropic.com
STRAVA_CLIENT_ID=""          # strava.com/settings/api
STRAVA_CLIENT_SECRET=""      # strava.com/settings/api
TELEGRAM_BOT_TOKEN=""        # from @BotFather
TELEGRAM_ALLOWED_USER_ID=""  # from @userinfobot
```

### 5. Authenticate with Strava

```bash
python auth.py
```

This opens a browser for OAuth authorisation and saves tokens to `.tokens.json`.

## Running

### Telegram bot

```bash
python bot.py
```

Send your bot a message on Telegram. Use `/reset` to clear conversation history.

### CLI

```bash
python cli.py
```

Type your questions at the prompt. Type `quit` to exit.

## Deploying to Railway

### 1. Push to GitHub

```bash
git add .
git commit -m "Initial commit"
git push
```

### 2. Create a Railway project

1. Go to [railway.app](https://railway.app) and create a new project
2. Connect your GitHub repository
3. Railway will auto-detect Python and install `requirements.txt`

### 3. Set environment variables in Railway

In your Railway service → **Variables**, add everything from `.env` plus your Strava tokens (since `.tokens.json` is not committed):

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `STRAVA_CLIENT_ID` | [strava.com/settings/api](https://www.strava.com/settings/api) |
| `STRAVA_CLIENT_SECRET` | [strava.com/settings/api](https://www.strava.com/settings/api) |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_USER_ID` | [@userinfobot](https://t.me/userinfobot) |
| `STRAVA_ACCESS_TOKEN` | from local `.tokens.json` → `access_token` |
| `STRAVA_REFRESH_TOKEN` | from local `.tokens.json` → `refresh_token` |
| `STRAVA_TOKEN_EXPIRES_AT` | from local `.tokens.json` → `expires_at` |

Run `auth.py` locally first to generate `.tokens.json`, then copy the values above.

### 4. Deploy

Railway deploys automatically on every push to your connected branch. The `Procfile` tells Railway to run `python bot.py` as a worker process.

## Project Structure

```
running-coach/
├── auth.py                      # One-time Strava OAuth flow
├── cli.py                       # CLI entry point
├── bot.py                       # Telegram bot entry point
├── config.py                    # Credential + token management
├── Procfile                     # Railway start command
├── requirements.txt
├── .env.example                 # Environment variable template
├── coach/
│   ├── agent.py                 # CLI agent loop
│   └── session.py               # Reusable session (used by bot)
└── strava_mcp/
    ├── server.py                # MCP server (Strava tools)
    └── strava_client.py         # Strava API HTTP client
```

## Available Strava Tools

The MCP server exposes these tools to Claude:

| Tool | Description |
|---|---|
| `get_athlete` | Athlete profile (name, weight, FTP, measurement preference) |
| `get_athlete_stats` | Recent, YTD, and lifetime run totals |
| `get_athlete_zones` | Configured HR and power zones |
| `list_activities` | Paginated activity list with filtering by date range |
| `get_activity` | Full activity details including splits and best efforts |
| `get_activity_laps` | Lap-by-lap breakdown (useful for intervals) |
| `get_activity_zones` | HR and pace zone distribution for an activity |


## To-do

- Add DB functionality to persist history across sessions.