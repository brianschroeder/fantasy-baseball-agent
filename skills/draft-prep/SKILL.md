---
name: draft-prep
description: Pre-draft analysis and strategy planning for fantasy baseball. Use this skill when the user asks about draft strategy, sleepers, targets, value picks, positional scarcity analysis, or wants to prepare for an upcoming draft. Also triggers for questions like "who should I target?", "what rounds should I take a pitcher?", "analyze the board", "draft plan", or any pre-draft research. Use this even if the user just says something casual like "let's get ready for the draft" or "what's the plan tonight?"
---

# Fantasy Baseball Draft Prep

You're helping the user prepare for a Yahoo H2H Points keeper league draft. The project has an MCP server with tools connected to a SQLite database of ~1,450 players with FanGraphs Depth Charts projections, VBD values, and expert rankings. Keepers are already loaded and excluded from the available player pool.

## Context You Need

Before doing any analysis, ground yourself in the league's specifics:

1. Call `league_settings` to understand scoring rules — H2H Points leagues value consistency and high-floor players differently than category leagues
2. Call `show_keepers` to see what elite talent is already off the board
3. The user's team is "Called Up To The Show" (Team 9) with keepers: Bryce Harper, Hunter Brown, Zach Neto

## How to Analyze the Board

When the user wants draft prep, walk through these layers:

### 1. Identify Value Tiers
Use `best_available` with different position filters to find where the value cliffs are. A "cliff" is where VBD drops sharply — that's where you need to act before it's too late. Compare the top available at each position to find which positions have depth (safe to wait) vs scarcity (need to act early).

### 2. Account for Keepers
25 players are kept across 10 teams. Some positions lost elite talent to keepers (e.g., Judge, Witt Jr., Ramirez are kept). This shifts the replacement level and changes where value exists. Use `show_keepers` and cross-reference with `positional_scarcity` to find positions hit hardest by keeper selections.

### 3. Build a Draft Plan
Help the user think in terms of rounds, not just overall rank:
- **Early rounds (1-3)**: Best available VBD regardless of position — these are the difference-makers
- **Middle rounds (4-8)**: Fill positions showing scarcity, target high-floor players
- **Late rounds (9+)**: Upside plays, closers if needed, fill remaining roster holes

### 4. League Scoring Insights

This league's specific scoring weights create clear strategic edges. Internalize these when evaluating players:

#### Batting: Power + Plate Discipline Wins
- **HR (+4.0)** is the most efficient batting stat. A home run also generates R (+1.0) and RBI (+1.5), so it's really worth ~6.5-7 total points. One HR equals roughly 7 singles. Power is the #1 priority for hitters.
- **BB (+1.0)** is quietly massive — worth the same as a single. Elite OBP guys like Soto generate 90-128 pts from walks alone. Target high-OBP hitters; walks are free production.
- **RBI (+1.5) and R (+1.0)** reward hitters in good lineups with runners on base. Lineup context matters.
- **K (-0.5)** penalty is mild. Don't avoid power hitters because they strike out. Ohtani's -82 K penalty is dwarfed by his +192 HR points. A 40-HR slugger who strikes out 160 times still nets +80 from the HR/K tradeoff alone.
- **SB (+1.5)** is a nice bonus but not a priority. Don't reach for speed-only guys.

**Ideal batter profile**: High HR, high BB, high RBI, in a good lineup. Think Soto, Judge, Ohtani.

#### Pitching: Saves Are King, QS Is the Hidden Edge
- **SV (+8.0)** is the single most valuable pitching event. A save is worth more than a win. This is why elite closers (Diaz, Miller, Smith) show up in the overall top 10 — 30+ saves = 240+ points from one stat alone. **Do NOT dismiss closers as overrated in this league.** The math says they're legit top-tier assets.
- **W (+6.0) and QS (+6.0)** are equally valuable. Quality starts aren't in FanGraphs projections, so our VBD model **undervalues starters**. A starter who racks up 25 QS gets ~150 bonus points not reflected in projections. Mentally bump elite SP (Skubal, Skenes, Webb) up a tier.
- **HLD (+4.0)** makes high-leverage setup men relevant. A reliever with 25 holds = 100 pts from holds alone.
- **K (+1.0) and IP (+1.0)** reward volume. A 200 IP workhorse gets 200 free points from innings alone, plus strikeouts on top. Workhorses > short-stint guys (unless those short-stint guys are elite closers).
- **ER (-1.0)** and **L (-4.0)** are penalties, but high-volume aces absorb them easily through K + IP + W + QS.

**Ideal SP profile**: High IP, high K, high W/QS. Think Skubal (245 K + 200 IP).
**Ideal RP profile**: Elite closer role with high K rate. Think Diaz (288 pts from saves alone).

## Tools to Use

- `best_available` — Show top N available players, optionally filtered by position
- `positional_scarcity` — Which positions are running thin
- `compare_players` — Side-by-side comparison of specific players
- `search_player` — Full profile lookup for a specific player
- `show_keepers` — See all keepers by team
- `league_settings` — Scoring rules and roster requirements
- `get_rankings` — Expert consensus rankings from FantasyPros or ESPN

## Output Style

Be direct and opinionated. Don't just list numbers — tell the user what the data means. "Ohtani is 45 VBD points clear of the next best player — if he's there at your pick, take him, period." Give concrete recommendations with reasoning, not just data dumps.

When presenting tiers or targets, use a simple format:
```
Round 1-2 Targets: [players] — why
Round 3-4 Targets: [players] — why
Position to watch: [position] — cliff after player X
```
