import json


class ColumnStore:
    """Stores each column independently as a sequence of JSON-encoded values."""

    def __init__(self, buffer_pool, disk_manager, columns):
        self.pool = buffer_pool
        self.disk = disk_manager
        self.columns = list(columns)
        self.column_pages = {name: [] for name in self.columns}
        self.row_count = 0
        self._rebuild()

    def _rebuild(self):
        # Column pages are allocated sequentially, one page chain per column.
        # This small M1 implementation records its page mapping in memory.
        # Reopening an existing column store requires retaining the mapping.
        pass

    def insert(self, record):
        if set(record) - set(self.columns):
            raise ValueError("Record contains an unknown column")
        for name in self.columns:
            value = record.get(name)
            raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
            pages = self.column_pages[name]
            inserted = False
            for page_id in pages:
                page = self.pool.fetch_page(page_id)
                try:
                    slot = page.insert_record(raw)
                    if slot is not None:
                        self.pool.unpin_page(page_id, dirty=True)
                        inserted = True
                        break
                finally:
                    if page_id in self.pool.frames and self.pool.frames[page_id].pin_count:
                        self.pool.unpin_page(page_id)
            if not inserted:
                page_id = self.disk.allocate_page()
                pages.append(page_id)
                page = self.pool.fetch_page(page_id)
                try:
                    if page.insert_record(raw) is None:
                        raise ValueError(f"Value for {name} is too large")
                    self.pool.unpin_page(page_id, dirty=True)
                except Exception:
                    self.pool.unpin_page(page_id)
                    raise
        self.row_count += 1

    def get_column(self, column_name):
        if column_name not in self.column_pages:
            raise KeyError(column_name)
        values = []
        for page_id in self.column_pages[column_name]:
            page = self.pool.fetch_page(page_id)
            try:
                for slot_id in range(len(page.slots)):
                    raw = page.get_record(slot_id)
                    if raw is not None:
                        values.append(json.loads(raw.decode("utf-8")))
            finally:
                self.pool.unpin_page(page_id)
        return values

    def scan(self):
        columns = {name: self.get_column(name) for name in self.columns}
        count = min((len(values) for values in columns.values()), default=0)
        return [{name: columns[name][i] for name in self.columns} for i in range(count)]
