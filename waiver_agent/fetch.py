"""Waiver agent data fetcher.

Pulls live Yahoo Fantasy data and prints structured output for the
morning scout agent to analyze. Designed to run in both local and
remote (CCR) environments — credentials come from oauth2.json if
present, otherwise from YAHOO_* environment variables.

Usage:
    python -m waiver_agent.fetch
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.yahoo_client import YahooClient

OAUTH_PATH = str(project_root / "oauth2.json")

# Positions to pull free agents for
FREE_AGENT_POSITIONS = ["SP", "RP", "OF", "1B", "2B", "SS", "3B", "C"]


def _section(title: str) -> str:
    bar = "═" * 60
    return f"\n{bar}\n  {title}\n{bar}\n"


def fetch_roster(client: YahooClient) -> str:
    out = [_section("MY CURRENT ROSTER")]
    try:
        roster = client.get_roster()
        if not roster:
            return out[0] + "No roster data returned.\n"
        out.append(f"{'Slot':<8} {'Name':<25} {'Team':<5} {'Pos':<15} {'Status'}")
        out.append("-" * 65)
        for p in roster:
            name = p.get("name", "?")
            slot = str(p.get("selected_position", "?"))
            team = str(p.get("editorial_team_abbr") or p.get("team", "?"))
            pos = p.get("display_position") or p.get("eligible_positions", "?")
            if isinstance(pos, list):
                pos = ",".join(str(x) for x in pos)
            status = p.get("status", "") or ""
            out.append(f"{slot:<8} {name:<25} {team:<5} {str(pos):<15} {status}")
        out.append(f"\nTotal players: {len(roster)}")
    except Exception as exc:
        out.append(f"Error fetching roster: {exc}")
    return "\n".join(out)


def fetch_standings(client: YahooClient) -> str:
    out = [_section("LEAGUE STANDINGS")]
    try:
        standings = client.get_standings()
        if not standings:
            return out[0] + "No standings data returned.\n"
        my_key = "469.l.3508.t.9"
        out.append(f"{'#':<4} {'Team':<30} {'W':>3} {'L':>3} {'T':>3} {'PF':>9} {'PA':>9}")
        out.append("-" * 65)
        for i, team in enumerate(standings, 1):
            name = team.get("name", "Unknown")
            tkey = team.get("team_key", "")
            outcome = team.get("outcome_totals") or {}
            w = outcome.get("wins", "?")
            l = outcome.get("losses", "?")
            t = outcome.get("ties", "?")
            pf = team.get("points_for", "?")
            pa = team.get("points_against", "?")
            marker = " ◄ MY TEAM" if my_key in str(tkey) else ""
            out.append(
                f"{i:<4} {name:<30} {str(w):>3} {str(l):>3} {str(t):>3} "
                f"{str(pf):>9} {str(pa):>9}{marker}"
            )
    except Exception as exc:
        out.append(f"Error fetching standings: {exc}")
    return "\n".join(out)


def fetch_matchup(client: YahooClient) -> str:
    out = [_section("CURRENT WEEK MATCHUP")]
    try:
        matchups = client.get_matchups()
        if not matchups:
            return out[0] + "No matchup data returned.\n"
        my_key = "469.l.3508.t.9"
        my_matchup = None
        for m in matchups:
            teams = m.get("teams") or {}
            for _tk, td in teams.items():
                if isinstance(td, dict) and my_key in str(td.get("team_key", "")):
                    my_matchup = m
                    break
            if my_matchup:
                break

        if not my_matchup:
            out.append("Could not find my matchup. Raw matchup count: " + str(len(matchups)))
            return "\n".join(out)

        week = my_matchup.get("week", "?")
        out.append(f"Week {week}\n")
        teams = my_matchup.get("teams") or {}
        for _tk, td in teams.items():
            if not isinstance(td, dict):
                continue
            name = td.get("name", "Unknown")
            pts = td.get("team_points", {})
            total = pts.get("total", "?") if isinstance(pts, dict) else "?"
            is_mine = my_key in str(td.get("team_key", ""))
            marker = "  ← MY TEAM" if is_mine else ""
            out.append(f"  {name:<30} {total} pts{marker}")

        is_over = my_matchup.get("is_over", False)
        winner = str(my_matchup.get("winner_team_key", ""))
        if is_over:
            result = "WIN" if my_key in winner else "LOSS"
            out.append(f"\nFinal result: {result}")
        else:
            out.append("\nStatus: In progress")
    except Exception as exc:
        out.append(f"Error fetching matchup: {exc}")
    return "\n".join(out)


def fetch_free_agents(client: YahooClient) -> str:
    out = [_section("WAIVER WIRE — TOP FREE AGENTS")]

    def _pct(p):
        val = p.get("percent_owned") or p.get("percent_started") or 0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    for pos in FREE_AGENT_POSITIONS:
        try:
            agents = client.get_free_agents(pos)
            if not agents:
                out.append(f"\n[{pos}] No free agents found.")
                continue
            agents = sorted(agents, key=_pct, reverse=True)[:15]
            out.append(f"\n--- {pos} Free Agents ---")
            out.append(f"{'#':>3}  {'Name':<25} {'Team':<5} {'Pos':<12} {'Own%':>6} {'Status'}")
            out.append("-" * 60)
            for i, p in enumerate(agents, 1):
                name = p.get("name", "?")
                team = str(p.get("editorial_team_abbr") or p.get("team", "?"))
                pos_str = p.get("display_position") or p.get("eligible_positions", "?")
                if isinstance(pos_str, list):
                    pos_str = ",".join(str(x) for x in pos_str)
                own = p.get("percent_owned", "-")
                status = p.get("status", "") or ""
                out.append(
                    f"{i:>3}  {name:<25} {team:<5} {str(pos_str):<12} {str(own):>6} {status}"
                )
        except Exception as exc:
            out.append(f"\n[{pos}] Error: {exc}")

    return "\n".join(out)


def main() -> None:
    print("Fantasy Baseball Morning Scout — Live Data Fetch")
    print("=" * 60)

    try:
        client = YahooClient(OAUTH_PATH)
    except Exception as exc:
        print(f"FATAL: Could not initialise Yahoo client: {exc}", file=sys.stderr)
        sys.exit(1)

    print(fetch_roster(client))
    print(fetch_standings(client))
    print(fetch_matchup(client))
    print(fetch_free_agents(client))

    print(_section("FETCH COMPLETE"))
    print("Claude: Use the data above plus web research to generate the morning report.")


if __name__ == "__main__":
    main()
