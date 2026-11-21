import json


class ColumnStore:
    """Column-oriented table: every column is stored in its own chain of pages.

    Page format (inside the M1 slotted ``Page``):
        slot 0   -> header record  {"c": <column name>, "s": <page sequence number>}
        slot 1.. -> one JSON-encoded value per row, in row order

    Rules that keep the columns aligned and persistent:
      * values are appended ONLY to the newest page of their column, so the row order
        is identical in every column (row i is value i of each column);
      * the header record in each page lets the page chains be rebuilt when an
        existing database file is opened, so the data survives a restart.
    The store is append-only (insert / get / get_column / scan); update and delete are not supported.
    """

    def __init__(self, buffer_pool, disk_manager, columns):
        self.pool = buffer_pool
        self.disk = disk_manager
        self.columns = list(columns)
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("duplicate column names")
        self.column_pages = {name: [] for name in self.columns}
        self.page_counts = {name: [] for name in self.columns}  # values per page (parallel list)
        self.row_count = 0
        self._rebuild()

    # ------------------------------------------------------------------ persistence
    def _rebuild(self):
        """Recover page chains from an existing file using each page's header record."""
        found = {name: [] for name in self.columns}
        for page_id in range(self.disk.page_count):
            page = self.pool.fetch_page(page_id)
            try:
                raw = page.get_record(0)
                if raw is None:
                    continue
                header = json.loads(raw.decode("utf-8"))
                values = len(page) - 1
            finally:
                self.pool.unpin_page(page_id)
            name = header["c"]
            if name not in found:
                raise ValueError(f"database file contains unknown column {name!r}")
            found[name].append((header["s"], page_id, values))
        for name in self.columns:
            chain = sorted(found[name])
            self.column_pages[name] = [pid for _, pid, _ in chain]
            self.page_counts[name] = [n for _, _, n in chain]
        totals = {sum(c) for c in self.page_counts.values()}
        if len(totals) > 1:
            raise ValueError("column lengths differ: the file is corrupted or was only partly written")
        self.row_count = totals.pop() if totals else 0

    # ------------------------------------------------------------------ writes
    @staticmethod
    def _encode(value):
        return json.dumps(value, separators=(",", ":")).encode("utf-8")

    def _new_column_page(self, name):
        seq = len(self.column_pages[name])
        page_id = self.disk.allocate_page()
        page = self.pool.fetch_page(page_id)
        header = json.dumps({"c": name, "s": seq}, separators=(",", ":")).encode("utf-8")
        page.insert_record(header)  # becomes slot 0
        self.column_pages[name].append(page_id)
        self.page_counts[name].append(0)
        return page_id, page

    def insert(self, record):
        if set(record) - set(self.columns):
            raise ValueError("Record contains an unknown column")
        encoded = {name: self._encode(record.get(name)) for name in self.columns}
        for name in self.columns:  # validate before touching any page
            if len(encoded[name]) > 3000:
                raise ValueError(f"Value for {name} is too large")
        for name in self.columns:
            raw = encoded[name]
            pages = self.column_pages[name]
            if pages:
                page_id = pages[-1]
                page = self.pool.fetch_page(page_id)
                slot = page.insert_record(raw)
                if slot is not None:
                    self.pool.unpin_page(page_id, dirty=True)
                    self.page_counts[name][-1] += 1
                    continue
                self.pool.unpin_page(page_id)  # newest page is full
            page_id, page = self._new_column_page(name)
            try:
                if page.insert_record(raw) is None:
                    raise ValueError(f"Value for {name} is too large")
            finally:
                self.pool.unpin_page(page_id, dirty=True)
            self.page_counts[name][-1] += 1
        self.row_count += 1

    # ------------------------------------------------------------------ reads
    def get_column(self, column_name):
        """Read ONE column: only that column's pages are fetched."""
        if column_name not in self.column_pages:
            raise KeyError(column_name)
        values = []
        for page_id in self.column_pages[column_name]:
            page = self.pool.fetch_page(page_id)
            try:
                for slot_id in range(1, len(page.slots)):
                    raw = page.get_record(slot_id)
                    values.append(json.loads(raw.decode("utf-8")))
            finally:
                self.pool.unpin_page(page_id)
        return values

    def get(self, row_id):
        """Rebuild row number ``row_id`` (0-based) from one page per column."""
        if not 0 <= row_id < self.row_count:
            raise IndexError(f"row {row_id} does not exist")
        record = {}
        for name in self.columns:
            remaining = row_id
            for page_id, count in zip(self.column_pages[name], self.page_counts[name]):
                if remaining < count:
                    page = self.pool.fetch_page(page_id)
                    try:
                        raw = page.get_record(remaining + 1)  # slot 0 is the header
                    finally:
                        self.pool.unpin_page(page_id)
                    record[name] = json.loads(raw.decode("utf-8"))
                    break
                remaining -= count
        return record

    def scan(self):
        columns = {name: self.get_column(name) for name in self.columns}
        return [{name: columns[name][i] for name in self.columns} for i in range(self.row_count)]