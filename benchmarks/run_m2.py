"""Run every M2 experiment and write CSVs, plots and environment.json to results/m2/.

  python -m benchmarks.run_m2 --runs 5 --seed 42
  python -m benchmarks.run_m2 --quick          # small smoke test (not for reporting)
"""
import argparse
import csv
import json
import time
from pathlib import Path

from . import bench_index as B
from .common import environment


def write_csv(path, rows):
    names = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Run AeroCore Milestone 2 benchmarks")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--output", default="results/m2")
    a = ap.parse_args()
    if a.runs < 2:
        ap.error("--runs must be at least 2")
    sizes, table_rows, wl_n, wl_ops = ((500, 2000), 2000, 2000, 400) if a.quick else ((2000, 10000, 20000), 20000, 10000, 2000)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("E1 insertion"); write_csv(out / "insert_results.csv", B.exp_insert(sizes, a.runs, a.seed))
    print("E2/E3 lookups and ranges")
    look, rng = B.exp_lookup_range(sizes, a.runs, a.seed)
    write_csv(out / "lookup_results.csv", look); write_csv(out / "range_results.csv", rng)
    print("E4 indexed lookup vs full scan"); write_csv(out / "scan_vs_index_results.csv", B.exp_scan_vs_index(table_rows, a.runs, a.seed))
    print("E5 workloads"); write_csv(out / "workload_results.csv", B.exp_workloads(wl_n, wl_ops, a.runs, a.seed))
    print("E6 index build"); write_csv(out / "build_results.csv", B.exp_build(table_rows, a.runs, a.seed))

    env = environment({
        "command": f"python -m benchmarks.run_m2 --runs {a.runs} --seed {a.seed}" + (" --quick" if a.quick else ""),
        "seed": a.seed, "warmup_runs": 1, "measured_runs": a.runs, "sizes": list(sizes), "table_rows": table_rows,
        "workload_preload_keys": wl_n, "workload_ops_per_run": wl_ops, "dataset": "synthetic, generated with fixed seed",
        "config": {"page_size": 4096, "bptree_buffer_frames": B.BPT_CAPACITY, "bptree_max_node_bytes": 3600,
                   "lsm_buffer_frames_per_run": B.LSM_CAPACITY, "lsm_memtable_entries": B.MEMTABLE,
                   "lsm_max_runs": B.MAX_RUNS, "table_buffer_frames": 16, "replacement_policy": "lru"},
        "total_seconds": round(time.time() - t0, 1)})
    (out / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    try:
        from .plot_m2 import create_plots
        create_plots(out)
    except ImportError:
        print("matplotlib not installed: skipped plots (pip install matplotlib)")
    print(f"\nResults saved in: {out}  ({env['total_seconds']} s)")


if __name__ == "__main__":
    main()