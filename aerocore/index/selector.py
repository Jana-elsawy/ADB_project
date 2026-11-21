"""Workload-based index selection rule (M2).

Rule (thresholds are constants so the benchmark can justify or tune them):
  write_ratio = writes / (writes + point_reads + range_reads)
  range_ratio = range_reads / (point_reads + range_reads)

  write_ratio >= WRITE_HEAVY and range_ratio < RANGE_HEAVY  ->  LSM Tree
  otherwise                                                  ->  B+ Tree

Why: the LSM Tree batches writes in memory and appends sorted runs, so it wins when
writes dominate; but a lookup may have to check several runs and a range scan must
merge them, so it loses when reads (especially range reads) matter. The B+ Tree
gives one root-to-leaf path per lookup and linked leaves for ranges.
"""

WRITE_HEAVY = 0.6
RANGE_HEAVY = 0.3


def choose_index(writes, point_reads, range_reads):
    """Return (kind, reason) where kind is 'bptree' or 'lsm'."""
    reads = point_reads + range_reads
    total = writes + reads
    if total == 0:
        return "bptree", "no workload information, defaulting to B+ Tree"
    write_ratio = writes / total
    range_ratio = range_reads / reads if reads else 0.0
    if write_ratio >= WRITE_HEAVY and range_ratio < RANGE_HEAVY:
        return "lsm", (f"write-heavy ({write_ratio:.0%} writes) with few range reads "
                       f"({range_ratio:.0%} of reads)")
    if write_ratio < WRITE_HEAVY:
        return "bptree", f"read-heavy ({write_ratio:.0%} writes)"
    return "bptree", (f"write-heavy ({write_ratio:.0%} writes) but range reads are "
                      f"{range_ratio:.0%} of reads")