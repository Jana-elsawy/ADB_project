# AeroCore – A Custom Database Management System for Airline Reservations

**CSAI 302 – Advanced Database Systems | Fall 2026**  
School of Computational Sciences and Artificial Intelligence, Zewail City

## 1. Overview

AeroCore is a custom Database Management System (DBMS) developed from scratch as part of the CSAI 302 Advanced Database Systems project.

The project is implemented incrementally across six milestones:

1. Storage Engine
2. Advanced Indexing
3. Query Processing
4. Transactions and Recovery
5. Distributed Database
6. Full System Integration

AeroCore does not use existing database engines such as SQLite, PostgreSQL, MySQL, or MongoDB. The main DBMS components are designed and implemented by our team.

**Application Domain:** Airline Reservations and Passenger Analytics.

The airline reservation system serves as the application domain used to demonstrate and test the DBMS capabilities. The main focus is building the database engine itself.

### Main Application Features

- Flight booking and seat availability management.
- Passenger and reservation management.
- Prevention of double-booking.
- Payment and reservation processing.
- Route demand and passenger analytics.
- Flight occupancy reports.

## 2. Team Members

| Name | Student ID | Main Contributions |
|---|---|---|
| Jana Mahmoud | 202301597 | Disk Manager and Page Format |
| Farah Ahmed | 202300267 | Buffer Pool and Replacement Policies |
| Soha Essam | 202300335 | Columnar Storage, Testing, and Benchmarks |

*Team responsibilities may be adjusted as development progresses.*

## 3. Project Status

| Milestone | Description | Status |
|---|---|---|
| M1 | Storage Engine | Completed |
| M2 | Advanced Indexing | Completed |
| M3 | Query Processing | Planned |
| M4 | Transactions and Recovery | Planned |
| M5 | Distributed Database | Planned |
| M6 | Full System Integration | Planned |

## 4. Application Domain: AeroCore Airline Reservations

AeroCore uses an airline reservation system as its demonstration application.

### 4.1 Core Database Tables

| Table | Purpose | Main Columns |
|---|---|---|
| Airports | Stores airport information | airport_id, code, city, region |
| Flights | Stores scheduled flights | flight_id, origin_id, dest_id, departure_time, capacity |
| Seats | Stores flight seat information | seat_id, flight_id, seat_number, status |
| Passengers | Stores passenger information | passenger_id, name, passport_ref |
| Reservations | Stores passenger flight bookings | reservation_id, passenger_id, flight_id, seat_id, created_at |
| Payments | Stores reservation payments | payment_id, reservation_id, amount, status |

All passenger and reservation data will be synthetic and generated using a fixed random seed. No real personal or payment information will be used.

### 4.2 Representative Queries

The DBMS will support application scenarios such as:

1. **Seat Availability:** Retrieve all available seats for a specific flight.
2. **Route Demand:** Calculate booking volume by route and date range using joins between reservations, flights, and airports.
3. **Flight Occupancy:** Calculate the occupancy percentage of each flight based on reserved seats and total capacity.
4. **Passenger Search:** Retrieve passenger records using their identifiers.
5. **Reservation History:** Retrieve all reservations associated with a passenger.

### 4.3 Representative Transaction

**Reserve a Seat and Record Payment Atomically**

The system will support a reservation transaction involving three operations:

1. Create a reservation.
2. Update the selected seat status to occupied.
3. Insert the corresponding payment record.

All three operations must succeed together or be rolled back.

Concurrent reservations for the same seat must never both succeed.

### 4.4 Distributed Database Scenario (M5)

Passenger and flight data will be partitioned across multiple nodes using a selected sharding strategy.

The system will support replication and distributed coordination to maintain data consistency and availability.

Cross-node booking operations will demonstrate distributed transaction processing.

### 4.5 Object Storage Scenario (M2)

The system will support storing airline-related objects, such as electronic tickets and passenger manifests, through its object storage functionality.

### 4.6 Vector Search Scenario (M5)

The system will implement exact Top-K similarity search over fixed-dimensional vectors representing travel policies or destination descriptions.

Cosine similarity or Euclidean distance will be used to measure vector similarity.

## 5. System Architecture

The initial M1 architecture consists of four main layers:

