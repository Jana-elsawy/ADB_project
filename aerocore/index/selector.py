"""Workload-based index selection rule (M2).

Rule:
    write_ratio = writes / (writes + point_reads + range_reads)
    write_ratio >= WRITE_HEAVY  ->  LSM Tree
    otherwise                   ->  B+ Tree

Why: the LSM Tree buffers writes in memory and appends sorted runs, so inserts cost a
fraction of a B+ Tree insert (which rewrites a leaf page every time). Reads pay for this:
a lookup or scan may have to check several runs. The B+ Tree has one root-to-leaf path
per lookup and linked leaves for ranges, so it wins on read-dominated workloads.

Where the threshold comes from: it is set from the M2 workload benchmark
(results/m2/workload_results.csv). In our measurements the B+ Tree was faster at about
20% writes and the LSM Tree was faster from about 30% writes, even with range scans in
the mix, so the threshold sits between them. Re-run `python -m benchmarks.run_m2` on
your own machine and adjust WRITE_HEAVY if the crossover moves. Read-only range
scans are the remaining case where the B+ Tree is clearly better (E3), and read-only
workloads are always below the threshold.
"""

WRITE_HEAVY = 0.25


def choose_index(writes, point_reads, range_reads):
    """Return (kind, reason) where kind is 'bptree' or 'lsm'."""
    reads = point_reads + range_reads
    total = writes + reads
    if total == 0:
        return "bptree", "no workload information, defaulting to B+ Tree"
    write_ratio = writes / total
    if write_ratio >= WRITE_HEAVY:
        return "lsm", (f"write-heavy: {write_ratio:.0%} of operations are writes "
                       f"(threshold {WRITE_HEAVY:.0%})")
    return "bptree", (f"read-dominated: {write_ratio:.0%} of operations are writes "
                      f"(threshold {WRITE_HEAVY:.0%})")