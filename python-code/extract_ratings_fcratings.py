from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.fcratings.com"
NATIONS_URL = f"{BASE_URL}/lists/all-nations"
ROOT = Path(__file__).resolve().parents[1]
SQUADS_CSV = ROOT / "data" / "raw" / "fifa_world_cup_2026_squads.csv"
RAW_DIR = ROOT / "data" / "raw"
OUT_CSV = RAW_DIR / "fcratings_fc26_ratings.csv"

STAT_NAMES = ["OVR", "PAC", "SHO", "PAS", "DRI", "DEF", "PHY"]
POSITIONS = {"GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"}

COUNTRY_ALIASES = {
    "IR Iran": "Iran",
    "USA": "United States",
    "United States of America": "United States",
    "Netherlands": "Holland",
}


def clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def normalize_country(country: str) -> str:
    country = re.sub(r"^.*?\d{4}\s+", "", clean(country))
    return COUNTRY_ALIASES.get(country, country)


def lookup_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_nation_urls() -> dict[str, str]:
    soup = get_soup(NATIONS_URL)
    nation_urls: dict[str, str] = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        name = clean(link.get_text(" "))
        if "/nations/" not in href or not name:
            continue
        nation_urls[lookup_key(name)] = urljoin(BASE_URL, href)
    return nation_urls


def extract_stat(block_text: str, stat: str) -> str:
    match = re.search(rf"\b{stat}\s+(\d+)", block_text)
    return match.group(1) if match else ""


def parse_nation_page(html: str, nation: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        player_name = clean(link.get_text(" "))
        if "/players/" not in href or not player_name:
            continue
        if player_name in seen:
            continue

        container = link
        for _ in range(8):
            if container.parent is None:
                break
            container = container.parent
            text = clean(container.get_text(" "))
            if "OVR" in text and "PAC" in text and "PHY" in text:
                break

        block_text = clean(container.get_text("\n"))
        stats = {stat.lower(): extract_stat(block_text, stat) for stat in STAT_NAMES}
        if not stats["ovr"]:
            continue

        text_parts = [clean(part) for part in container.get_text("\n").splitlines()]
        text_parts = [part for part in text_parts if part]
        position = next((part for part in text_parts if part in POSITIONS), "")

        club = ""
        if position:
            pos_index = text_parts.index(position)
            for item in text_parts[pos_index + 1 :]:
                if item not in STAT_NAMES and not item.isdigit():
                    club = item
                    break

        seen.add(player_name)
        rows.append(
            {
                "source": "FCRatings",
                "rank": str(len(rows) + 1),
                "player_name": player_name,
                "nationality": nation,
                "club": club,
                "position": position,
                **stats,
            }
        )

    return rows


def main() -> None:
    squads = pd.read_csv(SQUADS_CSV)
    squad_countries = sorted({normalize_country(country) for country in squads["country"].dropna().unique()})
    nation_urls = get_nation_urls()

    rows: list[dict[str, str]] = []
    missing_countries: list[str] = []

    for country in squad_countries:
        url = nation_urls.get(lookup_key(country))
        if not url:
            missing_countries.append(country)
            continue

        nation_url = f"{url}?gender=men"
        soup = get_soup(nation_url)
        country_rows = parse_nation_page(str(soup), country)
        print(f"{country}: {len(country_rows)} players")
        rows.extend(country_rows)

    if missing_countries:
        print("Countries not found in FCRatings:")
        for country in missing_countries:
            print(f"- {country}")

    if not rows:
        raise RuntimeError("No FCRatings rows extracted.")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