```text
              Table API
   (Insert / Get / Scan / Update / Delete)
                    |
                    v
              Layout Layer
          (RowStore | ColumnStore)
                    |
                    v
               Buffer Pool
                (LRU | FIFO)
                    |
                    v
               Disk Manager
              (4 KB Pages)
                    |
                    v
              Database File
```

### Component Responsibilities

**Table API:** Provides the interface for creating tables and performing basic record operations.

**Layout Layer:** Organizes records using row-oriented or column-oriented storage.

**Buffer Pool:** Caches database pages in memory and manages page replacement when the buffer becomes full.

**Replacement Policies:** Determine which page should be removed from the buffer pool. The current implementation supports FIFO and LRU.

**Disk Manager:** Handles reading and writing fixed-size pages to persistent database files and tracks physical I/O operations.

## 6. Milestone 1 – Storage Engine Foundation

The first milestone focuses on implementing the storage foundation of AeroCore.

### 6.1 Implemented Features

- Persistent 4 KB database pages.
- Slotted-page structure for row-oriented records.
- Disk Manager for page allocation and disk I/O.
- Buffer Pool with configurable capacity.
- LRU and FIFO page replacement policies.
- Page pinning and unpinning.
- Dirty-page tracking and flushing.
- Row-oriented storage.
- Column-oriented storage.
- Buffer Pool performance statistics.
- Unit testing and performance benchmarks.

### 6.2 Storage Format

**Database File**

The database file stores fixed-size pages and supports persistent page operations.

**Page Structure**

The initial row-oriented storage design uses slotted pages:

- Page header stores page metadata.
- Slot directory stores record locations.
- Record data is stored from the end of the page.
- Free space is maintained between the slot directory and record data.

**Record Identifier**

Each stored record is identified using:

`(page_id, slot_id)`

**Record Serialization**

Records are serialized into bytes using JSON encoding and stored as bytes in slotted pages.

### 6.3 Row-Oriented Storage

Records are stored one row at a time.

This layout is suitable for retrieving complete records, such as retrieving all information associated with a passenger.

### 6.4 Column-Oriented Storage

Values belonging to the same column are stored together.

This layout is suitable for analytical operations, such as calculating average passenger age or analyzing flight occupancy.

### 6.5 Buffer Pool

The Buffer Pool temporarily stores database pages in RAM to reduce disk access.

The implementation supports:

- Configurable buffer capacity.
- Page loading and eviction.
- Cache hit and miss tracking.
- Dirty-page management.
- Page pinning and unpinning.
- LRU and FIFO replacement policies.
- Flushing dirty pages to disk.

### 6.6 Performance Metrics

The following metrics are collected:

- Cache hits.
- Cache misses.
- Hit ratio.
- Page reads.
- Page writes.
- Page evictions.
- Execution time.

### 6.7 Design Decisions

| Component | Design |
|---|---|
| Page Size | 4 KB |
| Row Storage | Slotted Pages |
| Record Identification | Page ID and Slot ID |
| Replacement Policies | FIFO and LRU |
| Persistence | Database Files |
| Data Source | Synthetic Airline Data |

## 7. Technology Stack

The initial implementation uses:

- **Python 3:** Main programming language.
- **NumPy:** Numerical operations and benchmark support.
- **Matplotlib:** Benchmark visualization.
- **Pytest:** Unit testing and correctness validation.

Additional libraries may be introduced when required by later milestones.

The team maintains the dependencies in `requirements.txt`.

## 8. Repository Structure

