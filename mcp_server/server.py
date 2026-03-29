"""MCP server for Fantasy Baseball Draft Assistant.

Provides tools for draft-day decision making: best available players,
roster needs, positional scarcity analysis, and live draft tracking
via Yahoo Fantasy API.

Run with:  python -m mcp_server.server
Transport: stdio (for Claude Code integration)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Ensure project root is importable
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.db import DB
from mcp_server.yahoo_client import YahooClient
from mcp_server.draft_state import DraftState
from mcp_server.projections import ProjectionEngine

# ── Initialise shared components ──────────────────────────────────────

db_path = str(project_root / "data" / "fantasy_baseball.db")
db = DB(db_path)

# Yahoo client is optional — OAuth token may not be available yet
yahoo: YahooClient | None = None
draft_state: DraftState | None = None
try:
    oauth_path = str(project_root / "oauth2.json")
    if os.path.exists(oauth_path):
        yahoo = YahooClient(oauth_path)
        draft_state = DraftState(db, yahoo)
    else:
        # Still create DraftState for offline DB queries
        draft_state = DraftState(db, yahoo=None)
except Exception as exc:
    print(f"Warning: Yahoo client init failed: {exc}", file=sys.stderr)
    draft_state = DraftState(db, yahoo=None)

projection_engine = ProjectionEngine(db)

# ── Create MCP server ────────────────────────────────────────────────

mcp = FastMCP("Fantasy Baseball Draft Assistant")


# ═══════════════════════════════════════════════════════════════════════
# Draft tools
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def best_available(position: str = None, count: int = 10) -> str:
    """Get the best available undrafted players ranked by VBD value.

    Args:
        position: Filter by position (C, 1B, 2B, SS, 3B, OF, SP, RP, DH). None for all positions.
        count: Number of players to return (default 10).
    """
    players = db.get_best_available(position=position, limit=count)
    if not players:
        return "No available players found." + (
            f" (position filter: {position})" if position else ""
        )

    header = f"Top {len(players)} Available"
    if position:
        header += f" ({position})"

    lines = [header]
    lines.append(
        f"{'#':>4}  {'Name':<25} {'Team':<5} {'Pos':<12} "
        f"{'Proj Pts':>8} {'VBD':>7} {'FP#':>4} {'ESPN#':>5}"
    )
    lines.append("-" * 78)

    for i, p in enumerate(players, 1):
        pos_list = json.loads(p["positions"]) if p.get("positions") else []
        pos_str = ",".join(pos_list)
        proj = p.get("projected_points") or 0
        vbd = p.get("vbd_value") or 0
        fp_rank = p.get("fantasypros_rank")
        espn_rank = p.get("espn_rank")

        lines.append(
            f"{i:>4}  {p['name']:<25} {p.get('team') or '':<5} {pos_str:<12} "
            f"{proj:>8.1f} {vbd:>7.1f} "
            f"{fp_rank if fp_rank else '-':>4} "
            f"{espn_rank if espn_rank else '-':>5}"
        )
    return "\n".join(lines)


@mcp.tool()
def compare_players(names: str) -> str:
    """Compare two or more players side by side.

    Args:
        names: Comma-separated player names (e.g. "Aaron Judge, Juan Soto, Shohei Ohtani").
    """
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if len(name_list) < 2:
        return "Please provide at least two comma-separated player names."

    players = draft_state.compare_players(name_list)

    lines = ["Player Comparison:", ""]

    # Header row
    col_w = 22
    labels = [
        "Name", "Team", "Positions", "Proj Pts", "VBD",
        "FP Rank", "ESPN Rank", "Ownership %", "Status",
    ]
    lines.append(f"{'':>14}  " + "  ".join(f"{p.get('name', p.get('error', '?')):<{col_w}}" for p in players))
    lines.append("-" * (16 + (col_w + 2) * len(players)))

    def _val(p, key, fmt=None):
        if "error" in p:
            return "N/A"
        v = p.get(key)
        if v is None:
            return "-"
        if fmt:
            return fmt(v)
        return str(v)

    def _positions(p):
        if "error" in p:
            return "N/A"
        pos = p.get("positions")
        if not pos:
            return "-"
        return ",".join(json.loads(pos))

    rows = [
        ("Team", lambda p: _val(p, "team")),
        ("Positions", _positions),
        ("Proj Pts", lambda p: _val(p, "projected_points", lambda v: f"{v:.1f}")),
        ("VBD", lambda p: _val(p, "vbd_value", lambda v: f"{v:.1f}")),
        ("FP Rank", lambda p: _val(p, "fantasypros_rank")),
        ("ESPN Rank", lambda p: _val(p, "espn_rank")),
        ("Ownership", lambda p: _val(p, "ownership_pct", lambda v: f"{v:.1f}%")),
        ("Status", lambda p: _val(p, "status")),
    ]

    for label, fn in rows:
        line = f"{label:>14}  " + "  ".join(f"{fn(p):<{col_w}}" for p in players)
        lines.append(line)

    # Check if any are already drafted
    drafted_keys = db.get_drafted_player_keys()
    avail_line = f"{'Available':>14}  "
    for p in players:
        if "error" in p:
            avail_line += f"{'N/A':<{col_w}}  "
        elif p.get("player_key") in drafted_keys:
            avail_line += f"{'DRAFTED':<{col_w}}  "
        else:
            avail_line += f"{'Yes':<{col_w}}  "
    lines.append(avail_line)

    return "\n".join(lines)


@mcp.tool()
def search_player(name: str) -> str:
    """Search for a player by name and show their full profile.

    Args:
        name: Full or partial player name to search for.
    """
    matches = db.get_player(name)
    if not matches:
        return f"No players found matching '{name}'."

    drafted_keys = db.get_drafted_player_keys()
    lines = [f"Found {len(matches)} player(s) matching '{name}':", ""]

    for p in matches:
        pos_list = json.loads(p["positions"]) if p.get("positions") else []
        is_drafted = p["player_key"] in drafted_keys

        lines.append(f"  {p['name']}")
        lines.append(f"    Team:        {p.get('team') or '-'}")
        lines.append(f"    Positions:   {', '.join(pos_list) if pos_list else '-'}")
        lines.append(f"    Proj Pts:    {p['projected_points']:.1f}" if p.get("projected_points") else "    Proj Pts:    -")
        lines.append(f"    VBD:         {p['vbd_value']:.1f}" if p.get("vbd_value") else "    VBD:         -")
        lines.append(f"    FP Rank:     {p.get('fantasypros_rank') or '-'}")
        lines.append(f"    ESPN Rank:   {p.get('espn_rank') or '-'}")
        lines.append(f"    Ownership:   {p['ownership_pct']:.1f}%" if p.get("ownership_pct") else "    Ownership:   -")
        lines.append(f"    Status:      {p.get('status') or 'Healthy'}")
        lines.append(f"    Drafted:     {'YES' if is_drafted else 'No'}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def record_pick(player: str, team: str = None, round: int = None) -> str:
    """Manually record a draft pick (when Yahoo is slow to update).

    Args:
        player: Player name (partial match supported).
        team: Team/manager name who drafted the player.
        round: Round number (auto-estimated if omitted).
    """
    result = draft_state.record_manual_pick(
        player_name=player,
        team_name=team,
        round_num=round,
    )
    if "error" in result:
        return result["error"]

    return (
        f"Recorded: {result['player_name']} drafted by {result['team_name']} "
        f"(Round {result['round']}, Pick #{result['pick_number']})"
    )


# ═══════════════════════════════════════════════════════════════════════
# Roster tools
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def my_roster() -> str:
    """Show my current draft picks grouped by position with unfilled slots."""
    picks = draft_state.get_my_roster()

    if not picks:
        return "No picks yet."

    # Group by position
    by_position: dict[str, list] = {}
    for pick in picks:
        matches = db.get_player(pick["player_name"])
        if matches:
            player = matches[0]
            pos_list = json.loads(player["positions"]) if player.get("positions") else ["?"]
            primary_pos = pos_list[0] if pos_list else "?"
        else:
            primary_pos = "?"

        by_position.setdefault(primary_pos, []).append(pick)

    lines = ["My Roster:", ""]
    lines.append(f"{'Pos':<5} {'Rd':>3} {'Pick#':>5}  {'Player':<25} {'Keeper':>7}")
    lines.append("-" * 52)

    for pos in ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP", "DH", "?"]:
        if pos not in by_position:
            continue
        for pick in by_position[pos]:
            keeper_str = "Yes" if pick.get("is_keeper") else ""
            lines.append(
                f"{pos:<5} {pick['round']:>3} {pick['pick_number']:>5}  "
                f"{pick['player_name']:<25} {keeper_str:>7}"
            )

    # Show unfilled roster slots
    roster_positions = db.get_roster_positions()
    if roster_positions:
        lines.append("")
        lines.append("Unfilled Slots:")
        filled_counts: dict[str, int] = {}
        for pos, plist in by_position.items():
            filled_counts[pos] = len(plist)

        for rp in roster_positions:
            pos = rp["position"]
            needed = rp["count"]
            have = filled_counts.get(pos, 0)
            if have < needed:
                lines.append(f"  {pos}: {needed - have} remaining (have {have}/{needed})")

    lines.append(f"\nTotal picks: {len(picks)}")
    return "\n".join(lines)


@mcp.tool()
def roster_needs() -> str:
    """Show positions still needed with the best available player at each."""
    needs = draft_state.get_roster_needs()

    if not needs:
        return "All roster positions filled (or no roster config loaded)."

    lines = ["Roster Needs:", ""]
    for need in needs:
        lines.append(
            f"  {need['position']}: need {need['remaining']} more "
            f"(have {need['filled']}/{need['needed']})"
        )
        if need.get("best_available"):
            for j, ba in enumerate(need["best_available"], 1):
                proj = ba.get("projected_points") or 0
                vbd = ba.get("vbd_value") or 0
                lines.append(
                    f"      {j}. {ba['name']:<22} "
                    f"Proj: {proj:>7.1f}  VBD: {vbd:>6.1f}"
                )
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def positional_scarcity() -> str:
    """Analyse remaining player quality at each position to identify urgency.

    Positions with fewer quality players remaining should be prioritised.
    """
    scarcity = draft_state.get_positional_scarcity()

    lines = ["Positional Scarcity (sorted by fewest available):", ""]
    lines.append(f"{'Pos':<5} {'Available':>9} {'Avg VBD':>8}  {'Urgency'}")
    lines.append("-" * 40)

    # Determine urgency thresholds
    counts = [s["available_count"] for s in scarcity if s["available_count"] > 0]
    if counts:
        low_threshold = sorted(counts)[len(counts) // 3] if len(counts) >= 3 else counts[0]
    else:
        low_threshold = 0

    for s in scarcity:
        count = s["available_count"]
        avg_vbd = s["avg_vbd"]
        if count == 0:
            urgency = "EMPTY"
        elif count <= low_threshold:
            urgency = "HIGH"
        elif avg_vbd < 0:
            urgency = "MEDIUM"
        else:
            urgency = "low"

        lines.append(
            f"{s['position']:<5} {count:>9} {avg_vbd:>8.1f}  {urgency}"
        )

    return "\n".join(lines)


@mcp.tool()
def show_keepers(team: str = None) -> str:
    """Show all keepers across the league, grouped by team.

    Args:
        team: Filter to a specific team name (partial match). None for all teams.
    """
    keepers = db.get_all_keepers()
    if not keepers:
        return "No keeper data loaded. Run prefetch_data.py or refresh keepers from Yahoo."

    # Group by team
    by_team: dict[str, list[dict]] = {}
    for k in keepers:
        team_name = k.get("team_name", "Unknown")
        by_team.setdefault(team_name, []).append(k)

    if team:
        # Filter by team name (partial match)
        team_lower = team.lower()
        by_team = {
            tn: players
            for tn, players in by_team.items()
            if team_lower in tn.lower()
        }
        if not by_team:
            return f"No keepers found for team matching '{team}'."

    lines = ["League Keepers:", ""]
    for team_name in sorted(by_team.keys()):
        players = by_team[team_name]
        lines.append(f"  {team_name}:")
        for k in players:
            # Look up player details
            matches = db.get_player(k["player_name"])
            if matches:
                p = matches[0]
                proj = f"{p['projected_points']:.1f}" if p.get("projected_points") else "-"
                vbd = f"{p['vbd_value']:.1f}" if p.get("vbd_value") else "-"
                pos_list = json.loads(p["positions"]) if p.get("positions") else []
                pos_str = ",".join(pos_list) if pos_list else "?"
                lines.append(f"    - {k['player_name']:<22} {pos_str:<10} Pts: {proj:>7}  VBD: {vbd:>7}")
            else:
                lines.append(f"    - {k['player_name']}")
        lines.append("")

    lines.append(f"Total keepers: {len(keepers)}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Data tools
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def refresh_draft() -> str:
    """Poll Yahoo Fantasy API for new draft picks and update the database."""
    if yahoo is None:
        return "Yahoo client not available. Use record_pick() to manually track picks."

    try:
        new_picks = draft_state.refresh_draft_results()
    except Exception as exc:
        return f"Error refreshing draft results: {exc}"

    if not new_picks:
        return "No new picks since last refresh."

    lines = [f"{len(new_picks)} new pick(s):", ""]
    lines.append(f"{'Pick#':>5} {'Rd':>3}  {'Player':<25} {'Team':<20} {'Keeper':>7}")
    lines.append("-" * 65)

    for pick in new_picks:
        keeper_str = "Yes" if pick.get("is_keeper") else ""
        lines.append(
            f"{pick['pick_number']:>5} {pick['round']:>3}  "
            f"{pick['player_name']:<25} {pick['team_name']:<20} {keeper_str:>7}"
        )

    return "\n".join(lines)


@mcp.tool()
def league_settings() -> str:
    """Show league scoring rules, roster positions, and team count."""
    lines = ["League Settings:", ""]

    # General settings
    setting_keys = [
        ("name", "League Name"),
        ("num_teams", "Teams"),
        ("scoring_type", "Scoring"),
        ("draft_type", "Draft Type"),
        ("is_auction_draft", "Auction"),
        ("season", "Season"),
    ]
    for key, label in setting_keys:
        val = db.get_league_setting(key)
        if val is not None:
            lines.append(f"  {label + ':':<18} {val}")

    # Roster positions
    roster_pos = db.get_roster_positions()
    if roster_pos:
        lines.append("")
        lines.append("Roster Positions:")
        for rp in roster_pos:
            lines.append(f"  {rp['position']:<5} x{rp['count']}")

    # Stat modifiers (scoring)
    modifiers = db.get_stat_modifiers()
    if modifiers:
        lines.append("")
        lines.append("Scoring (Stat Modifiers):")
        # Group by position type
        batting = [m for m in modifiers if m.get("position_type") == "B"]
        pitching = [m for m in modifiers if m.get("position_type") == "P"]
        other = [m for m in modifiers if m.get("position_type") not in ("B", "P")]

        for group_label, group in [("  Batting:", batting), ("  Pitching:", pitching), ("  Other:", other)]:
            if group:
                lines.append(group_label)
                for m in group:
                    sign = "+" if m["point_value"] >= 0 else ""
                    display = m.get("display_name") or m.get("stat_name") or f"stat_{m['stat_id']}"
                    lines.append(
                        f"    {display:<25} {sign}{m['point_value']:.2f}"
                    )

    if len(lines) <= 2:
        return "No league settings loaded. Use refresh or load settings from Yahoo first."

    return "\n".join(lines)


@mcp.tool()
def get_rankings(source: str = "fantasypros", position: str = None) -> str:
    """Show expert rankings from FantasyPros or ESPN.

    Args:
        source: Ranking source - "fantasypros" or "espn".
        position: Filter by position (C, 1B, 2B, SS, 3B, OF, SP, RP). None for overall.
    """
    source = source.lower().strip()
    if source not in ("fantasypros", "espn"):
        return "Source must be 'fantasypros' or 'espn'."

    rank_col = "fantasypros_rank" if source == "fantasypros" else "espn_rank"

    # Query players that have a rank from this source
    if position:
        rows = db.conn.execute(
            f"""SELECT * FROM players
                WHERE {rank_col} IS NOT NULL
                  AND positions LIKE ?
                ORDER BY {rank_col} ASC
                LIMIT 30""",
            (f"%{position}%",),
        ).fetchall()
    else:
        rows = db.conn.execute(
            f"""SELECT * FROM players
                WHERE {rank_col} IS NOT NULL
                ORDER BY {rank_col} ASC
                LIMIT 30""",
        ).fetchall()

    players = [dict(r) for r in rows]

    if not players:
        return f"No {source} rankings found" + (f" for {position}" if position else "") + "."

    drafted_keys = db.get_drafted_player_keys()

    title = f"{source.title()} Rankings"
    if position:
        title += f" ({position})"

    lines = [title, ""]
    lines.append(
        f"{'Rank':>4}  {'Name':<25} {'Team':<5} {'Pos':<12} "
        f"{'Proj Pts':>8} {'VBD':>7} {'Avail':>5}"
    )
    lines.append("-" * 72)

    for p in players:
        pos_list = json.loads(p["positions"]) if p.get("positions") else []
        pos_str = ",".join(pos_list)
        proj = p.get("projected_points") or 0
        vbd = p.get("vbd_value") or 0
        avail = "No" if p["player_key"] in drafted_keys else "Yes"
        rank = p.get(rank_col, "-")

        lines.append(
            f"{rank:>4}  {p['name']:<25} {p.get('team') or '':<5} {pos_str:<12} "
            f"{proj:>8.1f} {vbd:>7.1f} {avail:>5}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# In-season / Waiver Wire tools
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_my_team_live() -> str:
    """Get current in-season roster from Yahoo Fantasy (live, not draft state).

    Shows the actual players currently on your team including their slot,
    injury status, and position eligibility.
    """
    if yahoo is None:
        return "Yahoo client not available. Ensure oauth2.json is present."

    try:
        roster = yahoo.get_roster()
    except Exception as exc:
        return f"Error fetching roster: {exc}"

    if not roster:
        return "No roster data returned from Yahoo."

    lines = ["My Current Roster (Live):", ""]
    lines.append(f"{'Slot':<8} {'Name':<25} {'Team':<5} {'Eligible':<15} {'Status'}")
    lines.append("-" * 70)

    for player in roster:
        name = player.get("name", "Unknown")
        slot = player.get("selected_position", "?")
        team = player.get("editorial_team_abbr") or player.get("team", "?")
        eligible = player.get("display_position") or player.get("eligible_positions", "?")
        if isinstance(eligible, list):
            eligible = ",".join(str(e) for e in eligible)
        status = player.get("status", "") or ""

        lines.append(f"{str(slot):<8} {name:<25} {str(team):<5} {str(eligible):<15} {status}")

    lines.append(f"\nTotal: {len(roster)} players")
    return "\n".join(lines)


@mcp.tool()
def get_free_agents_live(position: str = "ALL", count: int = 30) -> str:
    """Get top free agents currently available on the waiver wire.

    Args:
        position: Filter by position (C, 1B, 2B, SS, 3B, OF, SP, RP, ALL).
        count: Number of players to return (default 30).
    """
    if yahoo is None:
        return "Yahoo client not available. Ensure oauth2.json is present."

    try:
        free_agents = yahoo.get_free_agents(position)
    except Exception as exc:
        return f"Error fetching free agents: {exc}"

    if not free_agents:
        return f"No free agents found" + (f" at {position}" if position != "ALL" else "") + "."

    # Sort by ownership % descending (most owned = most desirable)
    def _pct(p):
        val = p.get("percent_owned") or p.get("percent_started") or 0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    free_agents = sorted(free_agents, key=_pct, reverse=True)[:count]

    header = f"Top Free Agents"
    if position != "ALL":
        header += f" ({position})"

    lines = [header, ""]
    lines.append(
        f"{'#':>3}  {'Name':<25} {'Team':<5} {'Pos':<12} {'Own%':>6} {'Started%':>9} {'Status'}"
    )
    lines.append("-" * 75)

    for i, p in enumerate(free_agents, 1):
        name = p.get("name", "Unknown")
        team = p.get("editorial_team_abbr") or p.get("team", "?")
        pos = p.get("display_position") or p.get("eligible_positions", "?")
        if isinstance(pos, list):
            pos = ",".join(str(x) for x in pos)
        own_pct = p.get("percent_owned", "-")
        started_pct = p.get("percent_started", "-")
        status = p.get("status", "") or ""

        lines.append(
            f"{i:>3}  {name:<25} {str(team):<5} {str(pos):<12} "
            f"{str(own_pct):>6} {str(started_pct):>9} {status}"
        )

    return "\n".join(lines)


@mcp.tool()
def get_current_matchup() -> str:
    """Get the current week's H2H matchup score and status for my team."""
    if yahoo is None:
        return "Yahoo client not available. Ensure oauth2.json is present."

    try:
        matchups = yahoo.get_matchups()
    except Exception as exc:
        return f"Error fetching matchups: {exc}"

    if not matchups:
        return "No matchup data returned from Yahoo."

    my_team_key = "469.l.3508.t.9"
    lines = ["Current Matchup:", ""]

    # matchups is a list of matchup objects; find the one with our team
    my_matchup = None
    for m in matchups:
        teams = m.get("teams") or {}
        for tk, td in teams.items():
            if isinstance(td, dict):
                key = td.get("team_key", "")
                if key == my_team_key or my_team_key in str(key):
                    my_matchup = m
                    break
        if my_matchup:
            break

    if my_matchup is None:
        # Fallback: show all matchups raw
        lines.append("(Could not isolate my matchup — showing all)")
        lines.append("")
        for i, m in enumerate(matchups, 1):
            lines.append(f"Matchup {i}: {m}")
        return "\n".join(lines)

    # Parse matchup
    week = my_matchup.get("week", "?")
    lines.append(f"Week {week}")
    lines.append("")

    teams = my_matchup.get("teams") or {}
    for _tk, td in teams.items():
        if not isinstance(td, dict):
            continue
        team_name = td.get("name", "Unknown")
        team_pts = td.get("team_points", {})
        total = team_pts.get("total", "?") if isinstance(team_pts, dict) else "?"
        is_mine = my_team_key in str(td.get("team_key", ""))
        marker = " ← MY TEAM" if is_mine else ""
        lines.append(f"  {team_name:<30} {total} pts{marker}")

    is_over = my_matchup.get("is_over", False)
    winner = my_matchup.get("winner_team_key", "")
    if is_over:
        lines.append("")
        lines.append(f"Result: {'WIN' if my_team_key in str(winner) else 'LOSS'}")
    else:
        lines.append("")
        lines.append("Status: In progress")

    return "\n".join(lines)


