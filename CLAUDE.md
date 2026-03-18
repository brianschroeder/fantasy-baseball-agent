# Fantasy Baseball Draft Assistant

You are helping with a live fantasy baseball draft. This project has MCP tools
for accessing Yahoo Fantasy API data, player projections, and draft tracking.

## League Info
- Yahoo H2H Points keeper league
- League key: 469.l.3508, Team 9
- Use `league_settings` tool to see current scoring and roster positions

## Available MCP Tools

### Draft Tools
- `best_available` - Get top available players by VBD. Use position filter (C/1B/2B/SS/3B/OF/SP/RP) or leave blank for all.
- `compare_players` - Compare 2-4 players side-by-side. Pass comma-separated names.
- `search_player` - Look up a specific player's full profile.
- `record_pick` - Mark a player as drafted when Yahoo isn't updating fast enough.

### Roster Tools
- `my_roster` - Show current draft picks and unfilled roster slots.
- `roster_needs` - Show which positions still need to be filled and best available at each.
- `positional_scarcity` - Show remaining quality at each position to identify urgency.
- `show_keepers` - Show all keepers across the league, grouped by team. Optional team filter.

### Data Tools
- `refresh_draft` - Poll Yahoo API for new draft picks. Run between rounds.
- `league_settings` - Show league scoring settings and roster positions.
- `get_rankings` - Show expert rankings from FantasyPros or ESPN.

## How to Help During the Draft
1. Before each pick, use `best_available` to see top options
2. Use `roster_needs` to check what positions are still needed
3. Use `compare_players` when deciding between 2-3 options
4. Use `positional_scarcity` to identify positions running thin
5. Use `refresh_draft` between rounds to see what others picked
6. Use `record_pick` if you need to manually track a pick

## H2H Points Strategy
- Consistent producers > boom/bust (weekly matchups reward floor over ceiling)
- High-K pitchers are premium in points leagues (strikeouts score well)
- Don't overpay for closers — saves less valuable in points format
- Balanced roster — don't punt any position
- Monitor positional scarcity — if quality drops at a position, act before it's too late
- VBD is the key metric — it measures value above what you'd get by waiting

## Data Sources
- **FanGraphs Depth Charts**: Primary projection source (Steamer+ZiPS blend)
- **FantasyPros**: Expert consensus rankings for H2H Points leagues
- **ESPN**: Additional ranking perspective
- **Yahoo API**: Live draft data, ownership %, roster management
