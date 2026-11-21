import random
from aerocore.index.bptree import BPlusTree
from aerocore.index.lsm import LSMTree


def _small(tmp_path, **kw):
    kw.setdefault("memtable_limit", 50)
    kw.setdefault("max_runs", 3)
    return LSMTree(tmp_path / "lsm", name="t", **kw)


def test_insert_search_range_match_reference(tmp_path):
    tree = _small(tmp_path)
    keys = list(range(1, 2001))
    random.Random(42).shuffle(keys)
    ref = {}
    for k in keys:
        tree.insert(k, (k // 10, k % 10))
        ref[k] = (k // 10, k % 10)
    assert tree.flushes > 5 and tree.compactions >= 1      # flush and compaction really happened
    for k in random.Random(1).sample(keys, 200):
        assert tree.search(k) == [ref[k]]
    assert tree.search(99999) == []
    assert tree.range(300, 450) == [(k, ref[k]) for k in range(300, 451)]
    assert [k for k, _ in tree.range()] == list(range(1, 2001))
    tree.close()


def test_delete_marker_overrides_older_insert(tmp_path):
    tree = _small(tmp_path)
    for k in range(1, 301):
        tree.insert(k, (k, 0))
    tree.flush_memtable()                                   # inserts now sit in older runs
    for k in range(1, 301, 2):
        tree.delete(k, (k, 0))                              # markers in newer components
    assert tree.search(1) == [] and tree.search(2) == [(2, 0)]
    assert [k for k, _ in tree.range()] == list(range(2, 301, 2))
    tree.compact()
    assert len(tree.runs) == 1 and tree.runs[0].count == 150  # markers dropped by compaction
    assert [k for k, _ in tree.range()] == list(range(2, 301, 2))
    tree.close()


def test_update_as_delete_plus_insert(tmp_path):
    tree = _small(tmp_path)
    tree.insert(7, (1, 1)); tree.flush_memtable()
    tree.delete(7, (1, 1)); tree.insert(7, (9, 9))          # record moved to a new RID
    assert tree.search(7) == [(9, 9)]
    tree.insert(7, (1, 1))                                  # re-insert after delete wins
    assert sorted(tree.search(7)) == [(1, 1), (9, 9)]
    tree.close()


def test_duplicate_keys(tmp_path):
    tree = _small(tmp_path)
    for i in range(300):
        tree.insert(5, (i, 0))
    assert sorted(tree.search(5)) == [(i, 0) for i in range(300)]
    tree.close()


def test_persistence_after_reopen(tmp_path):
    tree = _small(tmp_path)
    for k in range(1, 1001):
        tree.insert(k, (k, 1))
    tree.close()                                            # close flushes the memtable
    tree = _small(tmp_path)
    assert tree.search(777) == [(777, 1)]
    assert [k for k, _ in tree.range(10, 20)] == list(range(10, 21))
    assert len(tree) == 1000
    tree.insert(5000, (1, 1))
    tree.close()
    tree = _small(tmp_path)
    assert tree.search(5000) == [(1, 1)]
    tree.close()


def test_string_keys(tmp_path):
    tree = _small(tmp_path, key_type="str")
    dates = [f"2026-12-{d:02d}T{h:02d}:00" for d in range(1, 29) for h in range(0, 24, 3)]
    random.Random(3).shuffle(dates)
    for i, d in enumerate(dates):
        tree.insert(d, (i, 0))
    got = [k for k, _ in tree.range("2026-12-10T00:00", "2026-12-12T23:59")]
    assert got == sorted(d for d in dates if "2026-12-10T00:00" <= d <= "2026-12-12T23:59")
    try:
        tree.insert(5, (0, 0)); assert False
    except TypeError:
        pass
    tree.close()


def test_lsm_and_bptree_agree_on_random_workload(tmp_path):
    rng = random.Random(42)
    lsm = _small(tmp_path)
    bpt = BPlusTree(tmp_path / "b.idx", max_node_bytes=300)
    live = set()
    for _ in range(3000):
        k, rid = rng.randint(1, 200), (rng.randint(0, 50), rng.randint(0, 5))
        if live and rng.random() < 0.3:
            k, rid = rng.choice(sorted(live))
            lsm.delete(k, rid); bpt.delete(k, rid); live.discard((k, rid))
        else:
            lsm.insert(k, rid); bpt.insert(k, rid); live.add((k, rid))
    assert lsm.range() == bpt.range() == sorted((k, rid) for k, rid in live)
    for k in range(1, 201, 7):
        assert sorted(lsm.search(k)) == sorted(bpt.search(k))
    lsm.close(); bpt.close()


def test_flush_and_compaction_page_writes_are_counted(tmp_path):
    tree = _small(tmp_path, memtable_limit=20, max_runs=2)
    assert tree.stats()["disk_writes"] == 0
    for k in range(1, 201):
        tree.insert(k, (k, 0))
    assert tree.flushes > 0 and tree.compactions > 0
    writes = tree.stats()["disk_writes"]
    assert writes > 0                                   # run files were written through the pool
    tree.reset_stats()
    assert tree.stats()["disk_writes"] == 0
    tree.close()