import random
import pytest
from aerocore.sql import Database, SQLError, parse, tokenize, split_statements
from aerocore.sql.parser import Select, Insert, Cond, CreateIndex

RES_DDL = ("CREATE TABLE reservations (reservation_id INT, passenger_id INT, flight_id INT, "
           "seat_id INT, status TEXT, PRIMARY KEY (reservation_id))")


def _load(db, n=600, seed=42):
    rng = random.Random(seed)
    rows = [(i, rng.randint(1, 100), rng.randint(1, 20), i,
             rng.choice(["confirmed", "confirmed", "cancelled"])) for i in range(1, n + 1)]
    for i in range(0, n, 100):
        chunk = rows[i:i + 100]
        db.execute("INSERT INTO reservations VALUES " + ", ".join(["(?,?,?,?,?)"] * len(chunk)),
                   [v for r in chunk for v in r])
    return rows


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "db", buffer_capacity=4, memtable_limit=50)
    d.execute(RES_DDL)
    yield d
    d.close()


# ---------------------------------------------------------------- parser
def test_tokenizer_and_select_parse():
    node = parse("select reservation_id, status FROM Reservations "
                 "WHERE flight_id = 7 AND seat_id BETWEEN 1 AND 20 ORDER BY seat_id DESC LIMIT 5;")
    assert isinstance(node, Select) and node.table == "reservations"
    assert node.columns == ["reservation_id", "status"]
    assert [c.op for c in node.conds] == ["=", "between"]
    assert node.order_by == "seat_id" and node.descending and node.limit == 5
    assert [t.kind for t in tokenize("a = 'x''y'")] == ["ID", "OP", "STR", "EOF"]
    assert tokenize("a = 'x''y'")[2].value == "x'y"


def test_parameters_become_values_not_sql():
    node = parse("SELECT * FROM t WHERE name = ? AND id >= ?", ("x' OR '1'='1", -5))
    assert node.conds[0].value == "x' OR '1'='1" and node.conds[1].value == -5
    assert isinstance(parse("INSERT INTO t VALUES (?, ?)", (1, "a")), Insert)
    with pytest.raises(SQLError):
        parse("SELECT * FROM t WHERE id = ?", ())                  # too few
    with pytest.raises(SQLError):
        parse("SELECT * FROM t WHERE id = ?", (1, 2))             # too many
    with pytest.raises(SQLError):
        parse("SELECT * FROM t WHERE id = ?", ([1],))             # unsupported type
    with pytest.raises(SQLError):
        parse("SELECT * FROM t WHERE id = ?", (True,))            # bool is not a value


@pytest.mark.parametrize("bad", [
    "SELECT * FROM t; DROP INDEX ON t (a)",          # stacked statement
    "SELECT * FROM t WHERE a = 1; SELECT * FROM t",
    "SELECT * FROM t WHERE a = 1 -- comment",
    "SELECT * FROM t /* x */",
    'SELECT * FROM t WHERE a = "x"',                  # double quotes are not strings
    "SELECT * FROM t WHERE a = 1 OR b = 2",           # OR is not supported
    "SELECT * FROM t WHERE a = 1 UNION SELECT * FROM u",
    "SELECT * FROM t WHERE",
    "SELECT FROM t",
    "SELECT * FROM",
    "DROP TABLE t",
    "INSERT INTO t VALUES (1,",
    "SELECT * FROM t WHERE a = 'unterminated",
    "CREATE TABLE t (a BLOB)",
    "SELECT * FROM t LIMIT -1",
    "SELECT * FROM t LIMIT 1.5",
    "",
])
def test_malformed_or_hostile_sql_is_rejected(bad):
    with pytest.raises(SQLError):
        parse(bad)


def test_split_statements_respects_quotes():
    assert split_statements("SELECT 'a;b' FROM t; SELECT 1;;") == ["SELECT 'a;b' FROM t", "SELECT 1"]


def test_create_index_variants():
    n = parse("CREATE INDEX ON t (c) USING auto WORKLOAD (10, 85, 5)")
    assert isinstance(n, CreateIndex) and n.kind == "auto" and n.workload == (10, 85, 5)
    assert parse("CREATE INDEX ON t (c)").kind == "auto"
    assert parse("CREATE INDEX ON t (c) USING lsm").kind == "lsm"
    with pytest.raises(SQLError):
        parse("CREATE INDEX ON t (c) USING hash")
    with pytest.raises(SQLError):
        parse("CREATE INDEX ON t (a, b)")
    with pytest.raises(SQLError):
        parse("CREATE INDEX ON t (c) USING auto WORKLOAD (1, 2)")


