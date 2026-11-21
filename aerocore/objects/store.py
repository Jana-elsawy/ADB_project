"""Object storage on top of the M1 storage engine (M2).

Stores arbitrary byte objects (e-tickets, passenger manifests) under a string id.

Files for a store called `tickets` in directory D:
  D/tickets.objects       M1 page file: object chunks + one manifest record per object
  D/tickets_catalog.idx   B+ Tree  object_id -> RID of the object's manifest record

An object is optionally encrypted (cipher hook), split into <= CHUNK_SIZE byte chunks
(each chunk is one record in an M1 slotted page), and described by a JSON manifest
{size, checksum, cipher, content_type, chunks: [[page, slot], ...]}.

Limits (documented for the report): a manifest must fit in one record, so objects are
limited to MAX_OBJECT_SIZE (1 MB, plenty for tickets and manifests). Pages freed by
delete are reused only when they happen to be the last page; there is no free-page list.
"""
import hashlib
import json
from pathlib import Path

from aerocore.index.bptree import BPlusTree
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.disk import DiskManager

from .encryption import NullCipher

CHUNK_SIZE = 4000
MAX_OBJECT_SIZE = 1_000_000


class ObjectStore:
    def __init__(self, directory, name="objects", cipher=None, capacity=32, policy="lru"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher or NullCipher()
        self.disk = DiskManager(self.dir / f"{name}.objects")
        self.pool = BufferPool(self.disk, capacity=capacity, policy=policy)
        self.catalog = BPlusTree(self.dir / f"{name}_catalog.idx", key_type="str")

    # ---------- low-level record helpers ----------
    def _put_record(self, raw):
        if self.disk.page_count:
            last = self.disk.page_count - 1
            page = self.pool.fetch_page(last)
            slot = page.insert_record(raw)
            self.pool.unpin_page(last, dirty=slot is not None)
            if slot is not None:
                return (last, slot)
        pid, page = self.pool.new_page()
        slot = page.insert_record(raw)
        self.pool.unpin_page(pid, dirty=True)
        if slot is None:
            raise ValueError("record does not fit in a page")
        return (pid, slot)

    def _get_record(self, rid):
        page = self.pool.fetch_page(rid[0])
        try:
            raw = page.get_record(rid[1])
        finally:
            self.pool.unpin_page(rid[0])
        if raw is None:
            raise IOError(f"missing record at {rid}")
        return raw

    def _delete_record(self, rid):
        page = self.pool.fetch_page(rid[0])
        ok = page.delete_record(rid[1])
        self.pool.unpin_page(rid[0], dirty=ok)

    def _manifest_rid(self, object_id):
        hits = self.catalog.search(object_id)
        return hits[0] if hits else None

    # ---------- public API ----------
    def put(self, object_id, data, content_type="application/octet-stream"):
        """Store (or replace) an object. Returns its manifest dict."""
        if not isinstance(object_id, str) or not object_id:
            raise ValueError("object_id must be a non-empty string")
        data = bytes(data)
        if len(data) > MAX_OBJECT_SIZE:
            raise ValueError(f"object larger than {MAX_OBJECT_SIZE} bytes is not supported")
        stored = self.cipher.encrypt(data)
        self.delete(object_id)                                    # replace semantics
        chunks = [list(self._put_record(stored[i:i + CHUNK_SIZE]))
                  for i in range(0, len(stored), CHUNK_SIZE)]
        manifest = {"size": len(data), "stored_size": len(stored),
                    "checksum": hashlib.sha256(stored).hexdigest(), "cipher": self.cipher.name,
                    "content_type": content_type, "chunks": chunks}
        raw = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        if len(raw) > 4000:
            raise ValueError("object too large for a single manifest record")
        self.catalog.insert(object_id, self._put_record(raw))
        return manifest

    def info(self, object_id):
        rid = self._manifest_rid(object_id)
        if rid is None:
            raise KeyError(object_id)
        return json.loads(self._get_record(rid).decode("utf-8"))

    def get(self, object_id):
        m = self.info(object_id)
        if m["cipher"] != self.cipher.name:
            raise ValueError(f"object was stored with cipher '{m['cipher']}', store uses '{self.cipher.name}'")
        stored = b"".join(self._get_record(tuple(c)) for c in m["chunks"])
        if hashlib.sha256(stored).hexdigest() != m["checksum"]:
            raise IOError(f"checksum mismatch for object {object_id}")
        return self.cipher.decrypt(stored)

    def delete(self, object_id):
        rid = self._manifest_rid(object_id)
        if rid is None:
            return False
        m = json.loads(self._get_record(rid).decode("utf-8"))
        for c in m["chunks"]:
            self._delete_record(tuple(c))
        self._delete_record(rid)
        self.catalog.delete(object_id, rid)
        return True

    def exists(self, object_id):
        return self._manifest_rid(object_id) is not None

    def list(self, prefix=""):
        """Object ids starting with prefix, in sorted order."""
        hi = prefix + "\U0010ffff" if prefix else None
        return [k for k, _ in self.catalog.range(prefix or None, hi)]

    def size_bytes(self):
        return self.disk.page_count * 4096

    def close(self):
        self.catalog.close()
        self.pool.close()
        self.disk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()