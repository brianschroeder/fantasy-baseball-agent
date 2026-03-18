The user is entering a new draft round and wants round-specific guidance. The argument is the round number (e.g. "/round 3" or "/round 7").

1. Call `refresh_draft` to sync any picks made since last check
2. Call `my_roster` to see the current roster state
3. Call `roster_needs` to identify remaining gaps
4. Call `positional_scarcity` to see what positions are running thin league-wide

Then provide a round-specific briefing:

**Round [N] Briefing**
- What tier of player to expect at this round (based on VBD values remaining)
- Your single highest-priority need given the current roster
- 3-5 specific player targets for this round with one-line reasoning each
- Any "act now or miss out" warnings — positions with a cliff coming up
- Your approximate pick number this round (snake draft, 10 teams: odd rounds pick ~same slot, even rounds pick ~11-slot)

Keep it scannable. Use a tight list format. The next pick is coming fast.
