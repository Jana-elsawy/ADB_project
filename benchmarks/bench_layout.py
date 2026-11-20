import random
import statistics
import time
from pathlib import Path

from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.row_store import RowStore
from aerocore.storage.column_store import ColumnStore


def benchmark_layout(layout, records):
    path = Path(f"results/m1/layout_{layout}.db")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        path.unlink()

    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=16, policy="lru")

    if layout == "row":
        store = RowStore(pool, disk)

        for record in records:
            store.insert(record)

        # Measure reading the age field from all records
        start = time.perf_counter()

        result = [record["age"] for record in store.scan()]

        elapsed = time.perf_counter() - start

    elif layout == "column":
        store = ColumnStore(
            pool,
            disk,
            ["passenger_id", "name", "age", "country"]
        )

        for record in records:
            store.insert(record)

        # Measure reading only the age column
        start = time.perf_counter()

        result = store.get_column("age")

        elapsed = time.perf_counter() - start

    else:
        raise ValueError("Layout must be 'row' or 'column'")

    average = sum(result) / len(result)

    stats = dict(pool.stats)

    pool.close()
    disk.close()

    return elapsed, average, stats


def benchmark(runs=5, seed=42):
    if runs < 2:
        raise ValueError("runs must be at least 2 to calculate standard deviation")

    # Generate the same dataset for both storage layouts
    rng = random.Random(seed)

    records = []

    for i in range(500):
        record = {
            "passenger_id": i,
            "name": f"Passenger_{i}",
            "age": rng.randint(18, 75),
            "country": rng.choice(["Egypt", "Jordan", "UAE", "Saudi Arabia"])
        }

        records.append(record)

    results = []

    for layout in ("row", "column"):

        # One warm-up run (not included in measurements)
        benchmark_layout(layout, records)

        times = []
        last_average = 0
        last_stats = {}

        # Measured runs
        for _ in range(runs):
            elapsed, average, stats = benchmark_layout(layout, records)

            times.append(elapsed)
            last_average = average
            last_stats = stats

        mean_time = statistics.mean(times)
        std_time = statistics.stdev(times)

        results.append((
            layout,
            mean_time,
            std_time,
            last_average,
            last_stats
        ))

    return results


if __name__ == "__main__":
    for result in benchmark():
        print(result)