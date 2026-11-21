
import json


class ColumnStore:
    """Column-oriented storage backed by the buffer pool."""

    def __init__(self, buffer_pool, disk_manager, columns):
        self.pool = buffer_pool
        self.disk = disk_manager
        self.columns = list(columns)

        if not self.columns:
            raise ValueError("At least one column is required")

        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Duplicate column names")

        self.column_pages = {name: [] for name in self.columns}
        self.page_counts = {name: [] for name in self.columns}
        self.row_count = 0

        self._rebuild()

    # ---------------------------------------------------------
    # Encoding
    # ---------------------------------------------------------

    @staticmethod
    def _encode(value):
        return json.dumps(
            value, separators=(",", ":")
        ).encode("utf-8")

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------

    def _rebuild(self):
        """Rebuild column page chains after reopening the database."""

        found = {name: [] for name in self.columns}

        for page_id in range(self.disk.page_count):
            page = self.pool.fetch_page(page_id)

            try:
                raw = page.get_record(0)

                if raw is None:
                    continue

                header = json.loads(raw.decode("utf-8"))

                if not isinstance(header, dict):
                    raise ValueError("Invalid column page header")

                if "c" not in header or "s" not in header:
                    raise ValueError("Incomplete column page header")

                name = header["c"]
                sequence = header["s"]

                if not isinstance(sequence, int) or sequence < 0:
                    raise ValueError("Invalid column page sequence")

                values = 0

                for slot_id in range(1, len(page.slots)):
                    if page.get_record(slot_id) is not None:
                        values += 1

            finally:
                self.pool.unpin_page(page_id)

            if name not in found:
                raise ValueError(
                    f"Database contains unknown column: {name}"
                )

            found[name].append((sequence, page_id, values))

        for name in self.columns:
            chain = sorted(found[name])

            sequences = [sequence for sequence, _, _ in chain]

            if len(sequences) != len(set(sequences)):
                raise ValueError(
                    f"Duplicate page sequence for column {name}"
                )

            self.column_pages[name] = [
                page_id for _, page_id, _ in chain
            ]

            self.page_counts[name] = [
                count for _, _, count in chain
            ]

        totals = {
            sum(self.page_counts[name])
            for name in self.columns
        }

        if len(totals) > 1:
            raise ValueError(
                "Column lengths differ: database may be corrupted "
                "or an insertion may have been interrupted"
            )

        self.row_count = totals.pop() if totals else 0

    # ---------------------------------------------------------
    # Page creation
    # ---------------------------------------------------------

    def _new_column_page(self, name):
        """Create a new page and write its column header."""

        sequence = len(self.column_pages[name])
        page_id = self.disk.allocate_page()

        page = self.pool.fetch_page(page_id)
        dirty = False

        try:
            header = self._encode({
                "c": name,
                "s": sequence
            })

            slot = page.insert_record(header)

            if slot != 0:
                raise ValueError(
                    "Could not create column page header"
                )

            dirty = True

            self.column_pages[name].append(page_id)
            self.page_counts[name].append(0)

            return page_id, page

        except Exception:
            raise

        finally:
            self.pool.unpin_page(page_id, dirty=dirty)

    # ---------------------------------------------------------
    # Insert
    # ---------------------------------------------------------

    def insert(self, record):
        """Insert one row across all columns."""

        if not isinstance(record, dict):
            raise TypeError("Record must be a dictionary")

        unknown_columns = set(record) - set(self.columns)

        if unknown_columns:
            raise ValueError(
                f"Record contains unknown columns: {unknown_columns}"
            )

        # Encode and validate every value before writing.
        encoded = {}

        for name in self.columns:
            raw = self._encode(record.get(name))

            if len(raw) > 3000:
                raise ValueError(
                    f"Value for column {name} is too large"
                )

            encoded[name] = raw

        # Append the value to each column.
        for name in self.columns:
            raw = encoded[name]
            pages = self.column_pages[name]

            inserted = False

            # Try the newest page first.
            if pages:
                page_id = pages[-1]
                page = self.pool.fetch_page(page_id)
                dirty = False

                try:
                    slot = page.insert_record(raw)

                    if slot is not None:
                        dirty = True
                        inserted = True

                finally:
                    self.pool.unpin_page(
                        page_id, dirty=dirty
                    )

                if inserted:
                    self.page_counts[name][-1] += 1
                    continue

            # The column has no page or its newest page is full.
            page_id, page = self._new_column_page(name)

            # _new_column_page releases its own pin, so fetch again.
            page = self.pool.fetch_page(page_id)
            dirty = False

            try:
                slot = page.insert_record(raw)

                if slot is None:
                    raise ValueError(
                        f"Value for column {name} is too large"
                    )

                dirty = True

            finally:
                self.pool.unpin_page(
                    page_id, dirty=dirty
                )

            self.page_counts[name][-1] += 1

        self.row_count += 1

    # ---------------------------------------------------------
    # Read one column
    # ---------------------------------------------------------

    def get_column(self, column_name):
        """Read all values from one column."""

        if column_name not in self.column_pages:
            raise KeyError(column_name)

        values = []

        for page_id in self.column_pages[column_name]:
            page = self.pool.fetch_page(page_id)

            try:
                for slot_id in range(1, len(page.slots)):
                    raw = page.get_record(slot_id)

                    if raw is not None:
                        values.append(
                            json.loads(raw.decode("utf-8"))
                        )

            finally:
                self.pool.unpin_page(page_id)

        return values

    # ---------------------------------------------------------
    # Read one row
    # ---------------------------------------------------------

    def get(self, row_id):
        """Read one row using its zero-based row ID."""

        if not isinstance(row_id, int):
            raise TypeError("Row ID must be an integer")

        if not 0 <= row_id < self.row_count:
            raise IndexError(
                f"Row {row_id} does not exist"
            )

        record = {}

        for name in self.columns:
            remaining = row_id

            for page_id, count in zip(
                self.column_pages[name],
                self.page_counts[name]
            ):
                if remaining < count:
                    page = self.pool.fetch_page(page_id)

                    try:
                        raw = page.get_record(remaining + 1)

                        if raw is None:
                            raise ValueError(
                                "Missing value in column page"
                            )

                        record[name] = json.loads(
                            raw.decode("utf-8")
                        )

                    finally:
                        self.pool.unpin_page(page_id)

                    break

                remaining -= count

            else:
                raise ValueError(
                    f"Could not find row {row_id} in column {name}"
                )

        return record

    # ---------------------------------------------------------
    # Scan all rows
    # ---------------------------------------------------------

    def scan(self):
        """Return all rows as dictionaries."""

        columns = {
            name: self.get_column(name)
            for name in self.columns
        }

        result = []

        for i in range(self.row_count):
            row = {}

            for name in self.columns:
                row[name] = columns[name][i]

            result.append(row)

        return result
