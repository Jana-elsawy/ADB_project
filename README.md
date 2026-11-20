# AeroCore – A Custom Database Management System for Airline Reservations

**CSAI 302 – Advanced Database Systems, Fall 2026**
School of Computational Sciences and Artificial Intelligence, Zewail City

## Overview

AeroCore is a database engine built from scratch and extended incrementally across six milestones
(storage → indexing → query processing → transactions → distribution → integration).
It does **not** use SQLite, PostgreSQL, MySQL, MongoDB, or any other existing database engine.
Every component (pages, buffer pool, indexes, query engine, transactions, replication) is implemented by our team.

**Application domain:** Airline Reservations and Passenger Analytics
The domain provides realistic data and demonstration workloads. The DBMS itself is the main deliverable.

**What the demo workload covers:**
- Flight booking and seat availability lookups
- Double-booking prevention under concurrent reservations
- Route analytics (booking volume by route and date, occupancy)

## Team

| Name | Student ID | Main contributions |
|------|-----------|--------------------|
| Jana Mahmoud | 202301597 | Disk manager, page format (update as work progresses) |
| Farah Ahmed | 202300267 | Buffer pool, replacement policies (update as work progresses) |
| Soha Essam | 202300335 | Column layout, tests and benchmarks (update as work progresses) |

## Project Status

| Milestone | Status | Tag |
|-----------|--------|-----|
| M1 Storage Engine | In progress | `m1-storage` |
| M2 Indexing | Planned | – |
| M3 Query Processing | Planned | – |
| M4 Transactions & Recovery | Planned | – |
| M5 Distributed Layer | Planned | – |
| M6 Integration | Planned | – |

## Application Domain: AeroCore Airline Reservations

### Core tables

| Table | Purpose | Key columns (planned) |
|-------|---------|-----------------------|
| `airports` | Origin and destination airports | `airport_id`, `code`, `city`, `region` |
| `flights` | Scheduled flights | `flight_id`, `origin_id`, `dest_id`, `departure_time`, `capacity` |
| `seats` | Seat inventory per flight | `seat_id`, `flight_id`, `seat_number`, `status` |
| `passengers` | Passenger records | `passenger_id`, `name`, `passport_ref` (synthetic) |
| `reservations` | Bookings linking passenger, flight and seat | `reservation_id`, `passenger_id`, `flight_id`, `seat_id`, `created_at` |
| `payments` | Payment for each reservation | `payment_id`, `reservation_id`, `amount`, `status` |

All data is synthetic and generated with a fixed random seed.

### Representative queries

1. **Seat availability:** list free seats on a given flight.
2. **Route demand:** booking volume by route and date range (join of reservations, flights, airports).
3. **Occupancy report:** occupancy percentage per flight (reserved seats vs. capacity).

### Representative multi-record transaction

**Reserve a seat and record payment atomically.** Create the reservation, mark the seat as taken, and insert the payment. Either all three happen or none do. Concurrent reservations for the same seat must never both succeed (no double-booking).

### Distribution example (M5)

Partition data by region or flight identifier across nodes, replicate each shard, and coordinate cross-node bookings with distributed commit.

### Object-storage use case (M2)

Store tickets and passenger manifests as objects in the engine's object store.

### Vector-search scenario (M5)

Exact top-k similarity search over fixed-dimensional vectors of travel policies or destination descriptions.

## Architecture

![Architecture diagram](docs/architecture.png)

```
Table API (insert / get / scan / update / delete)
        │
   Layout layer: RowStore | ColumnStore
        │
   Buffer pool: LRU | FIFO | Clock
        │
   Disk manager: fixed-size pages in a file
```

- **Table API:** the interface the rest of the system uses to create tables and manipulate records.
- **Layout layer:** stores a table either row by row (good for fetching whole records) or column by column (good for analytics).
- **Buffer pool:** caches pages in memory and evicts them with a configurable replacement policy.
- **Disk manager:** reads and writes fixed-size pages to the database file and counts physical I/O.

## Milestone 1 – Storage Engine

### Features

- Custom persistent storage using 4 KB slotted pages; data survives restart
- Buffer pool with configurable replacement policy (LRU, FIFO, Clock)
- Row-oriented and column-oriented table layouts
- Statistics: hit/miss ratio, page reads/writes, evictions

### Storage format

- **File header:** magic number, page size, page count, free-page information.
- **Page layout (row store):** page header, slot directory at the front, record data growing from the end of the page.
- **Record format:** fixed-schema fields serialized to bytes (integers, floats, strings).
- **Record ID:** `(page_id, slot_id)`.

*(Update this section with the exact byte layout once finalized.)*

### Design decisions

- **Page size:** 4 KB, *(add justification)*.
- **Record format:** *(add justification)*.
- **Column layout:** *(describe how column values are stored and how rows are reassembled)*.

## Getting Started

### Prerequisites

- Python 3.x *(fill in the exact version your team uses)*
- `pip install -r requirements.txt`

### Setup

```bash
git clone https://github.com/Jana-elsawy/ADB_project-.git
cd ADB_project-
python -m venv venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

### Run the demo

```bash
python -m dbms.demo   # creates a table, inserts rows, restarts, reads them back
```

### Run tests

```bash
pytest -v
```

### Generate data

```bash
python data/generate_data.py --rows 100000 --seed 42
```

### Run benchmarks

```bash
python benchmarks/run_all.py --runs 5 --seed 42
```

Raw results are saved in `benchmarks/results/` and plots in `benchmarks/plots/`.

## Benchmarks (M1)

**Environment:** *(CPU, RAM, disk type, OS, Python version)*
**Method:** 1 warm-up run followed by 5 measured runs, mean ± standard deviation, seed 42.

| Experiment | Result summary |
|------------|----------------|
| LRU vs FIFO (skewed workload) | *(hit ratio, time)* |
| Row vs column (SUM over one column) | *(ms)* |

*(Insert plots from `benchmarks/plots/` here.)*

**Discussion:** *(what we expected, what we measured, and why).*

## Repository Structure

```
src/dbms/storage/   disk manager, pages, row/column stores
src/dbms/buffer/    buffer pool and replacement policies
tests/              correctness tests
benchmarks/         benchmark scripts and results
data/               synthetic data generators
docs/               architecture and design notes
```

## Known Limitations

- *(e.g., fixed-length strings only, no free-space compaction)*

## External Libraries

- pytest, matplotlib, numpy *(update to match requirements.txt)*

## Contribution Guidelines (Team)

- Work on a feature branch (`feature/<task>`), open a pull request, and have a teammate review before merging into `main`.
- Commit message style: `storage: add slotted page insert`
- Never commit generated data files or `.db` files.