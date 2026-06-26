from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.request import urlretrieve

import pdfplumber


PDF_URL = "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf"
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PDF_PATH = RAW_DIR / "SquadLists-English.pdf"
OUT_CSV = RAW_DIR / "fifa_world_cup_2026_squads.csv"

POSITION_VALUES = {"GK", "DF", "MF", "FW"}


def ensure_pdf() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not PDF_PATH.exists():
        print(f"Downloading FIFA squad PDF: {PDF_URL}")
        urlretrieve(PDF_URL, PDF_PATH)
    return PDF_PATH


def clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def parse_team(value: str) -> tuple[str, str]:
    match = re.search(r"(?P<team>.+?)\s+\((?P<code>[A-Z]{3})\)", value)
    if not match:
        return clean(value), ""
    return clean(match.group("team")), match.group("code")


def parse_team_from_page_text(text: str) -> tuple[str, str]:
    for line in text.splitlines():
        line = clean(line)
        if not re.match(r"^.+\s+\([A-Z]{3}\)$", line):
            continue
        team, code = parse_team(line)
        if code:
            return team, code

    compact_text = clean(text)
    match = re.search(r"SQUAD LIST.*?\d{4}\s*(?P<team>[^()]+?)\s+\((?P<code>[A-Z]{3})\)", compact_text)
    if match:
        return clean(match.group("team")), match.group("code")

    return "", ""


def row_from_table(country: str, country_code: str, row: list[object]) -> dict[str, str] | None:
    cells = [clean(cell) for cell in row]
    cells = [cell for cell in cells if cell]
    if len(cells) < 9:
        return None

    pos_index = next((idx for idx, cell in enumerate(cells) if cell in POSITION_VALUES), None)
    if pos_index is None:
        return None

    number = cells[pos_index - 1] if pos_index > 0 and cells[pos_index - 1].isdigit() else ""
    fields = cells[pos_index : pos_index + 8]
    if len(fields) < 8:
        return None

    position, player_name, first_names, last_names, name_on_shirt, dob, club, height_cm = fields[:8]

    return {
        "country": country,
        "country_code": country_code,
        "shirt_number": number,
        "position": position,
        "player_name": player_name,
        "first_names": first_names,
        "last_names": last_names,
        "name_on_shirt": name_on_shirt,
        "date_of_birth": dob,
        "club": club,
        "height_cm": height_cm,
    }


def fallback_rows_from_text(country: str, country_code: str, text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"^(?P<position>GK|DF|MF|FW)\s+"
        r"(?P<body>.+?)\s+"
        r"(?P<dob>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<club>.+?)\s+"
        r"(?P<height>\d{3})$"
    )
    for line in text.splitlines():
        line = clean(line)
        match = pattern.match(line)
        if not match:
            continue

        body = match.group("body")
        tokens = body.split()
        player_name = " ".join(tokens[:2]) if len(tokens) >= 2 else body
        rows.append(
            {
                "country": country,
                "country_code": country_code,
                "shirt_number": "",
                "position": match.group("position"),
                "player_name": player_name,
                "first_names": "",
                "last_names": "",
                "name_on_shirt": "",
                "date_of_birth": match.group("dob"),
                "club": match.group("club"),
                "height_cm": match.group("height"),
            }
        )
    return rows


def extract() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pdf_path = ensure_pdf()

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            country, country_code = parse_team_from_page_text(text)

            page_rows: list[dict[str, str]] = []
            for table in page.extract_tables():
                for raw_row in table:
                    parsed = row_from_table(country, country_code, raw_row)
                    if parsed:
                        page_rows.append(parsed)

            if not page_rows:
                page_rows = fallback_rows_from_text(country, country_code, text)

            print(f"Page {page_number:02d}: {country} ({country_code}) - {len(page_rows)} players")
            rows.extend(page_rows)

    return rows


def main() -> None:
    rows = extract()
    if not rows:
        raise RuntimeError("No squad rows extracted from FIFA PDF.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
