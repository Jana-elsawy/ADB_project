import csv
from pathlib import Path

import matplotlib.pyplot as plt


def read_csv(path):
    with open(path, "r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def create_plots():
    output = Path("results/m1")
    output.mkdir(parents=True, exist_ok=True)

    # Plot 1: LRU vs FIFO
    policy_file = output / "policy_results.csv"
    policy_data = read_csv(policy_file)

    policies = [row["policy"].upper() for row in policy_data]
    policy_times = [
        float(row["mean_seconds"]) for row in policy_data
    ]
    policy_errors = [
        float(row["std_seconds"]) for row in policy_data
    ]

    plt.figure(figsize=(7, 5))

    plt.bar(policies, policy_times, yerr=policy_errors, capsize=5)

    plt.title("LRU vs FIFO Replacement Policies")
    plt.xlabel("Replacement Policy")
    plt.ylabel("Average Execution Time (seconds)")
    plt.tight_layout()

    plt.savefig(output / "policy_comparison.png")
    plt.close()

    # Plot 2: Row vs Column storage
    layout_file = output / "layout_results.csv"
    layout_data = read_csv(layout_file)

    layouts = [row["layout"].upper() for row in layout_data]
    layout_times = [
        float(row["mean_seconds"]) for row in layout_data
    ]
    layout_errors = [
        float(row["std_seconds"]) for row in layout_data
    ]

    plt.figure(figsize=(7, 5))

    plt.bar(layouts, layout_times, yerr=layout_errors, capsize=5)

    plt.title("Row vs Column Storage")
    plt.xlabel("Storage Layout")
    plt.ylabel("Average Query Execution Time (seconds)")
    plt.tight_layout()

    plt.savefig(output / "layout_comparison.png")
    plt.close()

    print("Both benchmark plots were generated successfully.")


if __name__ == "__main__":
    create_plots()