"""End-to-end M2 demonstration:  python -m aerocore.demo_m2

SQL-like queries -> access plan -> B+ Tree / LSM Tree indexes -> M1 pages, plus an encrypted
ticket in the object store, and a restart to show that everything is persistent.
"""
import shutil
import statistics
import time
from pathlib import Path

from aerocore.objects import StreamCipher
from aerocore.sql import Database
from aerocore.sql.airline import create_airline_tables, load_rows
from data.generate_airline import generate

DB_DIR = Path("results/m2/demo_db")
SEED = 42


def step(title):
    print(f"\n=== {title} " + "=" * max(3, 70 - len(title)))


def timed(db, sql, params=(), runs=5, use_index=True):
    times = []
    for _ in range(runs):
        res = db.execute(sql, params, use_index=use_index)
        times.append(res.elapsed_ms)
    return res, statistics.median(times)


def main():
    if DB_DIR.exists():
        shutil.rmtree(DB_DIR)
    db = Database(DB_DIR, cipher=StreamCipher("demo-key"), buffer_capacity=16)

    step("1. Create the six airline tables (primary keys are indexed with a B+ Tree)")
    print("created:", ", ".join(create_airline_tables(db)))

    step("2. Load synthetic data (seed 42) with parameterised INSERTs")
    sizes = {"airports": 50, "flights": 500, "passengers": 2000, "reservations": 5000, "payments": 5000}
    for table, n in sizes.items():
        print(f"  {table:<13}{load_rows(db, table, generate(table, n, SEED)):>6} rows")

    step("3. Workload-based index selection (CREATE INDEX ... USING auto)")
    for sql in ("CREATE INDEX ON reservations (flight_id) USING auto WORKLOAD (10, 85, 5)",
                "CREATE INDEX ON reservations (passenger_id) USING auto WORKLOAD (60, 35, 5)",
                "CREATE INDEX ON flights (departure_time) USING bptree"):
        print(" ", sql, "\n   ->", db.execute(sql).message)

    step("4. EXPLAIN: which access path does each query use?")
    for sql in ("EXPLAIN SELECT * FROM reservations WHERE reservation_id = 4321",
                "EXPLAIN SELECT * FROM reservations WHERE flight_id = 12 AND status = 'confirmed'",
                "EXPLAIN SELECT flight_id, departure_time FROM flights "
                "WHERE departure_time BETWEEN '2026-12-01T00:00' AND '2026-12-31T23:59' "
                "ORDER BY departure_time LIMIT 5",
                "EXPLAIN SELECT * FROM reservations WHERE status = 'cancelled'"):
        print("\n" + sql.replace("EXPLAIN ", "", 1))
        print(db.execute(sql).plan)

    step("5. Indexed query vs full scan (median of 5 runs, same results required)")
    print(f"{'query':<52}{'index ms':>10}{'scan ms':>10}{'speed-up':>10}  same rows")
    cases = [("reservation_id = 4321 (B+ Tree)", "SELECT * FROM reservations WHERE reservation_id = ?", (4321,)),
             ("flight_id = 12 (B+ Tree)", "SELECT * FROM reservations WHERE flight_id = ?", (12,)),
             ("passenger_id = 77 (LSM)", "SELECT * FROM reservations WHERE passenger_id = ?", (77,)),
             ("flight_id BETWEEN 10 AND 12 (B+ Tree)",
              "SELECT * FROM reservations WHERE flight_id BETWEEN ? AND ?", (10, 12))]
    for label, sql, params in cases:
        fast, t_fast = timed(db, sql, params)
        slow, t_slow = timed(db, sql, params, runs=3, use_index=False)
        same = sorted(fast.rows) == sorted(slow.rows)
        print(f"{label:<52}{t_fast:>10.3f}{t_slow:>10.1f}{t_slow / t_fast:>9.0f}x  {same} ({len(fast.rows)} rows)")

    step("6. UPDATE / DELETE keep every index in sync")
    print(db.execute("UPDATE reservations SET flight_id = 999 WHERE reservation_id <= 5").message)
    print("flight 999 via index:", len(db.execute("SELECT * FROM reservations WHERE flight_id = 999").rows),
          "rows | via scan:", len(db.execute("SELECT * FROM reservations WHERE flight_id = 999",
                                              use_index=False).rows), "rows")
    print(db.execute("DELETE FROM reservations WHERE flight_id = 999").message)
    print("flight 999 after delete:", len(db.execute("SELECT * FROM reservations WHERE flight_id = 999").rows), "rows")

    step("7. Object storage with the encryption hook (e-ticket for reservation 6)")
    row = db.execute("SELECT passenger_id, flight_id, seat_id FROM reservations WHERE reservation_id = 6").as_dicts()[0]
    ticket = f"E-TICKET reservation=6 passenger={row['passenger_id']} flight={row['flight_id']} seat={row['seat_id']}".encode()
    manifest = db.objects.put("ticket:6", ticket, "text/plain")
    print("stored:", ticket.decode(), f"| cipher={manifest['cipher']}, {manifest['size']} -> {manifest['stored_size']} bytes")
    print("objects:", db.objects.list("ticket:"))

    step("8. Close, reopen, query again (persistence)")
    before = sorted(db.execute("SELECT * FROM reservations WHERE flight_id = 12").rows)
    db.close()
    raw = (DB_DIR / "objects.objects").read_bytes()
    print("plaintext visible in the object file on disk:", b"E-TICKET" in raw)
    db = Database(DB_DIR, cipher=StreamCipher("demo-key"))
    after = db.execute("SELECT * FROM reservations WHERE flight_id = 12")
    print("same rows after restart:", sorted(after.rows) == before, "| index used:", after.used_index)
    print("ticket after restart:", db.objects.get("ticket:6").decode())
    print(db.execute("SHOW INDEXES ON reservations").format())
    db.close()


if __name__ == "__main__":
    main()