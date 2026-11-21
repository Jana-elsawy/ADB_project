import argparse
import csv
import json
from pathlib import Path

from benchmarks.bench_layout import benchmark as layout_benchmark
from benchmarks.bench_policies import benchmark as policy_benchmark
from benchmarks.common import environment
from benchmarks.plot import create_plots


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Run AeroCore Milestone 1 benchmarks")
    parser.add_argument("--runs", type=int, default=5, help="measured runs after one warm-up")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=10000, help="records in the benchmark table")
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")

    output = Path("results/m1")
    output.mkdir(parents=True, exist_ok=True)

    write_csv(output / "policy_results.csv", policy_benchmark(args.runs, args.seed, args.rows))
    write_csv(output / "layout_results.csv", layout_benchmark(args.runs, args.seed, args.rows))
    env = environment({"milestone": "M1", "rows": args.rows, "runs": args.runs, "warmup_runs": 1,
                       "seed": args.seed, "page_size_bytes": 4096,
                       "command": f"python -m benchmarks.run_all --runs {args.runs} --seed {args.seed} "
                                  f"--rows {args.rows}"})
    (output / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    create_plots()
    print(f"\nResults saved in {output} | runs={args.runs} seed={args.seed} rows={args.rows}")


if __name__ == "__main__":
    main()