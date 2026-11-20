import json
from .page import Page


class RowStore:
    """Simple append-oriented row store backed by the buffer pool."""

    def __init__(self, buffer_pool, disk_manager):
        self.pool = buffer_pool
        self.disk = disk_manager
        self.page_ids = list(range(self.disk.page_count))
        self._next_id = 1
        self._records = {}
        self._rebuild_index()

    def _rebuild_index(self):
        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)
            try:
                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)
                    if raw is not None:
                        record = json.loads(raw.decode("utf-8"))
                        rid = (page_id, slot_id)
                        self._records[rid] = record
                        if isinstance(record, dict) and isinstance(record.get("_rid"), int):
                            self._next_id = max(self._next_id, record["_rid"] + 1)
            finally:
                self.pool.unpin_page(page_id)

    def insert(self, record):
        record = dict(record)
        record.setdefault("_rid", self._next_id)
        self._next_id = max(self._next_id, record["_rid"] + 1)
        raw = json.dumps(record, separators=(",", ":")).encode("utf-8")

        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)
            try:
                slot_id = page.insert_record(raw)
                if slot_id is not None:
                    self.pool.unpin_page(page_id, dirty=True)
                    rid = (page_id, slot_id)
                    self._records[rid] = record
                    return rid
            finally:
                # If insert succeeded, it was already unpinned above.
                if page_id in self.pool.frames and self.pool.frames[page_id].pin_count:
                    self.pool.unpin_page(page_id)

        page_id = self.disk.allocate_page()
        self.page_ids.append(page_id)
        page = self.pool.fetch_page(page_id)
        try:
            slot_id = page.insert_record(raw)
            if slot_id is None:
                raise ValueError("Record is too large to fit in an empty page")
            self.pool.unpin_page(page_id, dirty=True)
        except Exception:
            self.pool.unpin_page(page_id)
            raise
        rid = (page_id, slot_id)
        self._records[rid] = record
        return rid

    def get(self, rid):
        page_id, slot_id = rid
        page = self.pool.fetch_page(page_id)
        try:
            raw = page.get_record(slot_id)
            return None if raw is None else json.loads(raw.decode("utf-8"))
        finally:
            self.pool.unpin_page(page_id)

    def delete(self, rid):
        page_id, slot_id = rid
        page = self.pool.fetch_page(page_id)
        try:
            deleted = page.delete_record(slot_id)
            self.pool.unpin_page(page_id, dirty=deleted)
            self._records.pop(rid, None)
            return deleted
        finally:
            if page_id in self.pool.frames and self.pool.frames[page_id].pin_count:
                self.pool.unpin_page(page_id)

    def update(self, rid, record):
        if not self.delete(rid):
            return False
        self.insert(record)
        return True

    def scan(self):
        result = []
        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)
            try:
                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)
                    if raw is not None:
                        result.append(json.loads(raw.decode("utf-8")))
            finally:
                self.pool.unpin_page(page_id)
        return result
