from pathlib import Path
from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.row_store import RowStore


def main():
    db_path = Path("results/m1/demo.db")
    if db_path.exists():
        db_path.unlink()
    disk = DiskManager(db_path)
    pool = BufferPool(disk, capacity=3, policy="lru")
    store = RowStore(pool, disk)

    rid1 = store.insert({"passenger_id": 101, "name": "Ahmed", "country": "Egypt"})
    rid2 = store.insert({"passenger_id": 102, "name": "Sara", "country": "Jordan"})
    print("Passenger 101:", store.get(rid1))
    print("All passengers:", store.scan())

    pool.close()
    disk.close()

    # Reopen to demonstrate persistence.
    disk = DiskManager(db_path)
    pool = BufferPool(disk, capacity=3, policy="lru")
    store = RowStore(pool, disk)
    print("After reopening:", store.scan())
    pool.close()
    disk.close()


if __name__ == "__main__":
    main()
