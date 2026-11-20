import argparse
import json
import random
from pathlib import Path


def generate_passengers(rows, seed):
    random.seed(seed)
    countries = ["Egypt", "Jordan", "UAE", "Saudi Arabia"]
    return [
        {
            "passenger_id": i + 1,
            "name": f"Passenger_{i + 1}",
            "age": random.randint(18, 75),
            "country": random.choice(countries),
            "email": f"passenger{i + 1}@example.com",
        }
        for i in range(rows)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="data/passengers.json")
    args = parser.parse_args()
    records = generate_passengers(args.rows, args.seed)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Generated {len(records)} passenger records in {path}")


if __name__ == "__main__":
    main()
