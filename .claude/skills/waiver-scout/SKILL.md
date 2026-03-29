---
name: waiver-scout
description: Morning waiver wire research agent for in-season fantasy baseball. Triggers when user asks for a morning report, waiver wire recommendations, who to add/drop, or says things like "run the morning report", "what should I do on waivers", "who's hot this week", "morning scout", or "waiver analysis". Also runs automatically on the daily schedule.
---

# Waiver Wire Morning Scout

You're running the daily fantasy baseball research agent for the user's Yahoo H2H Points league. Your job is to produce a **prioritized, actionable recommendations report** they can act on immediately.

## League Context

- **League**: Yahoo H2H Points, 10 teams, keeper league (469.l.3508)
- **Team**: "Called Up To The Show" — Team 9 (469.l.3508.t.9)
- **Format**: Head-to-head weekly matchups, points scoring

### Scoring that drives decisions:
**Batting**: HR (+4.0), 3B (+3.0), 2B (+2.0), RBI (+1.5), SB (+1.5), R (+1.0), 1B (+1.0), BB (+1.0), HBP (+1.0), K (-0.5)
**Pitching**: SV (+8.0), W (+6.0), QS (+6.0), HLD (+4.0), K (+1.0), IP (+1.0), ER (-1.0), BB (-0.5), L (-4.0), BSV (-2.0)

---

## Step 1 — Pull League Context

Run these tools **in parallel** to establish your baseline:

1. `get_my_team_live` — current roster, injury flags, IL slots
2. `get_standings` — where we sit in the league, who we're chasing
3. `get_current_matchup` — this week's opponent and current score
4. `league_settings` — scoring confirmation (use cached, just to verify)

Internalize this before continuing. Note:
- Any players on IL or injured → they're candidates to drop for active contributors
- If we're up big in the matchup → can stream safely. If we're down → need high-upside adds.
- If we're chasing 1st or 2nd in standings → prioritize players who win matchups (floor). Behind → swing for ceiling.

---

## Step 2 — Get Waiver Wire Data

Run these **in parallel**:

1. `get_free_agents_live` (position="SP", count=20) — starting pitcher adds
2. `get_free_agents_live` (position="RP", count=15) — reliever/closer adds
3. `get_free_agents_live` (position="OF", count=15) — outfield adds
4. `get_free_agents_live` (position="ALL", count=40) — overall best available

Focus on:
- Players owned in 15-60% of leagues (rostered widely = known value, but still available = window)
- Players with 0-15% ownership who might be trending (hidden gems)
- Avoid players owned 70%+ (those are likely already gone or owned by others in this 10-team league)

---

## Step 3 — Pitching Week Analysis

Before web research, audit your current pitching situation for the week using `get_my_team_live`.

**For every SP and RP on your roster, identify:**
- How many starts do they have this week? (1-start vs 2-start is a huge difference)
- Which days are they starting?
- Any injury flags or recent struggles worth dropping for?

**Two-start math**: A 2-start SP who goes 6 IP, 7K, 1 ER each outing scores:
`(2 × QS +6) + (2 × 6 IP × +1) + (2 × 7 K × +1) + (2 × -1 ER) = 12 + 12 + 14 - 2 = **36 pts**`
vs a 1-start SP who only gets half that. Two-start pitchers are must-starts and must-adds.

**Determine your SP slot availability:**
- How many SP slots do you have filled vs open this week?
- Are any of your rostered SP only making 1 start this week? → candidate to swap for a 2-start streamer
- Is anyone on your pitching staff in a bad matchup? → candidate to bench/drop for a better option

---

## Step 4 — Web Research

Do targeted web searches. Run these searches:

1. Search: `fantasy baseball two start pitchers week [current week number] [current date]`
2. Search: `fantasy baseball streaming pitchers two starts this week [current date]`
3. Search: `fantasy baseball waiver wire adds [current date]`
4. Search: `fantasy baseball hot players this week [current date]`
5. Search: `fantasy baseball injury news today [current date]`
6. Search: `fantasy baseball closer news saves opportunities [current date]`
7. If any rostered players are injured or cold: search their name + "fantasy baseball"

**What to look for:**
- **Two-start pitchers available on waivers** — highest priority pitching add every week
- Favorable single-start matchups (bad offensive team, home park, high K rate vs opponent)
- Closers moving into save opportunities (injured closer = his backup is a target)
- Injury designations that open playing time (starter IL → his backup becomes relevant)
- Players breaking out (multi-HR games, pitch count increasing, role change)
- RP with hold/save opportunities this week

**Cross-reference with your roster**: If a waiver wire player overlaps with your weakest current player at the same position, flag it as an add/drop candidate.

---

## Step 5 — Generate the Report

Produce a structured morning report. Be direct and opinionated — tell the user exactly what to do, ranked by priority.

