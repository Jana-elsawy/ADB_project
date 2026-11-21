
import json


class RowStore:
    """Simple append-oriented row store backed by the buffer pool."""

    def __init__(self, buffer_pool, disk_manager):
        self.pool = buffer_pool
        self.disk = disk_manager
        self.page_ids = list(range(self.disk.page_count))
        self._next_id = 1
        self._freed = True
        self._rebuild_index()

    def _rebuild_index(self):
        """Restore the next record ID after reopening the store."""
        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)

            try:
                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)

                    if raw is not None:
                        record = json.loads(raw.decode("utf-8"))

                        if isinstance(record, dict):
                            rid = record.get("_rid")

                            if isinstance(rid, int):
                                self._next_id = max(
                                    self._next_id, rid + 1
                                )
            finally:
                self.pool.unpin_page(page_id)

    def _candidate_pages(self):
        """Return pages that may have free space."""
        if self.page_ids:
            yield self.page_ids[-1]

        if self._freed:
            yield from self.page_ids[:-1]

    def insert(self, record):
        """Insert a record and return its physical RID."""
        record = dict(record)

        record.setdefault("_rid", self._next_id)
        self._next_id = max(
            self._next_id, record["_rid"] + 1
        )

        raw = json.dumps(
            record, separators=(",", ":")
        ).encode("utf-8")

        # Try existing pages first.
        for page_id in list(self._candidate_pages()):
            page = self.pool.fetch_page(page_id)
            dirty = False

            try:
                slot_id = page.insert_record(raw)

                if slot_id is not None:
                    dirty = True
                    return (page_id, slot_id)

            finally:
                self.pool.unpin_page(
                    page_id, dirty=dirty
                )

        # Allocate a new page if existing pages are full.
        page_id = self.disk.allocate_page()
        self.page_ids.append(page_id)

        page = self.pool.fetch_page(page_id)
        dirty = False

        try:
            slot_id = page.insert_record(raw)

            if slot_id is None:
                raise ValueError(
                    "Record is too large to fit in an empty page"
                )

            dirty = True
            self._freed = False

            return (page_id, slot_id)

        finally:
            self.pool.unpin_page(
                page_id, dirty=dirty
            )

    def get(self, rid):
        """Retrieve a record using its physical RID."""
        page_id, slot_id = rid

        page = self.pool.fetch_page(page_id)

        try:
            raw = page.get_record(slot_id)

            if raw is None:
                return None

            return json.loads(raw.decode("utf-8"))

        finally:
            self.pool.unpin_page(page_id)

    def delete(self, rid):
        """Delete a record and return True if it existed."""
        page_id, slot_id = rid

        page = self.pool.fetch_page(page_id)
        dirty = False

        try:
            deleted = page.delete_record(slot_id)

            if deleted:
                dirty = True
                self._freed = True

            return deleted

        finally:
            self.pool.unpin_page(
                page_id, dirty=dirty
            )

    def update(self, rid, record):
        """Replace a record and return the new physical RID."""
        if self.get(rid) is None:
            return None

        # Generate a fresh internal record ID.
        record = dict(record)
        record.pop("_rid", None)

        # Insert first so the old physical slot cannot be reused.
        new_rid = self.insert(record)

        # Remove the original only after successful insertion.
        if not self.delete(rid):
            self.delete(new_rid)
            return None

        return new_rid

    def scan_with_rids(self):
        """Yield each physical RID and its record."""
        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)

            try:
                rows = []

                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)

                    if raw is not None:
                        record = json.loads(
                            raw.decode("utf-8")
                        )

                        rows.append(
                            ((page_id, slot_id), record)
                        )

            finally:
                self.pool.unpin_page(page_id)

            yield from rows

    def scan(self):
        """Return all existing records."""
        result = []

        for page_id in self.page_ids:
            page = self.pool.fetch_page(page_id)

            try:
                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)

                    if raw is not None:
                        result.append(
                            json.loads(raw.decode("utf-8"))
                        )

            finally:
                self.pool.unpin_page(page_id)

        return result
