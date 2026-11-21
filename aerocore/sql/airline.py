"""Helpers for the airline application domain: create the six tables and bulk-load rows.

The table definitions come from aerocore/index/schema.py (TABLE_SCHEMAS); the data comes from
data/generate_airline.py (synthetic, fixed seed). Everything goes through the SQL engine, so
the rows end up in the custom storage engine and its indexes.
"""
import json
from pathlib import Path

from aerocore.index.schema import TABLE_SCHEMAS

_SQL_TYPE = {"int": "INT", "str": "TEXT", "float": "FLOAT"}


def create_airline_tables(db):
    """CREATE TABLE for every airline table that does not exist yet. Returns the names created."""
    created = []
    for name, schema in TABLE_SCHEMAS.items():
        if name in db.tables:
            continue
        cols = ", ".join(f"{c} {_SQL_TYPE[t]}" for c, t in schema.columns.items())
        db.execute(f"CREATE TABLE {name} ({cols}, PRIMARY KEY ({schema.primary_key}))")
        created.append(name)
    return created


def load_rows(db, table, rows, batch=100):
    """Insert dict rows with parameterised multi-row INSERT statements. Returns the row count."""
    columns = list(db._table(table).schema.columns)           # trusted names from the catalog
    marks = "(" + ", ".join("?" * len(columns)) + ")"
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        params = [r[c] for r in chunk for c in columns]
        db.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                   + ", ".join([marks] * len(chunk)), params)
        total += len(chunk)
    # bulk loading is setup, not workload: don't let it bias the index-selection rule
    db._table(table).workload = {"writes": 0, "point": {}, "range": {}}
    return total


def load_json(db, table, path):
    """Load a file produced by `python data/generate_airline.py --table <table> ...`."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_rows(db, table, rows)