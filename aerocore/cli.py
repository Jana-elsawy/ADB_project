"""Command-line client for AeroCore (M2).

  python -m aerocore.cli                          interactive prompt (database in data/aerocore_db)
  python -m aerocore.cli --db my_db               use another database directory
  python -m aerocore.cli -c "SELECT * FROM flights WHERE flight_id = 5"
  python -m aerocore.cli --file script.sql        run a ';'-separated script

Dot commands in the interactive prompt:
  .help                      show this list
  .tables                    list tables
  .init-airline              create the six airline tables
  .load <table> <file.json>  bulk-load a file made by data/generate_airline.py
  .timing on|off             show the execution time of every statement
  .plan on|off               show the access plan after every SELECT
  .quit                      leave
Statements end with ';'. Use ? placeholders only through the Python API (Database.execute).
"""
import argparse
import sys

from aerocore.sql import Database, SQLError, split_statements
from aerocore.sql.airline import create_airline_tables, load_json

HELP = __doc__.split("Dot commands in the interactive prompt:")[1].split("Statements end")[0]


def run_statement(db, sql, timing=False, show_plan=False, out=print):
    try:
        res = db.execute(sql)
    except SQLError as e:
        out(f"error: {e}")
        return False
    out(res.format())
    if show_plan and res.plan and res.columns != ["plan"]:
        out("plan:\n" + res.plan)
    if timing:
        out(f"time: {res.elapsed_ms:.3f} ms")
    return True


def dot_command(db, line, state, out=print):
    parts = line.split()
    cmd = parts[0]
    if cmd in (".quit", ".exit"):
        return False
    if cmd == ".help":
        out(HELP)
    elif cmd == ".tables":
        out(db.execute("SHOW TABLES").format())
    elif cmd == ".init-airline":
        made = create_airline_tables(db)
        out("created: " + ", ".join(made) if made else "airline tables already exist")
    elif cmd == ".load" and len(parts) == 3:
        try:
            out(f"{load_json(db, parts[1], parts[2])} rows loaded into {parts[1]}")
        except (SQLError, OSError, ValueError, KeyError) as e:
            out(f"error: {e}")
    elif cmd in (".timing", ".plan") and len(parts) == 2 and parts[1] in ("on", "off"):
        state[cmd[1:]] = parts[1] == "on"
    else:
        out("unknown command, type .help")
    return True


def repl(db, inp=input, out=print):
    state = {"timing": False, "plan": False}
    out("AeroCore SQL shell. Statements end with ';'.  .help for commands, .quit to leave.")
    buf = []
    while True:
        try:
            line = inp("aerocore> " if not buf else "      ...> ")
        except EOFError:
            break
        if not buf and line.strip().startswith("."):
            if not dot_command(db, line.strip(), state, out):
                break
            continue
        buf.append(line)
        text = "\n".join(buf)
        if text.count("'") % 2 == 0 and text.rstrip().endswith(";"):
            for stmt in split_statements(text):
                run_statement(db, stmt, state["timing"], state["plan"], out)
            buf = []


def main(argv=None):
    ap = argparse.ArgumentParser(description="AeroCore SQL shell")
    ap.add_argument("--db", default="data/aerocore_db", help="database directory")
    ap.add_argument("-c", "--command", help="run one or more ';'-separated statements and exit")
    ap.add_argument("--file", help="run a SQL script file and exit")
    a = ap.parse_args(argv)
    with Database(a.db) as db:
        if a.command or a.file:
            text = a.command if a.command else open(a.file, encoding="utf-8").read()
            ok = all(run_statement(db, s) for s in split_statements(text))
            return 0 if ok else 1
        repl(db)
    return 0


if __name__ == "__main__":
    sys.exit(main())