"""Write-optimised LSM Tree index built on the M1 DiskManager and BufferPool.

Same interface as BPlusTree: insert(key, rid), search(key), range(lo, hi),
delete(key, rid). Entries are [key, page_id, slot_id], so duplicate keys work.

Structure
  memtable : in-memory dict {(key, page, slot): op}  (op 1 = put, 0 = delete marker)
  runs     : immutable sorted files (SSTables), one DiskManager file each
             page 0 = metadata, pages 1..n = one sorted chunk of entries per page
Writes go to the memtable. When it holds `memtable_limit` entries it is flushed
as a new sorted run. When more than `max_runs` runs exist they are merged into
one (full compaction); delete markers are dropped during the merge.
Reads check the memtable and every run; a newer component overrides an older one.

Limitations (documented for the report): no Bloom filters, no WAL (entries still
in the memtable are lost if the process crashes before flush/close - M4 adds the
WAL), full compaction instead of leveled compaction.
"""
import json
import os
from bisect import bisect_right
from pathlib import Path

from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.disk import DiskManager

CHUNK_BYTES = 3500       # target size of one sorted chunk (one page)
_LOW = -1


def _check_key(key_type, key):
    ok = {"int": lambda k: isinstance(k, int) and not isinstance(k, bool),
          "str": lambda k: isinstance(k, str),
          "float": lambda k: isinstance(k, (int, float)) and not isinstance(k, bool)}
    if not ok[key_type](key):
        raise TypeError(f"key {key!r} is not of type {key_type}")
    if isinstance(key, str) and len(key) > 400:
        raise ValueError("string keys longer than 400 chars are not supported")


