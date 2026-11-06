"""
Creates the foodbank database and loads the test data, using the settings in .env.
No mysql command needed.

  python setup_db.py
"""
import os, sys
import mysql.connector

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def statements(path):
    """Split a .sql file into single statements (skips comments)."""
    buf = []
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line.rstrip("\n"))
        if s.endswith(";"):
            yield "\n".join(buf).rstrip().rstrip(";")
            buf = []


def main():
    try:
        con = mysql.connector.connect(host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"),
                                      password=os.getenv("DB_PASS", ""))
    except mysql.connector.Error as e:
        print("Could not connect to MySQL:", e)
        print("Check DB_USER and DB_PASS in your .env file.")
        raise SystemExit(1)
    cur = con.cursor()
    for name in ("schema.sql", "seed_data.sql"):
        n = 0
        for st in statements(os.path.join(HERE, "database", name)):
            cur.execute(st)
            if cur.with_rows:
                cur.fetchall()
            n += 1
        con.commit()
        print(f"Loaded database/{name} ({n} statements)")
    cur.execute("SELECT COUNT(*) FROM foodbank.Inventory_Item")
    print(f"Done. foodbank database is ready with {cur.fetchone()[0]} inventory items.")
    print("Now run: python app.py   and open http://localhost:5000")
    con.close()


if __name__ == "__main__":
    main()
