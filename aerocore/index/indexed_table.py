"""A table (RowStore) whose secondary indexes are kept in sync on every write.

Files for a table called `reservations` in directory D:
  D/reservations.db                      table pages (M1 RowStore)
  D/reservations.meta.json               {column: "bptree" | "lsm"}
  D/reservations_<col>.idx               B+ Tree index file
  D/reservations_<col>_lsm/              LSM Tree run files
"""
import json
import shutil
from pathlib import Path

from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.disk import DiskManager
from aerocore.storage.row_store import RowStore

from .bptree import BPlusTree
from .lsm import LSMTree
from .selector import choose_index


class IndexedTable:
    def __init__(self, name, directory, schema, buffer_capacity=16, policy="lru",
                 index_capacity=64, memtable_limit=2000, max_runs=4):
        self.name, self.dir, self.schema = name, Path(directory), schema
        self.index_capacity, self.memtable_limit, self.max_runs = index_capacity, memtable_limit, max_runs
        self.dir.mkdir(parents=True, exist_ok=True)
        self.disk = DiskManager(self.dir / f"{name}.db")
        self.pool = BufferPool(self.disk, capacity=buffer_capacity, policy=policy)
        self.store = RowStore(self.pool, self.disk)
        self.indexes, self.kinds = {}, {}
        self.workload = {"writes": 0, "point": {}, "range": {}}
        meta = self.dir / f"{name}.meta.json"
        if meta.exists():
            for col, kind in json.loads(meta.read_text()).items():
                self.indexes[col], self.kinds[col] = self._open_index(col, kind), kind

    # ---------- index management ----------
    def _open_index(self, col, kind):
        key_type = self.schema.key_type(col)
        if kind == "bptree":
            return BPlusTree(self.dir / f"{self.name}_{col}.idx", key_type=key_type,
                             capacity=self.index_capacity)
        if kind == "lsm":
            return LSMTree(self.dir / f"{self.name}_{col}_lsm", name=col, key_type=key_type,
                           memtable_limit=self.memtable_limit, max_runs=self.max_runs)
        raise ValueError("kind must be 'bptree' or 'lsm'")

    def _save_meta(self):
        (self.dir / f"{self.name}.meta.json").write_text(json.dumps(self.kinds))

    def _drop_files(self, col, kind):
        if kind == "bptree":
            (self.dir / f"{self.name}_{col}.idx").unlink(missing_ok=True)
        else:
            shutil.rmtree(self.dir / f"{self.name}_{col}_lsm", ignore_errors=True)

    def create_index(self, col, kind="auto", workload=None):
        """Build an index over the existing rows. kind='auto' applies the selection rule.

        workload: optional dict {writes, point_reads, range_reads} of expected operations;
        if omitted, the operations observed so far on this column are used.
        Returns (kind, reason)."""
        if col not in self.schema.columns:
            raise KeyError(col)
        if col in self.indexes:
            raise ValueError(f"{col} is already indexed")
        reason = "chosen explicitly"
        if kind == "auto":
            w = workload or self._observed(col)
            kind, reason = choose_index(w["writes"], w["point_reads"], w["range_reads"])
        idx = self._open_index(col, kind)
        for rid, rec in self.store.scan_with_rids():
            if col in rec:
                idx.insert(rec[col], rid)
        self.indexes[col], self.kinds[col] = idx, kind
        self._save_meta()
        return kind, reason

    def drop_index(self, col):
        self.indexes.pop(col).close()
        self._drop_files(col, self.kinds.pop(col))
        self._save_meta()

    def _observed(self, col):
        return {"writes": self.workload["writes"],
                "point_reads": self.workload["point"].get(col, 0),
                "range_reads": self.workload["range"].get(col, 0)}

    def recommend(self, col):
        """Apply the selection rule to the operations observed so far on this column."""
        w = self._observed(col)
        return choose_index(w["writes"], w["point_reads"], w["range_reads"])

    def reselect(self, col):
        """Rebuild the index of `col` as the type the rule recommends. Returns (kind, changed)."""
        kind, _ = self.recommend(col)
        if kind == self.kinds[col]:
            return kind, False
        self.drop_index(col)
        self.create_index(col, kind)
        return kind, True

    # ---------- writes ----------
    def insert(self, record):
        self.schema.validate(record)
        rid = self.store.insert(record)
        for col, idx in self.indexes.items():
            if col in record:
                idx.insert(record[col], rid)
        self.workload["writes"] += 1
        return rid

    def delete(self, rid):
        old = self.store.get(rid)
        if old is None:
            return False
        self.store.delete(rid)
        for col, idx in self.indexes.items():
            if col in old:
                idx.delete(old[col], rid)
        self.workload["writes"] += 1
        return True

    def update(self, rid, record):
        """Replace the row; returns its new RID (it may move) or None if rid is unknown."""
        self.schema.validate(record)
        old = self.store.get(rid)
        if old is None:
            return None
        new_rid = self.store.update(rid, record)
        for col, idx in self.indexes.items():
            if col in old:
                idx.delete(old[col], rid)
            if col in record:
                idx.insert(record[col], new_rid)
        self.workload["writes"] += 1
        return new_rid

    # ---------- reads ----------
    def get(self, rid):
        return self.store.get(rid)

    def find(self, col, value):
        """Rows where col == value (index if present, else full scan)."""
        self.workload["point"][col] = self.workload["point"].get(col, 0) + 1
        if col in self.indexes:
            return [self.store.get(rid) for rid in self.indexes[col].search(value)]
        return self.scan_filter(col, value, value)

    def find_range(self, col, lo=None, hi=None):
        """Rows where lo <= col <= hi, ordered by key when an index is used."""
        self.workload["range"][col] = self.workload["range"].get(col, 0) + 1
        if col in self.indexes:
            return [self.store.get(rid) for _, rid in self.indexes[col].range(lo, hi)]
        return self.scan_filter(col, lo, hi)

    def scan_filter(self, col, lo=None, hi=None):
        """Full-scan baseline (no index)."""
        out = []
        for _, rec in self.store.scan_with_rids():
            v = rec.get(col)
            if v is not None and (lo is None or v >= lo) and (hi is None or v <= hi):
                out.append(rec)
        return out

    # ---------- housekeeping ----------
    def table_stats(self):
        return dict(self.pool.stats)

    def index_stats(self, col):
        idx = self.indexes[col]
        return dict(idx.pool.stats) if self.kinds[col] == "bptree" else idx.stats()

    def reset_stats(self):
        for k in self.pool.stats:
            self.pool.stats[k] = 0
        for idx in self.indexes.values():
            idx.reset_stats()

    def close(self):
        for idx in self.indexes.values():
            idx.close()
        self.pool.close()
        self.disk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()