# AeroCore – A Custom Database Management System for Airline Reservations

**CSAI 302 – Advanced Database Systems | Fall 2026**  
School of Computational Sciences and Artificial Intelligence, Zewail City

## 1. Overview

AeroCore is a custom Database Management System (DBMS) developed from scratch as part of the CSAI 302 Advanced Database Systems project.

The project will be implemented incrementally across six milestones:

1. Storage Engine
2. Advanced Indexing
3. Query Processing
4. Transactions and Recovery
5. Distributed Database
6. Full System Integration

AeroCore does not use existing database engines such as SQLite, PostgreSQL, MySQL, or MongoDB. The main DBMS components will be designed and implemented by our team.

**Application Domain:** Airline Reservations and Passenger Analytics.

The airline reservation system serves as the application domain used to demonstrate and test the DBMS capabilities. The main focus of the project is building the database engine itself.

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
| M1 | Storage Engine | In Progress |
| M2 | Advanced Indexing | Planned |
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
          (LRU | FIFO | Clock)
                    |
                    v
              Disk Manager
          (Fixed-Size Pages)
                    |
                    v
             Database File
```

### Component Responsibilities

**Table API:** Provides the interface for creating tables and performing basic record operations.

**Layout Layer:** Organizes records using row-oriented or column-oriented storage.

**Buffer Pool:** Caches database pages in memory and manages page replacement when the buffer becomes full.

**Replacement Policies:** Determine which page should be removed from the buffer pool. The initial implementation will support FIFO and LRU, with Clock as an additional policy.

**Disk Manager:** Handles reading and writing fixed-size pages to persistent database files and tracks physical I/O operations.

## 6. Milestone 1 – Storage Engine Foundation

The first milestone focuses on implementing the storage foundation of AeroCore.

### 6.1 Main Features

- Custom persistent storage using 4 KB pages.
- Slotted-page structure for row-oriented records.
- Buffer pool with configurable replacement policies.
- FIFO and LRU replacement algorithms.
- Row-oriented storage layout.
- Column-oriented storage layout.
- Persistent data that survives program restarts.
- Storage and buffer pool performance statistics.

### 6.2 Storage Format

**Database File Header**

The database file will contain metadata such as:

- Magic number.
- Page size.
- Page count.
- Free-page information.

**Page Structure**

The initial row-oriented storage design uses slotted pages:

- Page header stores page metadata.
- Slot directory stores record locations.
- Record data is stored from the end of the page.
- Free space is maintained between the slot directory and record data.

**Record Identifier**

Each stored record will be identified using:

`(page_id, slot_id)`

**Record Serialization**

Records will be serialized into bytes using a defined schema and supported data types, including integers, floating-point numbers, and strings.

### 6.3 Row-Oriented Storage

Records are stored one row at a time.

This layout is suitable for retrieving complete records, such as retrieving all information associated with a passenger.

### 6.4 Column-Oriented Storage

Values belonging to the same column are stored together.

This layout is suitable for analytical operations, such as calculating average passenger age or analyzing flight occupancy.

### 6.5 Buffer Pool

The buffer pool temporarily stores database pages in RAM to reduce disk access.

It will support:

- Configurable buffer capacity.
- Page loading and eviction.
- Cache hit and miss tracking.
- Dirty page management.
- Page replacement policies.

### 6.6 Performance Metrics

The following metrics will be collected:

- Cache hits.
- Cache misses.
- Hit ratio.
- Page reads.
- Page writes.
- Page evictions.
- Execution time.

### 6.7 Design Decisions

| Component | Initial Design |
|---|---|
| Page Size | 4 KB |
| Row Storage | Slotted Pages |
| Record Identification | Page ID and Slot ID |
| Replacement Policies | FIFO and LRU |
| Additional Policy | Clock |
| Persistence | Database Files |
| Data Source | Synthetic Airline Data |

The exact byte-level page format and columnar serialization design will be documented as implementation progresses.

## 7. Technology Stack

The initial implementation will use:

- **Python 3:** Main programming language.
- **NumPy:** Numerical operations and benchmark support.
- **Matplotlib:** Benchmark visualization.
- **Pytest:** Unit testing and correctness validation.

Additional libraries may be introduced when required by later milestones.

The team will maintain the exact dependency versions in `requirements.txt`.

## 8. Repository Structure

```text
AeroCore/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── aerocore/
│   ├── __init__.py
│   ├── schemas.py
│   ├── demo.py
│   │
│   └── storage/
│       ├── __init__.py
│       ├── page.py
│       ├── disk.py
│       ├── policies.py
│       ├── buffer_pool.py
│       ├── row_store.py
│       └── column_store.py
│
├── data/
│   └── generate_data.py
│
├── benchmarks/
│   ├── __init__.py
│   ├── bench_policies.py
│   ├── bench_layout.py
│   ├── plot.py
│   └── run_all.py
│
├── tests/
│   └── test_storage.py
│
├── docs/
│   ├── proposal.md
│   ├── architecture.md
│   └── m1_notes.md
│
├── results/
│   └── m1/
│
├── README.md
├── requirements.txt
└── .gitignore
```

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

```bash
python -m venv venv
```

Activate it:

**Windows PowerShell:**

```powershell
venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
source venv/bin/activate
```

### 9.4 Install Dependencies

```bash
pip install -r requirements.txt
```

## 10. Running the Project

The following commands will be available as the corresponding scripts are implemented.

### Run the Storage Demo

```bash
python -m aerocore.demo
```

The demo will demonstrate creating a table, inserting records, saving them to disk, and retrieving them after restarting the program.

### Generate Synthetic Airline Data

```bash
python data/generate_data.py --rows 100000 --seed 42
```

### Run Unit Tests

```bash
pytest -v
```

### Run Benchmarks

```bash
python -m benchmarks.run_all --runs 5 --seed 42
```

Benchmark results and plots will be saved under:

```text
results/m1/
```

## 11. M1 Benchmarks and Evaluation

The storage engine will be evaluated through repeatable experiments.

### 11.1 Buffer Pool Benchmark

Compare FIFO and LRU using the same page access workloads.

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

- Use a fixed random seed of 42.
- Perform one warm-up run.
- Perform five measured runs.
- Report the mean and standard deviation.
- Keep the workload and experimental settings consistent.

### 11.4 Results

**Environment:**

- Operating System: To be documented.
- CPU: To be documented.
- RAM: To be documented.
- Disk Type: To be documented.
- Python Version: To be documented.

**Benchmark Results:**

| Experiment | Metrics |
|---|---|
| FIFO vs. LRU | Hit ratio, misses, execution time |
| Row vs. Column Storage | Execution time, page reads |
| Buffer Pool | Hits, misses, evictions, I/O |

Plots and raw results will be added after running the experiments.

### 11.5 Discussion

The team will analyze the experimental results, compare the implemented approaches, and explain the observed performance differences.

## 12. Known Limitations

Limitations will be documented as the implementation progresses.

Potential initial limitations include:

- Limited supported data types.
- Fixed-length or bounded-length string fields.
- No advanced free-space compaction initially.
- Limited query functionality during M1.
- No transaction processing until M4.

## 13. External Libraries

The initial project dependencies will be maintained in `requirements.txt`.

Expected libraries:

- NumPy.
- Matplotlib.
- Pytest.

The custom database engine itself will be implemented by the team rather than delegated to an existing database engine.

## 14. Team Contribution Guidelines

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
```

Avoid committing generated database files, virtual environments, temporary files, or large generated datasets.

---

**Project:** AeroCore – A Custom Database Management System for Airline Reservations

**Course:** CSAI 302 – Advanced Database Systems

**Institution:** Zewail City, School of Computational Sciences and Artificial Intelligence