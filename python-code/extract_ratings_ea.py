from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import requests
from bs4 import BeautifulSoup


EA_URL = "https://www.ea.com/en/games/ea-sports-fc/ratings"
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_CSV = RAW_DIR / "ea_fc26_ratings.csv"
PAGE_SIZE = 100


def nested_label(value: dict | None, key: str = "label") -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get(key) or "")


def stat_value(item: dict, stat: str) -> str:
    stats = item.get("stats") or {}
    stat_item = stats.get(stat) or {}
    value = stat_item.get("value")
    return "" if value is None else str(value)


def player_name(item: dict) -> str:
    common_name = item.get("commonName")
    if common_name:
        return str(common_name)
    first = item.get("firstName") or ""
    last = item.get("lastName") or ""
    return f"{first} {last}".strip()


def fetch_page(page: int) -> tuple[list[dict], int]:
    params = {"gender": "0", "page": str(page)}
    response = requests.get(EA_URL, params=params, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise RuntimeError("EA __NEXT_DATA__ script not found.")

    data = json.loads(script.string)
    rating_details = data["props"]["pageProps"]["ratingDetails"]
    return rating_details.get("items", []), int(rating_details.get("totalItems", 0))


def row_from_item(item: dict) -> dict[str, str]:
    return {
        "source": "EA",
        "ea_id": str(item.get("id") or ""),
        "rank": str(item.get("rank") or ""),
        "player_name": player_name(item),
        "first_name": str(item.get("firstName") or ""),
        "last_name": str(item.get("lastName") or ""),
        "common_name": str(item.get("commonName") or ""),
        "gender": nested_label(item.get("gender")),
        "nationality": nested_label(item.get("nationality")),
        "team": nested_label(item.get("team")),
        "league": str(item.get("leagueName") or ""),
        "position": nested_label(item.get("position"), "shortLabel"),
        "position_label": nested_label(item.get("position")),
        "overall": str(item.get("overallRating") or ""),
        "pac": stat_value(item, "pac"),
        "sho": stat_value(item, "sho"),
        "pas": stat_value(item, "pas"),
        "dri": stat_value(item, "dri"),
        "def": stat_value(item, "def"),
        "phy": stat_value(item, "phy"),
        "height_cm": str(item.get("height") or ""),
        "weight_kg": str(item.get("weight") or ""),
        "birthdate": str(item.get("birthdate") or ""),
        "skill_moves": str(item.get("skillMoves") or ""),
        "weak_foot": str(item.get("weakFootAbility") or ""),
        "preferred_foot_id": str(item.get("preferredFoot") or ""),
    }


def main() -> None:
    first_items, total_items = fetch_page(1)
    if not first_items:
        raise RuntimeError("No EA FC 26 rating rows found on page 1.")

    total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
    rows = [row_from_item(item) for item in first_items]
    print(f"Page 1/{total_pages}: {len(first_items)} players")

    for page in range(2, total_pages + 1):
        items, _ = fetch_page(page)
        if not items:
            print(f"Page {page}/{total_pages}: 0 players, stopping.")
            break
        rows.extend(row_from_item(item) for item in items)
        print(f"Page {page}/{total_pages}: {len(items)} players")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
