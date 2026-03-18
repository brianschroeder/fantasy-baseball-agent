import json
import sqlite3
from pathlib import Path


class DB:
    def __init__(self, db_path="data/fantasy_baseball.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init_db()

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS league_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS stat_modifiers (
                stat_id INTEGER PRIMARY KEY,
                stat_name TEXT,
                display_name TEXT,
                point_value REAL,
                position_type TEXT
            );

            CREATE TABLE IF NOT EXISTS roster_positions (
                position TEXT PRIMARY KEY,
                count INTEGER,
                position_type TEXT
            );

            CREATE TABLE IF NOT EXISTS players (
                player_key TEXT PRIMARY KEY,
                yahoo_player_id INTEGER,
                name TEXT NOT NULL,
                team TEXT,
                positions TEXT,
                position_type TEXT,
                fg_stats TEXT,
                projected_points REAL,
                vbd_value REAL,
                fantasypros_rank INTEGER,
                espn_rank INTEGER,
                ownership_pct REAL,
                status TEXT,
                last_updated TEXT
            );

            CREATE TABLE IF NOT EXISTS draft_picks (
                pick_number INTEGER PRIMARY KEY,
                round INTEGER,
                team_key TEXT,
                team_name TEXT,
                player_key TEXT,
                player_name TEXT,
                cost INTEGER,
                is_keeper BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS my_keepers (
                player_key TEXT PRIMARY KEY,
                player_name TEXT,
                round_cost INTEGER
            );

            CREATE TABLE IF NOT EXISTS draft_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_players_vbd
                ON players(vbd_value DESC);
            CREATE INDEX IF NOT EXISTS idx_players_position
                ON players(position_type, vbd_value DESC);
            CREATE INDEX IF NOT EXISTS idx_players_status
                ON players(status);
            CREATE INDEX IF NOT EXISTS idx_draft_picks_round
                ON draft_picks(round);
        """)
        self.conn.commit()

    # ── Upsert helpers ──────────────────────────────────────────────

    def upsert_player(self, player_dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO players
               (player_key, yahoo_player_id, name, team, positions,
                position_type, fg_stats, projected_points, vbd_value,
                fantasypros_rank, espn_rank, ownership_pct, status, last_updated)
               VALUES (:player_key, :yahoo_player_id, :name, :team, :positions,
                       :position_type, :fg_stats, :projected_points, :vbd_value,
                       :fantasypros_rank, :espn_rank, :ownership_pct, :status,
                       :last_updated)""",
            player_dict,
        )
        self.conn.commit()

    def upsert_draft_pick(self, pick_dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO draft_picks
               (pick_number, round, team_key, team_name,
                player_key, player_name, cost, is_keeper)
               VALUES (:pick_number, :round, :team_key, :team_name,
                       :player_key, :player_name, :cost, :is_keeper)""",
            pick_dict,
        )
        self.conn.commit()

    def upsert_stat_modifier(self, mod_dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO stat_modifiers
               (stat_id, stat_name, display_name, point_value, position_type)
               VALUES (:stat_id, :stat_name, :display_name, :point_value,
                       :position_type)""",
            mod_dict,
        )
        self.conn.commit()

    def upsert_roster_position(self, pos, count, pos_type):
        self.conn.execute(
            """INSERT OR REPLACE INTO roster_positions
               (position, count, position_type)
               VALUES (?, ?, ?)""",
            (pos, count, pos_type),
        )
        self.conn.commit()

    # ── League settings ─────────────────────────────────────────────

    def set_league_setting(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def get_league_setting(self, key):
        row = self.conn.execute(
            "SELECT value FROM league_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    # ── Draft state ─────────────────────────────────────────────────

    def set_draft_state(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO draft_state (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def get_draft_state(self, key):
        row = self.conn.execute(
            "SELECT value FROM draft_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    # ── Query helpers ───────────────────────────────────────────────

    def get_best_available(self, position=None, limit=10):
        # Exclude both drafted players and keepers
        exclude_sql = """player_key NOT IN (SELECT player_key FROM draft_picks WHERE player_key IS NOT NULL)
                     AND player_key NOT IN (SELECT player_key FROM my_keepers WHERE player_key IS NOT NULL)
                     AND (status IS NULL OR status != 'K')"""
        if position:
            rows = self.conn.execute(
                f"""SELECT * FROM players
                   WHERE {exclude_sql}
                     AND positions LIKE ?
                   ORDER BY vbd_value DESC
                   LIMIT ?""",
                (f"%{position}%", limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""SELECT * FROM players
                   WHERE {exclude_sql}
                   ORDER BY vbd_value DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_player(self, name):
        rows = self.conn.execute(
            "SELECT * FROM players WHERE name LIKE ?", (f"%{name}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_draft_picks(self):
        rows = self.conn.execute(
            "SELECT * FROM draft_picks ORDER BY pick_number"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_drafted_player_keys(self):
        rows = self.conn.execute(
            "SELECT player_key FROM draft_picks WHERE player_key IS NOT NULL"
        ).fetchall()
        return {row["player_key"] for row in rows}

    def get_my_roster(self, my_team_key):
        rows = self.conn.execute(
            "SELECT * FROM draft_picks WHERE team_key = ? ORDER BY round",
            (my_team_key,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_roster_positions(self):
        rows = self.conn.execute("SELECT * FROM roster_positions").fetchall()
        return [dict(r) for r in rows]

    def get_stat_modifiers(self):
        rows = self.conn.execute("SELECT * FROM stat_modifiers").fetchall()
        return [dict(r) for r in rows]

    def upsert_keeper(self, player_key, player_name, team_key, team_name, round_cost=None):
        self.conn.execute(
            """INSERT OR REPLACE INTO my_keepers
               (player_key, player_name, round_cost)
               VALUES (?, ?, ?)""",
            (player_key, player_name, round_cost),
        )
        self.conn.commit()

    def get_all_keepers(self):
        """Get all keeper records from draft_picks where is_keeper=1."""
        rows = self.conn.execute(
            "SELECT * FROM draft_picks WHERE is_keeper = 1 ORDER BY team_key, player_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_positional_scarcity(self, position):
        row = self.conn.execute(
            """SELECT COUNT(*) as count, AVG(vbd_value) as avg_vbd
               FROM players
               WHERE player_key NOT IN (SELECT player_key FROM draft_picks WHERE player_key IS NOT NULL)
                 AND positions LIKE ?""",
            (f"%{position}%",),
        ).fetchone()
        return dict(row)

    # ── Lifecycle ───────────────────────────────────────────────────

    def close(self):
        self.conn.close()
