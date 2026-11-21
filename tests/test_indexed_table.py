import random
from aerocore.index import IndexedTable, TABLE_SCHEMAS, choose_index


def _rows(n, seed=42):
    rng = random.Random(seed)
    return [{"reservation_id": i, "passenger_id": rng.randint(1, 100), "flight_id": rng.randint(1, 20),
             "seat_id": i, "status": "confirmed"} for i in range(1, n + 1)]


def _table(tmp_path, **kw):
    return IndexedTable("reservations", tmp_path, TABLE_SCHEMAS["reservations"], buffer_capacity=4, **kw)


def test_selection_rule():
    assert choose_index(900, 90, 10)[0] == "lsm"          # write-heavy
    assert choose_index(300, 600, 100)[0] == "lsm"        # 30% writes is above the 25% threshold
    assert choose_index(200, 700, 100)[0] == "bptree"     # 20% writes
    assert choose_index(100, 800, 100)[0] == "bptree"     # read-heavy
    assert choose_index(0, 100, 900)[0] == "bptree"       # read-only range scans
    assert choose_index(0, 0, 0)[0] == "bptree"           # no information
    assert "write-heavy" in choose_index(900, 90, 10)[1]


def test_index_lookup_matches_scan_and_reads_fewer_pages(tmp_path):
    t = _table(tmp_path)
    rows = _rows(600)
    for r in rows:
        t.insert(r)
    t.create_index("reservation_id", "bptree")
    t.create_index("flight_id", "bptree")
    t.reset_stats()
    via_index = t.find("reservation_id", 321)
    index_reads = t.table_stats()["misses"]
    t.reset_stats()
    via_scan = t.scan_filter("reservation_id", 321, 321)
    scan_reads = t.table_stats()["misses"]
    assert [r["reservation_id"] for r in via_index] == [321] == [r["reservation_id"] for r in via_scan]
    assert index_reads < scan_reads
    expected = sorted(r["reservation_id"] for r in rows if r["flight_id"] == 5)
    assert sorted(r["reservation_id"] for r in t.find("flight_id", 5)) == expected
    got = [r["flight_id"] for r in t.find_range("flight_id", 3, 6)]
    assert got == sorted(got) and set(got) <= {3, 4, 5, 6} and len(got) == sum(3 <= r["flight_id"] <= 6 for r in rows)
    t.close()


def test_indexes_stay_in_sync_on_update_and_delete(tmp_path):
    t = _table(tmp_path, memtable_limit=20)
    t.create_index("flight_id", "bptree")
    t.create_index("passenger_id", "lsm")
    rids = {r["reservation_id"]: t.insert(r) for r in _rows(200)}
    rid = rids[50]
    old = t.get(rid)
    new = dict(old, flight_id=99, passenger_id=777)
    new.pop("_rid")
    new_rid = t.update(rid, new)
    assert new_rid is not None
    assert all(r["reservation_id"] != 50 for r in t.find("flight_id", old["flight_id"]))
    assert [r["reservation_id"] for r in t.find("flight_id", 99)] == [50]
    assert [r["reservation_id"] for r in t.find("passenger_id", 777)] == [50]
    assert t.delete(new_rid) is True and t.delete(new_rid) is False
    assert t.find("flight_id", 99) == [] and t.find("passenger_id", 777) == []
    assert t.update(new_rid, new) is None      # row was deleted
    t.close()


def test_indexes_survive_reopen(tmp_path):
    t = _table(tmp_path)
    for r in _rows(300):
        t.insert(r)
    t.create_index("flight_id", "bptree")
    t.create_index("passenger_id", "lsm")
    expected = sorted(r["reservation_id"] for r in t.scan_filter("flight_id", 7, 7))
    t.close()
    t = _table(tmp_path)
    assert t.kinds == {"flight_id": "bptree", "passenger_id": "lsm"}
    assert sorted(r["reservation_id"] for r in t.find("flight_id", 7)) == expected
    assert len(t.find("passenger_id", 5)) == len(t.scan_filter("passenger_id", 5, 5))
    t.close()


def test_auto_select_and_reselect(tmp_path):
    t = _table(tmp_path, memtable_limit=50)
    kind, reason = t.create_index("seat_id", "auto", workload={"writes": 900, "point_reads": 90, "range_reads": 10})
    assert kind == "lsm" and "write-heavy" in reason
    t.create_index("flight_id", "auto")                      # nothing observed yet -> default
    assert t.kinds["flight_id"] == "bptree"
    for r in _rows(100):
        t.insert(r)
    for i in range(400):                                     # now mostly reads on seat_id
        t.find("seat_id", i % 100 + 1)
    kind, changed = t.reselect("seat_id")
    assert kind == "bptree" and changed and t.kinds["seat_id"] == "bptree"
    assert [r["seat_id"] for r in t.find("seat_id", 10)] == [10]
    assert t.reselect("seat_id") == ("bptree", False)
    t.close()


def test_type_validation(tmp_path):
    t = _table(tmp_path)
    try:
        t.insert({"reservation_id": "oops"}); assert False
    except TypeError:
        pass
    t.close()