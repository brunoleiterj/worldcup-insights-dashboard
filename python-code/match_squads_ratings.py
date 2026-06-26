from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd
from thefuzz import fuzz, process


ROOT = Path(__file__).resolve().parents[1]
SQUADS_CSV = ROOT / "data" / "raw" / "fifa_world_cup_2026_squads.csv"
RATINGS_CSV = ROOT / "data" / "raw" / "ea_fc26_ratings.csv"
FCRATINGS_CSV = ROOT / "data" / "raw" / "fcratings_fc26_ratings.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_CSV = PROCESSED_DIR / "world_cup_2026_players_with_ratings.csv"
UNMATCHED_CSV = PROCESSED_DIR / "unmatched_squad_players.csv"
MATCH_THRESHOLD = 84

COUNTRY_ALIASES = {
    "Bosnia And Herzegovina": "Bosnia and Herzegovina",
    "Cabo Verde": "Cape Verde Islands",
    "Czechia": "Czech Republic",
    "IR Iran": "Iran",
    "Netherlands": "Holland",
    "Türkiye": "Turkey",
    "USA": "United States",
}


def normalize(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|junior|sr|ii|iii)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def country_for_rating(country: object) -> str:
    country_text = "" if country is None else str(country)
    return COUNTRY_ALIASES.get(country_text, country_text)


def squad_name_variants(row: pd.Series) -> list[str]:
    first_names = str(row.get("first_names", "") or "")
    last_names = str(row.get("last_names", "") or "")
    player_name = str(row.get("player_name", "") or "")
    name_on_shirt = str(row.get("name_on_shirt", "") or "")

    first_tokens = first_names.split()
    first_name = first_tokens[0] if first_tokens else ""

    variants = []

    # Long legal names can create false positives on common tokens such as Silva/Santos.
    if len(first_tokens) <= 2 and len(last_names.split()) <= 2:
        variants.append(f"{first_names} {last_names}")

    variants.extend(
        [
            f"{first_name} {last_names}",
            player_name,
            name_on_shirt,
        ]
    )

    player_tokens = player_name.split()
    if len(player_tokens) >= 2:
        variants.append(" ".join(player_tokens[1:] + player_tokens[:1]))

    normalized = []
    for variant in variants:
        cleaned = normalize(variant)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def best_rating_match(row: pd.Series, ratings: pd.DataFrame) -> tuple[int | None, int]:
    squad_names = squad_name_variants(row)
    country = normalize(country_for_rating(row.get("country", "")))

    candidates = ratings
    if "nationality_norm" in ratings.columns and country:
        same_country = ratings[ratings["nationality_norm"] == country]
        if not same_country.empty:
            candidates = same_country

    candidate_pairs = []
    for candidate_index, candidate in candidates.iterrows():
        for column in ["player_name_norm", "first_last_norm", "common_name_norm"]:
            name = candidate.get(column, "")
            if name:
                candidate_pairs.append((candidate_index, name))

    choices = [name for _, name in candidate_pairs]
    if not choices:
        return None, 0

    best_name = ""
    best_score = 0
    for squad_name in squad_names:
        match = process.extractOne(squad_name, choices, scorer=fuzz.token_sort_ratio)
        if match and match[1] > best_score:
            best_name, best_score = match[0], int(match[1])

    if not best_name:
        return None, 0

    candidate_index = next(index for index, name in candidate_pairs if name == best_name)
    return int(candidate_index), best_score


def main() -> None:
    squads = pd.read_csv(SQUADS_CSV)
    ratings_csv = RATINGS_CSV if RATINGS_CSV.exists() else FCRATINGS_CSV
    ratings = pd.read_csv(ratings_csv)
    print(f"Using ratings file: {ratings_csv}")

    ratings["player_name_norm"] = ratings["player_name"].map(normalize)
    ratings["first_last_norm"] = (
        ratings.get("first_name", "").fillna("").astype(str) + " " + ratings.get("last_name", "").fillna("").astype(str)
    ).map(normalize)
    ratings["common_name_norm"] = ratings.get("common_name", "").fillna("").map(normalize)
    ratings["match_name_norm"] = ratings["common_name_norm"]
    ratings.loc[ratings["match_name_norm"] == "", "match_name_norm"] = ratings.loc[
        ratings["match_name_norm"] == "", "player_name_norm"
    ]
    ratings.loc[ratings["match_name_norm"] == "", "match_name_norm"] = ratings.loc[
        ratings["match_name_norm"] == "", "first_last_norm"
    ]
    if "nationality" in ratings.columns:
        ratings["nationality_norm"] = ratings["nationality"].map(normalize)
    else:
        ratings["nationality_norm"] = ""

    matched_rows = []
    unmatched_rows = []

    for _, squad_row in squads.iterrows():
        rating_index, score = best_rating_match(squad_row, ratings)
        if rating_index is None or score < MATCH_THRESHOLD:
            row = squad_row.to_dict()
            row["match_score"] = score
            unmatched_rows.append(row)
            continue

        rating_row = ratings.loc[rating_index].to_dict()
        combined = {
            **{f"squad_{key}": value for key, value in squad_row.to_dict().items()},
            **{f"rating_{key}": value for key, value in rating_row.items()},
            "match_score": score,
        }
        matched_rows.append(combined)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(matched_rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    pd.DataFrame(unmatched_rows).to_csv(UNMATCHED_CSV, index=False, encoding="utf-8-sig")

    print(f"Matched rows: {len(matched_rows)} -> {OUT_CSV}")
    print(f"Unmatched rows: {len(unmatched_rows)} -> {UNMATCHED_CSV}")


if __name__ == "__main__":
    main()
