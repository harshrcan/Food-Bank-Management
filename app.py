"""
Food Bank database viewer + AI assistant (local web app).

  pip install -r requirements.txt
  python app.py            then open http://localhost:5000

The page (static/index.html) reads live data from MySQL through /api/data.
Muse AI is only called from this server, so the API key never reaches the browser.
The AI check also runs automatically every 6 hours while the app is running.
"""
import os, threading, time, decimal, datetime as dt
from flask import Flask, jsonify, request, send_from_directory
import ai_engine

app = Flask(__name__, static_folder="static")
EVERY_HOURS = float(os.getenv("AI_EVERY_HOURS", "6"))
state = {"last_run": None, "next_run": None, "running": False}
lock = threading.Lock()

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
    "emails": """SELECT e.Sent_At Sent, e.To_Email `To`, e.Subject, e.Written_By `Written By`, e.Run_Mode Mode,
        e.Status, e.Body body FROM Email_Log e ORDER BY e.Email_ID DESC""",
    "donors": """SELECT dn.Donor_ID ID, dn.Name, dn.Donor_Type Type, dn.Phone, u.Email,
        COUNT(DISTINCT d.Donation_ID) Donations, COUNT(i.Item_ID) `Items Given`
        FROM Donor dn JOIN User_Account u USING(User_ID) LEFT JOIN Donation d USING(Donor_ID)
        LEFT JOIN Inventory_Item i ON i.Donation_ID=d.Donation_ID GROUP BY dn.Donor_ID""",
    "recipients": """SELECT r.Recipient_ID ID, r.Name, r.Household_Size Household, r.Phone, u.Email,
        r.Food_Preferences `Dietary Needs`, r.Emergency_Contact `Emergency Contact`, r.Approval_Status Status,
        (SELECT COUNT(*) FROM Distribution d WHERE d.Recipient_ID=r.Recipient_ID AND d.Status='Fulfilled') `Hampers Received`
        FROM Recipient r JOIN User_Account u USING(User_ID)""",
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
                 "smtp": ai_engine.smtp_ready(), "every_hours": EVERY_HOURS, **state}
    out["today"] = str(day)
    out["demo_date"] = str(day) if day != dt.date.today() else None
    out["items"] = [{"id": r["ID"], "label": f"#{r['ID']} {r['Item']} (exp {r['Expires']})"} for r in out["inventory"]]
    return jsonify(out)


def do_run(mode):
    with lock:
        state["running"] = True
        try:
            res = ai_engine.run_check(mode=mode)
        finally:
            state["running"] = False
            state["last_run"] = dt.datetime.now().strftime("%b %d, %Y %I:%M %p")
    return res


@app.post("/api/ai/run")
def ai_run():
    if state["running"]:
        return jsonify({"log": ["An AI check is already running. Try again in a moment."]}), 409
    return jsonify(do_run("Manual"))


@app.post("/api/ai/insights")
def ai_insights():
    q = (request.get_json(silent=True) or {}).get("question", "").strip()[:500]
    return jsonify(ai_engine.insights(q or None))


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
    return jsonify({"ok": True, "msg": f"Demo date set to {d}." if d else "Back to the real date."})


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
    return jsonify({"ok": bool(n), "msg": f"Item #{item} now expires {d}. Run the AI check to see it handled."
                    if n else "That item is not in stock any more."})


@app.post("/api/demo/reset")
def demo_reset():
    """Reload the original test data (clears demo changes, alerts and emails)."""
    import setup_db
    setup_db.main()
    return jsonify({"ok": True, "msg": "Test data reloaded."})


def scheduler():
    """Automatic AI check every EVERY_HOURS while the app is running."""
    while True:
        state["next_run"] = (dt.datetime.now() + dt.timedelta(hours=EVERY_HOURS)).strftime("%b %d, %Y %I:%M %p")
        time.sleep(EVERY_HOURS * 3600)
        try:
            do_run("Automatic")
        except Exception as e:
            print("Automatic AI check failed:", e)


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
