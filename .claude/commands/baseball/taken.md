The user is recording a draft pick that Yahoo hasn't updated yet, or wants to manually track a pick.

The argument(s) passed to this command are the player name(s) that were just drafted. There may be one player or multiple (e.g. "/taken Aaron Judge" or "/taken Judge, Soto").

For each player mentioned:
1. Call `search_player` to confirm the correct full name and spelling
2. Call `record_pick` with the confirmed player name to mark them as drafted

After recording:
- Confirm which player(s) were marked as taken
- Briefly note how it affects the board (e.g. "Contreras gone — Herrera is now the top C at VBD 67")
- If it affects YOUR roster strategy, flag it (e.g. "That was your R3 target — pivot to Goodman or grab C earlier")

Keep it brief — one confirmation line per player, one strategic note if relevant.