# ---------------------------------------------------------------- engine
def test_create_insert_select_basics(db):
    assert "created" in db.execute("CREATE TABLE airports (airport_id INT, city TEXT)").message
    assert db.execute("INSERT INTO airports VALUES (1, 'Cairo'), (2, 'Dubai')").rowcount == 2
    res = db.execute("SELECT city FROM airports WHERE airport_id = 2")
    assert res.columns == ["city"] and res.rows == [("Dubai",)]
    assert db.execute("SELECT * FROM airports ORDER BY city DESC").rows == [(2, "Dubai"), (1, "Cairo")]
    assert "_rid" not in db.execute("SELECT * FROM airports").columns


def test_index_results_equal_full_scan_results(db):
    rows = _load(db)
    db.execute("CREATE INDEX ON reservations (flight_id) USING bptree")
    db.execute("CREATE INDEX ON reservations (passenger_id) USING lsm")
    queries = [
        "SELECT * FROM reservations WHERE flight_id = 5",
        "SELECT * FROM reservations WHERE flight_id = 5 AND status = 'confirmed'",
        "SELECT * FROM reservations WHERE flight_id BETWEEN 3 AND 6",
        "SELECT * FROM reservations WHERE flight_id > 17",
        "SELECT * FROM reservations WHERE flight_id < 3",
        "SELECT * FROM reservations WHERE flight_id >= 4 AND flight_id <= 4",
        "SELECT * FROM reservations WHERE flight_id > 3 AND flight_id < 6 AND status != 'cancelled'",
        "SELECT * FROM reservations WHERE passenger_id = 50",
        "SELECT * FROM reservations WHERE passenger_id BETWEEN 10 AND 20 AND flight_id = 2",
        "SELECT * FROM reservations WHERE reservation_id BETWEEN 100 AND 130",
        "SELECT * FROM reservations WHERE reservation_id = 321",
        "SELECT * FROM reservations WHERE flight_id = 5 AND flight_id = 6",      # empty
        "SELECT * FROM reservations WHERE flight_id = 99",                       # no match
    ]
    for q in queries:
        fast, slow = db.execute(q), db.execute(q, use_index=False)
        assert fast.used_index is not None, q
        assert slow.used_index is None
        assert sorted(fast.rows) == sorted(slow.rows), q
    expected = sorted(r for r in rows if r[2] == 5)
    assert sorted(db.execute("SELECT * FROM reservations WHERE flight_id = 5").rows) == expected


def test_random_queries_index_equals_scan(db):
    _load(db, 400)
    db.execute("CREATE INDEX ON reservations (flight_id) USING bptree")
    db.execute("CREATE INDEX ON reservations (passenger_id) USING lsm")
    rng = random.Random(7)
    ops = ["=", "<", "<=", ">", ">=", "!="]
    for _ in range(80):
        col = rng.choice(["flight_id", "passenger_id", "reservation_id"])
        parts = [f"{col} {rng.choice(ops)} {rng.randint(0, 110)}"]
        if rng.random() < 0.5:
            lo = rng.randint(0, 100)
            parts.append(f"{rng.choice(['flight_id', 'passenger_id'])} BETWEEN {lo} AND {lo + rng.randint(0, 30)}")
        q = "SELECT * FROM reservations WHERE " + " AND ".join(parts)
        assert sorted(db.execute(q).rows) == sorted(db.execute(q, use_index=False).rows), q


def test_explain_shows_access_path(db):
    _load(db, 200)
    db.execute("CREATE INDEX ON reservations (flight_id) USING lsm")
    plan = db.execute("EXPLAIN SELECT * FROM reservations WHERE flight_id = 4 AND status = 'confirmed' "
                      "ORDER BY seat_id LIMIT 3").plan
    assert "IndexScan reservations.flight_id using lsm" in plan
    assert "Filter status = 'confirmed'" in plan and "Sort seat_id ASC" in plan and "Limit 3" in plan
    assert "FullScan" in db.execute("EXPLAIN SELECT * FROM reservations WHERE status = 'cancelled'").plan
    assert "IndexRangeScan" in db.execute("EXPLAIN SELECT * FROM reservations "
                                          "WHERE flight_id BETWEEN 2 AND 5").plan
    assert "IndexScan reservations.reservation_id using bptree" in db.execute(
        "EXPLAIN SELECT * FROM reservations WHERE reservation_id = 9").plan
    exp = db.execute("EXPLAIN SELECT * FROM reservations WHERE flight_id = 4")
    assert exp.columns == ["plan"] and exp.used_index == "lsm"


