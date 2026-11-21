import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path("results/m1")


def read_csv(name):
    with open(OUT / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def create_plots():
    OUT.mkdir(parents=True, exist_ok=True)
    pol = read_csv("policy_results.csv")
    workloads = list(dict.fromkeys(r["workload"] for r in pol))
    for metric, ylabel, fname in (("hit_ratio", "Buffer-pool hit ratio", "policy_hit_ratio.png"),
                                  ("disk_reads", "Physical page reads", "policy_disk_reads.png")):
        fig, axes = plt.subplots(1, len(workloads), figsize=(5 * len(workloads), 4))
        for ax, wl in zip(axes, workloads):
            for policy in dict.fromkeys(r["policy"] for r in pol):
                pts = [r for r in pol if r["workload"] == wl and r["policy"] == policy]
                ax.plot([float(p["pool_fraction"]) * 100 for p in pts], [float(p[metric]) for p in pts],
                        marker="o", label=policy.upper())
            ax.set_title(f"{wl} workload")
            ax.set_xlabel("Pool size (% of table pages)")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.3)
        axes[0].legend()
        fig.tight_layout()
        fig.savefig(OUT / fname, dpi=150)
        plt.close(fig)

    lay = read_csv("layout_results.csv")
    ops = list(dict.fromkeys(r["operation"] for r in lay))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.38
    for k, layout in enumerate(("row", "column")):
        rows = [next(r for r in lay if r["layout"] == layout and r["operation"] == o) for o in ops]
        ax.bar([i + k * width for i in range(len(ops))], [float(r["mean_seconds"]) for r in rows], width,
               yerr=[float(r["std_seconds"]) for r in rows], capsize=3, label=layout.upper())
    ax.set_xticks([i + width / 2 for i in range(len(ops))])
    ax.set_xticklabels(ops, rotation=12)
    ax.set_yscale("log")
    ax.set_ylabel("Time in seconds (mean ± std, log scale)")
    ax.set_title("Row vs column layout")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "layout_comparison.png", dpi=150)
    plt.close(fig)
    print("Plots written to", OUT)


if __name__ == "__main__":
    create_plots()