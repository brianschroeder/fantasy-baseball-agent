"""Scrape FantasyPros H2H Points rankings using Playwright."""

import asyncio
from playwright.async_api import async_playwright


async def scrape_points_rankings():
    """Scrape FantasyPros overall rankings for points leagues.

    URL: https://www.fantasypros.com/mlb/rankings/overall.php

    Returns list of dicts: {rank: int, name: str, team: str, position: str}
    sorted by rank.
    """
    url = "https://www.fantasypros.com/mlb/rankings/overall.php"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")

            # Dismiss cookie consent banner if present
            try:
                consent_selectors = [
                    "button:has-text('Accept')",
                    "button:has-text('I Accept')",
                    "button:has-text('Got it')",
                    "button:has-text('OK')",
                    ".cookie-consent button",
                    "#onetrust-accept-btn-handler",
                    ".qc-cmp2-summary-buttons button:first-child",
                ]
                for selector in consent_selectors:
                    btn = page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(500)
                        break
            except Exception:
                pass

            # Wait for the rankings table to load
            table_selector = None
            for sel in [
                "#ranking-table",
                "table.ranking-table",
                ".rankings-table",
                "table.player-table",
                "#data-table",
                "table",
            ]:
                try:
                    await page.wait_for_selector(sel, timeout=10000)
                    table_selector = sel
                    break
                except Exception:
                    continue

            if not table_selector:
                print("Warning: Could not find rankings table on FantasyPros.")
                await browser.close()
                return []

            # Extract player data from the table
            players = await page.evaluate(r"""(tableSelector) => {
                const table = document.querySelector(tableSelector);
                if (!table) return [];

                const results = [];
                const rows = table.querySelectorAll('tbody tr');

                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length < 2) continue;

                    // Try to extract rank from first cell
                    const rankText = cells[0]?.textContent?.trim();
                    const rank = parseInt(rankText, 10);
                    if (isNaN(rank)) continue;

                    // Player name - may be in a link or span within the cell
                    const nameCell = cells[1];
                    let name = '';
                    let team = '';
                    let position = '';

                    // Try to get name from link or player-name class
                    const nameLink = nameCell?.querySelector('a.player-name, a');
                    if (nameLink) {
                        name = nameLink.textContent.trim();
                    } else {
                        name = nameCell?.textContent?.trim() || '';
                    }

                    // Team and position are often in small text or separate spans
                    const smallText = nameCell?.querySelector('small, .player-team, .player-info span');
                    if (smallText) {
                        const info = smallText.textContent.trim();
                        // Format is often "TEAM - POS" or "TEAM POS"
                        const parts = info.split(/[\s-]+/).filter(Boolean);
                        if (parts.length >= 2) {
                            team = parts[0];
                            position = parts.slice(1).join(', ');
                        } else if (parts.length === 1) {
                            team = parts[0];
                        }
                    }

                    // Fallback: check other cells for team/position
                    if (!team && cells.length > 2) {
                        team = cells[2]?.textContent?.trim() || '';
                    }
                    if (!position && cells.length > 3) {
                        position = cells[3]?.textContent?.trim() || '';
                    }

                    // Clean up name (remove team/pos info that may be appended)
                    name = name.replace(/\s*\(.*?\)\s*$/, '').trim();

                    if (name) {
                        results.push({ rank, name, team, position });
                    }
                }

                return results;
            }""", table_selector)

            await browser.close()

            if not players:
                print("Warning: No ranking data extracted from FantasyPros.")
                return []

            # Ensure sorted by rank
            players.sort(key=lambda x: x.get("rank", 9999))
            return players

    except Exception as e:
        print(f"Error scraping FantasyPros rankings: {e}")
        return []


if __name__ == "__main__":
    async def main():
        print("Scraping FantasyPros overall rankings for points leagues...")
        rankings = await scrape_points_rankings()

        print(f"\n=== FantasyPros Rankings ({len(rankings)} players) ===")
        for player in rankings[:10]:
            print(
                f"  #{player['rank']} {player['name']} "
                f"({player['team']}) - {player['position']}"
            )

    asyncio.run(main())
