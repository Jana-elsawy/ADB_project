"""Charts for the M2 results (reads the CSV files written by run_m2.py)."""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {"bptree": "#1f77b4", "lsm": "#d62728", "full_scan": "#7f7f7f",
          "bptree_index": "#1f77b4", "lsm_index": "#d62728"}


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _series(rows, kind, key):
    pts = sorted((int(r["n"]), float(r[key])) for r in rows if r["structure"] == kind)
    return [p[0] for p in pts], [p[1] for p in pts]


def create_plots(out):
    out = Path(out)
    ins = _read(out / "insert_results.csv")
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    for kind in ("bptree", "lsm"):
        rows = [r for r in ins if r["structure"] == kind]
        x = [int(r["n"]) for r in rows]
        ax[0].errorbar(x, [float(r["mean_s"]) for r in rows], yerr=[float(r["std_s"]) for r in rows],
                       marker="o", capsize=3, label=kind, color=COLORS[kind])
        ax[1].plot(x, [float(r["p95_ms"]) for r in rows], marker="o", label=f"{kind} p95", color=COLORS[kind])
        ax[1].plot(x, [float(r["median_ms"]) for r in rows], marker="s", ls="--", label=f"{kind} median", color=COLORS[kind])
    ax[0].set(title="Insert time (mean ± std, 5 runs)", xlabel="rows inserted", ylabel="seconds")
    ax[1].set(title="Per-insert latency", xlabel="rows inserted", ylabel="ms", yscale="log")
    for a in ax:
        a.legend(); a.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(out / "insert_comparison.png", dpi=150); plt.close(fig)

    for fname, title in (("lookup_results.csv", "Point lookup"), ("range_results.csv", "Range scan (1% of keys)")):
        rows = _read(out / fname)
        fig, ax = plt.subplots(1, 2, figsize=(10, 4))
        for kind in ("bptree", "lsm"):
            x, med = _series(rows, kind, "median_ms")
            _, p95 = _series(rows, kind, "p95_ms")
            _, rd = _series(rows, kind, "page_reads_per_op")
            ax[0].plot(x, med, marker="s", ls="--", label=f"{kind} median", color=COLORS[kind])
            ax[0].plot(x, p95, marker="o", label=f"{kind} p95", color=COLORS[kind])
            ax[1].plot(x, rd, marker="o", label=kind, color=COLORS[kind])
        ax[0].set(title=f"{title}: latency", xlabel="indexed keys", ylabel="ms", yscale="log")
        ax[1].set(title=f"{title}: page reads per query", xlabel="indexed keys", ylabel="disk page reads")
        for a in ax:
            a.legend(); a.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / fname.replace("_results.csv", "_comparison.png"), dpi=150); plt.close(fig)

    rows = _read(out / "scan_vs_index_results.csv")
    exps = sorted({r["experiment"] for r in rows})
    methods = ["full_scan", "bptree_index", "lsm_index"]
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    for j, (key, label) in enumerate((("median_ms", "median latency (ms)"), ("page_reads_per_op", "disk page reads per query"))):
        for i, m in enumerate(methods):
            vals = [float(next(r[key] for r in rows if r["experiment"] == e and r["structure"] == m)) for e in exps]
            ax[j].bar([x + i * 0.27 for x in range(len(exps))], vals, 0.27, label=m, color=COLORS[m])
        ax[j].set_xticks([x + 0.27 for x in range(len(exps))])
        ax[j].set_xticklabels(exps)
        ax[j].set(ylabel=label, yscale="log", title=f"Indexed lookup vs full scan: {label}")
        ax[j].legend(); ax[j].grid(alpha=.3, axis="y")
    fig.tight_layout(); fig.savefig(out / "scan_vs_index_comparison.png", dpi=150); plt.close(fig)

    rows = _read(out / "workload_results.csv")
    names = list(dict.fromkeys(r["experiment"] for r in rows))
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, kind in enumerate(("bptree", "lsm")):
        vals = [float(next(r["ops_per_sec"] for r in rows if r["experiment"] == nm and r["structure"] == kind)) for nm in names]
        ax.bar([x + i * 0.38 for x in range(len(names))], vals, 0.38, label=kind, color=COLORS[kind])
    labels = [f"{nm}\n{next(r['mix_write_point_range'] for r in rows if r['experiment'] == nm)} (w/p/r %)\nrule: "
              f"{next(r['rule_choice'] for r in rows if r['experiment'] == nm)}" for nm in names]
    ax.set_xticks([x + 0.19 for x in range(len(names))]); ax.set_xticklabels(labels, fontsize=8)
    ax.set(ylabel="operations / second", title="Throughput by workload (higher is better)")
    ax.legend(); ax.grid(alpha=.3, axis="y")
    fig.tight_layout(); fig.savefig(out / "workload_comparison.png", dpi=150); plt.close(fig)