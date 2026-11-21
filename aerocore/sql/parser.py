"""Tokenizer and recursive-descent parser for the AeroCore SQL-like language (M2).

Supported statements
    CREATE TABLE t (col INT|TEXT|FLOAT, ..., PRIMARY KEY (col))
    CREATE INDEX ON t (col) [USING auto [WORKLOAD (writes, point_reads, range_reads)] | bptree | lsm]
    DROP INDEX ON t (col)
    REINDEX ON t (col)                       -- re-apply the workload rule
    INSERT INTO t [(col, ...)] VALUES (v, ...) [, (v, ...)]
    SELECT * | col, ... FROM t [WHERE cond [AND cond]...] [ORDER BY col [ASC|DESC]] [LIMIT n]
    UPDATE t SET col = v [, col = v] [WHERE ...]
    DELETE FROM t [WHERE ...]
    EXPLAIN SELECT ...
    SHOW TABLES | SHOW INDEXES ON t

    cond :=  col (= | != | <> | < | <= | > | >=) value   |   col BETWEEN value AND value

Safety (this is the "no injection" part of the design)
    * The text is split into tokens by a fixed regular expression. Anything that is not a
      number, a quoted string, an identifier, an operator or one of ( ) , * ? ; is rejected.
    * Values are never pasted into SQL. Use `?` placeholders and pass `params`; a bound value
      only ever becomes a literal in the syntax tree, so it cannot change the statement.
    * Only ONE statement per call is accepted (a trailing ';' is allowed), so "stacked"
      statements such as  `...; DROP INDEX ...`  are rejected.
    * Quoted strings are data: `'x'' OR 1=1 --'` is just a string value.
    * Table and column names are checked against the catalog by the engine; they can never
      come from `params`.
"""
import re
from dataclasses import dataclass, field


class SQLError(ValueError):
    """Raised for any syntax, type or catalog error."""


# --------------------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------------------
KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
    "CREATE", "TABLE", "INDEX", "ON", "USING", "DROP", "EXPLAIN", "BETWEEN", "ORDER", "BY",
    "ASC", "DESC", "LIMIT", "PRIMARY", "KEY", "SHOW", "REINDEX",
}

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+\.\d+|\d+)
  | (?P<str>'(?:[^']|'')*')
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|<>|!=|=|<|>)
  | (?P<sym>[(),*?;-])