```text
ADB_project/
│
├── aerocore/
│   ├── __init__.py
│   ├── schemas.py
│   ├── demo.py
│   ├── demo_m2.py              # M2 end-to-end demo
│   ├── cli.py                  # M2 SQL shell
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── page.py
│   │   ├── disk.py
│   │   ├── policies.py
│   │   ├── buffer_pool.py
│   │   ├── row_store.py
│   │   └── column_store.py
│   │
│   ├── index/                  # M2
│   │   ├── __init__.py
│   │   ├── schema.py
│   │   ├── bptree.py
│   │   ├── lsm.py
│   │   ├── selector.py
│   │   └── indexed_table.py
│   │
│   ├── objects/                # M2
│   │   ├── __init__.py
│   │   ├── encryption.py
│   │   └── store.py
│   │
│   └── sql/                    # M2
│       ├── __init__.py
│       ├── parser.py
│       ├── engine.py
│       └── airline.py
│
├── benchmarks/
│   ├── __init__.py
│   ├── bench_policies.py
│   ├── bench_layout.py
│   ├── plot.py
│   ├── run_all.py
│   ├── common.py               # M2
│   ├── bench_index.py          # M2
│   ├── plot_m2.py              # M2
│   └── run_m2.py               # M2
│
├── data/
│   ├── generate_data.py
│   └── generate_airline.py     # M2
│
├── tests/
│   ├── test_storage.py
│   ├── test_bptree.py          # M2
│   ├── test_lsm.py             # M2
│   ├── test_indexed_table.py   # M2
│   ├── test_objects.py         # M2
│   ├── test_sql.py             # M2
│   └── test_cli.py             # M2
│
├── docs/
│   └── m2_notes.md             # M2 design, results and limitations
│
├── results/
│   ├── m1/
│   │   ├── layout_results.csv
│   │   ├── layout_comparison.png
│   │   ├── policy_results.csv
│   │   └── policy_comparison.png
│   └── m2/                     # CSV results, charts, environment.json
│
├── README.md
├── requirements.txt
└── .gitignore
```

Generated database files and generated datasets are excluded from Git.

## 9. Getting Started

### 9.1 Prerequisites

- Python 3.x.
- Git.
- pip.

### 9.2 Clone the Repository

```bash
git clone https://github.com/Jana-elsawy/ADB_project.git

cd ADB_project
```

### 9.3 Create a Virtual Environment

```powershell
python -m venv .venv
```

Activate it:

**Windows PowerShell:**

```powershell
.venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
source .venv/bin/activate
```

### 9.4 Install Dependencies

```bash
pip install -r requirements.txt
```

## 10. Running the Project

### Run the Storage Demo

```bash
python -m aerocore.demo
```

### Generate Synthetic Airline Data

```bash
python data/generate_data.py --rows 100000 --seed 42
```

The generated dataset is saved under `data/`.

### Run Unit Tests

```bash
python -m pytest -v
```

### Run Individual Policy Benchmarks

```bash
python -m benchmarks.bench_policies
```

### Run All Benchmarks

```bash
python -m benchmarks.run_all --runs 5 --seed 42
```

Benchmark results and plots are saved under:

```text
results/m1/
```

### Run the M2 Index Benchmarks

```bash
python -m benchmarks.run_m2 --runs 5 --seed 42
```

This takes a few minutes and writes CSV files, charts and `environment.json` to:

```text
results/m2/
```

Use `--quick` for a short smoke test.

### Run the M2 Demo and the SQL Shell

```bash
python -m aerocore.demo_m2
python -m aerocore.cli
python -m aerocore.cli -c "CREATE TABLE t (id INT, name TEXT); INSERT INTO t VALUES (1, 'a'); SELECT * FROM t WHERE id = 1"
```

The shell stores its database in `data/aerocore_db` (change it with `--db`). Type `.help` for the dot commands (`.init-airline`, `.load`, `.timing`, `.plan`).

## 11. M1 Benchmarks and Evaluation

The storage engine is evaluated through repeatable experiments.

### 11.1 Buffer Pool Benchmark

Compare FIFO and LRU using the same page access workload.

Metrics:

- Cache hit ratio.
- Cache misses.
- Page reads and writes.
- Number of evictions.
- Execution time.

### 11.2 Storage Layout Benchmark

Compare row-oriented and column-oriented storage using representative workloads.

Examples:

- Retrieving complete passenger records.
- Calculating aggregate values from selected columns.

### 11.3 Experimental Methodology

The benchmark configuration uses:

- A fixed random seed of 42.
- One warm-up run.
- Five measured runs.
- Mean and standard deviation for timing measurements.
- Consistent workload and experimental settings.

### 11.4 Generated Results

Both benchmark experiments completed successfully.

The following result files were generated:

| File | Description |
|---|---|
| `policy_results.csv` | FIFO and LRU benchmark measurements |
| `policy_comparison.png` | FIFO and LRU performance comparison |
| `layout_results.csv` | Row and Column storage measurements |
| `layout_comparison.png` | Row and Column performance comparison |

All generated benchmark results are located in `results/m1/`.

### 11.5 Unit Testing Results

