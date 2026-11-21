from aerocore.cli import main, repl, run_statement
from aerocore.sql import Database
from aerocore.sql.airline import create_airline_tables, load_rows


def test_one_shot_command_and_exit_codes(tmp_path, capsys):
    db = str(tmp_path / "db")
    code = main(["--db", db, "-c",
                 "CREATE TABLE t (id INT, name TEXT); INSERT INTO t VALUES (1,'a'),(2,'b'); "
                 "SELECT * FROM t WHERE id = 2"])
    out = capsys.readouterr().out
    assert code == 0 and "| 2  | b    |" in out
    assert main(["--db", db, "-c", "SELECT * FROM missing"]) == 1
    assert "unknown table" in capsys.readouterr().out
    script = tmp_path / "s.sql"
    script.write_text("SELECT * FROM t;\nSELECT name FROM t WHERE id = 1;", encoding="utf-8")
    assert main(["--db", db, "--file", str(script)]) == 0


def test_interactive_shell(tmp_path):
    lines = iter([".init-airline", "SELECT * FROM airports", "WHERE airport_id = 1;", ".timing on",
                  ".plan on", "INSERT INTO airports VALUES (1, 'CAI', 'Cairo', 'Egypt');",
                  "SELECT city FROM airports WHERE airport_id = 1;", "DROP TABLE x;", ".quit"])
    out = []
    with Database(tmp_path / "db") as db:
        repl(db, inp=lambda prompt: next(lines), out=out.append)
    text = "\n".join(out)
    assert "created:" in text and "Cairo" in text and "time:" in text
    assert "IndexScan airports.airport_id" in text and "error:" in text


def test_airline_tables_and_bulk_load(tmp_path):
    with Database(tmp_path / "db") as db:
        assert len(create_airline_tables(db)) == 6 and create_airline_tables(db) == []
        rows = [{"passenger_id": i, "name": f"P{i}", "email": f"p{i}@x.org", "passport_number": f"P{i}"}
                for i in range(1, 251)]
        assert load_rows(db, "passengers", rows, batch=60) == 250
        assert db.execute("SELECT name FROM passengers WHERE passenger_id = 250").rows == [("P250",)]
        assert len(db.execute("SELECT * FROM passengers").rows) == 250