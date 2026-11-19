"""
Food Bank database viewer + AI assistant (local web app).

  pip install -r requirements.txt
  python app.py            then open http://localhost:5000

The page (static/index.html) reads live data from MySQL through /api/data.
The AI service is only called from this server, so the API key never reaches the browser.
The AI check runs automatically (no button): once at startup, every AI_EVERY_HOURS, a quick pickup
check every PICKUP_CHECK_MINUTES, and right after any data change. Other code can call trigger_check().
"""
import os, threading, time, decimal, datetime as dt
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector
import ai_engine, setup_db

app = Flask(__name__, static_folder="static")
app.json.sort_keys = False      # keep table columns in the order the queries define
EVERY_HOURS = float(os.getenv("AI_EVERY_HOURS", "1"))           # full check (expiry + pickups)
PICKUP_MINUTES = float(os.getenv("PICKUP_CHECK_MINUTES", "15"))  # quick missed/delayed pickup check
state = {"last_run": None, "next_run": None, "running": False, "last_reason": None, "last_log": []}
lock = threading.Lock()
pending = threading.Event()     # a data change arrived while a check was running: run once more after

QUERIES = {
    "stats": """SELECT (SELECT COUNT(*) FROM Donor) donors,
        (SELECT COUNT(*) FROM Recipient WHERE Approval_Status='Approved') recipients,
        (SELECT COUNT(*) FROM Volunteer) volunteers, (SELECT COUNT(*) FROM Coordinator) coordinators,
        (SELECT COUNT(*) FROM Donation) donations,
        (SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0 AND Expiration_Date>=CURDATE()) instock,
        (SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0
            AND DATEDIFF(Expiration_Date,CURDATE()) BETWEEN 0 AND 3) highrisk,
        (SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0 AND Expiration_Date<CURDATE()) pending,
        (SELECT COUNT(*) FROM Expiry_Record) expired,
        (SELECT COUNT(*) FROM Distribution WHERE Status='Fulfilled') hampers,
        (SELECT COUNT(*) FROM Email_Log) emails""",
    "donations": """SELECT d.Donation_ID id, d.Date_Time date, dn.Name donor, dn.Donor_Type type, v.Name collected,
        COUNT(i.Item_ID) n, GROUP_CONCAT(CONCAT(i.Name,' x',TRIM(TRAILING '.00' FROM i.Quantity),' ',i.Unit)
        ORDER BY i.Name SEPARATOR '||') items
        FROM Donation d JOIN Donor dn USING(Donor_ID) LEFT JOIN Volunteer v ON v.Volunteer_ID=d.Collected_By_Volunteer_ID
        LEFT JOIN Inventory_Item i ON i.Donation_ID=d.Donation_ID GROUP BY d.Donation_ID ORDER BY d.Date_Time DESC""",
    "hampers": """SELECT ds.Distribution_ID id, ds.Pickup_Date_Time date, ds.Status status, r.Name recipient,
        r.Household_Size hh, r.Food_Preferences prefs, v.Name given,
        GROUP_CONCAT(CONCAT(i.Name,' x',TRIM(TRAILING '.00' FROM di.Quantity),' ',i.Unit) SEPARATOR '||') items
        FROM Distribution ds JOIN Recipient r USING(Recipient_ID) LEFT JOIN Volunteer v ON v.Volunteer_ID=ds.Given_By_Volunteer_ID
        LEFT JOIN Distribution_Item di ON di.Distribution_ID=ds.Distribution_ID LEFT JOIN Inventory_Item i ON i.Item_ID=di.Item_ID
        GROUP BY ds.Distribution_ID ORDER BY ds.Pickup_Date_Time DESC""",
    "inventory": """SELECT i.Item_ID ID, i.Name Item, c.Name Category, i.Quantity Qty, i.Unit, i.Expiration_Date Expires,
        DATEDIFF(i.Expiration_Date,CURDATE()) DaysLeft,
        CASE WHEN i.Expiration_Date<CURDATE() THEN 'EXPIRED' WHEN DATEDIFF(i.Expiration_Date,CURDATE())<=3 THEN 'HIGH' ELSE 'OK' END Risk,
        dn.Name `Donated By`
        FROM Inventory_Item i JOIN Category c USING(Category_ID) JOIN Donation d USING(Donation_ID) JOIN Donor dn USING(Donor_ID)
        WHERE i.Status='Available' AND i.Quantity>0 ORDER BY i.Expiration_Date, i.Name""",
    "expiry": """SELECT e.Expiry_ID ID, i.Name Item, c.Name Category, e.Quantity Qty, i.Unit, e.Expired_On `Expired On`,
        e.Recorded_At `Removed On`, dn.Name `Donated By`
        FROM Expiry_Record e JOIN Inventory_Item i USING(Item_ID) JOIN Category c ON c.Category_ID=e.Category_ID
        JOIN Donation d ON d.Donation_ID=i.Donation_ID JOIN Donor dn USING(Donor_ID) ORDER BY e.Expiry_ID DESC""",
    "coordinators": """SELECT c.Coordinator_ID ID, c.Name, u.Email, c.Phone,
        (SELECT COUNT(*) FROM Shift s WHERE s.Coordinator_ID=c.Coordinator_ID) `Shifts Created`,
        (SELECT COUNT(*) FROM Recipient r WHERE r.Approved_By=c.Coordinator_ID) `Recipients Approved`,
        (SELECT COUNT(*) FROM Email_Log e WHERE e.To_User_ID=c.User_ID) `Alerts Received`
        FROM Coordinator c JOIN User_Account u USING(User_ID)""",
    "volunteers": """SELECT v.Volunteer_ID ID, v.Name, u.Email, v.Phone, v.Availability,
        (SELECT COUNT(*) FROM Donation d WHERE d.Collected_By_Volunteer_ID=v.Volunteer_ID) `Donations Collected`,
        (SELECT COUNT(*) FROM Distribution d WHERE d.Given_By_Volunteer_ID=v.Volunteer_ID AND d.Status='Fulfilled') `Hampers Given`,
        (SELECT COUNT(*) FROM Shift_Assignment sa WHERE sa.Volunteer_ID=v.Volunteer_ID) Shifts
        FROM Volunteer v JOIN User_Account u USING(User_ID)""",
    "shifts": """SELECT s.Shift_ID ID, DATE_FORMAT(s.Start_Time,'%a %b %d') Day,
        CONCAT(DATE_FORMAT(s.Start_Time,'%l %p'),' - ',DATE_FORMAT(s.End_Time,'%l %p')) Time, s.Task,
        GROUP_CONCAT(v.Name ORDER BY v.Name SEPARATOR ', ') Volunteers, co.Name `Assigned By`,
        IF(s.Start_Time>NOW(),'Upcoming','Done') `When`
        FROM Shift s JOIN Shift_Assignment sa USING(Shift_ID) JOIN Volunteer v USING(Volunteer_ID)
        JOIN Coordinator co USING(Coordinator_ID) GROUP BY s.Shift_ID ORDER BY s.Start_Time DESC""",
    "emails": """SELECT e.Sent_At Sent, e.To_Email `To`, ua.Role, e.Subject, e.Written_By `Written By`, e.Run_Mode Mode,
        e.Status, e.Body body FROM Email_Log e JOIN User_Account ua ON ua.User_ID=e.To_User_ID ORDER BY e.Email_ID DESC""",
    "donors": """SELECT dn.Donor_ID ID, dn.Name, dn.Donor_Type Type, dn.Phone, u.Email,
        COUNT(DISTINCT d.Donation_ID) Donations, COUNT(i.Item_ID) `Items Given`
        FROM Donor dn JOIN User_Account u USING(User_ID) LEFT JOIN Donation d USING(Donor_ID)
        LEFT JOIN Inventory_Item i ON i.Donation_ID=d.Donation_ID GROUP BY dn.Donor_ID""",
    "recipients": """SELECT r.Recipient_ID ID, r.Name, r.Household_Size Household, r.Phone, u.Email,
        r.Food_Preferences `Dietary Needs`, r.Emergency_Contact `Emergency Contact`, r.Approval_Status Status,
        (SELECT COUNT(*) FROM Distribution d WHERE d.Recipient_ID=r.Recipient_ID AND d.Status='Fulfilled') `Hampers Received`
        FROM Recipient r JOIN User_Account u USING(User_ID)""",
    "accounts": """SELECT u.User_ID ID, u.Email, u.Role,
        COALESCE(co.Name, v.Name, dn.Name, r.Name) Name, IF(u.Is_Active,'Active','Disabled') Status,
        u.Last_Login `Last Login` FROM User_Account u
        LEFT JOIN Coordinator co ON co.User_ID=u.User_ID LEFT JOIN Volunteer v ON v.User_ID=u.User_ID
        LEFT JOIN Donor dn ON dn.User_ID=u.User_ID LEFT JOIN Recipient r ON r.User_ID=u.User_ID ORDER BY u.User_ID""",
    "categories": """SELECT c.Category_ID ID, c.Name Category,
        SUM(i.Status='Available' AND i.Quantity>0 AND i.Expiration_Date>=CURDATE()) `In Stock`,
        SUM(i.Status='Available' AND i.Quantity>0 AND DATEDIFF(i.Expiration_Date,CURDATE()) BETWEEN 0 AND 3) `High Risk`,
        SUM(i.Status='Available' AND i.Quantity>0 AND i.Expiration_Date<CURDATE()) `Waiting Removal`,
        (SELECT COUNT(*) FROM Expiry_Record e WHERE e.Category_ID=c.Category_ID) Expired
        FROM Category c LEFT JOIN Inventory_Item i USING(Category_ID) GROUP BY c.Category_ID""",
}


