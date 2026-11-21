"""M1 buffer-pool benchmark: LRU vs FIFO on three access patterns and three pool sizes.

Workloads (all run on the same row-store table, same seed):
  sequential  3 full table scans (scan-resistance test: the table is larger than the pool)
  uniform     random point lookups, every record equally likely
  skewed      random point lookups, Zipf-like skew (a few hot records get most accesses)
Each measured run starts with an EMPTY (cold) buffer pool over the same database file.
"""
import random
import statistics
import time

from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.disk import DiskManager
from aerocore.storage.row_store import RowStore
from benchmarks.common import tmpdir
from data.generate_data import generate_passengers

POLICIES = ("lru", "fifo")
WORKLOADS = ("sequential", "uniform", "skewed")
POOL_FRACTIONS = (0.10, 0.25, 0.50)


def build_table(path, rows, seed):
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=64)
    store = RowStore(pool, disk)
    rids = [store.insert(r) for r in generate_passengers(rows, seed)]
    pool.close()
    return disk, store, rids


def make_sequence(workload, n, ops, seed):
    rng = random.Random(seed)
    if workload == "uniform":
        return [rng.randrange(n) for _ in range(ops)]
    hot_order = list(range(n))
    rng.shuffle(hot_order)
    weights = [1.0 / (i + 1) ** 1.1 for i in range(n)]
    return [hot_order[i] for i in rng.choices(range(n), weights=weights, k=ops)]


def run_case(disk, store, rids, policy, capacity, workload, sequence):
    store.pool = BufferPool(disk, capacity=capacity, policy=policy)  # cold pool, fresh statistics
    start = time.perf_counter()
    if workload == "sequential":
        for _ in range(3):
            store.scan()
    else:
        for i in sequence:
            store.get(rids[i])
    elapsed = time.perf_counter() - start
    return elapsed, dict(store.pool.stats)


def benchmark(runs=5, seed=42, rows=10000):
    if runs < 2:
        raise ValueError("runs must be at least 2 to calculate standard deviation")
    results = []
    with tmpdir() as tmp:
        disk, store, rids = build_table(tmp / "policies.db", rows, seed)
        pages = disk.page_count
        ops = max(rows, 5000)
        for workload in WORKLOADS:
            sequence = make_sequence(workload, len(rids), ops, seed) if workload != "sequential" else None
            for fraction in POOL_FRACTIONS:
                capacity = max(2, int(pages * fraction))
                for policy in POLICIES:
                    run_case(disk, store, rids, policy, capacity, workload, sequence)  # warm-up
                    times, stats = [], None
                    for _ in range(runs):
                        elapsed, stats = run_case(disk, store, rids, policy, capacity, workload, sequence)
                        times.append(elapsed)
                    total = stats["hits"] + stats["misses"]
                    results.append({
                        "workload": workload, "policy": policy, "pool_fraction": fraction,
                        "pool_pages": capacity, "table_pages": pages,
                        "accesses": total, "hits": stats["hits"], "misses": stats["misses"],
                        "hit_ratio": round(stats["hits"] / total, 4), "evictions": stats["evictions"],
                        "disk_reads": stats["disk_reads"],
                        "mean_seconds": statistics.mean(times), "std_seconds": statistics.stdev(times),
                    })
                    r = results[-1]
                    print(f"[policy] {workload:10s} {policy:4s} pool={capacity:4d}/{pages} pages "
                          f"hit_ratio={r['hit_ratio']:.3f} reads={r['disk_reads']:6d} "
                          f"{r['mean_seconds'] * 1000:8.1f} ms")
        disk.close()
    return results


if __name__ == "__main__":
    benchmark()