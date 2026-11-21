"""SQL-like execution engine (M2): parser -> access-path choice -> IndexedTable.

`Database(directory)` owns a catalog (catalog.json) and one IndexedTable per table, so every
statement ends up in the M1 storage engine (RowStore + BufferPool + DiskManager) and the M2
indexes (B+ Tree / LSM Tree). Nothing here uses SQLite or any other ready-made engine.

Access-path rule (kept deliberately simple; M3 replaces it with a cost-based optimizer):
    1. an equality condition on an indexed column        -> index point lookup
    2. a range condition (<, <=, >, >=, BETWEEN) on an indexed column -> index range scan
    3. otherwise                                          -> full table scan
Every condition is still re-checked on each fetched row, so exclusive bounds (< and >),
`!=` and conditions on other columns are always applied correctly.

`execute(sql, params, use_index=False)` forces a full scan. The tests and the benchmarks use
it as the correctness baseline: an indexed query must return exactly what a scan returns.
"""
import json
import os
import time
from pathlib import Path

from aerocore.index.indexed_table import IndexedTable
from aerocore.index.schema import TableSchema
from aerocore.objects import ObjectStore

from . import parser as P
from .parser import SQLError

_PY_TYPES = {"int": "an integer", "str": "a string", "float": "a number"}


class Result:
    def __init__(self, columns=(), rows=(), message="", plan="", used_index=None, rowcount=None):
        self.columns = list(columns)
        self.rows = [tuple(r) for r in rows]
        self.message = message
        self.plan = plan                 # human-readable plan (SELECT / EXPLAIN)
        self.used_index = used_index     # None (scan) or "bptree" / "lsm"
        self.rowcount = len(self.rows) if rowcount is None else rowcount
        self.elapsed_ms = 0.0

    def as_dicts(self):
        return [dict(zip(self.columns, r)) for r in self.rows]

    def format(self):
        if not self.columns:
            return self.message
        cells = [[("NULL" if v is None else str(v)) for v in r] for r in self.rows]
        widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(self.columns)]
        line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        out = [line, "| " + " | ".join(c.ljust(w) for c, w in zip(self.columns, widths)) + " |", line]
        out += ["| " + " | ".join(v.ljust(w) for v, w in zip(r, widths)) + " |" for r in cells]
        out.append(line)
        out.append(self.message or f"({len(self.rows)} row{'s' if len(self.rows) != 1 else ''})")
        return "\n".join(out)


class _Access:
    """Chosen way to read a table."""

    def __init__(self, kind, column=None, lo=None, hi=None, driving=None):
        self.kind = kind            # "scan" | "point" | "range"
        self.column, self.lo, self.hi = column, lo, hi
        self.guaranteed = driving or []   # conditions the index already satisfies exactly


