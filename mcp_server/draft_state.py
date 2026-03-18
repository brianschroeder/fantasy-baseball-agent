"""Draft state tracker backed by SQLite."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import DB
    from .yahoo_client import YahooClient

log = logging.getLogger(__name__)

TEAM_KEY = "469.l.3508.t.9"

# Positions that count toward roster construction.  Utility slots
# (Util / BN / IL) are excluded because any player can fill them.
ROSTER_POSITIONS = ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP"]


class DraftState:
    """Bridges Yahoo API and SQLite for live draft tracking."""

    def __init__(self, db: DB, yahoo: YahooClient | None = None) -> None:
        self.db = db
        self.yahoo = yahoo
        self.my_team_key = TEAM_KEY

    # ── League bootstrap ──────────────────────────────────────────────

    def load_league_settings(self) -> dict:
        """Fetch league settings from Yahoo and persist them in SQLite.

        Stores general settings, stat modifiers (point values), and
        roster position requirements.  Returns the raw settings dict
        for inspection.
        """
        if self.yahoo is None:
            raise RuntimeError("Yahoo client is not initialised")

        settings = self.yahoo.get_settings()

        # Store general scalar settings we care about
        general_keys = [
            "name", "num_teams", "scoring_type", "draft_type",
            "is_auction_draft", "max_teams", "season",
            "current_week", "start_week", "end_week",
        ]
        for key in general_keys:
            if key in settings:
                self.db.set_league_setting(key, settings[key])

        # ── Stat modifiers (point values) from settings['stat_modifiers'] ──
        stat_modifiers_raw = settings.get("stat_modifiers", {})
        stats_list = stat_modifiers_raw.get("stats", [])
        stat_cats = self.yahoo.get_stat_categories()
        for i, entry in enumerate(stats_list):
            stat = entry.get("stat", {})
            stat_id = stat.get("stat_id")
            point_value = stat.get("value")
            if stat_id is None or point_value is None:
                continue
            cat = stat_cats[i] if i < len(stat_cats) else {}
            mod_dict = {
                "stat_id": int(stat_id),
                "stat_name": cat.get("display_name", "").lower(),
                "display_name": cat.get("display_name", f"stat_{stat_id}"),
                "point_value": float(point_value),
                "position_type": cat.get("position_type", ""),
            }
            self.db.upsert_stat_modifier(mod_dict)

        # ── Roster positions via league.positions() ──
        positions = self.yahoo.get_positions()
        for pos, info in positions.items():
            count = info.get("count", 1)
            pos_type = info.get("position_type", "B")
            self.db.upsert_roster_position(pos, int(count), pos_type)

        log.info("Loaded league settings from Yahoo")
        return settings

    # ── Keeper loading ───────────────────────────────────────────────

    def load_keepers(self) -> list[dict]:
        """Fetch keepers from Yahoo (status=K) and store in draft_picks.

        Keepers are stored as draft picks with is_keeper=True and
        pick_number in the negative range to distinguish them from
        actual draft picks.  Also marks them in the players table
        with status='K' so best_available excludes them.

        Returns the list of keeper dicts.
        """
        if self.yahoo is None:
            raise RuntimeError("Yahoo client is not initialised")

        keepers = self.yahoo.get_keepers()
        if not keepers:
            log.info("No keepers found")
            return []

        for i, keeper in enumerate(keepers):
            player_key = keeper["player_key"]
            team_key = keeper["team_key"]
            team_name = keeper["team_name"]
            name = keeper["name"]

            # Store as a draft pick with is_keeper=True
            pick_dict = {
                "pick_number": -(i + 1),  # negative to avoid collision with real picks
                "round": 0,
                "team_key": team_key,
                "team_name": team_name,
                "player_key": player_key,
                "player_name": name,
                "cost": 0,
                "is_keeper": True,
            }
            self.db.upsert_draft_pick(pick_dict)

            # If it's our keeper, store in my_keepers too
            if team_key == self.my_team_key:
                self.db.upsert_keeper(player_key, name, team_key, team_name)

            # Mark player status in players table if they exist
            self.db.conn.execute(
                "UPDATE players SET status = 'K' WHERE player_key = ?",
                (player_key,),
            )

        self.db.conn.commit()
        log.info("Loaded %d keepers from Yahoo", len(keepers))
        return keepers

    # ── Draft tracking ────────────────────────────────────────────────

    def refresh_draft_results(self) -> list[dict]:
        """Poll Yahoo for draft results, upsert into SQLite.

        Returns only the *new* picks that weren't previously stored.
        """
        if self.yahoo is None:
            raise RuntimeError("Yahoo client is not initialised")

        results = self.yahoo.get_draft_results()
        existing_keys = self.db.get_drafted_player_keys()
        new_picks: list[dict] = []

        for pick in results:
            # yahoo_fantasy_api draft_results() returns dicts with keys
            # that may vary slightly.  Normalise them here.
            player_key = pick.get("player_key") or pick.get("player_id", "")
            pick_dict = {
                "pick_number": int(pick.get("pick", 0)),
                "round": int(pick.get("round", 0)),
                "team_key": pick.get("team_key", ""),
                "team_name": pick.get("team_name", ""),
                "player_key": str(player_key),
                "player_name": pick.get("player_name", ""),
                "cost": int(pick.get("cost", 0)),
                "is_keeper": bool(pick.get("is_keeper", False)),
            }
            self.db.upsert_draft_pick(pick_dict)

            if str(player_key) not in existing_keys:
                new_picks.append(pick_dict)

        log.info(
            "Refreshed draft results: %d total, %d new",
            len(results),
            len(new_picks),
        )
        return new_picks

    def record_manual_pick(
        self,
        player_name: str,
        team_name: str | None = None,
        round_num: int | None = None,
        pick_number: int | None = None,
    ) -> dict:
        """Manually record a draft pick when Yahoo is slow to update.

        Searches the players table for a match and marks the player as
        drafted.  Returns the recorded pick dict or an error dict.
        """
        matches = self.db.get_player(player_name)
        if not matches:
            return {"error": f"Player '{player_name}' not found in database"}

        # Take the best match (first result from LIKE query)
        player = matches[0]

        # Auto-assign pick number from existing picks
        if pick_number is None:
            existing = self.db.get_draft_picks()
            pick_number = len(existing) + 1

        if round_num is None:
            # Estimate round from pick number and league size
            num_teams = self.db.get_league_setting("num_teams")
            num_teams = int(num_teams) if num_teams else 12
            round_num = (pick_number - 1) // num_teams + 1

        pick_dict = {
            "pick_number": pick_number,
            "round": round_num,
            "team_key": team_name or "unknown",
            "team_name": team_name or "unknown",
            "player_key": player["player_key"],
            "player_name": player["name"],
            "cost": 0,
            "is_keeper": False,
        }
        self.db.upsert_draft_pick(pick_dict)
        log.info("Manually recorded pick %d: %s", pick_number, player["name"])
        return pick_dict

    # ── Best available / comparisons ──────────────────────────────────

    def get_best_available(
        self, position: str | None = None, count: int = 10
    ) -> list[dict]:
        """Return top N available players by VBD, optionally filtered by position."""
        return self.db.get_best_available(position=position, limit=count)

    def get_my_roster(self) -> list[dict]:
        """Return all of my draft picks so far."""
        return self.db.get_my_roster(self.my_team_key)

    def get_roster_needs(self) -> list[dict]:
        """Compare filled vs required roster positions.

        For each position where we still need players, includes the top
        3 available options.
        """
        roster_positions = self.db.get_roster_positions()
        my_picks = self.db.get_my_roster(self.my_team_key)

        # Count how many of each position we've drafted
        filled: dict[str, int] = {}
        for pick in my_picks:
            # Look up the player to find their positions
            matches = self.db.get_player(pick["player_name"])
            if matches:
                player = matches[0]
                positions = (
                    json.loads(player["positions"])
                    if player.get("positions")
                    else []
                )
                # Credit one slot for the best unfilled position
                for pos in positions:
                    filled[pos] = filled.get(pos, 0) + 1

        needs: list[dict] = []
        for pos_row in roster_positions:
            pos = pos_row["position"]
            needed = pos_row["count"]
            have = filled.get(pos, 0)
            if pos not in ROSTER_POSITIONS:
                continue  # skip Util/BN/IL etc.
            if have < needed:
                best = self.db.get_best_available(position=pos, limit=3)
                needs.append(
                    {
                        "position": pos,
                        "needed": needed,
                        "filled": have,
                        "remaining": needed - have,
                        "best_available": best,
                    }
                )
        return needs

    def get_positional_scarcity(self) -> list[dict]:
        """Analyse remaining player quality at each roster position.

        Returns positions sorted by scarcity (fewest available first).
        """
        scarcity: list[dict] = []
        for pos in ROSTER_POSITIONS:
            data = self.db.get_positional_scarcity(pos)
            scarcity.append(
                {
                    "position": pos,
                    "available_count": data.get("count", 0),
                    "avg_vbd": round(data.get("avg_vbd") or 0, 2),
                }
            )
        return sorted(scarcity, key=lambda x: x["available_count"])

    def compare_players(self, names: list[str]) -> list[dict]:
        """Look up multiple players for side-by-side comparison."""
        players: list[dict] = []
        for name in names:
            matches = self.db.get_player(name.strip())
            if matches:
                players.append(dict(matches[0]))
            else:
                players.append({"name": name.strip(), "error": "Not found"})
        return players

    def search_player(self, name: str) -> list[dict]:
        """Search for a player by name (supports partial matching)."""
        return self.db.get_player(name)
