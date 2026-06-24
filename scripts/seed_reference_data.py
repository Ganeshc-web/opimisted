import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.models.education_db import EducationProgram
from app.models.tour_db import TourDestination
from run import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDUCATION_CSV = PROJECT_ROOT / "data" / "education_programs.csv"
TOUR_JSON = PROJECT_ROOT / "data" / "tour_destinations.json"


def parse_bool(value):
    return str(value).strip().lower() in {"yes", "true", "1"}


def seed_education_programs():
    inserted = 0
    data = pd.read_csv(EDUCATION_CSV)

    for _, row in data.iterrows():
        exists = EducationProgram.query.filter_by(
            level=row["Level"],
            course_category=row["Course Category"],
            country=row["Country"],
        ).first()
        if exists:
            continue

        program = EducationProgram(
            level=row["Level"],
            course_category=row["Course Category"],
            country=row["Country"],
            country_famous_for=row["Country Famous For"],
            approx_cost_inr=float(row["Approx Current Cost (INR)"]),
            duration=row["Suggested Duration"],
            category=row["Category"],
            living_cost_included=parse_bool(row["Living Cost Included"]),
            lifestyle_level=row["Lifestyle Level"],
            inflation_rate=float(row["Future Inflation Rate (%)"]) / 100,
        )
        db.session.add(program)
        inserted += 1

    return inserted


def seed_tour_destinations():
    inserted = 0
    with TOUR_JSON.open(encoding="utf-8") as file:
        data = json.load(file)

    for entry in data:
        exists = TourDestination.query.filter_by(country=entry["country"]).first()
        if exists:
            continue

        destination = TourDestination(
            country=entry["country"],
            budget_inr=float(entry["budget_inr"]),
            duration=entry["duration"],
            category=entry["category"],
        )
        db.session.add(destination)
        inserted += 1

    return inserted


def main():
    with app.app_context():
        education_count = seed_education_programs()
        tour_count = seed_tour_destinations()
        db.session.commit()

    print(f"Inserted {education_count} education programs")
    print(f"Inserted {tour_count} tour destinations")


if __name__ == "__main__":
    main()