class Database:
    def __init__(self, directory, cipher=None, buffer_capacity=16, memtable_limit=2000):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher
        self.buffer_capacity, self.memtable_limit = buffer_capacity, memtable_limit
        self.tables = {}
        self._objects = None
        self._catalog_path = self.dir / "catalog.json"
        if self._catalog_path.exists():
            for name, spec in json.loads(self._catalog_path.read_text()).items():
                schema = TableSchema(name, spec["columns"], spec["primary_key"])
                self.tables[name] = self._open_table(name, schema)

    # ---------- catalog ----------
    def _open_table(self, name, schema):
        return IndexedTable(name, self.dir, schema, buffer_capacity=self.buffer_capacity,
                            memtable_limit=self.memtable_limit)

    def _save_catalog(self):
        data = {n: {"columns": t.schema.columns, "primary_key": t.schema.primary_key}
                for n, t in self.tables.items()}
        tmp = self._catalog_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self._catalog_path)

    def _table(self, name):
        if name not in self.tables:
            raise SQLError(f"unknown table {name!r}")
        return self.tables[name]

    @property
    def objects(self):
        """Object store (tickets, manifests) that lives next to the tables."""
        if self._objects is None:
            self._objects = ObjectStore(self.dir, "objects", cipher=self.cipher)
        return self._objects

    # ---------- public API ----------
    def execute(self, sql, params=(), use_index=True):
        t0 = time.perf_counter()
        node = P.parse(sql, params)
        handler = {
            P.CreateTable: self._create_table, P.CreateIndex: self._create_index,
            P.DropIndex: self._drop_index, P.Reindex: self._reindex, P.Insert: self._insert,
            P.Select: self._select, P.Update: self._update, P.Delete: self._delete,
            P.Explain: self._explain, P.ShowTables: self._show_tables,
            P.ShowIndexes: self._show_indexes,
        }[type(node)]
        result = handler(node, use_index)
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result

    def execute_script(self, text, use_index=True):
        """Run several ';'-separated statements (no parameters). Returns a list of Results."""
        return [self.execute(stmt, use_index=use_index) for stmt in P.split_statements(text)]

    def close(self):
        for t in self.tables.values():
            t.close()
        if self._objects is not None:
            self._objects.close()
            self._objects = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- validation helpers ----------
    @staticmethod
    def _check_value(table, col, value):
        if col not in table.schema.columns:
            raise SQLError(f"unknown column {col!r} in table {table.name!r}")
        typ = table.schema.columns[col]
        ok = {"int": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "str": lambda v: isinstance(v, str),
              "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)}[typ](value)
        if not ok:
            raise SQLError(f"column {table.name}.{col} needs {_PY_TYPES[typ]}, got {value!r}")

    def _check_conds(self, table, conds):
        for c in conds:
            self._check_value(table, c.column, c.value)
            if c.op == "between":
                self._check_value(table, c.column, c.value2)

    # ---------- access path ----------
    @staticmethod
    def _choose_access(table, conds, use_index):
        if not use_index:
            return _Access("scan")
        for c in conds:
            if c.op == "=" and c.column in table.indexes:
                return _Access("point", c.column, c.value, c.value, [c])
        bounds, used = {}, {}
        for c in conds:
            if c.column not in table.indexes or c.op not in ("<", "<=", ">", ">=", "between"):
                continue
            lo, hi = bounds.get(c.column, (None, None))
            if c.op in (">", ">=", "between"):
                lo = c.value if lo is None else max(lo, c.value)
            if c.op in ("<", "<=", "between"):
                top = c.value2 if c.op == "between" else c.value
                hi = top if hi is None else min(hi, top)
            bounds[c.column] = (lo, hi)
            if c.op in (">=", "<=", "between"):          # inclusive: index is exact for these
                used.setdefault(c.column, []).append(c)
        if bounds:
            col = max(bounds, key=lambda k: (bounds[k][0] is not None) + (bounds[k][1] is not None))
            lo, hi = bounds[col]
            return _Access("range", col, lo, hi, used.get(col, []))
        return _Access("scan")

    @staticmethod
    def _note_workload(table, conds):
        """Feed the observed read pattern to the index-selection rule (selector.py)."""
        for c in conds:
            if c.op == "=":
                table.workload["point"][c.column] = table.workload["point"].get(c.column, 0) + 1
            elif c.op != "!=":
                table.workload["range"][c.column] = table.workload["range"].get(c.column, 0) + 1

    def _fetch(self, table, conds, use_index):
        """Return ([(rid, record)], access) for the rows matching every condition."""
        self._check_conds(table, conds)
        access = self._choose_access(table, conds, use_index)
        self._note_workload(table, conds)
        if access.kind == "point":
            rids = table.indexes[access.column].search(access.lo)
        elif access.kind == "range":
            rids = [rid for _, rid in table.indexes[access.column].range(access.lo, access.hi)]
        else:
            pairs = list(table.store.scan_with_rids())
            return [(rid, rec) for rid, rec in pairs if self._match(rec, conds)], access
        out = []
        for rid in rids:
            rec = table.store.get(rid)
            if rec is not None and self._match(rec, conds):
                out.append((rid, rec))
        return out, access

    @staticmethod
    def _match(rec, conds):
        return all(c.matches(rec.get(c.column)) for c in conds)

    # ---------- plan text ----------
    @staticmethod
    def _plan_text(table, sel, access):
        def bound(v, default):
            return default if v is None else repr(v)

        if access.kind == "point":
            leaf = (f"IndexScan {table.name}.{access.column} using {table.kinds[access.column]} "
                    f"index  (key = {access.lo!r})")
        elif access.kind == "range":
            leaf = (f"IndexRangeScan {table.name}.{access.column} using {table.kinds[access.column]} "
                    f"index  ({bound(access.lo, '-inf')} <= {access.column} <= {bound(access.hi, '+inf')})")
        else:
            leaf = f"FullScan {table.name}  ({len(table.store.page_ids)} pages)"
        layers = []
        if sel.limit is not None:
            layers.append(f"Limit {sel.limit}")
        if sel.order_by:
            layers.append(f"Sort {sel.order_by} {'DESC' if sel.descending else 'ASC'}")
        rest = [c for c in sel.conds if not any(c is g for g in access.guaranteed)]
        if rest:
            layers.append("Filter " + " AND ".join(str(c) for c in rest))
        layers.append(leaf)
        return "\n".join("  " * i + ("-> " if i else "") + text for i, text in enumerate(layers))

    # ---------- statements ----------
    def _select(self, sel, use_index):
        table = self._table(sel.table)
        cols = sel.columns or list(table.schema.columns)
        for c in cols:
            if c not in table.schema.columns:
                raise SQLError(f"unknown column {c!r} in table {table.name!r}")
        if sel.order_by and sel.order_by not in table.schema.columns:
            raise SQLError(f"unknown column {sel.order_by!r} in ORDER BY")
        pairs, access = self._fetch(table, sel.conds, use_index)
        recs = [rec for _, rec in pairs]
        if sel.order_by:
            present = [r for r in recs if r.get(sel.order_by) is not None]
            absent = [r for r in recs if r.get(sel.order_by) is None]
            present.sort(key=lambda r: r[sel.order_by], reverse=sel.descending)
            recs = present + absent
        if sel.limit is not None:
            recs = recs[:sel.limit]
        rows = [tuple(r.get(c) for c in cols) for r in recs]
        return Result(cols, rows, plan=self._plan_text(table, sel, access),
                      used_index=table.kinds[access.column] if access.kind != "scan" else None)

    def _explain(self, node, use_index):
        res = self._select(node.select, use_index)
        return Result(["plan"], [(line,) for line in res.plan.split("\n")],
                      plan=res.plan, used_index=res.used_index)

    def _insert(self, node, use_index):
        table = self._table(node.table)
        schema = table.schema
        cols = node.columns or list(schema.columns)
        for c in cols:
            if c not in schema.columns:
                raise SQLError(f"unknown column {c!r} in table {table.name!r}")
        if len(set(cols)) != len(cols):
            raise SQLError("a column is listed twice")
        if schema.primary_key not in cols:
            raise SQLError(f"the primary key {schema.primary_key!r} must be given")
        pk_index, seen, records = table.indexes[schema.primary_key], set(), []
        for row in node.rows:
            if len(row) != len(cols):
                raise SQLError(f"expected {len(cols)} values per row, got {len(row)}")
            rec = dict(zip(cols, row))
            for c, v in rec.items():
                self._check_value(table, c, v)
            pk = rec[schema.primary_key]
            if pk in seen or pk_index.search(pk):
                raise SQLError(f"duplicate primary key {schema.primary_key}={pk!r}")
            seen.add(pk)
            records.append(rec)
        for rec in records:                # validated first: either every row is valid or none is stored
            table.insert(rec)
        return Result(message=f"{len(records)} row{'s' if len(records) != 1 else ''} inserted",
                      rowcount=len(records))

    def _update(self, node, use_index):
        table = self._table(node.table)
        for col, v in node.assignments.items():
            if col == table.schema.primary_key:
                raise SQLError("the primary key cannot be updated")
            self._check_value(table, col, v)
        pairs, _ = self._fetch(table, node.conds, use_index)
        for rid, rec in pairs:
            new = {k: v for k, v in rec.items() if k != "_rid"}
            new.update(node.assignments)
            table.update(rid, new)
        return Result(message=f"{len(pairs)} row{'s' if len(pairs) != 1 else ''} updated",
                      rowcount=len(pairs))

    def _delete(self, node, use_index):
        table = self._table(node.table)
        pairs, _ = self._fetch(table, node.conds, use_index)
        for rid, _ in pairs:
            table.delete(rid)
        return Result(message=f"{len(pairs)} row{'s' if len(pairs) != 1 else ''} deleted",
                      rowcount=len(pairs))

    def _create_table(self, node, use_index):
        if node.name in self.tables:
            raise SQLError(f"table {node.name!r} already exists")
        schema = TableSchema(node.name, dict(node.columns), node.primary_key)
        table = self._open_table(node.name, schema)
        table.create_index(node.primary_key, "bptree")      # primary key is always indexed
        self.tables[node.name] = table
        self._save_catalog()
        return Result(message=f"table {node.name} created (primary key {node.primary_key}, "
                              f"bptree index)")

    def _create_index(self, node, use_index):
        table = self._table(node.table)
        if node.column not in table.schema.columns:
            raise SQLError(f"unknown column {node.column!r} in table {table.name!r}")
        if node.column in table.indexes:
            raise SQLError(f"{node.table}.{node.column} is already indexed")
        workload = None
        if node.workload is not None:
            w, p, r = node.workload
            workload = {"writes": w, "point_reads": p, "range_reads": r}
        kind, reason = table.create_index(node.column, node.kind, workload=workload)
        return Result(message=f"index on {node.table}({node.column}) created: {kind}  [{reason}]")

    def _drop_index(self, node, use_index):
        table = self._table(node.table)
        if node.column == table.schema.primary_key:
            raise SQLError("the primary-key index cannot be dropped")
        if node.column not in table.indexes:
            raise SQLError(f"{node.table}.{node.column} has no index")
        table.drop_index(node.column)
        return Result(message=f"index on {node.table}({node.column}) dropped")

    def _reindex(self, node, use_index):
        table = self._table(node.table)
        if node.column not in table.indexes:
            raise SQLError(f"{node.table}.{node.column} has no index")
        kind, changed = table.reselect(node.column)
        return Result(message=(f"index on {node.table}({node.column}) rebuilt as {kind}" if changed
                               else f"index on {node.table}({node.column}) kept as {kind}"))

    def _show_tables(self, node, use_index):
        rows = [(n, t.schema.primary_key, ", ".join(f"{c} {ty}" for c, ty in t.schema.columns.items()))
                for n, t in sorted(self.tables.items())]
        return Result(["table", "primary_key", "columns"], rows)

    def _show_indexes(self, node, use_index):
        table = self._table(node.table)
        rows = [(c, table.kinds[c], round(table.indexes[c].size_bytes() / 1024, 1))
                for c in sorted(table.indexes)]
        return Result(["column", "kind", "size_kb"], rows)