class _Run:
    """One immutable sorted run stored in its own page file."""

    def __init__(self, path, seq, capacity=16, policy="lru"):
        self.path, self.seq = Path(path), seq
        self.disk = DiskManager(self.path)
        self.pool = BufferPool(self.disk, capacity=capacity, policy=policy)
        self.fences = []                       # first entry of every data page
        self.last = None                       # last entry of the run
        n = self.disk.page_count
        for pid in range(1, n):
            chunk = self._chunk(pid)
            self.fences.append(chunk[0])
            if pid == n - 1:
                self.last = chunk[-1]
        self.count = int(json.loads(self._record(0))["count"]) if n else 0

    def _record(self, pid):
        page = self.pool.fetch_page(pid)
        try:
            return page.get_record(0).decode("utf-8")
        finally:
            self.pool.unpin_page(pid)

    def _chunk(self, pid):
        return json.loads(self._record(pid))

    @classmethod
    def write(cls, path, entries, seq):
        """entries: sorted list of [key, page, slot, op]. Writes then returns nothing."""
        disk = DiskManager(path)
        pool = BufferPool(disk, capacity=8)

        def put(obj):
            pid, page = pool.new_page()
            page.insert_record(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
            pool.unpin_page(pid, dirty=True)

        put({"seq": seq, "count": len(entries)})
        chunk, size = [], 0
        for e in entries:
            esize = len(json.dumps(e, separators=(",", ":"))) + 1
            if chunk and size + esize > CHUNK_BYTES:
                put(chunk)
                chunk, size = [], 0
            chunk.append(e)
            size += esize
        if chunk:
            put(chunk)
        pool.close()
        disk.close()

    def overlaps(self, lo, hi):
        if not self.fences:
            return False
        if hi is not None and self.fences[0][0] > hi:
            return False
        if lo is not None and self.last[0] < lo:
            return False
        return True

    def entries(self, lo=None, hi=None):
        """All [key, page, slot, op] with lo <= key <= hi, in order."""
        if not self.overlaps(lo, hi):
            return []
        start = 0 if lo is None else max(bisect_right(self.fences, [lo, _LOW, _LOW, 0]) - 1, 0)
        out = []
        for i in range(start, len(self.fences)):
            if hi is not None and self.fences[i][0] > hi:
                break
            for e in self._chunk(i + 1):
                if (lo is None or e[0] >= lo) and (hi is None or e[0] <= hi):
                    out.append(e)
        return out

    def close(self):
        self.pool.close()
        self.disk.close()


class LSMTree:
    def __init__(self, directory, name="index", key_type="int", memtable_limit=2000,
                 max_runs=4, capacity=16, policy="lru"):
        if key_type not in ("int", "str", "float"):
            raise ValueError("key_type must be 'int', 'str' or 'float'")
        self.dir, self.name, self.key_type = Path(directory), name, key_type
        self.memtable_limit, self.max_runs = memtable_limit, max_runs
        self.capacity, self.policy = capacity, policy
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memtable = {}
        self.flushes = self.compactions = 0
        self._retired = {"hits": 0, "misses": 0, "evictions": 0, "disk_reads": 0, "disk_writes": 0}
        for tmp in self.dir.glob(f"{name}_*.tmp"):       # leftovers of an interrupted flush
            tmp.unlink()
        self.runs = []
        for path in sorted(self.dir.glob(f"{name}_*.sst")):
            seq = int(path.stem.rsplit("_", 1)[1])
            self.runs.append(_Run(path, seq, capacity, policy))
        self._next_seq = (self.runs[-1].seq + 1) if self.runs else 1

    # ---------- writes ----------
    def insert(self, key, rid):
        _check_key(self.key_type, key)
        self.memtable[(key, rid[0], rid[1])] = 1
        self._maybe_flush()
        return True

    def delete(self, key, rid):
        _check_key(self.key_type, key)
        self.memtable[(key, rid[0], rid[1])] = 0          # delete marker
        self._maybe_flush()
        return True

    def _maybe_flush(self):
        if len(self.memtable) >= self.memtable_limit:
            self.flush_memtable()

    def _run_path(self, seq):
        return self.dir / f"{self.name}_{seq:06d}.sst"

    def _write_run(self, entries):
        seq = self._next_seq
        self._next_seq += 1
        final = self._run_path(seq)
        tmp = final.with_suffix(".tmp")
        _Run.write(tmp, entries, seq)
        os.replace(tmp, final)                             # atomic publish
        self.runs.append(_Run(final, seq, self.capacity, self.policy))

    def flush_memtable(self):
        if not self.memtable:
            return
        entries = [[k, p, s, op] for (k, p, s), op in sorted(self.memtable.items())]
        self._write_run(entries)
        self.memtable = {}
        self.flushes += 1
        if len(self.runs) > self.max_runs:
            self.compact()

    def compact(self):
        """Merge every run into one; newest entry wins; delete markers are dropped."""
        merged = self._collect(None, None, include_memtable=False)
        live = [[k, p, s, 1] for (k, p, s), op in sorted(merged.items()) if op == 1]
        old = self.runs
        self.runs = []
        if live:
            self._write_run(live)
        for r in old:
            self._retire(r)
            r.close()
            r.path.unlink()
        self.compactions += 1

    # ---------- reads ----------
    def _collect(self, lo, hi, include_memtable=True):
        state = {}
        for run in self.runs:                              # oldest -> newest
            for k, p, s, op in run.entries(lo, hi):
                state[(k, p, s)] = op
        if include_memtable:
            for (k, p, s), op in self.memtable.items():
                if (lo is None or k >= lo) and (hi is None or k <= hi):
                    state[(k, p, s)] = op
        return state

    def search(self, key):
        return [rid for _, rid in self.range(key, key)]

    def range(self, lo=None, hi=None):
        state = self._collect(lo, hi)
        return [(k, (p, s)) for (k, p, s), op in sorted(state.items()) if op == 1]

    def __len__(self):
        return len(self.range())                           # O(n); for tests/reporting only

    # ---------- housekeeping ----------
    def _retire(self, run):
        for k in self._retired:
            self._retired[k] += run.pool.stats[k]

    def stats(self):
        total = dict(self._retired)
        for r in self.runs:
            for k in total:
                total[k] += r.pool.stats[k]
        return total

    def reset_stats(self):
        for k in self._retired:
            self._retired[k] = 0
        for r in self.runs:
            for k in r.pool.stats:
                r.pool.stats[k] = 0

    def size_bytes(self):
        return sum(r.disk.page_count * 4096 for r in self.runs)

    def close(self):
        self.flush_memtable()
        for r in self.runs:
            r.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()