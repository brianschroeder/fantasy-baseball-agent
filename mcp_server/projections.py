"""VBD calculation engine for fantasy baseball projections."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import DB

log = logging.getLogger(__name__)

# ── Mapping from FanGraphs stat names to Yahoo stat IDs ──────────────
#
# Yahoo H2H Points leagues expose stat_modifiers that map
# stat_id -> point_value.  The maps below bridge FanGraphs column
# names to those numeric IDs so we can score a projection row.

YAHOO_BATTING_STAT_MAP: dict[str, int] = {
    # FanGraphs name -> Yahoo stat_id (Backyard Baseball league)
    "R": 7,       # Runs
    "2B": 10,     # Doubles
    "3B": 11,     # Triples
    "HR": 12,     # Home Runs
    "RBI": 13,    # RBI
    "SB": 16,     # Stolen Bases
    "BB": 18,     # Walks
    "HBP": 20,    # Hit By Pitch
    "SO": 21,     # Strikeouts (batting) — FanGraphs uses "SO" or "K"
    # Singles (stat_id 9) are derived below, not mapped directly.
    # CYC (64) and SLAM (66) are rare events, not in projections.
}

YAHOO_PITCHING_STAT_MAP: dict[str, int] = {
    "W": 28,      # Wins
    "L": 29,      # Losses
    "CG": 30,     # Complete Games
    "SV": 32,     # Saves
    "ER": 37,     # Earned Runs
    "BB": 39,     # Walks (pitching)
    "SO": 42,     # Strikeouts (pitching) — FanGraphs uses "SO" or "K"
    "HLD": 48,    # Holds
    "IP": 50,     # Innings Pitched
    "QS": 83,     # Quality Starts
    # HBP (41) against — not typically in FanGraphs projections
    # NH (79), PG (80) — rare events, not in projections
    # BSV (84) — Blown Saves — FanGraphs may have "BS"
}

SINGLES_STAT_ID = 9

# Default replacement-level depth per position (12-team league).
# Values represent the number of players drafted at each position
# before the "replacement level" player is reached.
DEFAULT_REPLACEMENT_PICKS: dict[str, int] = {
    "C": 12,
    "1B": 12,
    "2B": 12,
    "SS": 12,
    "3B": 12,
    "OF": 60,   # ~5 OF slots * 12 teams
    "SP": 72,   # ~6 SP per team * 12
    "RP": 24,   # ~2 RP per team * 12
}


class ProjectionEngine:
    """Score FanGraphs projections with Yahoo league modifiers and compute VBD."""

    def __init__(self, db: DB) -> None:
        self.db = db
        self.stat_modifiers: dict[int, float] = {}
        self._load_modifiers()

    # ── Internal helpers ──────────────────────────────────────────────

    def _load_modifiers(self) -> None:
        """Load stat modifiers from the database into a lookup dict."""
        mods = self.db.get_stat_modifiers()
        self.stat_modifiers = {m["stat_id"]: m["point_value"] for m in mods}
        if not self.stat_modifiers:
            log.warning("No stat modifiers found – projected points will be 0")

    @staticmethod
    def _safe_float(value) -> float:
        """Coerce a value to float, returning 0.0 on failure."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # ── Points calculation ────────────────────────────────────────────

    def calculate_projected_points(
        self,
        fg_stats: dict,
        position_type: str,
    ) -> float:
        """Return projected fantasy points for one player's stat line.

        Args:
            fg_stats: Dict of FanGraphs stat projections
                      (e.g. ``{"HR": 35, "R": 90, ...}``).
            position_type: ``"B"`` for batter, ``"P"`` for pitcher.

        Returns:
            Total projected fantasy points for the season, rounded to
            two decimal places.
        """
        stat_map = (
            YAHOO_BATTING_STAT_MAP if position_type == "B" else YAHOO_PITCHING_STAT_MAP
        )

        total = 0.0
        for fg_name, stat_id in stat_map.items():
            if stat_id in self.stat_modifiers and fg_name in fg_stats:
                total += self._safe_float(fg_stats[fg_name]) * self.stat_modifiers[stat_id]

        # Derive singles for batters when the league scores them.
        if position_type == "B" and SINGLES_STAT_ID in self.stat_modifiers:
            h = self._safe_float(fg_stats.get("H"))
            doubles = self._safe_float(fg_stats.get("2B"))
            triples = self._safe_float(fg_stats.get("3B"))
            hr = self._safe_float(fg_stats.get("HR"))
            singles = h - doubles - triples - hr
            if singles > 0:
                total += singles * self.stat_modifiers[SINGLES_STAT_ID]

        return round(total, 2)

    # ── Bulk operations ───────────────────────────────────────────────

    def calculate_all_projections(self) -> int:
        """Score every player that has FanGraphs stats.  Returns count."""
        conn = self.db.conn
        rows = conn.execute(
            "SELECT player_key, fg_stats, position_type "
            "FROM players WHERE fg_stats IS NOT NULL"
        ).fetchall()

        updates: list[tuple[float, str]] = []
        for row in rows:
            fg_stats = json.loads(row["fg_stats"]) if row["fg_stats"] else {}
            if not fg_stats:
                continue
            pts = self.calculate_projected_points(fg_stats, row["position_type"])
            updates.append((pts, row["player_key"]))

        if updates:
            conn.executemany(
                "UPDATE players SET projected_points = ? WHERE player_key = ?",
                updates,
            )
            conn.commit()

        log.info("Scored %d players", len(updates))
        return len(updates)

    def calculate_vbd(self, num_teams: int | None = None) -> int:
        """Compute Value Based Drafting values for all scored players.

        VBD = player's projected points − replacement-level points at
        their most favourable eligible position.

        Args:
            num_teams: Override for league size.  If *None*, read from
                       the ``league_settings`` table (falls back to 12).

        Returns:
            Number of players updated.
        """
        if num_teams is None:
            setting = self.db.get_league_setting("num_teams")
            num_teams = int(setting) if setting is not None else 12

        # Build replacement-pick counts, preferring actual roster config.
        replacement_picks = dict(DEFAULT_REPLACEMENT_PICKS)
        for pos_row in self.db.get_roster_positions():
            pos = pos_row["position"]
            count = pos_row["count"]
            if pos in replacement_picks:
                replacement_picks[pos] = num_teams * count

        # Find replacement-level points at each position.
        conn = self.db.conn
        replacement_levels: dict[str, float] = {}

        for position, pick_count in replacement_picks.items():
            pos_type = "P" if position in ("SP", "RP") else "B"
            row = conn.execute(
                "SELECT projected_points FROM players "
                "WHERE positions LIKE ? AND position_type = ? "
                "AND projected_points IS NOT NULL "
                "ORDER BY projected_points DESC "
                "LIMIT 1 OFFSET ?",
                (f"%{position}%", pos_type, max(pick_count - 1, 0)),
            ).fetchone()
            replacement_levels[position] = row["projected_points"] if row else 0.0

        # Assign VBD per player (best eligible position).
        rows = conn.execute(
            "SELECT player_key, positions, position_type, projected_points "
            "FROM players WHERE projected_points IS NOT NULL"
        ).fetchall()

        updates: list[tuple[float, str]] = []
        for row in rows:
            positions = json.loads(row["positions"]) if row["positions"] else []
            proj_pts: float = row["projected_points"]

            best_vbd: float | None = None
            for pos in positions:
                if pos in replacement_levels:
                    vbd = proj_pts - replacement_levels[pos]
                    if best_vbd is None or vbd > best_vbd:
                        best_vbd = vbd

            # Fallback when no eligible position matched replacement data.
            if best_vbd is None:
                generic = "SP" if row["position_type"] == "P" else "OF"
                best_vbd = proj_pts - replacement_levels.get(generic, 0.0)

            updates.append((round(best_vbd, 2), row["player_key"]))

        if updates:
            conn.executemany(
                "UPDATE players SET vbd_value = ? WHERE player_key = ?",
                updates,
            )
            conn.commit()

        log.info("Computed VBD for %d players", len(updates))
        return len(updates)

    def recalculate_all(self, num_teams: int | None = None) -> tuple[int, int]:
        """Reload modifiers, re-score projections, and recompute VBD.

        Returns:
            ``(num_scored, num_vbd)`` — counts of players updated in
            each phase.
        """
        self._load_modifiers()
        n_proj = self.calculate_all_projections()
        n_vbd = self.calculate_vbd(num_teams)
        return n_proj, n_vbd
