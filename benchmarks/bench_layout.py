"""M1 layout benchmark: row store vs column store on the same passenger data.

Operations:
  insert_all        build the table from scratch
  avg_age           analytical query touching ONE column (column-store friendly)
  full_scan         read every complete record (row-store friendly)
  point_lookup_1000 fetch 1000 random complete records
Read operations start with a cold buffer pool (16 frames, smaller than the table).
"""
import random
import statistics
import time

from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.column_store import ColumnStore
from aerocore.storage.disk import DiskManager
from aerocore.storage.row_store import RowStore
from benchmarks.common import tmpdir
from data.generate_data import generate_passengers

COLUMNS = ["passenger_id", "name", "age", "country", "email"]
POOL_CAPACITY = 16
OPERATIONS = ("insert_all", "avg_age", "full_scan", "point_lookup_1000")


def build(path, layout, records):
    """Create the table; return (disk, store, keys, insert_seconds)."""
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=POOL_CAPACITY)
    store = RowStore(pool, disk) if layout == "row" else ColumnStore(pool, disk, COLUMNS)
    start = time.perf_counter()
    keys = []
    for i, rec in enumerate(records):
        rid = store.insert(rec)
        keys.append(rid if layout == "row" else i)
    pool.flush_all()
    return disk, store, keys, time.perf_counter() - start


def read_op(disk, store, layout, keys, operation, sample):
    store.pool = BufferPool(disk, capacity=POOL_CAPACITY)  # cold pool, fresh statistics
    start = time.perf_counter()
    if operation == "avg_age":
        ages = [r["age"] for r in store.scan()] if layout == "row" else store.get_column("age")
        result = sum(ages) / len(ages)
    elif operation == "full_scan":
        result = len(store.scan())
    else:
        result = sum(store.get(keys[i])["passenger_id"] for i in sample)
    return time.perf_counter() - start, result, dict(store.pool.stats)


def benchmark(runs=5, seed=42, rows=10000):
    if runs < 2:
        raise ValueError("runs must be at least 2 to calculate standard deviation")
    records = generate_passengers(rows, seed)
    sample = random.Random(seed).sample(range(rows), 1000)
    results, answers = [], {}
    with tmpdir() as tmp:
        for layout in ("row", "column"):
            insert_times = []
            for k in range(runs + 1):  # first build is the warm-up
                disk, store, keys, secs = build(tmp / f"{layout}{k}.db", layout, records)
                if k > 0:
                    insert_times.append(secs)
                if k < runs:
                    disk.close()
            pages = disk.page_count
            results.append({"layout": layout, "operation": "insert_all",
                            "mean_seconds": statistics.mean(insert_times),
                            "std_seconds": statistics.stdev(insert_times),
                            "hits": "", "misses": "", "hit_ratio": "", "disk_reads": "", "table_pages": pages})
            for operation in OPERATIONS[1:]:
                read_op(disk, store, layout, keys, operation, sample)  # warm-up
                times, stats = [], None
                for _ in range(runs):
                    secs, result, stats = read_op(disk, store, layout, keys, operation, sample)
                    times.append(secs)
                answers[(layout, operation)] = result
                total = stats["hits"] + stats["misses"]
                results.append({"layout": layout, "operation": operation,
                                "mean_seconds": statistics.mean(times), "std_seconds": statistics.stdev(times),
                                "hits": stats["hits"], "misses": stats["misses"],
                                "hit_ratio": round(stats["hits"] / total, 4) if total else 0,
                                "disk_reads": stats["disk_reads"], "table_pages": pages})
                r = results[-1]
                print(f"[layout] {layout:6s} {operation:18s} {r['mean_seconds'] * 1000:9.2f} ms "
                      f"reads={r['disk_reads']}")
            disk.close()
    # correctness: both layouts must return identical answers
    for operation in OPERATIONS[1:]:
        assert answers[("row", operation)] == answers[("column", operation)], f"layouts disagree on {operation}"
    return results


if __name__ == "__main__":
    benchmark()