The M1 storage implementation was tested using Pytest.

**Final test result: 9 passed.**

The tests cover:

| Test | Description |
|---|---|
| Page Insert and Serialization | Checks page insertion and serialization roundtrip |
| Disk Persistence | Checks that data persists after reopening the database |
| LRU Eviction | Checks the LRU replacement policy |
| Row Store | Checks row-oriented record storage |
| Column Store | Checks column-oriented record storage |
| Page Delete and Slot Reuse | Checks deletion and reuse of available slots |
| FIFO Eviction | Checks the FIFO replacement policy |
| Pinned Page Protection | Checks that pinned pages cannot be evicted |
| Dirty Page Flushing | Checks that modified pages are flushed correctly |

## 12. Milestone 2 – Advanced Indexing

M2 adds indexing and object storage on top of the M1 storage engine. Every index is its own page file built with the M1 `DiskManager` and `BufferPool`. The full design, results and limitations are in [`docs/m2_notes.md`](docs/m2_notes.md).

### 12.1 Implemented Features

- **B+ Tree** index (`aerocore/index/bptree.py`): equality and range lookup, duplicate keys, delete, persistence across restarts, integer, string and float keys.
- **LSM Tree** index (`aerocore/index/lsm.py`): memtable, immutable sorted runs, delete markers, compaction, same interface as the B+ Tree.
- **Workload-based index selection** (`aerocore/index/selector.py`): writes of 25% or more of the operations select the LSM Tree, otherwise the B+ Tree. `IndexedTable.create_index(col, "auto")` applies the rule.
- **IndexedTable** (`aerocore/index/indexed_table.py`): a `RowStore` whose indexes are kept in sync on insert, update and delete, with indexed `find` and `find_range`.
- **SQL-like query layer** (`aerocore/sql/`): tokenizer, parser and execution engine for `CREATE TABLE`, `CREATE/DROP INDEX`, `INSERT`, `SELECT ... WHERE ... ORDER BY ... LIMIT`, `UPDATE`, `DELETE`, `EXPLAIN` and `SHOW`. Equality and range conditions on indexed columns use the B+ Tree or LSM Tree; everything else is a full scan. Parameterised (`?`) and injection-safe. See section 12.5.
- **Command-line client** (`aerocore/cli.py`) and an end-to-end **demo** (`aerocore/demo_m2.py`).
- **Object storage** (`aerocore/objects/store.py`): tickets and manifests stored as chunked objects in M1 pages, with an object catalog kept in a B+ Tree.
- **Encryption hook** (`aerocore/objects/encryption.py`): pluggable `Cipher` interface with a demonstration stream cipher.
- Typed schemas for the six tables (`aerocore/index/schema.py`) and a generator for all six tables (`data/generate_airline.py`).

Small additive changes to M1: `BufferPool.new_page()`, `RowStore.scan_with_rids()`, `RowStore.update()` returns the new record ID, and `RowStore.insert()` tries the newest page first.

### 12.2 Test Results

Final test result: **76 passed** (9 M1 tests and 67 M2 tests covering the B+ Tree, LSM Tree, IndexedTable, object storage, the SQL parser and engine, and the command-line client).

### 12.3 Benchmark Summary

Measured with 1 warm-up run and 5 measured runs, seed 42 (machine details in `results/m2/environment.json`).

| Experiment (20,000 keys or rows) | B+ Tree | LSM Tree |
|---|---:|---:|
| Insert throughput | 2,626 ops/s | 21,973 ops/s |
| Page writes per insert | 0.112 | 0.012 |
| Point lookup, median | 0.136 ms | 0.209 ms |
| 1% range scan, median | 0.261 ms | 0.389 ms |
| Build index over 20,000 rows | 6.66 s | 0.88 s |
| Index size | 508 KB | 380 KB |

An indexed lookup on a unique key took 0.32 ms (B+ Tree) compared with 111 ms for a full scan of the 550-page table. The LSM Tree is better for write-heavy workloads and the B+ Tree for read-dominated ones; the 10–30% write range is a near tie and the winner changed between runs (see `docs/m2_notes.md`, section 4.5).

### 12.4 M2 Limitations

