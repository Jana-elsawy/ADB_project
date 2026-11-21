
from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.row_store import RowStore
from aerocore.storage.column_store import ColumnStore
from aerocore.storage.page import PAGE_SIZE


def test_column_store_survives_restart(tmp_path):
    path = tmp_path / "column_restart.db"

    # First database session
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=4)
    store = ColumnStore(pool, disk, ["name", "age"])

    store.insert({"name": "Jana", "age": 20})
    store.insert({"name": "Farah", "age": 21})
    store.insert({"name": "Toka", "age": 22})

    pool.close()
    disk.close()

    # Reopen the same database
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=4)
    store = ColumnStore(pool, disk, ["name", "age"])

    assert store.row_count == 3
    assert store.get_column("name") == ["Jana", "Farah", "Toka"]
    assert store.get_column("age") == [20, 21, 22]

    assert store.get(1) == {"name": "Farah", "age": 21}

    pool.close()
    disk.close()


def test_row_store_survives_restart(tmp_path):
    path = tmp_path / "row_restart.db"

    # First database session
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=4)
    store = RowStore(pool, disk)

    rid1 = store.insert({"name": "Jana", "age": 20})
    rid2 = store.insert({"name": "Farah", "age": 21})

    pool.close()
    disk.close()

    # Reopen the same database
    disk = DiskManager(path)
    pool = BufferPool(disk, capacity=4)
    store = RowStore(pool, disk)

    assert store.get(rid1)["name"] == "Jana"
    assert store.get(rid2)["age"] == 21

    assert len(store.scan()) == 2

    # Check that record IDs continue after reopening
    rid3 = store.insert({"name": "Toka", "age": 22})

    assert store.get(rid3)["name"] == "Toka"
    assert store.get(rid3)["_rid"] > store.get(rid2)["_rid"]

    pool.close()
    disk.close()


def test_delete_update_and_slot_reuse(tmp_path):
    disk = DiskManager(tmp_path / "delete_update.db")
    pool = BufferPool(disk, capacity=3)
    store = RowStore(pool, disk)

    rid1 = store.insert({"name": "Jana", "age": 20})
    rid2 = store.insert({"name": "Farah", "age": 21})

    # Delete a record
    assert store.delete(rid1) is True
    assert store.get(rid1) is None

    # Deleting it again should return False
    assert store.delete(rid1) is False

    # Insert another record and check slot reuse
    rid3 = store.insert({"name": "Toka", "age": 22})

    assert rid3[0] == rid1[0]
    assert rid3[1] == rid1[1]

    assert store.get(rid3)["name"] == "Toka"

    # Update an existing record
    new_rid = store.update(
        rid2,
        {"name": "Updated Farah", "age": 25}
    )

    assert new_rid is not None
    assert store.get(rid2) is None
    assert store.get(new_rid)["name"] == "Updated Farah"
    assert store.get(new_rid)["age"] == 25

    # Updating a nonexistent record should return None
    assert store.update(
        rid2,
        {"name": "Missing", "age": 0}
    ) is None

    pool.close()
    disk.close()


def test_larger_than_a_page(tmp_path):
    disk = DiskManager(tmp_path / "oversized.db")
    pool = BufferPool(disk, capacity=3)
    store = RowStore(pool, disk)

    oversized_record = {
        "payload": "x" * PAGE_SIZE
    }

    # An oversized record must be rejected.
    try:
        store.insert(oversized_record)
        assert False, "Expected ValueError for oversized record"
    except ValueError:
        pass

    # The failed insertion must not create a stored record.
    assert store.scan() == []

    # The store should still accept normal records.
    rid = store.insert({"name": "Jana"})

    assert store.get(rid)["name"] == "Jana"

    pool.close()
    disk.close()
