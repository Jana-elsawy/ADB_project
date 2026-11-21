"""Synthetic airline data for all six AeroCore tables (fixed seed, no real data).

  python data/generate_airline.py --table reservations --rows 100000 --seed 42
"""
import argparse
import json
import random
from pathlib import Path

CITIES = ["Cairo", "Dubai", "Riyadh", "Amman", "Jeddah", "Doha", "Muscat", "Kuwait"]
COUNTRIES = ["Egypt", "UAE", "Saudi Arabia", "Jordan", "Qatar", "Oman", "Kuwait"]
SEAT_LETTERS = "ABCDEF"


def generate(table, rows, seed=42):
    rng = random.Random(seed)             # local RNG: does not touch the global random state
    out = []
    for i in range(1, rows + 1):
        if table == "airports":
            out.append({"airport_id": i, "name": f"Airport_{i}", "city": rng.choice(CITIES),
                        "country": rng.choice(COUNTRIES)})
        elif table == "flights":
            out.append({"flight_id": i, "source_airport": rng.randint(1, 50),
                        "destination_airport": rng.randint(1, 50),
                        "departure_time": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
                                          f"T{rng.randint(0, 23):02d}:{rng.choice([0, 15, 30, 45]):02d}"})
        elif table == "seats":
            out.append({"seat_id": i, "flight_id": rng.randint(1, max(1, rows // 150)),
                        "seat_number": f"{rng.randint(1, 40)}{rng.choice(SEAT_LETTERS)}",
                        "status": rng.choice(["free", "reserved"])})
        elif table == "passengers":
            out.append({"passenger_id": i, "name": f"Passenger_{i}", "email": f"passenger{i}@example.com",
                        "passport_number": f"P{rng.randint(10**7, 10**8 - 1)}"})
        elif table == "reservations":
            out.append({"reservation_id": i, "passenger_id": rng.randint(1, max(1, rows // 4)),
                        "flight_id": rng.randint(1, max(1, rows // 100)), "seat_id": i,
                        "status": rng.choice(["confirmed", "confirmed", "confirmed", "cancelled"])})
        elif table == "payments":
            out.append({"payment_id": i, "reservation_id": i, "amount": round(rng.uniform(50, 900), 2),
                        "payment_status": rng.choice(["paid", "paid", "pending", "failed"])})
        else:
            raise ValueError(f"unknown table {table}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--table", default="reservations")
    p.add_argument("--rows", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output")
    a = p.parse_args()
    path = Path(a.output or f"data/{a.table}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(generate(a.table, a.rows, a.seed)), encoding="utf-8")
    print(f"Generated {a.rows} {a.table} rows in {path}")


if __name__ == "__main__":
    main()