@mcp.tool()
def get_standings() -> str:
    """Get current league standings with win/loss records and points totals."""
    if yahoo is None:
        return "Yahoo client not available. Ensure oauth2.json is present."

    try:
        standings = yahoo.get_standings()
    except Exception as exc:
        return f"Error fetching standings: {exc}"

    if not standings:
        return "No standings data returned from Yahoo."

    my_team_key = "469.l.3508.t.9"
    lines = ["League Standings:", ""]
    lines.append(f"{'Rank':<5} {'Team':<30} {'W':>3} {'L':>3} {'T':>3} {'Pts For':>9} {'Pts Agst':>9}")
    lines.append("-" * 65)

    for i, team in enumerate(standings, 1):
        name = team.get("name", "Unknown")
        team_key = team.get("team_key", "")
        outcome = team.get("outcome_totals", {})
        wins = outcome.get("wins", "?") if isinstance(outcome, dict) else "?"
        losses = outcome.get("losses", "?") if isinstance(outcome, dict) else "?"
        ties = outcome.get("ties", "?") if isinstance(outcome, dict) else "?"
        pts_for = team.get("points_for", "?")
        pts_against = team.get("points_against", "?")
        marker = " ◄" if my_team_key in str(team_key) else ""

        lines.append(
            f"{i:<5} {name:<30} {str(wins):>3} {str(losses):>3} {str(ties):>3} "
            f"{str(pts_for):>9} {str(pts_against):>9}{marker}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
