import argparse
import csv
from pathlib import Path

from benchmarks.bench_policies import benchmark as policy_benchmark
from benchmarks.bench_layout import benchmark as layout_benchmark
from benchmarks.plot import create_plots


def main():
    parser = argparse.ArgumentParser(
        description="Run AeroCore Milestone 1 benchmarks"
    )

    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    if args.runs < 2:
        parser.error("--runs must be at least 2")

    output = Path("results/m1")
    output.mkdir(parents=True, exist_ok=True)

    # Run replacement policy benchmarks
    policy_results = policy_benchmark(runs=args.runs)

    with open(
        output / "policy_results.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "policy",
            "mean_seconds",
            "std_seconds",
            "hits",
            "misses",
            "evictions",
            "disk_reads",
            "disk_writes"
        ])

        for name, mean, std, stats in policy_results:
            writer.writerow([
                name,
                mean,
                std,
                stats["hits"],
                stats["misses"],
                stats["evictions"],
                stats["disk_reads"],
                stats["disk_writes"]
            ])

    # Run row and column storage benchmarks
    layout_results = layout_benchmark(
        runs=args.runs,
        seed=args.seed
    )

    with open(
        output / "layout_results.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "layout",
            "mean_seconds",
            "std_seconds",
            "average_age",
            "hits",
            "misses",
            "evictions",
            "disk_reads",
            "disk_writes"
        ])

        for name, mean, std, average, stats in layout_results:
            writer.writerow([
                name,
                mean,
                std,
                average,
                stats["hits"],
                stats["misses"],
                stats["evictions"],
                stats["disk_reads"],
                stats["disk_writes"]
            ])

    # Generate plots from the CSV files
    create_plots()

    print(f"\nBenchmark results saved in: {output}")
    print(f"Measured runs per benchmark: {args.runs}")
    print(f"Random seed: {args.seed}")


if __name__ == "__main__":
    main()