def clean(v):
    if isinstance(v, decimal.Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, dt.datetime):
        return v.strftime("%b %d, %Y %I:%M %p")
    if isinstance(v, dt.date):
        return v.strftime("%b %d, %Y")
    return v


@app.errorhandler(Exception)
def on_error(e):
    """Every /api error comes back as JSON with a plain-English reason (no stack traces in the browser)."""
    if isinstance(e, mysql.connector.Error):
        hints = {1049: "The foodbank database does not exist yet. Run: python setup_db.py",
                 1045: "MySQL rejected the login. Check DB_USER and DB_PASS in .env.",
                 2003: "MySQL is not running. Start the MySQL service, then refresh.",
                 1146: "The database is out of date. Run: python setup_db.py"}
        return jsonify({"ok": False, "error": hints.get(e.errno, f"Database error: {e.msg}")}), 500
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    if code >= 500:
        app.logger.exception(e)
    return jsonify({"ok": False, "error": str(e) if code < 500 else f"Server error: {e}"}), code


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/data")
def data():
    con = ai_engine.connect()
    cur = con.cursor(dictionary=True, buffered=True)
    out = {}
    try:
        for k, q in QUERIES.items():
            cur.execute(ai_engine.use_demo_dates(q, cur))
            out[k] = [{c: clean(v) for c, v in r.items()} for r in cur.fetchall()]
        day = ai_engine.today(cur)
    finally:
        con.close()
    out["stats"] = out["stats"][0]
    out["generated"] = dt.datetime.now().strftime("%b %d, %Y %I:%M %p")
    out["ai"] = {"muse": ai_engine.muse_enabled(), "muse_status": ai_engine.muse_status(),
                 "smtp": ai_engine.smtp_ready(), "every_hours": EVERY_HOURS, "pickup_minutes": PICKUP_MINUTES, **state}
    out["today"] = str(day)
    out["demo_date"] = str(day) if day != dt.date.today() else None
    out["items"] = [{"id": r["ID"], "label": f"#{r['ID']} {r['Item']} (exp {r['Expires']})"} for r in out["inventory"]]
    out["test_password"] = setup_db.TEST_PASSWORD
    return jsonify(out)


