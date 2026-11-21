"""M2 experiments: B+ Tree vs LSM Tree, indexed lookup vs full scan, workload mixes."""
import random
import time
from collections import Counter

from aerocore.index import BPlusTree, LSMTree, IndexedTable, TABLE_SCHEMAS, choose_index
from data.generate_airline import generate
from .common import repeat, summarize, tmpdir

BPT_CAPACITY, LSM_CAPACITY, MEMTABLE, MAX_RUNS = 64, 16, 2000, 4
KINDS = ("bptree", "lsm")


def make_index(kind, d, name="i"):
    if kind == "bptree":
        return BPlusTree(d / f"{name}.idx", capacity=BPT_CAPACITY)
    return LSMTree(d / f"{name}_lsm", name, memtable_limit=MEMTABLE, max_runs=MAX_RUNS, capacity=LSM_CAPACITY)


def io(idx):
    s = idx.pool.stats if isinstance(idx, BPlusTree) else idx.stats()
    return s["disk_reads"], s["disk_writes"]


def persist(idx):
    idx.flush() if isinstance(idx, BPlusTree) else idx.flush_memtable()


def rid_of(k):
    return (k // 50, k % 50)


def shuffled(n, seed):
    keys = list(range(1, n + 1))
    random.Random(seed).shuffle(keys)
    return keys


def build(kind, d, n, seed):
    idx = make_index(kind, d)
    for k in shuffled(n, seed):
        idx.insert(k, rid_of(k))
    persist(idx)
    return idx


# ---------------- E1: insertion ----------------
def exp_insert(sizes, runs, seed):
    rows = []
    for n in sizes:
        for kind in KINDS:
            def one():
                with tmpdir() as d:
                    idx = make_index(kind, d)
                    keys, lat = shuffled(n, seed), []
                    t0 = time.perf_counter()
                    for k in keys:
                        t = time.perf_counter()
                        idx.insert(k, rid_of(k))
                        lat.append(time.perf_counter() - t)
                    persist(idx)
                    elapsed = time.perf_counter() - t0
                    r, w = io(idx)
                    probe = random.Random(seed).sample(keys, min(100, n))
                    ok = all(idx.search(k) == [rid_of(k)] for k in probe)
                    res = {"elapsed": elapsed, "lat": lat, "reads": r, "writes": w, "size": idx.size_bytes(), "ok": ok}
                    idx.close()
                    return res
            rows.append({"experiment": "insert", "structure": kind, "n": n, **summarize(repeat(one, runs), n)})
            print(f"  insert {kind} n={n}: {rows[-1]['ops_per_sec']} ops/s")
    return rows


# ---------------- E2/E3: point lookups and range scans ----------------
def exp_lookup_range(sizes, runs, seed):
    look, rng_rows = [], []
    for n in sizes:
        for kind in KINDS:
            with tmpdir() as d:
                idx = build(kind, d, n, seed)
                q = min(2000, n)
                keys = random.Random(seed + 1).sample(range(1, n + 1), q)

                def point():
                    idx.reset_stats()
                    lat, ok = [], True
                    t0 = time.perf_counter()
                    for k in keys:
                        t = time.perf_counter()
                        res = idx.search(k)
                        lat.append(time.perf_counter() - t)
                        ok &= res == [rid_of(k)]
                    el = time.perf_counter() - t0
                    return {"elapsed": el, "lat": lat, "reads": io(idx)[0], "size": idx.size_bytes(), "ok": ok}
                look.append({"experiment": "point_lookup", "structure": kind, "n": n, **summarize(repeat(point, runs), q)})

                width, nq = max(1, n // 100), 50
                starts = [random.Random(seed + 2).randint(1, n - width + 1) for _ in range(nq)]
                starts = [random.Random(seed + i).randint(1, n - width + 1) for i in range(nq)]

                def ranged():
                    idx.reset_stats()
                    lat, ok = [], True
                    t0 = time.perf_counter()
                    for lo in starts:
                        t = time.perf_counter()
                        res = idx.range(lo, lo + width - 1)
                        lat.append(time.perf_counter() - t)
                        ok &= [k for k, _ in res] == list(range(lo, lo + width))
                    el = time.perf_counter() - t0
                    return {"elapsed": el, "lat": lat, "reads": io(idx)[0], "size": idx.size_bytes(), "ok": ok}
                rng_rows.append({"experiment": f"range_1pct", "structure": kind, "n": n, **summarize(repeat(ranged, runs), nq)})
                idx.close()
            print(f"  lookup/range {kind} n={n}: {look[-1]['median_ms']} ms median lookup")
    return look, rng_rows


# ---------------- E4: indexed lookup vs full scan ----------------
def exp_scan_vs_index(n, runs, seed):
    rows_data = generate("reservations", n, seed)
    flight_counts = Counter(r["flight_id"] for r in rows_data)
    out = []
    with tmpdir() as d:
        t = IndexedTable("reservations", d, TABLE_SCHEMAS["reservations"], buffer_capacity=16)
        for r in rows_data:
            t.insert(r)
        t.pool.flush_all()
        rng = random.Random(seed + 3)
        queries = {"reservation_id": [rng.randint(1, n) for _ in range(100)],
                   "flight_id": [rng.choice(sorted(flight_counts)) for _ in range(100)]}
        for col, vals in queries.items():
            def expect_ok(res, v):
                return (len(res) == 1 and res[0]["reservation_id"] == v) if col == "reservation_id" \
                    else len(res) == flight_counts[v]

            def via_scan():
                t.reset_stats()
                lat, ok = [], True
                t0 = time.perf_counter()
                for v in vals[:8]:
                    s = time.perf_counter()
                    res = t.scan_filter(col, v, v)
                    lat.append(time.perf_counter() - s)
                    ok &= expect_ok(res, v)
                return {"elapsed": time.perf_counter() - t0, "lat": lat, "reads": t.table_stats()["disk_reads"], "ok": ok}
            out.append({"experiment": f"{col}_equality", "structure": "full_scan", "n": n, **summarize(repeat(via_scan, runs), 8)})
            for kind in KINDS:
                idx = make_index(kind, d, name=f"{col}_{kind}")
                for rid, rec in t.store.scan_with_rids():
                    idx.insert(rec[col], rid)
                persist(idx)

                def via_index(idx=idx):
                    t.reset_stats()
                    idx.reset_stats()
                    lat, ok = [], True
                    t0 = time.perf_counter()
                    for v in vals:
                        s = time.perf_counter()
                        res = [t.get(rid) for rid in idx.search(v)]
                        lat.append(time.perf_counter() - s)
                        ok &= expect_ok(res, v)
                    return {"elapsed": time.perf_counter() - t0, "lat": lat, "size": idx.size_bytes(),
                            "reads": t.table_stats()["disk_reads"] + io(idx)[0], "ok": ok}
                out.append({"experiment": f"{col}_equality", "structure": kind + "_index", "n": n,
                            **summarize(repeat(via_index, runs), len(vals))})
                idx.close()
            print(f"  scan vs index on {col}: done")
        t.close()
    return out


# ---------------- E5: workload mixes ----------------
WORKLOADS = {  # name: (write %, point-read %, range-read %)
    "read_heavy": (10, 85, 5),
    "mixed_20pct_writes": (20, 75, 5),
    "mixed_30pct_writes": (30, 65, 5),
    "write_heavy": (90, 8, 2),
    "write_heavy_range": (70, 5, 25),
}


def exp_workloads(n, ops, runs, seed):
    rows = []
    for wname, (w, p, r_) in WORKLOADS.items():
        stats = {}
        for kind in KINDS:
            with tmpdir() as d:
                idx = build(kind, d, n, seed)
                state = {"next": n + 1, "pass": 0}

                def one():
                    rng = random.Random(seed + 100 + state["pass"])
                    state["pass"] += 1
                    idx.reset_stats()
                    t0 = time.perf_counter()
                    for _ in range(ops):
                        x = rng.random() * 100
                        if x < w:
                            k = state["next"]
                            state["next"] += 1
                            idx.insert(k, rid_of(k))
                        elif x < w + p:
                            idx.search(rng.randint(1, state["next"] - 1))
                        else:
                            lo = rng.randint(1, max(1, state["next"] - 60))
                            idx.range(lo, lo + 49)
                    el = time.perf_counter() - t0
                    ok = idx.search(state["next"] - 1) in ([rid_of(state["next"] - 1)], [])
                    return {"elapsed": el, "reads": io(idx)[0], "writes": io(idx)[1], "size": idx.size_bytes(), "ok": ok}
                stats[kind] = summarize(repeat(one, runs), ops)
                idx.close()
        winner = max(KINDS, key=lambda k: stats[k]["ops_per_sec"])
        rule, reason = choose_index(w, p, r_)
        for kind in KINDS:
            rows.append({"experiment": wname, "structure": kind, "n": n,
                         "mix_write_point_range": f"{w}/{p}/{r_}", **stats[kind],
                         "faster": winner, "rule_choice": rule, "rule_matches_faster": rule == winner})
        print(f"  workload {wname}: faster={winner}, rule={rule}")
    return rows


# ---------------- E6: building an index over existing rows ----------------
def exp_build(n, runs, seed):
    rows = []
    with tmpdir() as d:
        t = IndexedTable("reservations", d, TABLE_SCHEMAS["reservations"], buffer_capacity=16)
        for r in generate("reservations", n, seed):
            t.insert(r)
        t.pool.flush_all()
        for kind in KINDS:
            def one():
                t.reset_stats()
                t0 = time.perf_counter()
                t.create_index("reservation_id", kind)
                persist(t.indexes["reservation_id"])
                el = time.perf_counter() - t0
                idx = t.indexes["reservation_id"]
                res = {"elapsed": el, "size": idx.size_bytes(), "reads": t.table_stats()["disk_reads"],
                       "writes": io(idx)[1], "ok": len(idx.range()) == n}
                t.drop_index("reservation_id")
                return res
            rows.append({"experiment": "build_index", "structure": kind, "n": n, **summarize(repeat(one, runs), n)})
            print(f"  build {kind}: {rows[-1]['mean_s']} s")
        t.close()
    return rows