import json
from aerocore.storage.page import Page, PAGE_SIZE
from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.row_store import RowStore
from aerocore.storage.column_store import ColumnStore


def test_page_insert_serialize_roundtrip():
    page = Page(7)
    slot = page.insert_record(b"hello")
    assert page.get_record(slot) == b"hello"
    raw = page.serialize()
    assert len(raw) == PAGE_SIZE
    restored = Page.deserialize(raw)
    assert restored.get_record(slot) == b"hello"


def test_disk_persistence(tmp_path):
    path = tmp_path / "test.db"
    disk = DiskManager(path)
    page_id = disk.allocate_page()
    page = disk.read_page(page_id)
    slot = page.insert_record(b"persistent")
    disk.write_page(page_id, page.serialize())
    disk.close()

    disk = DiskManager(path)
    assert disk.read_page(page_id).get_record(slot) == b"persistent"
    disk.close()


def test_buffer_pool_lru_eviction(tmp_path):
    disk = DiskManager(tmp_path / "buffer.db")
    ids = [disk.allocate_page() for _ in range(3)]
    pool = BufferPool(disk, capacity=2, policy="lru")
    pool.fetch_page(ids[0]); pool.unpin_page(ids[0])
    pool.fetch_page(ids[1]); pool.unpin_page(ids[1])
    pool.fetch_page(ids[0]); pool.unpin_page(ids[0])
    pool.fetch_page(ids[2]); pool.unpin_page(ids[2])
    assert ids[0] in pool.frames
    assert ids[1] not in pool.frames
    pool.close()
    disk.close()


def test_row_store_roundtrip(tmp_path):
    disk = DiskManager(tmp_path / "row.db")
    pool = BufferPool(disk, capacity=3)
    store = RowStore(pool, disk)
    rid = store.insert({"passenger_id": 1, "name": "Jana"})
    assert store.get(rid)["name"] == "Jana"
    pool.close(); disk.close()


def test_column_store(tmp_path):
    disk = DiskManager(tmp_path / "column.db")
    pool = BufferPool(disk, capacity=4)
    store = ColumnStore(pool, disk, ["name", "age"])
    store.insert({"name": "Jana", "age": 20})
    store.insert({"name": "Farah", "age": 21})
    assert store.get_column("age") == [20, 21]
    assert store.scan()[0]["name"] == "Jana"
    pool.close(); disk.close()


def test_page_delete_and_reuse_slot():
    page = Page(1)

    slot1 = page.insert_record(b"first")
    slot2 = page.insert_record(b"second")

    assert page.delete_record(slot1) is True
    assert page.get_record(slot1) is None

    new_slot = page.insert_record(b"new")

    assert new_slot == slot1
    assert page.get_record(new_slot) == b"new"
    assert page.get_record(slot2) == b"second"


def test_fifo_eviction(tmp_path):
    disk = DiskManager(tmp_path / "fifo.db")
    ids = [disk.allocate_page() for _ in range(3)]

    pool = BufferPool(disk, capacity=2, policy="fifo")

    pool.fetch_page(ids[0])
    pool.unpin_page(ids[0])

    pool.fetch_page(ids[1])
    pool.unpin_page(ids[1])

    pool.fetch_page(ids[0])
    pool.unpin_page(ids[0])

    pool.fetch_page(ids[2])
    pool.unpin_page(ids[2])

    assert ids[0] not in pool.frames
    assert ids[1] in pool.frames

    pool.close()
    disk.close()


def test_pinned_page_cannot_be_evicted(tmp_path):
    disk = DiskManager(tmp_path / "pinned.db")
    ids = [disk.allocate_page() for _ in range(2)]

    pool = BufferPool(disk, capacity=1)

    pool.fetch_page(ids[0])

    try:
        pool.fetch_page(ids[1])
        assert False, "Expected an error because the only page is pinned"
    except RuntimeError:
        pass

    assert ids[0] in pool.frames

    pool.unpin_page(ids[0])
    pool.close()
    disk.close()


def test_dirty_page_is_flushed(tmp_path):
    disk = DiskManager(tmp_path / "dirty.db")
    page_id = disk.allocate_page()

    pool = BufferPool(disk, capacity=1)

    page = pool.fetch_page(page_id)
    slot = page.insert_record(b"saved data")

    pool.unpin_page(page_id, dirty=True)
    pool.close()

    assert pool.stats["disk_writes"] == 1

    disk.close()

    disk = DiskManager(tmp_path / "dirty.db")
    assert disk.read_page(page_id).get_record(slot) == b"saved data"

    disk.close()