def do_run(reason, pickups_only=False):
    with lock:
        state["running"] = True
        try:
            res = ai_engine.run_check(mode="Automatic", pickups_only=pickups_only)
            if not pickups_only or any(l.startswith("  Email") for l in res["log"]):
                state["last_log"], state["last_reason"] = res["log"], reason
        finally:
            state["running"] = False
            if not pickups_only:
                state["last_run"] = dt.datetime.now().strftime("%b %d, %Y %I:%M %p")
    return res


def trigger_check(reason):
    """Start the full AI check in the background right away. Call this after anything that changes
    inventory, pickups or shifts. If a check is already running, one more run follows it."""
    def work():
        while True:
            pending.clear()
            try:
                do_run(reason)
            except Exception as e:
                print("Automatic check failed:", e)
                state["last_log"], state["last_reason"] = [f"Automatic check failed: {e}"], reason
            if not pending.is_set():
                break
    if state["running"]:
        pending.set()
    else:
        threading.Thread(target=work, daemon=True).start()


@app.post("/api/ai/insights")
def ai_insights():
    q = (request.get_json(silent=True) or {}).get("question", "").strip()[:500]
    return jsonify(ai_engine.insights(q or None))


# ---------------- logins ----------------
@app.post("/api/login")
def login():
    """Checks an email + password against User_Account. The main app can reuse this for its login page."""
    b = request.get_json(silent=True) or {}
    email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    con = ai_engine.connect(); cur = con.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT User_ID, Password_Hash, Role, Is_Active FROM User_Account WHERE LOWER(Email)=%s", (email,))
        u = cur.fetchone()
        if not u or not setup_db.check_password(pw, u["Password_Hash"]):
            return jsonify({"ok": False, "msg": "Wrong email or password."}), 401
        if not u["Is_Active"]:
            return jsonify({"ok": False, "msg": "This account is disabled."}), 403
        cur.execute("UPDATE User_Account SET Last_Login=NOW() WHERE User_ID=%s", (u["User_ID"],))
        con.commit()
        return jsonify({"ok": True, "user_id": u["User_ID"], "role": u["Role"],
                        "msg": f"Login OK. Role: {u['Role']}."})
    finally:
        con.close()


