"""Scrape ESPN points league player rankings using Playwright."""

import asyncio
from playwright.async_api import async_playwright


async def scrape_espn_rankings():
    """Scrape ESPN player rankings for points leagues.

    Tries multiple ESPN fantasy baseball ranking URLs.
    Falls back to an empty list with a warning if the page structure
    cannot be parsed.

    Returns list of dicts: {rank: int, name: str, team: str, position: str}
    """
    urls = [
        "https://www.espn.com/fantasy/baseball/story/_/id/40062694/fantasy-baseball-2026-rankings-points-leagues",
        "https://www.espn.com/fantasy/baseball/story/_/page/mlbdk2k26_pitcherranks/fantasy-baseball-rankings-2026",
        "https://www.espn.com/fantasy/baseball/story/_/page/mlbdk2k26_ranks/fantasy-baseball-rankings-2026",
    ]

    for url in urls:
        players = await _try_scrape_espn(url)
        if players:
            return players

    print("Warning: Could not scrape ESPN rankings from any known URL.")
    return []


async def _try_scrape_espn(url):
    """Attempt to scrape ESPN rankings from a single URL.

    Returns list of player dicts, or empty list on failure.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"Warning: Failed to load {url}: {e}")
                await browser.close()
                return []

            # Wait a moment for dynamic content to render
            await page.wait_for_timeout(3000)

            # Strategy 1: Look for a structured table on the page
            players = await page.evaluate("""() => {
                const results = [];

                // Try to find a rankings table
                const tables = document.querySelectorAll('table');
                for (const table of tables) {
                    const rows = table.querySelectorAll('tbody tr, tr');
                    if (rows.length < 5) continue;  // Skip small/nav tables

                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 2) continue;

                        const rankText = cells[0]?.textContent?.trim();
                        const rank = parseInt(rankText, 10);
                        if (isNaN(rank) || rank < 1 || rank > 500) continue;

                        let name = '';
                        let team = '';
                        let position = '';

                        // Name is typically in the second cell
                        const nameCell = cells[1];
                        const link = nameCell?.querySelector('a');
                        name = link ? link.textContent.trim() : nameCell?.textContent?.trim() || '';

                        // Team and position may be in subsequent cells or within name cell
                        if (cells.length > 2) {
                            team = cells[2]?.textContent?.trim() || '';
                        }
                        if (cells.length > 3) {
                            position = cells[3]?.textContent?.trim() || '';
                        }

                        if (name && name.length > 1) {
                            results.push({ rank, name, team, position });
                        }
                    }

                    if (results.length > 0) break;  // Found data in this table
                }

                return results;
            }""")

            # Strategy 2: If no table found, try parsing article-style ranked lists
            if not players:
                players = await page.evaluate("""() => {
                    const results = [];
                    const body = document.querySelector('.article-body, article, .story-body, main');
                    if (!body) return results;

                    // Look for patterns like "1. Player Name, Team, POS" or
                    // numbered list items in the article
                    const text = body.innerText;
                    const lines = text.split('\\n');

                    const rankPattern = /^\\s*(\\d{1,3})\\.\\s+(.+)/;

                    for (const line of lines) {
                        const match = line.match(rankPattern);
                        if (!match) continue;

                        const rank = parseInt(match[1], 10);
                        if (rank < 1 || rank > 500) continue;

                        let rest = match[2].trim();
                        let name = rest;
                        let team = '';
                        let position = '';

                        // Try to parse "Name, Team POS" or "Name, POS, Team"
                        const commaParts = rest.split(',').map(s => s.trim());
                        if (commaParts.length >= 2) {
                            name = commaParts[0];
                            // Second part might be "Team POS" or just team
                            const teamPos = commaParts[1].trim().split(/\\s+/);
                            if (teamPos.length >= 2) {
                                team = teamPos[0];
                                position = teamPos.slice(1).join(', ');
                            } else {
                                team = commaParts[1].trim();
                            }
                            if (commaParts.length >= 3) {
                                position = commaParts[2].trim();
                            }
                        }

                        if (name && name.length > 1 && name.length < 50) {
                            results.push({ rank, name, team, position });
                        }
                    }

                    return results;
                }""")

            # Strategy 3: Look for inline-table or custom ESPN components
            if not players:
                players = await page.evaluate("""() => {
                    const results = [];

                    // ESPN sometimes uses custom inline tables within articles
                    const inlineTables = document.querySelectorAll(
                        '.inline-table, .mod-content table, .Table'
                    );
                    for (const table of inlineTables) {
                        const rows = table.querySelectorAll('tr');
                        for (const row of rows) {
                            const cells = row.querySelectorAll('td, th');
                            if (cells.length < 2) continue;

                            const firstText = cells[0]?.textContent?.trim();
                            const rank = parseInt(firstText, 10);
                            if (isNaN(rank) || rank < 1) continue;

                            const name = cells[1]?.textContent?.trim() || '';
                            const team = cells.length > 2 ? cells[2]?.textContent?.trim() : '';
                            const position = cells.length > 3 ? cells[3]?.textContent?.trim() : '';

                            if (name) {
                                results.push({ rank, name, team, position });
                            }
                        }
                        if (results.length > 0) break;
                    }

                    return results;
                }""")

            await browser.close()

            if players:
                players.sort(key=lambda x: x.get("rank", 9999))

            return players

    except Exception as e:
        print(f"Error scraping ESPN rankings from {url}: {e}")
        return []


if __name__ == "__main__":
    async def main():
        print("Scraping ESPN fantasy baseball rankings...")
        rankings = await scrape_espn_rankings()

        if rankings:
            print(f"\n=== ESPN Rankings ({len(rankings)} players) ===")
            for player in rankings[:10]:
                print(
                    f"  #{player['rank']} {player['name']} "
                    f"({player['team']}) - {player['position']}"
                )
        else:
            print("\nNo rankings data could be extracted from ESPN.")
            print("ESPN's page structure may have changed. Manual inspection needed.")

    asyncio.run(main())