""", re.VERBOSE)


@dataclass(frozen=True)
class Token:
    kind: str       # NUM STR ID KW OP SYM EOF
    value: object
    pos: int


def tokenize(text):
    if not isinstance(text, str):
        raise SQLError("SQL text must be a string")
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise SQLError(f"unexpected character {text[pos]!r} at position {pos}")
        kind, raw = m.lastgroup, m.group()
        if kind == "num":
            tokens.append(Token("NUM", float(raw) if "." in raw else int(raw), pos))
        elif kind == "str":
            tokens.append(Token("STR", raw[1:-1].replace("''", "'"), pos))
        elif kind == "id":
            up = raw.upper()
            tokens.append(Token("KW", up, pos) if up in KEYWORDS else Token("ID", raw.lower(), pos))
        elif kind == "op":
            tokens.append(Token("OP", "!=" if raw == "<>" else raw, pos))
        elif kind == "sym":
            tokens.append(Token("SYM", raw, pos))
        pos = m.end()
    tokens.append(Token("EOF", None, len(text)))
    return tokens


def split_statements(text):
    """Split a script on ';' that are outside quoted strings. Empty statements are dropped."""
    out, buf, in_str = [], [], False
    for ch in text:
        if ch == "'":
            in_str = not in_str
        if ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


# --------------------------------------------------------------------------------------
# Syntax tree
# --------------------------------------------------------------------------------------
@dataclass
class Cond:
    column: str
    op: str                      # = != < <= > >= between
    value: object
    value2: object = None        # upper bound for BETWEEN

    def matches(self, v):
        if v is None:
            return False
        if self.op == "=":
            return v == self.value
        if self.op == "!=":
            return v != self.value
        if self.op == "<":
            return v < self.value
        if self.op == "<=":
            return v <= self.value
        if self.op == ">":
            return v > self.value
        if self.op == ">=":
            return v >= self.value
        return self.value <= v <= self.value2        # between

    def __str__(self):
        if self.op == "between":
            return f"{self.column} BETWEEN {self.value!r} AND {self.value2!r}"
        return f"{self.column} {self.op} {self.value!r}"


@dataclass
class CreateTable:
    name: str
    columns: list                # [(name, "int"|"str"|"float")]
    primary_key: str


@dataclass
class CreateIndex:
    table: str
    column: str
    kind: str = "auto"
    workload: object = None      # (writes, point_reads, range_reads) for kind == "auto", or None


@dataclass
class DropIndex:
    table: str
    column: str


@dataclass
class Reindex:
    table: str
    column: str


@dataclass
class Insert:
    table: str
    columns: object              # list of names or None (= all columns in schema order)
    rows: list


@dataclass
class Select:
    table: str
    columns: object              # list of names or None for *
    conds: list = field(default_factory=list)
    order_by: object = None
    descending: bool = False
    limit: object = None


@dataclass
class Update:
    table: str
    assignments: dict
    conds: list = field(default_factory=list)


@dataclass
class Delete:
    table: str
    conds: list = field(default_factory=list)


@dataclass
class Explain:
    select: Select


@dataclass
class ShowTables:
    pass


@dataclass
class ShowIndexes:
    table: str


_TYPE_NAMES = {"int": "int", "integer": "int", "text": "str", "varchar": "str", "str": "str",
               "float": "float", "real": "float", "double": "float"}
_INDEX_KINDS = {"auto", "bptree", "lsm"}


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------
class _Parser:
    def __init__(self, text, params):
        self.tokens = tokenize(text)
        self.i = 0
        self.params = list(params)
        self.used = 0

    # ----- token helpers -----
    @property
    def tok(self):
        return self.tokens[self.i]

    def _advance(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    def _fail(self, expected):
        t = self.tok
        got = "end of statement" if t.kind == "EOF" else repr(t.value)
        raise SQLError(f"syntax error at position {t.pos}: expected {expected}, got {got}")

    def _kw(self, *words):
        if self.tok.kind == "KW" and self.tok.value in words:
            return self._advance().value
        return None

    def _expect_kw(self, word):
        if not self._kw(word):
            self._fail(word)

    def _sym(self, ch):
        if self.tok.kind == "SYM" and self.tok.value == ch:
            self._advance()
            return True
        return False

    def _expect_sym(self, ch):
        if not self._sym(ch):
            self._fail(repr(ch))

    def _ident(self, what="a name"):
        if self.tok.kind != "ID":
            self._fail(what)
        return self._advance().value

    def _word(self, *words):
        """Contextual (non-reserved) word such as a type name or index kind."""
        if self.tok.kind == "ID" and self.tok.value in words:
            return self._advance().value
        return None

    # ----- values -----
    def _value(self):
        t = self.tok
        if t.kind == "SYM" and t.value == "?":
            self._advance()
            if self.used >= len(self.params):
                raise SQLError("not enough parameters for the '?' placeholders")
            v = self.params[self.used]
            self.used += 1
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise SQLError(f"unsupported parameter type {type(v).__name__}")
            return v
        if t.kind == "SYM" and t.value == "-":
            self._advance()
            if self.tok.kind != "NUM":
                self._fail("a number after '-'")
            return -self._advance().value
        if t.kind in ("NUM", "STR"):
            return self._advance().value
        self._fail("a value (number, 'string' or ?)")

    def _conds(self):
        conds = []
        if not self._kw("WHERE"):
            return conds
        while True:
            col = self._ident("a column name")
            if self._kw("BETWEEN"):
                lo = self._value()
                self._expect_kw("AND")
                hi = self._value()
                conds.append(Cond(col, "between", lo, hi))
            elif self.tok.kind == "OP":
                op = self._advance().value
                conds.append(Cond(col, op, self._value()))
            else:
                self._fail("a comparison operator or BETWEEN")
            if not self._kw("AND"):
                break
        return conds

    def _name_list(self):
        self._expect_sym("(")
        names = [self._ident()]
        while self._sym(","):
            names.append(self._ident())
        self._expect_sym(")")
        return names

    # ----- statements -----
    def statement(self):
        if self._kw("EXPLAIN"):
            self._expect_kw("SELECT")
            node = Explain(self._select())
        elif self._kw("SELECT"):
            node = self._select()
        elif self._kw("INSERT"):
            node = self._insert()
        elif self._kw("UPDATE"):
            node = self._update()
        elif self._kw("DELETE"):
            node = self._delete()
        elif self._kw("CREATE"):
            node = self._create()
        elif self._kw("DROP"):
            self._expect_kw("INDEX")
            self._expect_kw("ON")
            table = self._ident("a table name")
            col = self._name_list()
            if len(col) != 1:
                raise SQLError("an index covers exactly one column")
            node = DropIndex(table, col[0])
        elif self._kw("REINDEX"):
            self._expect_kw("ON")
            table = self._ident("a table name")
            col = self._name_list()
            if len(col) != 1:
                raise SQLError("an index covers exactly one column")
            node = Reindex(table, col[0])
        elif self._kw("SHOW"):
            if self._word("tables"):
                node = ShowTables()
            elif self._word("indexes"):
                self._expect_kw("ON")
                node = ShowIndexes(self._ident("a table name"))
            else:
                self._fail("TABLES or INDEXES")
        else:
            self._fail("a statement (SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, EXPLAIN, SHOW)")
        self._sym(";")
        if self.tok.kind != "EOF":
            raise SQLError("only one statement is allowed per call "
                           f"(unexpected {self.tok.value!r} at position {self.tok.pos})")
        if self.used != len(self.params):
            raise SQLError(f"{len(self.params)} parameters given but {self.used} '?' placeholders used")
        return node

    def _select(self):
        if self._sym("*"):
            cols = None
        else:
            cols = [self._ident("a column name or *")]
            while self._sym(","):
                cols.append(self._ident("a column name"))
        self._expect_kw("FROM")
        table = self._ident("a table name")
        node = Select(table, cols, self._conds())
        if self._kw("ORDER"):
            self._expect_kw("BY")
            node.order_by = self._ident("a column name")
            if self._kw("DESC"):
                node.descending = True
            else:
                self._kw("ASC")
        if self._kw("LIMIT"):
            n = self._value()
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise SQLError("LIMIT must be a non-negative integer")
            node.limit = n
        return node

    def _insert(self):
        self._expect_kw("INTO")
        table = self._ident("a table name")
        cols = self._name_list() if self.tok.kind == "SYM" and self.tok.value == "(" else None
        self._expect_kw("VALUES")
        rows = []
        while True:
            self._expect_sym("(")
            row = [self._value()]
            while self._sym(","):
                row.append(self._value())
            self._expect_sym(")")
            rows.append(row)
            if not self._sym(","):
                break
        return Insert(table, cols, rows)

    def _update(self):
        table = self._ident("a table name")
        self._expect_kw("SET")
        assignments = {}
        while True:
            col = self._ident("a column name")
            if not (self.tok.kind == "OP" and self.tok.value == "="):
                self._fail("'='")
            self._advance()
            if col in assignments:
                raise SQLError(f"column {col} is assigned twice")
            assignments[col] = self._value()
            if not self._sym(","):
                break
        return Update(table, assignments, self._conds())

    def _delete(self):
        self._expect_kw("FROM")
        table = self._ident("a table name")
        return Delete(table, self._conds())

    def _create(self):
        if self._kw("TABLE"):
            name = self._ident("a table name")
            self._expect_sym("(")
            columns, pk = [], None
            while True:
                if self._kw("PRIMARY"):
                    self._expect_kw("KEY")
                    names = self._name_list()
                    if len(names) != 1:
                        raise SQLError("composite primary keys are not supported")
                    pk = names[0]
                else:
                    col = self._ident("a column name")
                    tname = self._ident("a column type (INT, TEXT, FLOAT)")
                    if tname not in _TYPE_NAMES:
                        raise SQLError(f"unknown column type {tname!r}; use INT, TEXT or FLOAT")
                    columns.append((col, _TYPE_NAMES[tname]))
                if not self._sym(","):
                    break
            self._expect_sym(")")
            names = [c for c, _ in columns]
            if not columns:
                raise SQLError("a table needs at least one column")
            if len(set(names)) != len(names):
                raise SQLError("duplicate column name")
            if pk is None:
                pk = names[0]
            if pk not in names:
                raise SQLError(f"primary key {pk!r} is not a column")
            return CreateTable(name, columns, pk)
        if self._kw("INDEX"):
            self._expect_kw("ON")
            table = self._ident("a table name")
            cols = self._name_list()
            if len(cols) != 1:
                raise SQLError("an index covers exactly one column")
            kind, workload = "auto", None
            if self._kw("USING"):
                kind = self._word(*_INDEX_KINDS)
                if kind is None:
                    self._fail("auto, bptree or lsm")
                if kind == "auto" and self._word("workload"):
                    self._expect_sym("(")
                    nums = [self._value()]
                    while self._sym(","):
                        nums.append(self._value())
                    self._expect_sym(")")
                    if len(nums) != 3 or any(isinstance(n, bool) or not isinstance(n, int) or n < 0
                                             for n in nums):
                        raise SQLError("WORKLOAD needs three non-negative integers: "
                                       "(writes, point_reads, range_reads)")
                    workload = tuple(nums)
            return CreateIndex(table, cols[0], kind, workload)
        self._fail("TABLE or INDEX")


def parse(text, params=()):
    """Parse one statement; `params` fill the `?` placeholders in order."""
    return _Parser(text, params).statement()