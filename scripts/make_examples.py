"""Generate the public demo's synthetic example datasets.

Writes 3 small CSVs (each well under 50 KB) to
`src/sandbox_analyst/api/examples/`, plus `examples.json` describing them
(title, description, 3 suggested questions each). Every value is produced
by `random.Random(SEED)` -- re-running this script always writes byte-
identical output. These datasets are entirely synthetic: no real-world
source data, no licence to track (see DECISIONS.md).

Run with: uv run python scripts/make_examples.py
"""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 2026
OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "sandbox_analyst" / "api" / "examples"

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Widget A", "Widget B", "Gadget X", "Gizmo Z", "Thingamajig"]

FIRST_NAMES = [
    "Aarav",
    "Priya",
    "Rohan",
    "Ananya",
    "Vikram",
    "Diya",
    "Karan",
    "Isha",
    "Arjun",
    "Meera",
    "Sahil",
    "Tara",
    "Nikhil",
    "Riya",
    "Aditya",
    "Sneha",
    "Varun",
    "Pooja",
    "Kabir",
    "Neha",
]
CLASSES = ["9A", "9B", "10A", "10B"]
SUBJECTS = ["Math", "Science", "English"]

CITIES = ["Delhi", "Mumbai", "Bengaluru"]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def make_sales(rng: random.Random) -> list[list[str]]:
    """date, region, product, units, unit_price -- with some missing values."""
    rows = []
    start = date(2026, 1, 1)
    for day_offset in range(45):
        day = start + timedelta(days=day_offset)
        for region in REGIONS:
            product = rng.choice(PRODUCTS)
            units = "" if rng.random() < 0.05 else str(rng.randint(1, 50))
            unit_price = "" if rng.random() < 0.05 else f"{rng.uniform(5.0, 500.0):.2f}"
            rows.append([day.isoformat(), region, product, units, unit_price])
    return rows


def make_students(rng: random.Random) -> list[list[str]]:
    """name, class, subject, score, attendance."""
    rows = []
    names = list(FIRST_NAMES)
    rng.shuffle(names)
    assignments = [(name, CLASSES[i % len(CLASSES)]) for i, name in enumerate(names)]
    for name, klass in assignments:
        for subject in SUBJECTS:
            score = rng.randint(40, 100)
            attendance = round(rng.uniform(60.0, 100.0), 1)
            rows.append([name, klass, subject, str(score), f"{attendance:.1f}"])
    return rows


def make_weather(rng: random.Random) -> list[list[str]]:
    """date, city, temp_c, rainfall_mm, humidity."""
    rows = []
    start = date(2026, 1, 1)
    for day_offset in range(30):
        day = start + timedelta(days=day_offset)
        for city in CITIES:
            temp_c = round(rng.uniform(10.0, 38.0), 1)
            rainfall_mm = round(rng.uniform(0.0, 40.0), 1) if rng.random() < 0.3 else 0.0
            humidity = rng.randint(30, 95)
            rows.append(
                [day.isoformat(), city, f"{temp_c:.1f}", f"{rainfall_mm:.1f}", str(humidity)]
            )
    return rows


EXAMPLES = {
    "sales": {
        "title": "Retail Sales",
        "description": (
            "Daily unit sales and prices across 4 regions and 5 products, "
            "with some missing values -- synthetic data."
        ),
        "file_name": "sales.csv",
        "questions": [
            "What is the total revenue (units * unit_price) by region?",
            "Which product has the highest average unit price?",
            "Plot total units sold per region as a bar chart.",
        ],
    },
    "students": {
        "title": "Student Scores",
        "description": (
            "Scores and attendance for 20 students across 3 subjects and "
            "4 classes -- synthetic data."
        ),
        "file_name": "students.csv",
        "questions": [
            "What is the average score per subject?",
            "Which class has the highest average attendance?",
            "Plot a histogram of all student scores.",
        ],
    },
    "weather": {
        "title": "City Weather",
        "description": (
            "30 days of temperature, rainfall, and humidity for 3 cities -- synthetic data."
        ),
        "file_name": "weather.csv",
        "questions": [
            "What is the average temperature per city?",
            "Which city had the most total rainfall over the period?",
            "Plot daily temperature over time for each city as a line chart.",
        ],
    },
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    _write_csv(
        OUT_DIR / "sales.csv", ["date", "region", "product", "units", "unit_price"], make_sales(rng)
    )
    rng = random.Random(SEED)
    _write_csv(
        OUT_DIR / "students.csv",
        ["name", "class", "subject", "score", "attendance"],
        make_students(rng),
    )
    rng = random.Random(SEED)
    _write_csv(
        OUT_DIR / "weather.csv",
        ["date", "city", "temp_c", "rainfall_mm", "humidity"],
        make_weather(rng),
    )

    examples_json = OUT_DIR / "examples.json"
    examples_json.write_text(json.dumps(EXAMPLES, indent=2) + "\n", encoding="utf-8")

    for name in ["sales.csv", "students.csv", "weather.csv", "examples.json"]:
        size = (OUT_DIR / name).stat().st_size
        print(f"wrote {OUT_DIR / name} ({size} bytes)")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
