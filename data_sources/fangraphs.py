"""Scrape FanGraphs Depth Charts projections using Playwright.

FanGraphs projections page structure (as of March 2026):
- Table is inside `.table-scroll table` (not `.fg-data-grid`)
- URL param `statgroup=standard` shows counting stats (H, 2B, HR, R, RBI, etc.)
- Page size dropdown is a `select` with options: 30, 50, 100, 200, Infinity
- Two identical tables exist: `.table-scroll table` and `.table-fixed table`
  (the fixed one is for the sticky left columns). Use `.table-scroll table`.
"""

import asyncio
from playwright.async_api import async_playwright


# Batting Standard: #, Name, Team, G, AB, PA, H, 1B, 2B, 3B, HR, R, RBI, BB, IBB, SO, HBP, SF, SH, SB, CS, AVG
BATTING_URL = "https://www.fangraphs.com/projections?type=fangraphsdc&stats=bat&pos=all&team=0&statgroup=standard"
# Batting Dashboard (for position info): #, Name, Team, G, PA, HR, R, RBI, SB, BB%, K%, ISO, BABIP, AVG, OBP, SLG, wOBA, wRC+, BsR, Off, Def, WAR
BATTING_DASH_URL = "https://www.fangraphs.com/projections?type=fangraphsdc&stats=bat&pos=all&team=0&statgroup=dashboard"

# Pitching Standard: #, Name, Team, W, L, SV, HLD, G, GS, IP, SO, BB, HR, ERA, WHIP, etc.
PITCHING_URL = "https://www.fangraphs.com/projections?type=fangraphsdc&stats=pit&pos=all&team=0&statgroup=standard"


async def _scrape_fangraphs_table(url: str, label: str) -> list[dict]:
    """Generic scraper for a FanGraphs projection table.

    Navigates to the URL, switches to show all rows, and extracts
    headers + data from the `.table-scroll table`.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            print(f"  Loading {label} page...")
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")

            # FanGraphs is a Next.js app — the table renders after JS hydration.
            # Wait generously for JS to render the data table.
            await page.wait_for_timeout(5000)

            # Try multiple selectors for the projections table
            table_found = False
            for selector in [".table-scroll table tbody tr", "table tbody tr td a[href*='/players/']"]:
                try:
                    await page.wait_for_selector(selector, timeout=20000)
                    table_found = True
                    break
                except Exception:
                    continue

            if not table_found:
                # Debug: check what tables exist
                table_count = await page.evaluate("() => document.querySelectorAll('table').length")
                print(f"  Debug: found {table_count} tables on page but no data rows")
            print(f"  Table loaded. Selecting all rows...")

            # Select "Infinity" in the page size dropdown to show all rows.
            # There may be two identical dropdowns (top and bottom of table).
            try:
                selects = page.locator("select").filter(has=page.locator("option", has_text="Infinity"))
                if await selects.count() > 0:
                    await selects.first.select_option(label="Infinity")
                    # Wait for table to re-render with all rows
                    await page.wait_for_timeout(3000)
                    await page.wait_for_selector(".table-scroll table tbody tr", timeout=15000)
            except Exception as e:
                print(f"  Warning: Could not select Infinity page size: {e}")

            # Extract headers and data from .table-scroll table
            result = await page.evaluate("""() => {
                const table = document.querySelector('.table-scroll table');
                if (!table) return { headers: [], rows: [] };
                const headers = Array.from(table.querySelectorAll('thead th'))
                    .map(th => th.textContent.trim());
                const rows = Array.from(table.querySelectorAll('tbody tr'))
                    .map(tr => Array.from(tr.querySelectorAll('td'))
                        .map(td => td.textContent.trim()));
                return { headers, rows };
            }""")

            await browser.close()

            headers = result.get("headers", [])
            rows = result.get("rows", [])

            if not headers or not rows:
                print(f"  Warning: No {label} data found on FanGraphs.")
                return []

            print(f"  Extracted {len(rows)} rows with {len(headers)} columns.")

            # Build list of dicts
            players = []
            for row in rows:
                if len(row) < len(headers):
                    continue
                player = {}
                for i, header in enumerate(headers):
                    key = header.strip()
                    if not key:
                        continue
                    value = row[i] if i < len(row) else ""
                    # Convert numeric values
                    try:
                        if value == "":
                            pass
                        elif "." in value:
                            player[key] = float(value)
                            continue
                        elif value.lstrip("-").isdigit():
                            player[key] = int(value)
                            continue
                    except (ValueError, AttributeError):
                        pass
                    player[key] = value

                # Normalize field names
                if "Name" in player:
                    player["name"] = player["Name"]
                if "Team" in player:
                    player["team"] = player["Team"]
                if "Pos" in player:
                    player["positions"] = player["Pos"]
                players.append(player)

            return players

    except Exception as e:
        print(f"  Error scraping FanGraphs {label}: {e}")
        return []


async def scrape_batting_projections() -> list[dict]:
    """Scrape FanGraphs Depth Charts batting projections (standard stats).

    Returns list of dicts with keys: name, team, and counting stats.
    Position data is NOT available in the FanGraphs standard table — positions
    should be supplemented via Yahoo API or other sources.
    """
    return await _scrape_fangraphs_table(BATTING_URL, "batting projections")


async def scrape_pitching_projections() -> list[dict]:
    """Scrape FanGraphs Depth Charts pitching projections (standard stats).

    Returns list of dicts with keys: name, team, and counting stats
    (W, L, SV, HLD, G, GS, IP, SO, BB, HR, ERA, WHIP, etc.).
    """
    return await _scrape_fangraphs_table(PITCHING_URL, "pitching projections")


async def scrape_all_projections() -> tuple[list[dict], list[dict]]:
    """Scrape both batting and pitching projections.

    Returns:
        tuple: (batters, pitchers) where each is a list of player dicts.
    """
    batters = await scrape_batting_projections()
    pitchers = await scrape_pitching_projections()
    return batters, pitchers


if __name__ == "__main__":
    async def main():
        print("Scraping FanGraphs Depth Charts projections...")
        batters, pitchers = await scrape_all_projections()

        print(f"\n=== Batting Projections ({len(batters)} players) ===")
        for player in batters[:10]:
            name = player.get("name", "Unknown")
            team = player.get("team", "")
            hr = player.get("HR", "")
            rbi = player.get("RBI", "")
            sb = player.get("SB", "")
            print(f"  {name} ({team}) - HR: {hr}, RBI: {rbi}, SB: {sb}")

        print(f"\n=== Pitching Projections ({len(pitchers)} players) ===")
        for player in pitchers[:10]:
            name = player.get("name", "Unknown")
            team = player.get("team", "")
            so = player.get("SO", "")
            w = player.get("W", "")
            sv = player.get("SV", "")
            print(f"  {name} ({team}) - W: {w}, SO: {so}, SV: {sv}")

    asyncio.run(main())
