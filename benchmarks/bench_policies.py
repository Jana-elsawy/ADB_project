
import statistics
import time
from pathlib import Path

from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool


def run_once(policy, page_count=20, capacity=4):
    path = Path(f"results/m1/policy_{policy}.db")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        path.unlink()

    disk = DiskManager(path)

    for _ in range(page_count):
        disk.allocate_page()

    pool = BufferPool(disk, capacity=capacity, policy=policy)

    access_sequence = [
        0, 1, 2, 3, 0, 1, 4, 0,
        2, 5, 1, 4, 6, 0, 3, 6
    ]

    start = time.perf_counter()

    for page_id in access_sequence:
        pool.fetch_page(page_id)
        pool.unpin_page(page_id)

    elapsed = time.perf_counter() - start

    stats = dict(pool.stats)

    pool.close()
    disk.close()

    return elapsed, stats


def benchmark(runs=5):

    if runs < 2:
        raise ValueError("runs must be at least 2 to calculate standard deviation")

    results = []

    for policy in ("lru", "fifo"):

        # Warm-up run
        run_once(policy)

        times = []
        last_stats = {}

        # Measured runs
        for _ in range(runs):
            elapsed, stats = run_once(policy)

            times.append(elapsed)
            last_stats = stats

        mean_time = statistics.mean(times)
        std_time = statistics.stdev(times)

        results.append((
            policy,
            mean_time,
            std_time,
            last_stats
        ))

    return results


if __name__ == "__main__":
    for result in benchmark():
        print(result)
