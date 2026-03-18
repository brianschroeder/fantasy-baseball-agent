#!/usr/bin/env python3
"""Pre-draft data preparation script.

Run before the draft to populate the SQLite database with projections,
rankings, and league settings.

Usage:
    python scripts/prefetch_data.py
    python scripts/prefetch_data.py --skip-yahoo --skip-espn
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path so imports work from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.db import DB
from mcp_server.projections import ProjectionEngine


# ── Name normalisation helpers ───────────────────────────────────────────

_SUFFIX_RE = re.compile(
    r",?\s+(Jr\.?|Sr\.?|II|III|IV|V)$", re.IGNORECASE
)


def normalize_name(name: str) -> str:
    """Lowercase, strip suffixes/accents, collapse whitespace."""
    import unicodedata
    name = _SUFFIX_RE.sub("", name)
    name = name.strip().lower()
    # Normalize unicode accents (é -> e, ñ -> n, etc.)
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)
    return name


def make_fg_key(name: str, position_type: str = "") -> str:
    """Generate a player_key from a FanGraphs name.

    For two-way players (like Ohtani), append position_type to disambiguate.
    """
    norm = normalize_name(name)
    slug = norm.replace(" ", ".")
    if position_type:
        return f"fg.{slug}.{position_type.lower()}"
    return f"fg.{slug}"


def build_name_index(db: DB) -> dict[str, str]:
    """Build normalized-name -> player_key lookup from existing players."""
    rows = db.conn.execute("SELECT player_key, name FROM players").fetchall()
    index: dict[str, str] = {}
    for row in rows:
        index[normalize_name(row["name"])] = row["player_key"]
    return index


def match_player_key(name: str, index: dict[str, str]) -> str | None:
    """Try to find a matching player_key. Exact match first, then without suffix."""
    norm = normalize_name(name)
    if norm in index:
        return index[norm]
    # Already stripped suffix via normalize_name, so try as-is
    # Also try stripping periods (e.g. "J.D. Martinez" vs "JD Martinez")
    alt = norm.replace(".", "")
    for idx_name, key in index.items():
        if idx_name.replace(".", "") == alt:
            return key
    return None


# ── Yahoo data fetching ─────────────────────────────────────────────────

def fetch_yahoo_data(db: DB) -> None:
    """Connect to Yahoo API, fetch league settings, stat modifiers, roster positions."""
    print("\n=== Fetching Yahoo League Settings ===")

    from mcp_server.yahoo_client import YahooClient

    try:
        client = YahooClient(oauth_file=str(PROJECT_ROOT / "oauth2.json"))
    except Exception as e:
        print(f"  ERROR: Could not authenticate with Yahoo: {e}")
        raise

    # League settings
    print("  Fetching league settings...")
    settings = client.get_settings()

    # Store useful settings
    db.set_league_setting("num_teams", settings.get("num_teams", 12))
    db.set_league_setting("name", settings.get("name", ""))
    db.set_league_setting("scoring_type", settings.get("scoring_type", ""))
    db.set_league_setting("draft_type", settings.get("draft_type", ""))
    db.set_league_setting("max_teams", settings.get("max_teams", 12))
    db.set_league_setting("raw_settings", settings)
    print(f"  League: {settings.get('name', 'Unknown')}")
    print(f"  Teams: {settings.get('num_teams', '?')}")
    print(f"  Scoring: {settings.get('scoring_type', '?')}")

    # Roster positions via league.positions()
    print("  Fetching roster positions...")
    positions = client.get_positions()
    for pos, info in positions.items():
        count = info.get("count", 1)
        pos_type = info.get("position_type", "B")
        db.upsert_roster_position(pos, count, pos_type)
        print(f"    {pos}: {count} ({pos_type})")

    # Stat modifiers (point values) from settings['stat_modifiers']['stats']
    print("  Fetching stat modifiers...")
    stat_modifiers_raw = settings.get("stat_modifiers", {})
    stats_list = stat_modifiers_raw.get("stats", [])

    # Also get stat categories for display names (stat_categories has names but not IDs)
    stat_cats = client.get_stat_categories()
    # Build a display_name lookup by matching order with stat_modifiers
    # stat_cats is ordered to match stat_modifiers entries
    cat_by_index = {i: cat for i, cat in enumerate(stat_cats)}

    stored_count = 0
    for i, entry in enumerate(stats_list):
        stat = entry.get("stat", {})
        stat_id = stat.get("stat_id")
        point_value = stat.get("value")
        if stat_id is None or point_value is None:
            continue
        try:
            point_value = float(point_value)
        except (TypeError, ValueError):
            continue

        # Get display name and position type from stat_categories
        cat = cat_by_index.get(i, {})
        display_name = cat.get("display_name", f"stat_{stat_id}")
        pos_type = cat.get("position_type", "")

        mod = {
            "stat_id": int(stat_id),
            "stat_name": display_name.lower(),
            "display_name": display_name,
            "point_value": point_value,
            "position_type": pos_type,
        }
        db.upsert_stat_modifier(mod)
        print(f"    {display_name:<6} (id={stat_id:>3}): {point_value:>+6.1f} pts  [{pos_type}]")
        stored_count += 1

    print(f"  Done. Stored {stored_count} stat modifiers.")


# ── FanGraphs data ───────────────────────────────────────────────────────

async def fetch_fangraphs_data(db: DB) -> None:
    """Scrape FanGraphs Depth Charts and store in players table."""
    print("\n=== Scraping FanGraphs Depth Charts ===")

    from data_sources.fangraphs import scrape_all_projections

    batters, pitchers = await scrape_all_projections()
    print(f"  Batters scraped: {len(batters)}")
    print(f"  Pitchers scraped: {len(pitchers)}")

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    # Process batters
    for p in batters:
        name = p.get("name", p.get("Name", ""))
        if not name:
            continue
        team = p.get("team", p.get("Team", ""))
        positions_raw = p.get("positions", p.get("Pos", ""))

        # Parse positions into a list
        if isinstance(positions_raw, str):
            positions = [pos.strip() for pos in positions_raw.split("/") if pos.strip()]
            if not positions:
                positions = [pos.strip() for pos in positions_raw.split(",") if pos.strip()]
        elif isinstance(positions_raw, list):
            positions = positions_raw
        else:
            positions = []

        # Build stat dict (everything except name/team/positions metadata)
        skip_keys = {"name", "Name", "team", "Team", "positions", "Pos", "#"}
        fg_stats = {k: v for k, v in p.items() if k not in skip_keys}

        player_key = make_fg_key(name, "b")
        player_dict = {
            "player_key": player_key,
            "yahoo_player_id": None,
            "name": name,
            "team": team,
            "positions": json.dumps(positions),
            "position_type": "B",
            "fg_stats": json.dumps(fg_stats),
            "projected_points": None,
            "vbd_value": None,
            "fantasypros_rank": None,
            "espn_rank": None,
            "ownership_pct": None,
            "status": None,
            "last_updated": now,
        }
        db.upsert_player(player_dict)
        count += 1

    # Process pitchers
    for p in pitchers:
        name = p.get("name", p.get("Name", ""))
        if not name:
            continue
        team = p.get("team", p.get("Team", ""))

        fg_stats_raw = {k: v for k, v in p.items()
                        if k not in {"name", "Name", "team", "Team", "#"}}

        # Determine SP vs RP from stats (GS > 0 suggests starter)
        gs = 0
        try:
            gs = int(fg_stats_raw.get("GS", 0))
        except (TypeError, ValueError):
            pass
        sv = 0
        try:
            sv = int(fg_stats_raw.get("SV", 0))
        except (TypeError, ValueError):
            pass

        if gs >= 5:
            positions = ["SP"]
        elif sv >= 5:
            positions = ["RP"]
        else:
            # Could be either; check IP and GS ratio
            positions = ["SP"] if gs > 0 else ["RP"]

        player_key = make_fg_key(name, "p")
        player_dict = {
            "player_key": player_key,
            "yahoo_player_id": None,
            "name": name,
            "team": team,
            "positions": json.dumps(positions),
            "position_type": "P",
            "fg_stats": json.dumps(fg_stats_raw),
            "projected_points": None,
            "vbd_value": None,
            "fantasypros_rank": None,
            "espn_rank": None,
            "ownership_pct": None,
            "status": None,
            "last_updated": now,
        }
        db.upsert_player(player_dict)
        count += 1

    print(f"  Total players stored: {count}")


# ── Yahoo player positions ────────────────────────────────────────────────

def fetch_yahoo_positions(db: DB) -> None:
    """Fetch player positions from Yahoo API by querying free agents at each position."""
    print("\n=== Fetching Player Positions from Yahoo ===")

    from mcp_server.yahoo_client import YahooClient
    try:
        client = YahooClient(oauth_file=str(PROJECT_ROOT / "oauth2.json"))
    except Exception as e:
        print(f"  ERROR: Could not authenticate with Yahoo: {e}")
        return

    name_index = build_name_index(db)
    total_matched = 0

    # Query each position to get player position mappings
    for pos in ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP"]:
        try:
            print(f"  Fetching {pos} players...")
            fa_players = client.league.free_agents(pos)
            matched = 0
            for yp in fa_players:
                name = yp.get("name", "")
                if not name:
                    continue
                player_key = match_player_key(name, name_index)
                if player_key:
                    # Get existing positions and merge
                    row = db.conn.execute(
                        "SELECT positions FROM players WHERE player_key = ?",
                        (player_key,),
                    ).fetchone()
                    existing = json.loads(row["positions"]) if row and row["positions"] else []
                    yahoo_positions = yp.get("eligible_positions", [])
                    # Filter out utility/bench positions
                    real_pos = [p for p in yahoo_positions if p not in ("Util", "BN", "IL", "NA", "DL", "G")]
                    if real_pos and (not existing or existing == ["?"]):
                        db.conn.execute(
                            "UPDATE players SET positions = ? WHERE player_key = ?",
                            (json.dumps(real_pos), player_key),
                        )
                        matched += 1
            db.conn.commit()
            total_matched += matched
            print(f"    {pos}: updated {matched} players")
        except Exception as e:
            print(f"    {pos}: error - {e}")

    # Also get rostered players from taken_players
    try:
        print("  Fetching rostered players...")
        taken = client.league.taken_players()
        matched = 0
        for yp in taken:
            name = yp.get("name", "")
            if not name:
                continue
            player_key = match_player_key(name, name_index)
            if player_key:
                row = db.conn.execute(
                    "SELECT positions FROM players WHERE player_key = ?",
                    (player_key,),
                ).fetchone()
                existing = json.loads(row["positions"]) if row and row["positions"] else []
                yahoo_positions = yp.get("eligible_positions", [])
                real_pos = [p for p in yahoo_positions if p not in ("Util", "BN", "IL", "NA", "DL", "G")]
                if real_pos and (not existing or existing == ["?"]):
                    db.conn.execute(
                        "UPDATE players SET positions = ? WHERE player_key = ?",
                        (json.dumps(real_pos), player_key),
                    )
                    matched += 1
        db.conn.commit()
        total_matched += matched
        print(f"    Rostered: updated {matched} players")
    except Exception as e:
        print(f"    Rostered: error - {e}")

    print(f"  Total positions updated: {total_matched}")


# ── FantasyPros rankings ────────────────────────────────────────────────

async def fetch_fantasypros_data(db: DB) -> None:
    """Scrape FantasyPros rankings and match to existing players."""
    print("\n=== Scraping FantasyPros Rankings ===")

    from data_sources.fantasypros import scrape_points_rankings

    rankings = await scrape_points_rankings()
    print(f"  Rankings scraped: {len(rankings)}")

    if not rankings:
        print("  WARNING: No rankings data from FantasyPros. Skipping.")
        return

    name_index = build_name_index(db)
    matched = 0
    unmatched = []

    for entry in rankings:
        name = entry.get("name", "")
        rank = entry.get("rank")
        if not name or rank is None:
            continue

        player_key = match_player_key(name, name_index)
        if player_key:
            db.conn.execute(
                "UPDATE players SET fantasypros_rank = ? WHERE player_key = ?",
                (int(rank), player_key),
            )
            matched += 1
        else:
            unmatched.append(name)

    db.conn.commit()
    print(f"  Matched: {matched}")
    if unmatched:
        print(f"  Unmatched: {len(unmatched)} (first 10: {unmatched[:10]})")


# ── ESPN rankings ────────────────────────────────────────────────────────

async def fetch_espn_data(db: DB) -> None:
    """Scrape ESPN rankings and match to existing players."""
    print("\n=== Scraping ESPN Rankings ===")

    from data_sources.espn import scrape_espn_rankings

    rankings = await scrape_espn_rankings()
    print(f"  Rankings scraped: {len(rankings)}")

    if not rankings:
        print("  WARNING: No rankings data from ESPN. Skipping.")
        return

    name_index = build_name_index(db)
    matched = 0
    unmatched = []

    for entry in rankings:
        name = entry.get("name", "")
        rank = entry.get("rank")
        if not name or rank is None:
            continue

        player_key = match_player_key(name, name_index)
        if player_key:
            db.conn.execute(
                "UPDATE players SET espn_rank = ? WHERE player_key = ?",
                (int(rank), player_key),
            )
            matched += 1
        else:
            unmatched.append(name)

    db.conn.commit()
    print(f"  Matched: {matched}")
    if unmatched:
        print(f"  Unmatched: {len(unmatched)} (first 10: {unmatched[:10]})")


# ── Keepers ──────────────────────────────────────────────────────────────

def fetch_keepers(db: DB) -> None:
    """Load keeper data from Yahoo API and store in database."""
    print("\n=== Loading Keepers from Yahoo ===")

    from mcp_server.yahoo_client import YahooClient, TEAM_KEY
    from mcp_server.draft_state import DraftState

    try:
        client = YahooClient(oauth_file=str(PROJECT_ROOT / "oauth2.json"))
    except Exception as e:
        print(f"  ERROR: Could not authenticate with Yahoo: {e}")
        return

    draft_state = DraftState(db, client)
    keepers = draft_state.load_keepers()

    if not keepers:
        print("  No keepers found.")
        return

    # Also try to match keepers to FanGraphs player entries
    name_index = build_name_index(db)
    matched = 0
    for keeper in keepers:
        yahoo_key = keeper["player_key"]
        name = keeper["name"]
        team_key = keeper["team_key"]

        # Try to find matching FanGraphs entry and link them
        fg_key = match_player_key(name, name_index)
        if fg_key and fg_key != yahoo_key:
            # Mark the FanGraphs entry as kept too
            db.conn.execute(
                "UPDATE players SET status = 'K' WHERE player_key = ?",
                (fg_key,),
            )
            matched += 1

    db.conn.commit()

    # Print keeper summary by team
    my_keepers = [k for k in keepers if k["team_key"] == TEAM_KEY]
    other_keepers = [k for k in keepers if k["team_key"] != TEAM_KEY]

    print(f"\n  Your keepers ({len(my_keepers)}):")
    for k in my_keepers:
        print(f"    - {k['name']}")

    print(f"\n  Other teams' keepers ({len(other_keepers)}):")
    teams: dict[str, list] = {}
    for k in other_keepers:
        teams.setdefault(k["team_name"], []).append(k["name"])
    for team_name, players in sorted(teams.items()):
        print(f"    {team_name}: {', '.join(players)}")

    print(f"\n  FanGraphs entries matched to keepers: {matched}")
    print(f"  Total keepers loaded: {len(keepers)}")


# ── Projections & VBD ────────────────────────────────────────────────────

def calculate_projections_and_vbd(db: DB) -> None:
    """Calculate projected points and VBD for all players."""
    print("\n=== Calculating Projections & VBD ===")

    engine = ProjectionEngine(db)
    n_scored, n_vbd = engine.recalculate_all()
    print(f"  Players scored: {n_scored}")
    print(f"  Players with VBD: {n_vbd}")


# ── Summary ──────────────────────────────────────────────────────────────

def print_summary(db: DB) -> None:
    """Print a summary of the database contents."""
    print("\n" + "=" * 60)
    print("PREFETCH SUMMARY")
    print("=" * 60)

    # Total players
    row = db.conn.execute("SELECT COUNT(*) as cnt FROM players").fetchone()
    total = row["cnt"]
    print(f"\nTotal players in database: {total}")

    # Players with projections
    row = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE projected_points IS NOT NULL"
    ).fetchone()
    print(f"Players with projections: {row['cnt']}")

    # Players with VBD
    row = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE vbd_value IS NOT NULL"
    ).fetchone()
    print(f"Players with VBD: {row['cnt']}")

    # Players with FantasyPros rank
    row = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE fantasypros_rank IS NOT NULL"
    ).fetchone()
    print(f"Players with FantasyPros rank: {row['cnt']}")

    # Players with ESPN rank
    row = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE espn_rank IS NOT NULL"
    ).fetchone()
    print(f"Players with ESPN rank: {row['cnt']}")

    # Top 25 by VBD
    print(f"\n{'-' * 60}")
    print("TOP 25 PLAYERS BY VBD")
    print(f"{'-' * 60}")
    print(f"{'Rank':<5} {'Name':<25} {'Pos':<10} {'Pts':>8} {'VBD':>8} {'FP#':>5} {'ESPN#':>5}")
    print(f"{'-'*5} {'-'*25} {'-'*10} {'-'*8} {'-'*8} {'-'*5} {'-'*5}")

    top25 = db.conn.execute(
        "SELECT * FROM players WHERE vbd_value IS NOT NULL "
        "ORDER BY vbd_value DESC LIMIT 25"
    ).fetchall()

    for i, p in enumerate(top25, 1):
        positions = json.loads(p["positions"]) if p["positions"] else []
        pos_str = "/".join(positions) if positions else "?"
        fp = str(p["fantasypros_rank"]) if p["fantasypros_rank"] else "-"
        espn = str(p["espn_rank"]) if p["espn_rank"] else "-"
        pts = f"{p['projected_points']:.1f}" if p["projected_points"] else "-"
        vbd = f"{p['vbd_value']:.1f}" if p["vbd_value"] else "-"
        print(f"{i:<5} {p['name']:<25} {pos_str:<10} {pts:>8} {vbd:>8} {fp:>5} {espn:>5}")

    # Top 10 per position
    key_positions = ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP"]
    for pos in key_positions:
        print(f"\n{'-' * 60}")
        print(f"TOP 10 {pos}")
        print(f"{'-' * 60}")
        print(f"{'Rank':<5} {'Name':<25} {'Pts':>8} {'VBD':>8}")
        print(f"{'-'*5} {'-'*25} {'-'*8} {'-'*8}")

        top10 = db.conn.execute(
            "SELECT * FROM players WHERE vbd_value IS NOT NULL "
            "AND positions LIKE ? "
            "ORDER BY vbd_value DESC LIMIT 10",
            (f'%"{pos}"%',),
        ).fetchall()

        for i, p in enumerate(top10, 1):
            pts = f"{p['projected_points']:.1f}" if p["projected_points"] else "-"
            vbd = f"{p['vbd_value']:.1f}" if p["vbd_value"] else "-"
            print(f"{i:<5} {p['name']:<25} {pts:>8} {vbd:>8}")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-draft data preparation script"
    )
    parser.add_argument(
        "--skip-yahoo", action="store_true",
        help="Skip Yahoo API calls (useful if oauth is expired)"
    )
    parser.add_argument(
        "--skip-fangraphs", action="store_true",
        help="Skip FanGraphs scraping"
    )
    parser.add_argument(
        "--skip-fantasypros", action="store_true",
        help="Skip FantasyPros scraping"
    )
    parser.add_argument(
        "--skip-espn", action="store_true",
        help="Skip ESPN scraping"
    )
    args = parser.parse_args()

    db_path = PROJECT_ROOT / "data" / "fantasy_baseball.db"
    print(f"Database: {db_path}")
    db = DB(str(db_path))

    print("Database initialised.")

    # Step 1: Yahoo league settings
    if not args.skip_yahoo:
        try:
            fetch_yahoo_data(db)
        except Exception as e:
            print(f"\n  ERROR fetching Yahoo data: {e}")
            print("  Continuing without Yahoo data. Use --skip-yahoo to suppress.")
    else:
        print("\n=== Skipping Yahoo (--skip-yahoo) ===")

    # Step 2: FanGraphs projections
    if not args.skip_fangraphs:
        try:
            asyncio.run(fetch_fangraphs_data(db))
        except Exception as e:
            print(f"\n  ERROR fetching FanGraphs data: {e}")
            print("  Continuing without FanGraphs data.")
    else:
        print("\n=== Skipping FanGraphs (--skip-fangraphs) ===")

    # Step 3: FantasyPros rankings
    if not args.skip_fantasypros:
        try:
            asyncio.run(fetch_fantasypros_data(db))
        except Exception as e:
            print(f"\n  ERROR fetching FantasyPros data: {e}")
            print("  Continuing without FantasyPros data.")
    else:
        print("\n=== Skipping FantasyPros (--skip-fantasypros) ===")

    # Step 4: ESPN rankings
    if not args.skip_espn:
        try:
            asyncio.run(fetch_espn_data(db))
        except Exception as e:
            print(f"\n  ERROR fetching ESPN data: {e}")
            print("  Continuing without ESPN data.")
    else:
        print("\n=== Skipping ESPN (--skip-espn) ===")

    # Step 5: Fetch player positions from Yahoo
    if not args.skip_yahoo:
        try:
            fetch_yahoo_positions(db)
        except Exception as e:
            print(f"\n  ERROR fetching Yahoo positions: {e}")
            print("  Continuing without position data.")

    # Step 6: Calculate projections and VBD
    calculate_projections_and_vbd(db)

    # Step 7: Load keepers from Yahoo
    if not args.skip_yahoo:
        try:
            fetch_keepers(db)
        except Exception as e:
            print(f"\n  ERROR fetching keepers: {e}")
            print("  Continuing without keeper data.")

    # Step 8: Print summary
    print_summary(db)

    db.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