# ---------------- pickups ----------------
@app.post("/api/pickup/status")
def pickup_status():
    """A volunteer marks a pickup Fulfilled, Missed or Delayed. Missed/Delayed emails go out right away
    (SRS 3.1.3), to the coordinators and the volunteers on shift that day. The main app can reuse this."""
    b = request.get_json(silent=True) or {}
    status = str(b.get("status", "")).title()
    try:
        dist_id = int(b.get("distribution_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Send distribution_id and status."}), 400
    if status not in ("Fulfilled", "Missed", "Delayed"):
        return jsonify({"ok": False, "error": "Status must be Fulfilled, Missed or Delayed."}), 400
    con = ai_engine.connect(); cur = con.cursor()
    try:
        cur.execute("UPDATE Distribution SET Status=%s WHERE Distribution_ID=%s", (status, dist_id))
        n = cur.rowcount; con.commit()
    finally:
        con.close()
    if not n:
        return jsonify({"ok": False, "error": "No pickup with that ID (or it already has that status)."}), 404
    if status != "Fulfilled":
        trigger_check(f"pickup #{dist_id} marked {status.lower()}")
    return jsonify({"ok": True, "msg": f"Pickup #{dist_id} marked {status}."
                    + (" Alert emails are going out automatically." if status != "Fulfilled" else "")})


# ---------------- reports (2 types, monthly or annual) ----------------
REPORT_TYPES = {"donation": "Donation & Distribution Summary", "waste": "Inventory Waste Summary"}


