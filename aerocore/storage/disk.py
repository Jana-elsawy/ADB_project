import os
from pathlib import Path
from .page import PAGE_SIZE, Page


class DiskManager:
    """Stores fixed-size pages in one database file."""

    def __init__(self, filename):
        self.filename = Path(filename)
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if self.filename.exists() else "w+b"
        self.file = open(self.filename, mode)
        self.file.seek(0, 2)
        self.page_count = self.file.tell() // PAGE_SIZE

    def allocate_page(self):
        page_id = self.page_count
        self.page_count += 1
        page = Page(page_id)
        self.write_page(page_id, page.serialize())
        return page_id

    def read_page(self, page_id):
        if page_id < 0 or page_id >= self.page_count:
            raise ValueError(f"Unknown page id: {page_id}")
        self.file.seek(page_id * PAGE_SIZE)
        raw = self.file.read(PAGE_SIZE)
        if len(raw) != PAGE_SIZE:
            raise IOError("Could not read a complete page")
        return Page.deserialize(raw)

    def write_page(self, page_id, data):
        if len(data) != PAGE_SIZE:
            raise ValueError(f"Page data must be exactly {PAGE_SIZE} bytes")
        self.file.seek(page_id * PAGE_SIZE)
        self.file.write(data)
        self.file.flush()
        if page_id >= self.page_count:
            self.page_count = page_id + 1

    def close(self):
        if not self.file.closed:
            self.file.flush()
            os.fsync(self.file.fileno())  # make sure the data reached the disk
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()