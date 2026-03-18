The user wants a quick refreshed view of the best available players. No arguments needed.

1. Call `refresh_draft` to sync latest picks
2. Call `best_available` with count=20
3. Call `my_roster` to see current roster

Then display a clean, scannable board:
- Group players into tiers by VBD (Elite 100+, Premium 50-99, Solid 10-49)
- Bold or flag any players that fill an open roster need
- Mark positions with HIGH scarcity (C, SS) so the user knows to prioritize
- Keep it tight — name, position, team, VBD, one-word note (e.g. "URGENT", "TARGET", "DEPTH")

No long explanations. Just the board.
