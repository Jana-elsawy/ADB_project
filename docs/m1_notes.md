# AeroCore – Milestone 1: Storage Engine Foundation

CSAI 302 – Advanced Database Systems, Fall 2026

## 1. Scope (mapped to the M1 rubric)

| Rubric criterion | What was built | Code |
|---|---|---|
| Custom persistent storage (5) | 4 KB slotted pages in one database file; page allocation, read, write; data survives restart | `aerocore/storage/page.py`, `disk.py`, `row_store.py` |
| Buffer pool (3) | Fixed-capacity pool, pin/unpin, dirty flags, flush, hit/miss/eviction/I-O statistics, pluggable LRU and FIFO policies | `aerocore/storage/buffer_pool.py`, `policies.py` |
| Storage layouts (3) | Row-oriented `RowStore` and column-oriented `ColumnStore` on the same pages | `row_store.py`, `column_store.py` |
| Testing and measurements (4) | 17 pytest tests for M1; policy and layout benchmarks with 1 warm-up and 5 measured runs | `tests/test_storage.py`, `tests/test_storage_extra.py`, `benchmarks/` |

## 2. Design

### 2.1 Disk manager
One file per database. The file is an array of 4096-byte pages; page `i` starts at byte `i * 4096` and the page count is derived from the file size. Every page starts with a 4-byte magic number (`ACPG`) so a wrong file is detected. `close()` flushes and calls `fsync`.

### 2.2 Slotted page
```
+------------------------------+----------------------+------------- free -------------+-----------+
| header: magic,page_id,        | slot directory:      |                                | records   |
| slot_count,free_start,free_end| (offset,length) x n  |                                | <- grow   |
+------------------------------+----------------------+--------------------------------+-----------+
```
A record id is `(page_id, slot_id)` and stays valid when other records are deleted. A deleted slot has length 0 and is reused by the next insert. Deleting compacts the page so free space stays contiguous.

### 2.3 Record format
Records are dictionaries serialised as compact UTF-8 JSON. JSON was chosen for simplicity and readability (any field can be added without a schema); the cost is larger records and slower decoding than a binary format. Typed binary encoding is a possible later improvement.

### 2.4 Buffer pool
`fetch_page` returns a pinned page; callers must `unpin_page(page_id, dirty)`. When the pool is full an unpinned victim is chosen by the policy, written back if dirty, and removed. If every frame is pinned a `RuntimeError` is raised. Fetching a page id that does not exist fails before anything is evicted.

| Policy | Rule |
|---|---|
| LRU | A hit moves the page to the most-recent position; the least recently used unpinned page is evicted |
| FIFO | A hit does not change the order; the oldest loaded unpinned page is evicted |

### 2.5 Row store
Whole records live in slotted pages. The newest page is tried first on insert; older pages are only searched after a delete has freed space. `insert`, `get`, `update`, `delete`, `scan` and `scan_with_rids` are supported. Existing files are re-opened by scanning their pages.

### 2.6 Column store
Each column has its own chain of pages. Slot 0 of every column page is a header record `{"c": column, "s": sequence}`; slots 1.. hold one value per row in row order. Two rules keep it correct:

1. **Append only to the newest page of a column**, so row *i* is value *i* in every column even when values have different lengths.
2. **The header record lets the page chains be rebuilt on open**, so the column store survives a restart.

Supported operations: `insert`, `get(row_id)`, `get_column(name)`, `scan()`. The store is append-only (no update/delete). Reading one column touches only that column's pages; rebuilding one full row touches one page per column.

## 3. Evaluation method

* Command: `python -m benchmarks.run_all --runs 5 --seed 42 --rows 10000`
* 1 warm-up run (discarded) followed by 5 measured runs; mean and standard deviation are reported.
* Dataset: 10,000 synthetic passenger records (`data/generate_data.py`, seed 42), 312 pages in the row store.
* Every measured run starts with a cold buffer pool over the same file; statistics are reset per run.
* Machine, OS, Python version and settings are written to `results/m1/environment.json`.
* Correctness: the layout benchmark asserts that both layouts return identical answers for every read operation.

Files: `results/m1/policy_results.csv`, `layout_results.csv`, `environment.json`, `policy_hit_ratio.png`, `policy_disk_reads.png`, `layout_comparison.png`.

## 4. Results

Hit ratios and page-read counts are deterministic for a given seed; timings depend on the machine (see the CSV files).

### 4.1 Replacement policies (10,000 records, 312 pages)

| Workload | Pool size | LRU hit ratio | FIFO hit ratio | LRU page reads | FIFO page reads |
|---|---|---:|---:|---:|---:|
| Sequential (3 scans) | any (10–50%) | 0.000 | 0.000 | 936 | 936 |
| Uniform random | 25% (78 pages) | 0.245 | 0.244 | 7,550 | 7,562 |
| Skewed random | 10% (31 pages) | 0.435 | 0.385 | 5,648 | 6,155 |
| Skewed random | 25% (78 pages) | 0.631 | 0.578 | 3,692 | 4,225 |
| Skewed random | 50% (156 pages) | 0.800 | 0.757 | 1,997 | 2,434 |

Interpretation:

* **Skewed access:** LRU is better because hot pages are re-used and LRU keeps them, while FIFO evicts a hot page once it is the oldest. The gap is 4–5 percentage points of hit ratio.
* **Uniform access:** with no locality neither policy can predict re-use, so they are equal within noise; the hit ratio is roughly the pool size as a fraction of the table.
* **Sequential scans larger than the pool:** both policies get 0% hits (the classic sequential-flooding behaviour), because each page is evicted before the next scan needs it.

### 4.2 Row vs column layout (10,000 records)

Row and column layouts are compared on insert, `avg(age)` (one column), full scan and 1,000 random full-record lookups. Both layouts must return identical answers (checked by the benchmark).

| Operation | Row (ms) | Column (ms) | Row page reads | Column page reads |
|---|---:|---:|---:|---:|
| `avg(age)` (one column) | 135.5 | 78.1 | 312 | 15 |
| Full scan (all fields) | 148.5 | 404.7 | 312 | 194 |
| 1,000 random full-record lookups | 216.2 | 2580.9 | 950 | 4,463 |

The column layout reads far fewer pages for a single-column query, but the time saving is smaller because JSON decoding dominates in Python. Rebuilding whole records from five column chains is much slower than reading a row, which is the expected trade-off.

## 5. Tests

17 pytest tests cover the M1 code (page round trip, delete and slot reuse, disk persistence, LRU/FIFO eviction order, pinned-page protection, dirty-page write-back, buffer statistics, unknown-page handling, row store restart/delete/update, column store alignment with variable-length values, column store restart, bad-input rejection). With the 27 M2 tests the suite has 44 tests: `python -m pytest -v`.

## 6. Limitations

* Records and column values are JSON-encoded, not a typed binary format.
* The column store is append-only and its values are limited to 3000 bytes each.
* The catalog (table names and schemas) is not stored in the database file; a table is one file opened by the code that knows its columns.
* One table per file; single-threaded; no write-ahead log (planned for M4), so a crash during a write can leave a page partly written.
* Deleting a record compacts the whole page, which is simple but not the fastest design.