def test_index_reads_fewer_pages_than_scan(db):
    _load(db, 600)
    db.execute("CREATE INDEX ON reservations (flight_id) USING bptree")
    t = db.tables["reservations"]
    t.reset_stats()
    db.execute("SELECT * FROM reservations WHERE reservation_id = 321")
    index_reads = t.table_stats()["misses"]
    t.reset_stats()
    db.execute("SELECT * FROM reservations WHERE reservation_id = 321", use_index=False)
    assert index_reads < t.table_stats()["misses"]


def test_update_and_delete_keep_indexes_correct(db):
    _load(db, 300)
    db.execute("CREATE INDEX ON reservations (flight_id) USING bptree")
    db.execute("CREATE INDEX ON reservations (status) USING lsm")
    before = len(db.execute("SELECT * FROM reservations WHERE flight_id = 3").rows)
    n = db.execute("UPDATE reservations SET flight_id = 99, status = 'moved' WHERE flight_id = 3").rowcount
    assert n == before and n > 0
    assert db.execute("SELECT * FROM reservations WHERE flight_id = 3").rows == []
    moved = db.execute("SELECT reservation_id FROM reservations WHERE flight_id = 99")
    assert len(moved.rows) == n
    assert len(db.execute("SELECT * FROM reservations WHERE status = 'moved'").rows) == n
    assert db.execute("DELETE FROM reservations WHERE flight_id = 99").rowcount == n
    assert db.execute("SELECT * FROM reservations WHERE flight_id = 99").rows == []
    assert db.execute("SELECT * FROM reservations WHERE status = 'moved'").rows == []
    q = "SELECT * FROM reservations WHERE flight_id BETWEEN 1 AND 20"
    assert sorted(db.execute(q).rows) == sorted(db.execute(q, use_index=False).rows)
    assert len(db.execute("SELECT * FROM reservations").rows) == 300 - n


def test_update_one_row_by_primary_key(db):
    _load(db, 50)
    db.execute("UPDATE reservations SET status = ? WHERE reservation_id = ?", ("cancelled", 7))
    assert db.execute("SELECT status FROM reservations WHERE reservation_id = 7").rows == [("cancelled",)]
    assert len(db.execute("SELECT * FROM reservations").rows) == 50


def test_persistence_after_reopen(tmp_path):
    d = tmp_path / "db"
    db = Database(d, buffer_capacity=4, memtable_limit=50)
    db.execute(RES_DDL)
    _load(db, 250)
    db.execute("CREATE INDEX ON reservations (flight_id) USING bptree")
    db.execute("CREATE INDEX ON reservations (passenger_id) USING lsm")
    expected = sorted(db.execute("SELECT * FROM reservations WHERE flight_id = 8", use_index=False).rows)
    expected_p = sorted(db.execute("SELECT * FROM reservations WHERE passenger_id = 9", use_index=False).rows)
    db.close()
    db = Database(d, buffer_capacity=4, memtable_limit=50)
    assert "reservations" in db.tables and db.tables["reservations"].kinds == {
        "reservation_id": "bptree", "flight_id": "bptree", "passenger_id": "lsm"}
    res = db.execute("SELECT * FROM reservations WHERE flight_id = 8")
    assert res.used_index == "bptree" and sorted(res.rows) == expected
    assert sorted(db.execute("SELECT * FROM reservations WHERE passenger_id = 9").rows) == expected_p
    assert len(db.execute("SELECT * FROM reservations").rows) == 250
    db.close()


def test_primary_key_is_unique_and_insert_is_all_or_nothing(db):
    db.execute("INSERT INTO reservations VALUES (1, 1, 1, 1, 'confirmed')")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO reservations VALUES (1, 2, 2, 2, 'confirmed')")
    with pytest.raises(SQLError):          # second row is bad, so the first must not be stored
        db.execute("INSERT INTO reservations VALUES (2, 1, 1, 1, 'ok'), (3, 'oops', 1, 1, 'x')")
    with pytest.raises(SQLError):          # duplicate inside one statement
        db.execute("INSERT INTO reservations VALUES (5, 1, 1, 1, 'a'), (5, 1, 1, 1, 'b')")
    assert [r[0] for r in db.execute("SELECT reservation_id FROM reservations").rows] == [1]


