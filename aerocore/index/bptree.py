"""Disk-based B+ Tree built on the M1 DiskManager and BufferPool.

Layout (one index = one file, 4 KB pages):
  page 0  : metadata record  {root, key_type, count, height}
  page N  : one tree node stored as a single record in slot 0 of an M1 slotted page

Entries are [key, page_id, slot_id]. Including the RID makes every entry unique,
so non-unique keys (e.g. flight_id in reservations) need no special handling.
Leaves are linked through "next" for range scans. Deletes are lazy (no merging).
"""
import json
from bisect import bisect_left, bisect_right

from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.disk import DiskManager

META_PAGE = 0
MAX_RECORD = 4000          # hard limit for one node record inside a 4 KB page
_LOW = -1                  # sorts before any real page/slot id


class BPlusTree:
    def __init__(self, path, key_type="int", capacity=64, policy="lru",
                 max_node_bytes=3600):
        if key_type not in ("int", "str", "float"):
            raise ValueError("key_type must be 'int', 'str' or 'float'")
        if max_node_bytes > MAX_RECORD:
            raise ValueError(f"max_node_bytes cannot exceed {MAX_RECORD}")
        self.max_node_bytes = max_node_bytes
        self.disk = DiskManager(path)
        self.pool = BufferPool(self.disk, capacity=capacity, policy=policy)
        if self.disk.page_count == 0:           # new index file
            self.key_type = key_type
            self.count = 0
            self.height = 1
            self._write(self.disk.allocate_page(), {})           # page 0 placeholder
            self.root = self._new_node({"leaf": True, "e": [], "next": -1})
            self._write_meta()
        else:                                    # reopen
            meta = self._read(META_PAGE)
            if meta["key_type"] != key_type:
                raise ValueError(f"index was built with key_type={meta['key_type']}")
            self.key_type = meta["key_type"]
            self.root, self.count, self.height = meta["root"], meta["count"], meta["height"]

    # ---------- page helpers ----------
    def _read(self, pid):
        page = self.pool.fetch_page(pid)
        try:
            return json.loads(page.get_record(0).decode("utf-8"))
        finally:
            self.pool.unpin_page(pid)

    def _write(self, pid, node):
        raw = json.dumps(node, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_RECORD:
            raise ValueError("node record too large for one page")
        page = self.pool.fetch_page(pid)
        try:
            page.delete_record(0)
            if page.insert_record(raw) != 0:
                raise RuntimeError("node must live in slot 0")
        finally:
            self.pool.unpin_page(pid, dirty=True)

    def _new_node(self, node):
        pid, _ = self.pool.new_page()
        self.pool.unpin_page(pid)
        self._write(pid, node)
        return pid

    def _write_meta(self):
        self._write(META_PAGE, {"root": self.root, "key_type": self.key_type,
                                "count": self.count, "height": self.height})

    def _size(self, node):
        return len(json.dumps(node, separators=(",", ":")))

    def _check_key(self, key):
        ok = {"int": lambda k: isinstance(k, int) and not isinstance(k, bool),
              "str": lambda k: isinstance(k, str),
              "float": lambda k: isinstance(k, (int, float)) and not isinstance(k, bool)}
        if not ok[self.key_type](key):
            raise TypeError(f"key {key!r} is not of type {self.key_type}")
        if isinstance(key, str) and len(key) > 400:
            raise ValueError("string keys longer than 400 chars are not supported")

    # ---------- insert ----------
    def insert(self, key, rid):
        self._check_key(key)
        entry = [key, rid[0], rid[1]]
        split = self._insert(self.root, entry)
        if split:
            sep, right = split
            self.root = self._new_node({"leaf": False, "s": [sep], "c": [self.root, right]})
            self.height += 1
        self.count += 1          # duplicates are rare; recount handled in _insert
        return True

    def _insert(self, pid, entry):
        node = self._read(pid)
        if node["leaf"]:
            es = node["e"]
            i = bisect_left(es, entry)
            if i < len(es) and es[i] == entry:
                self.count -= 1          # exact duplicate (key, rid): ignore
                return None
            es.insert(i, entry)
            if self._size(node) <= self.max_node_bytes:
                self._write(pid, node)
                return None
            mid = len(es) // 2
            right = {"leaf": True, "e": es[mid:], "next": node["next"]}
            right_pid = self._new_node(right)
            node["e"], node["next"] = es[:mid], right_pid
            self._write(pid, node)
            return right["e"][0], right_pid

        seps, ch = node["s"], node["c"]
        i = bisect_right(seps, entry)
        split = self._insert(ch[i], entry)
        if split is None:
            return None
        sep, new_pid = split
        seps.insert(i, sep)
        ch.insert(i + 1, new_pid)
        if self._size(node) <= self.max_node_bytes:
            self._write(pid, node)
            return None
        mid = len(seps) // 2
        up = seps[mid]
        right = {"leaf": False, "s": seps[mid + 1:], "c": ch[mid + 1:]}
        right_pid = self._new_node(right)
        node["s"], node["c"] = seps[:mid], ch[:mid + 1]
        self._write(pid, node)
        return up, right_pid

    # ---------- lookup ----------
    def _find_leaf(self, entry=None):
        pid = self.root
        while True:
            node = self._read(pid)
            if node["leaf"]:
                return pid, node
            i = 0 if entry is None else bisect_right(node["s"], entry)
            pid = node["c"][i]

    def search(self, key):
        """All RIDs stored under key."""
        return [rid for _, rid in self.range(key, key)]

    def range(self, lo=None, hi=None):
        """Sorted [(key, rid)] with lo <= key <= hi (None = unbounded)."""
        probe = None if lo is None else [lo, _LOW, _LOW]
        _, node = self._find_leaf(probe)
        out = []
        start = 0 if probe is None else bisect_left(node["e"], probe)
        while True:
            for key, p, s in node["e"][start:]:
                if hi is not None and key > hi:
                    return out
                out.append((key, (p, s)))
            if node["next"] == -1:
                return out
            node, start = self._read(node["next"]), 0

    # ---------- delete (lazy: no merging) ----------
    def delete(self, key, rid):
        entry = [key, rid[0], rid[1]]
        pid, node = self._find_leaf(entry)
        i = bisect_left(node["e"], entry)
        if i < len(node["e"]) and node["e"][i] == entry:
            del node["e"][i]
            self._write(pid, node)
            self.count -= 1
            return True
        return False

    # ---------- housekeeping ----------
    def __len__(self):
        return self.count

    def size_bytes(self):
        return self.disk.page_count * 4096

    def reset_stats(self):
        for k in self.pool.stats:
            self.pool.stats[k] = 0

    def flush(self):
        self._write_meta()
        self.pool.flush_all()

    def close(self):
        self.flush()
        self.disk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()