import random
from aerocore.index.bptree import BPlusTree
from aerocore.index.schema import TABLE_SCHEMAS
from aerocore.storage.disk import DiskManager
from aerocore.storage.buffer_pool import BufferPool
from aerocore.storage.row_store import RowStore


def _fill(tree, n, seed=42, shuffle=True):
    keys = list(range(1, n + 1))
    if shuffle:
        random.Random(seed).shuffle(keys)
    ref = {}
    for k in keys:
        rid = (k // 10, k % 10)
        tree.insert(k, rid)
        ref[k] = rid
    return ref


def test_equality_and_range_match_reference(tmp_path):
    tree = BPlusTree(tmp_path / "t.idx", max_node_bytes=300)   # tiny nodes force deep splits
    ref = _fill(tree, 3000)
    assert tree.height >= 3 and len(tree) == 3000
    for k in random.Random(1).sample(range(1, 3001), 300):
        assert tree.search(k) == [ref[k]]
    assert tree.search(99999) == []
    got = tree.range(500, 800)
    assert got == [(k, ref[k]) for k in range(500, 801)]
    assert [k for k, _ in tree.range()] == list(range(1, 3001))
    assert [k for k, _ in tree.range(None, 10)] == list(range(1, 11))
    assert [k for k, _ in tree.range(2995, None)] == list(range(2995, 3001))
    tree.close()


def test_sequential_insert_order(tmp_path):
    tree = BPlusTree(tmp_path / "t.idx", max_node_bytes=300)
    ref = _fill(tree, 1500, shuffle=False)
    assert [k for k, _ in tree.range()] == sorted(ref)
    tree.close()


def test_duplicate_keys_return_all_rids(tmp_path):
    tree = BPlusTree(tmp_path / "t.idx", max_node_bytes=300)
    for i in range(200):
        tree.insert(7, (i, 0))          # same flight_id, 200 different reservations
        tree.insert(8, (i, 1))
    assert sorted(tree.search(7)) == [(i, 0) for i in range(200)]
    assert len(tree.search(8)) == 200
    tree.insert(7, (5, 0))              # exact duplicate is ignored
    assert len(tree.search(7)) == 200 and len(tree) == 400
    tree.close()


def test_delete(tmp_path):
    tree = BPlusTree(tmp_path / "t.idx", max_node_bytes=300)
    ref = _fill(tree, 1000)
    for k in range(1, 1001, 2):
        assert tree.delete(k, ref[k]) is True
    assert tree.delete(1, ref[1]) is False
    assert tree.search(1) == [] and tree.search(2) == [ref[2]]
    assert [k for k, _ in tree.range()] == list(range(2, 1001, 2))
    assert len(tree) == 500
    tree.close()


def test_persistence_after_reopen(tmp_path):
    path = tmp_path / "t.idx"
    tree = BPlusTree(path, max_node_bytes=300)
    ref = _fill(tree, 2000)
    tree.close()
    tree = BPlusTree(path, max_node_bytes=300)
    assert len(tree) == 2000
    assert tree.search(1234) == [ref[1234]]
    assert tree.range(10, 20) == [(k, ref[k]) for k in range(10, 21)]
    tree.close()


def test_string_keys(tmp_path):
    tree = BPlusTree(tmp_path / "s.idx", key_type="str", max_node_bytes=300)
    dates = [f"2026-12-{d:02d}T{h:02d}:00" for d in range(1, 29) for h in range(0, 24, 3)]
    random.Random(3).shuffle(dates)
    for i, d in enumerate(dates):
        tree.insert(d, (i, 0))
    got = [k for k, _ in tree.range("2026-12-10T00:00", "2026-12-12T23:59")]
    assert got == sorted(d for d in dates if "2026-12-10T00:00" <= d <= "2026-12-12T23:59")
    try:
        tree.insert(5, (0, 0))
        assert False
    except TypeError:
        pass
    tree.close()


def test_index_points_at_real_rows(tmp_path):
    disk = DiskManager(tmp_path / "res.db")
    pool = BufferPool(disk, capacity=8)
    store = RowStore(pool, disk)
    tree = BPlusTree(tmp_path / "res_flight.idx", capacity=16)
    rng = random.Random(42)
    for i in range(1, 601):
        row = {"reservation_id": i, "passenger_id": rng.randint(1, 100),
               "flight_id": rng.randint(1, 20), "seat_id": i, "status": "confirmed"}
        TABLE_SCHEMAS["reservations"].validate(row)
        tree.insert(row["flight_id"], store.insert(row))
    expected = sorted(r["reservation_id"] for r in store.scan() if r["flight_id"] == 5)
    via_index = sorted(store.get(rid)["reservation_id"] for rid in tree.search(5))
    assert via_index == expected and len(expected) > 0
    pool.close(); disk.close(); tree.close()