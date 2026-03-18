# Fantasy Baseball Agent

AI-powered draft assistant for Yahoo H2H Points keeper leagues. Built on Claude Code with an MCP server that connects to live Yahoo Fantasy API data, FanGraphs projections, and a local SQLite player database.

## What's in here

- **MCP server** (`mcp_server/`) — tools for live draft tracking, player rankings, roster management
- **Player database** (`data/fantasy_baseball.db`) — ~1,450 players with FanGraphs Depth Charts projections and VBD values
- **Draft plan** (`draft_plan.html`) — war room cheat sheet, open in a browser during the draft
- **Slash commands** (`.claude/commands/baseball/`) — quick actions for live draft use
- **Scripts** (`scripts/`) — data pipeline for refreshing projections

## Setup on a new machine

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Yahoo OAuth

The Yahoo API requires an OAuth token. On a fresh machine:

1. Copy your `oauth2.json` file into the project root (this file is gitignored — don't commit it)
2. If you don't have one, run the auth flow:
   ```bash
   python scripts/yahoo_auth.py
   ```
   This will open a browser, ask you to log into Yahoo, and write `oauth2.json`

### 3. Open in Claude Code

```bash
cd fantasy-baseball-agent
claude
```

Claude Code will auto-detect `.mcp.json` and connect the `fantasy-baseball` MCP server. You should see it listed in `/mcp`.

### 4. Verify the connection

In Claude Code, run:
```
/mcp
```
The `fantasy-baseball` server should show as connected. Then try:
```
/baseball:board
```

## Slash commands

| Command | Usage |
|---|---|
| `/baseball:pick` | On the clock — syncs picks and gives one recommendation |
| `/baseball:taken [player]` | Manually record a pick when Yahoo lags |
| `/baseball:compare [p1, p2]` | Side-by-side player comparison with a verdict |
| `/baseball:round [n]` | Round briefing — targets and urgency warnings |
| `/baseball:board` | Quick refreshed top-20 available |
| `/baseball:scarcity` | Positional scarcity vs your current roster |

## Refreshing player data

To re-pull projections from FanGraphs and rebuild the database:

```bash
python scripts/refresh_projections.py
```

## League info

- **League**: Backyard Baseball
- **Format**: Yahoo H2H Points, 10 teams, keeper league
- **Team**: Called Up To The Show (Team 9)
- **Keepers**: Bryce Harper (1B), Hunter Brown (SP), Zach Neto (SS)
