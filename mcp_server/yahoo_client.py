from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import json


LEAGUE_KEY = "469.l.3508"
TEAM_KEY = "469.l.3508.t.9"


class YahooClient:
    def __init__(self, oauth_file="oauth2.json"):
        self.oauth = OAuth2(None, None, from_file=oauth_file)
        self.game = yfa.Game(self.oauth, "mlb")
        self._league = None
        self._team = None

    @property
    def league(self):
        if self._league is None:
            self._league = self.game.to_league(LEAGUE_KEY)
        return self._league

    @property
    def team(self):
        if self._team is None:
            self._team = self.league.to_team(self.league.team_key())
        return self._team

    def get_team(self, team_key):
        return self.league.to_team(team_key)

    def get_settings(self):
        return self.league.settings()

    def get_stat_categories(self):
        return self.league.stat_categories()

    def get_positions(self):
        return self.league.positions()

    def get_draft_results(self):
        return self.league.draft_results()

    def get_free_agents(self, position="ALL"):
        return self.league.free_agents(position)

    def get_roster(self):
        return self.team.roster()

    def get_standings(self):
        return self.league.standings()

    def get_matchups(self, week=None):
        if week:
            return self.league.matchups(week)
        return self.league.matchups()

    def get_keepers(self):
        """Get all keeper players with their team ownership.

        Returns list of dicts with keys: player_key, name, team_key, team_name.
        Uses the Yahoo API status=K filter.
        """
        base = "https://fantasysports.yahooapis.com/fantasy/v2"
        url = f"{base}/league/{LEAGUE_KEY}/players;status=K;out=ownership?format=json"
        resp = self.oauth.session.get(url)
        if resp.status_code != 200:
            return []

        data = resp.json()
        league_data = data.get("fantasy_content", {}).get("league", [])
        if len(league_data) < 2:
            return []

        players_data = league_data[1].get("players", {})
        count = players_data.get("count", 0)
        keepers = []
        for i in range(count):
            p_data = players_data.get(str(i), {}).get("player", [])
            p_info = p_data[0] if p_data else []

            player_key = None
            name = None
            positions = []
            for item in p_info:
                if isinstance(item, dict):
                    if "player_key" in item:
                        player_key = item["player_key"]
                    if "name" in item:
                        name = item["name"].get("full", "")
                    if "display_position" in item:
                        positions = item["display_position"].split(",")
                    if "eligible_positions" in item:
                        pos_list = item["eligible_positions"]
                        if isinstance(pos_list, list):
                            positions = [
                                p.get("position", p) if isinstance(p, dict) else p
                                for p in pos_list
                            ]

            ownership = p_data[1] if len(p_data) > 1 else {}
            owner_info = ownership.get("ownership", {})
            team_key = owner_info.get("owner_team_key", "")
            team_name = owner_info.get("owner_team_name", "")

            keepers.append({
                "player_key": player_key,
                "name": name,
                "team_key": team_key,
                "team_name": team_name,
                "positions": positions,
            })
        return keepers
