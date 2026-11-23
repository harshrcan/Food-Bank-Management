"""
Creates the foodbank database and loads the test data, using the settings in .env.
No mysql command needed.

  python setup_db.py

Every test account gets the password  Password123!  (stored as a secure hash, never plain text).
"""
import os
import mysql.connector

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_PASSWORD = "Password123!"


def hash_password(pw):
    """bcrypt if installed (what the schema expects), otherwise Werkzeug's built-in hash."""
    try:
        import bcrypt
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(10)).decode()
    except ImportError:
        from werkzeug.security import generate_password_hash
        return generate_password_hash(pw)


def check_password(pw, stored):
    try:
        if stored.startswith("$2"):
            import bcrypt
            return bcrypt.checkpw(pw.encode(), stored.encode())
        from werkzeug.security import check_password_hash
        return check_password_hash(stored, pw)
    except Exception:
        return False


def catch_up(cur):
    """The test data is written as of Nov 20, 2026. If it is loaded later, act as if the system ran
    in between: past pickups were handed out, and food that expired before yesterday was removed.
    Food that expired yesterday or today is left for the live AI check to find."""
    cur.execute("""UPDATE foodbank.Distribution SET Status='Fulfilled'
                   WHERE Status='Scheduled' AND DATE(Pickup_Date_Time) < CURDATE()""")
    pickups = cur.rowcount
    cur.execute("""INSERT INTO foodbank.Expiry_Record (Item_ID, Quantity, Expired_On, Category_ID, Recorded_At)
                   SELECT Item_ID, Quantity, Expiration_Date, Category_ID, TIMESTAMP(Expiration_Date + INTERVAL 1 DAY, '06:00:00')
                   FROM foodbank.Inventory_Item
                   WHERE Status='Available' AND Quantity > 0 AND Expiration_Date < CURDATE() - INTERVAL 1 DAY""")
    expired = cur.rowcount
    cur.execute("""UPDATE foodbank.Inventory_Item SET Status='Expired'
                   WHERE Status='Available' AND Quantity > 0 AND Expiration_Date < CURDATE() - INTERVAL 1 DAY""")
    if pickups or expired:
        return (f"Brought the test data up to today: {pickups} past pickups marked fulfilled, "
                f"{expired} long-expired items moved to the expiry section.")
    return ""


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


def main(quiet=False):
    say = (lambda *a: None) if quiet else print
    try:
        con = mysql.connector.connect(host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"),
                                      password=os.getenv("DB_PASS", ""))
    except mysql.connector.Error as e:
        raise RuntimeError(f"Could not connect to MySQL: {e}. Is MySQL running? Check DB_USER and DB_PASS in .env.")
    cur = con.cursor()
    try:
        for name in ("schema.sql", "seed_data.sql"):
            n = 0
            for st in statements(os.path.join(HERE, "database", name)):
                cur.execute(st)
                if cur.with_rows:
                    cur.fetchall()
                n += 1
            con.commit()
            say(f"Loaded database/{name} ({n} statements)")
        cur.execute("UPDATE foodbank.User_Account SET Password_Hash=%s", (hash_password(TEST_PASSWORD),))
        con.commit()
        caught_up = catch_up(cur)
        con.commit()
        if caught_up:
            say(caught_up)
        cur.execute("SELECT COUNT(*) FROM foodbank.Inventory_Item")
        items = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM foodbank.User_Account")
        say(f"Done. foodbank database is ready: {items} inventory items, {cur.fetchone()[0]} test logins "
            f"(password for all: {TEST_PASSWORD}).")
        say("Now run: python app.py   and open http://localhost:5000")
    finally:
        con.close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(e)
        raise SystemExit(1)