def test_type_and_catalog_errors(db):
    for bad in ["SELECT * FROM nope",
                "SELECT nope FROM reservations",
                "SELECT * FROM reservations WHERE nope = 1",
                "SELECT * FROM reservations WHERE flight_id = 'seven'",
                "SELECT * FROM reservations WHERE status = 3",
                "SELECT * FROM reservations ORDER BY nope",
                "INSERT INTO reservations (reservation_id, nope) VALUES (1, 2)",
                "INSERT INTO reservations (status) VALUES ('x')",             # primary key missing
                "INSERT INTO reservations VALUES (1, 2)",                     # wrong value count
                "UPDATE reservations SET reservation_id = 5 WHERE reservation_id = 1",
                "UPDATE reservations SET nope = 5",
                "CREATE TABLE reservations (a INT)",
                "CREATE INDEX ON reservations (nope)",
                "DROP INDEX ON reservations (reservation_id)",                # primary key index
                "DROP INDEX ON reservations (status)"]:
        with pytest.raises(SQLError):
            db.execute(bad)


def test_injection_text_is_stored_as_plain_data(db):
    db.execute("CREATE TABLE passengers (passenger_id INT, name TEXT)")
    evil = "Robert'); DROP TABLE passengers; --"
    db.execute("INSERT INTO passengers VALUES (?, ?)", (1, evil))
    db.execute("INSERT INTO passengers VALUES (2, 'x'' OR ''1''=''1')")
    assert "passengers" in db.tables
    assert db.execute("SELECT name FROM passengers WHERE passenger_id = 1").rows == [(evil,)]
    assert db.execute("SELECT name FROM passengers WHERE name = ?", (evil,)).rows == [(evil,)]
    # a classic always-true payload as a *value* matches nothing
    assert db.execute("SELECT * FROM passengers WHERE name = ?", ("' OR '1'='1",)).rows == []
    assert db.execute("SELECT name FROM passengers WHERE passenger_id = 2").rows == [("x' OR '1'='1",)]
    # payload in the *syntax* position is a syntax error, never executed
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM passengers WHERE passenger_id = 1 OR 1=1")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM passengers WHERE passenger_id = 1; DELETE FROM passengers")
    assert len(db.execute("SELECT * FROM passengers").rows) == 2


def test_auto_index_selection_through_sql(db):
    _load(db, 100)
    msg = db.execute("CREATE INDEX ON reservations (flight_id) USING auto WORKLOAD (900, 90, 10)").message
    assert "lsm" in msg and "write-heavy" in msg
    msg = db.execute("CREATE INDEX ON reservations (passenger_id) USING auto WORKLOAD (50, 850, 100)").message
    assert "bptree" in msg and "read-dominated" in msg
    assert db.tables["reservations"].kinds["flight_id"] == "lsm"
    # explicit choice and observed-workload choice
    assert "chosen explicitly" in db.execute("CREATE INDEX ON reservations (seat_id) USING bptree").message
    with pytest.raises(SQLError):
        db.execute("CREATE INDEX ON reservations (flight_id)")                # already indexed


def test_reindex_follows_observed_workload(db):
    _load(db, 100)
    db.execute("CREATE INDEX ON reservations (seat_id) USING lsm")
    for i in range(1, 400):                                                   # read-dominated workload
        db.execute("SELECT * FROM reservations WHERE seat_id = ?", (i % 100 + 1,))
    assert "rebuilt as bptree" in db.execute("REINDEX ON reservations (seat_id)").message
    assert db.execute("REINDEX ON reservations (seat_id)").message.endswith("kept as bptree")
    assert db.execute("SELECT * FROM reservations WHERE seat_id = 5").rows[0][3] == 5


def test_show_statements_and_result_format(db):
    assert db.execute("SHOW TABLES").rows[0][0] == "reservations"
    assert ("reservation_id", "bptree") == db.execute("SHOW INDEXES ON reservations").rows[0][:2]
    text = db.execute("SHOW TABLES").format()
    assert "reservations" in text and text.startswith("+")


def test_object_store_is_reachable_from_database(tmp_path):
    from aerocore.objects import StreamCipher
    with Database(tmp_path / "db", cipher=StreamCipher("k")) as db:
        db.execute(RES_DDL)
        db.execute("INSERT INTO reservations VALUES (1, 1, 1, 1, 'confirmed')")
        db.objects.put("ticket:1", b"PASSENGER=Jana;SEAT=1A", "text/plain")
    with Database(tmp_path / "db", cipher=StreamCipher("k")) as db:
        assert db.objects.get("ticket:1") == b"PASSENGER=Jana;SEAT=1A"
    assert b"PASSENGER" not in (tmp_path / "db" / "objects.objects").read_bytes()