```
════════════════════════════════════════════════════════
  MORNING WAIVER SCOUT — [DATE]
════════════════════════════════════════════════════════

ROSTER SNAPSHOT
Record: [W-L], [rank] in league
This week: vs. [opponent] — [my score] to [their score] (Week X)
Flags: [any IL, injured, or players to watch]

────────────────────────────────────────────────────────
MY PITCHING THIS WEEK
────────────────────────────────────────────────────────

2-Start SP:  [Name] vs [OPP] ([day]), vs [OPP] ([day]) ← priority starts
1-Start SP:  [Name] vs [OPP] ([day])
             [Name] vs [OPP] ([day])
No start:    [Name] — [reason: off week / skip start]
RP:          [Name] — [save/hold opps this week]

Projected pitching pts this week: ~[estimate based on starts × avg output]
Open SP slots: [X of Y filled]

────────────────────────────────────────────────────────
STREAMING PITCHERS THIS WEEK
────────────────────────────────────────────────────────

[Ranked by value — 2-start streamers always listed first]

⭐ 2-START: [SP Name] ([Team], [X]% owned)
   Starts: vs [OPP] [day] + vs [OPP] [day]
   Why: [matchup quality, K rate, recent form — cite scoring math]
   ADD for: [who to drop or bench]

   [SP Name] ([Team], [X]% owned)
   Starts: vs [OPP] [day] + vs [OPP] [day]
   Why: [...]
   ADD for: [...]

1-START: [SP Name] ([Team], [X]% owned)
   Starts: vs [OPP] [day]
   Why: [only recommend if matchup is excellent or you have open slots]
   ADD for: [...]

────────────────────────────────────────────────────────
TOP ADDS (Non-Pitching, Priority Order)
────────────────────────────────────────────────────────

1. ADD [Player Name] ([Pos], [Team]) — DROP [Player to cut]
   Why: [scoring-specific reason — cite actual point values]
   Owned: [X]% | Impact: [High/Medium/Low]

[2-5 same format]

────────────────────────────────────────────────────────
HOLD / MONITOR
────────────────────────────────────────────────────────

- [Player]: [why watching — role uncertainty, coming back from IL, etc.]

────────────────────────────────────────────────────────
MATCHUP STRATEGY
────────────────────────────────────────────────────────

[2-3 sentences: how to win this week given your pitching slate, opponent's
roster, and any streaming moves. Call out if you're thin on starts and
need to add a streamer to compete on the pitching side.]

════════════════════════════════════════════════════════
```

---

## Scoring Priorities for Recommendations

When ranking adds, weight them by scoring impact:

**Pitchers:**
- **2-start SP on waivers = #1 priority** — two starts doubles every counting stat. A mediocre SP with 2 starts often outscores an ace with 1 start.
- Closer with save opps = elite add (SV +8 is the single most valuable pitching event)
- SP who racks up QS + K + IP (QS +6, each K +1, each IP +1 — workhorses accumulate fast)
- Setup man with 5+ holds/week potential (HLD +4 each)
- Avoid SP in bad matchups (strong offensive team, hitter's park) — ER -1.0 and L -4.0 hurt
- Always note start count and opponent quality for every pitcher recommendation

**Batters:**
- Power hitters (HR +4 + R +1 + RBI +1.5 = ~6.5 pts per HR)
- High OBP players (BB = free +1.0 pts same as a single)
- SB guys are nice bonus but only if they also hit (SB +1.5)
- Don't chase speed-only profiles

**General:**
- Prioritize floor over ceiling (weekly H2H rewards consistency)
- Hot streaks matter — but check if it's sustainable vs. small-sample luck
- Playing time is the #1 filter — a .280 hitter playing every day beats a .320 hitter in a platoon

---

## Step 6 — Send to Telegram

After the report is generated, send it to the Fantasy Baseball Telegram chat using the `send_message` tool from the `telegram` MCP server.

- **Chat ID**: Use the `FANTASY_BASEBALL_CHAT_ID` (check with `list_chats` if you don't have it, look for "⚾ Fantasy Baseball Scout")
- **Format**: Send as plain text — the report format already has clear visual structure
- **Split long messages**: If the report is very long, send the Roster Snapshot + Top Adds as one message and Streaming/Hold/Strategy as a second
- Call: `send_message(chat_id=CHAT_ID, message=report_text)`

---

## Important Notes

- **Be specific** — "Add Player X, drop Player Y" not "consider adding..."
- **Rank your recommendations** — user has limited waiver moves, help them prioritize
- **Explain the why in terms of this league's scoring** — not generic fantasy advice
- **Check injury status** from your web research — don't recommend an injured player
- Use real ownership percentages from `get_free_agents_live` when ranking
- If you find conflicting info between web research and Yahoo data, note it
- Always send the final report to Telegram — that's the delivery mechanism