@app.get("/api/report")
def report():
    kind = request.args.get("type", "donation")
    if kind not in REPORT_TYPES:
        return jsonify({"ok": False, "error": "Unknown report type."}), 400
    try:
        year = int(request.args.get("year", dt.date.today().year))
        month = int(request.args.get("month") or 0)
        assert 2000 <= year <= 2100 and 0 <= month <= 12
    except (ValueError, AssertionError):
        return jsonify({"ok": False, "error": "Pick a valid year and month."}), 400

    def period(col):   # year/month are validated integers
        return f"YEAR({col})={year}" + (f" AND MONTH({col})={month}" if month else "")

    con = ai_engine.connect(); cur = con.cursor(dictionary=True, buffered=True)

    def q(sql):
        cur.execute(sql)
        return [{c: clean(v) for c, v in r.items()} for r in cur.fetchall()]
    try:
        if kind == "donation":
            t = q(f"""SELECT COUNT(DISTINCT d.Donation_ID) donations, COUNT(DISTINCT d.Donor_ID) donors, COALESCE(SUM(i.Original_Quantity),0) qty
                      FROM Donation d LEFT JOIN Inventory_Item i USING(Donation_ID) WHERE {period('d.Date_Time')}""")[0]
            h = q(f"""SELECT COALESCE(SUM(Status='Fulfilled'),0) fulfilled, COALESCE(SUM(Status IN ('Missed','Delayed')),0) missed,
                      COUNT(DISTINCT IF(Status='Fulfilled',Recipient_ID,NULL)) households
                      FROM Distribution WHERE {period('Pickup_Date_Time')}""")[0]
            summary = [["Donations received", t["donations"]], ["Total quantity donated", t["qty"]], ["Active donors", t["donors"]],
                       ["Hampers distributed", h["fulfilled"]], ["Households served", h["households"]],
                       ["Missed or delayed pickups", h["missed"]]]
            by_donor = q(f"""SELECT dn.Name Donor, dn.Donor_Type Type, COUNT(DISTINCT d.Donation_ID) Donations,
                    COUNT(i.Item_ID) `Item Lines` FROM Donation d JOIN Donor dn USING(Donor_ID)
                    LEFT JOIN Inventory_Item i USING(Donation_ID) WHERE {period('d.Date_Time')}
                    GROUP BY dn.Donor_ID ORDER BY `Item Lines` DESC""")
            tables = [
                ["Donations received by category (most to least)", q(f"""SELECT c.Name Category,
                    SUM(i.Original_Quantity) `Total Quantity`, COUNT(*) `Item Lines` FROM Donation d
                    JOIN Inventory_Item i USING(Donation_ID) JOIN Category c USING(Category_ID)
                    WHERE {period('d.Date_Time')} GROUP BY c.Category_ID ORDER BY `Total Quantity` DESC""")],
                ["Missed or delayed pickups by recipient (most to least)", q(f"""SELECT r.Name Recipient,
                    r.Household_Size Household, SUM(ds.Status IN ('Missed','Delayed')) `Missed or Delayed`,
                    SUM(ds.Status='Fulfilled') `Hampers Received`
                    FROM Distribution ds JOIN Recipient r USING(Recipient_ID) WHERE {period('ds.Pickup_Date_Time')}
                    GROUP BY r.Recipient_ID ORDER BY `Missed or Delayed` DESC, `Hampers Received` DESC""")],
                ["Donations by donor", by_donor]]
        else:
            t = q(f"SELECT COUNT(*) n, COUNT(DISTINCT Category_ID) cats FROM Expiry_Record WHERE {period('Expired_On')}")[0]
            d = q(f"""SELECT COUNT(*) n FROM Inventory_Item i JOIN Donation d USING(Donation_ID) WHERE {period('d.Date_Time')}""")[0]
            rate = f"{100 * t['n'] / d['n']:.0f}%" if d["n"] else "n/a"
            summary = [["Expired or wasted items", t["n"]], ["Categories affected", t["cats"]],
                       ["Item lines donated in period", d["n"]], ["Waste rate (expired / donated)", rate]]
            tables = [
                ["Expired or wasted items by category (most to least)", q(f"""SELECT c.Name Category, COUNT(*) `Expired Items`, SUM(e.Quantity) `Total Quantity`,
                    CONCAT(ROUND(100*COUNT(*)/(SELECT COUNT(*) FROM Expiry_Record WHERE {period('Expired_On')})),'%') Share
                    FROM Expiry_Record e JOIN Category c ON c.Category_ID=e.Category_ID WHERE {period('e.Expired_On')}
                    GROUP BY c.Category_ID ORDER BY `Expired Items` DESC, `Total Quantity` DESC""")],
                ["Most wasted items", q(f"""SELECT i.Name Item, COUNT(*) `Expired Lines`, SUM(e.Quantity) `Total Qty`, i.Unit
                    FROM Expiry_Record e JOIN Inventory_Item i USING(Item_ID) WHERE {period('e.Expired_On')}
                    GROUP BY i.Name, i.Unit ORDER BY `Expired Lines` DESC, `Total Qty` DESC LIMIT 10""")],
                ["Waste by donor", q(f"""SELECT dn.Name Donor, COUNT(*) `Expired Lines` FROM Expiry_Record e
                    JOIN Inventory_Item i USING(Item_ID) JOIN Donation d ON d.Donation_ID=i.Donation_ID JOIN Donor dn USING(Donor_ID)
                    WHERE {period('e.Expired_On')} GROUP BY dn.Donor_ID ORDER BY `Expired Lines` DESC""")]]
        # record that the report was generated (Report table)
        cur.execute("""INSERT INTO Report (Report_Type, Report_Year, Report_Month, Generated_By)
                       SELECT %s, %s, %s, MIN(Coordinator_ID) FROM Coordinator""", (REPORT_TYPES[kind], year, month or None))
        con.commit()
    finally:
        con.close()
    when = (dt.date(year, month, 1).strftime("%B %Y") if month else f"{year} (annual)")
    return jsonify({"ok": True, "title": f"{REPORT_TYPES[kind]}: {when}", "summary": summary, "tables": tables})