- B+ Tree deletes are lazy (nodes are not merged) and nodes are JSON encoded.
- The LSM Tree has no Bloom filters and no write-ahead log: entries still in the memtable are lost on a crash until the WAL is added in M4.
- The SQL layer has no `OR`, joins, aggregates or sub-queries (joins and the optimizer are M3), indexes cover one column, and the access path is a fixed rule, not a cost-based choice.
- Statements are validated before they run, but they are not transactional: a crash in the middle of an `UPDATE` can leave some rows changed (transactions and recovery are M4).
- The demonstration cipher is not production security.
- Object size is limited to 1 MB.

### 12.5 SQL-Like Interface

```sql
CREATE TABLE reservations (reservation_id INT, passenger_id INT, flight_id INT,
                           seat_id INT, status TEXT, PRIMARY KEY (reservation_id));
INSERT INTO reservations VALUES (1, 10, 7, 1, 'confirmed'), (2, 11, 7, 2, 'cancelled');
CREATE INDEX ON reservations (flight_id) USING auto WORKLOAD (10, 85, 5);   -- rule picks B+ Tree
CREATE INDEX ON reservations (passenger_id) USING lsm;
SELECT reservation_id, status FROM reservations
  WHERE flight_id = 7 AND status = 'confirmed' ORDER BY reservation_id DESC LIMIT 10;
SELECT * FROM reservations WHERE flight_id BETWEEN 3 AND 6;
EXPLAIN SELECT * FROM reservations WHERE flight_id = 7;
UPDATE reservations SET status = 'cancelled' WHERE reservation_id = 2;
DELETE FROM reservations WHERE flight_id = 7;
REINDEX ON reservations (flight_id);       -- re-apply the workload rule to the observed workload
SHOW TABLES;  SHOW INDEXES ON reservations;
```

Types are `INT`, `TEXT` and `FLOAT`. Conditions are joined with `AND` and use `=`, `!=`, `<`, `<=`, `>`, `>=` or `BETWEEN`. The primary key is indexed automatically with a B+ Tree and is unique.

**Access path.** An equality condition on an indexed column uses an index lookup, a range condition on an indexed column uses an index range scan, and anything else is a full scan. All conditions are re-checked on every fetched row. `EXPLAIN` prints the chosen path. Running `Database.execute(sql, use_index=False)` forces a scan; the tests require both to return identical rows.

**No injection.** SQL text is split by a fixed tokenizer that accepts only numbers, quoted strings, identifiers, comparison operators and `( ) , * ? ;`. Values are passed separately with `?` placeholders, for example `db.execute("SELECT * FROM passengers WHERE name = ?", (name,))`, so a value can never become part of the statement. Only one statement per call is accepted (stacked statements, comments and `OR 1=1` are syntax errors). Table and column names are checked against the catalog.

**Object storage link.** `db.objects` is an `ObjectStore` in the same directory (with the optional cipher), used by the demo to keep an encrypted e-ticket for a reservation.

## 13. Known Limitations

The current M1 implementation provides the storage foundation but does not yet implement all features of a complete DBMS.

Current limitations include:

- Limited supported data types.
- Basic record serialization.
- ColumnStore page mapping is currently maintained in memory.
- No advanced free-space compaction.
- No advanced query processing yet.
- No transaction processing or recovery yet.
- No distributed database functionality yet.

These features will be addressed in later milestones where applicable.

## 14. External Libraries

The project dependencies are maintained in `requirements.txt`.

The main libraries include:

- NumPy.
- Matplotlib.
- Pytest.

The custom database engine itself is implemented by the team rather than delegated to an existing database engine.

## 15. Team Contribution Guidelines

To maintain organized development:

1. Create a separate feature branch for each task.
2. Use descriptive commit messages.
3. Test changes before pushing.
4. Open a pull request for review.
5. Have another team member review changes before merging into `main`.

**Branch naming:**

```text
feature/<task-name>
```

**Commit message examples:**

```text
storage: implement slotted page insertion

buffer: add LRU replacement policy

storage: add column-oriented layout

tests: add persistence tests

benchmarks: add storage performance evaluation
```

Avoid committing generated database files, virtual environments, temporary files, or large generated datasets.

---

**Project:** AeroCore – A Custom Database Management System for Airline Reservations

**Course:** CSAI 302 – Advanced Database Systems

**Institution:** Zewail City, School of Computational Sciences and Artificial Intelligence