# ---------------- demo controls ----------------
@app.post("/api/demo/date")
def demo_date():
    """Set a pretend 'today' (YYYY-MM-DD) or clear it with null."""
    d = (request.get_json(silent=True) or {}).get("date")
    if d:
        try:
            dt.date.fromisoformat(d)
        except ValueError:
            return jsonify({"ok": False, "msg": "Use the date picker (YYYY-MM-DD)."}), 400
    con = ai_engine.connect(); cur = con.cursor()
    cur.execute("REPLACE INTO App_Setting (Setting_Key, Setting_Value) VALUES ('Demo_Date', %s)", (d or None,))
    con.commit(); con.close()
    trigger_check("demo date changed")
    return jsonify({"ok": True, "msg": (f"Demo date set to {d}." if d else "Back to the real date.") +
                    " The AI check is running automatically."})


@app.post("/api/demo/expiry")
def demo_expiry():
    """Change one inventory item's expiry date."""
    b = request.get_json(silent=True) or {}
    try:
        item, d = int(b.get("item_id")), dt.date.fromisoformat(b.get("date", ""))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Pick an item and a date."}), 400
    con = ai_engine.connect(); cur = con.cursor()
    cur.execute("UPDATE Inventory_Item SET Expiration_Date=%s WHERE Item_ID=%s AND Status='Available'", (d, item))
    n = cur.rowcount; con.commit(); con.close()
    if n:
        trigger_check(f"item #{item} expiry date changed")
    return jsonify({"ok": bool(n), "msg": f"Item #{item} now expires {d}. The AI check is running automatically."
                    if n else "That item is not in stock any more."})


@app.post("/api/demo/reset")
def demo_reset():
    """Reload the original test data (clears demo changes, alerts and emails)."""
    if state["running"]:
        return jsonify({"ok": False, "msg": "An AI check is running. Try again in a moment."}), 409
    with lock:
        setup_db.main(quiet=True)
        state["last_log"], state["last_reason"] = [], None
    trigger_check("test data reset")
    return jsonify({"ok": True, "msg": "Test data reloaded. The AI check is running automatically."})


def scheduler():
    """Runs by itself while the app is open: the full check once at startup, a quick missed/delayed
    pickup check every PICKUP_MINUTES, and the full check every EVERY_HOURS and when the day changes
    (so that day's shift volunteers get the alerts)."""
    trigger_check("app started")
    next_full, day = dt.datetime.now() + dt.timedelta(hours=EVERY_HOURS), dt.date.today()
    while True:
        state["next_run"] = next_full.strftime("%b %d, %Y %I:%M %p")
        time.sleep(PICKUP_MINUTES * 60)
        if state["running"]:
            continue
        full = dt.datetime.now() >= next_full or dt.date.today() != day
        try:
            do_run("scheduled full check" if full else "scheduled pickup check", pickups_only=not full)
        except Exception as e:
            print("Automatic check failed:", e)
        if full:
            next_full, day = dt.datetime.now() + dt.timedelta(hours=EVERY_HOURS), dt.date.today()


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
