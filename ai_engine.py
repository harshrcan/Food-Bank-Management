"""
AI engine for the Food Bank system (Algorithms 3 and 4), powered by Muse AI.

Used two ways:
  - by the web app (app.py): "Run AI check" button + automatic run every 6 hours
  - from the command line:   python ai_engine.py            (one manual run)
                             python ai_engine.py --dry-run  (preview, changes nothing)

Muse AI jobs:
  1. Writes the alert emails sent to coordinators (Harsh and AJ)
  2. Writes an inventory insight report from the live tables
  3. Answers coordinator questions about the data ("Ask Muse")

The expiry and late-pickup rules are plain code, so the data is always correct.
Muse AI only writes text. If Muse is unreachable, a built-in template is used.
"""
import os, sys, json, smtplib, datetime as dt
from email.message import EmailMessage
import mysql.connector, requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB = dict(host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"),
          password=os.getenv("DB_PASS", ""), database=os.getenv("DB_NAME", "foodbank"))

MUSE_API_KEY = os.getenv("MUSE_API_KEY")
# Meta's own Muse API is tried first, then the AI/ML API provider, so either kind of key works.
# Set MUSE_API_URL / MUSE_MODEL in .env to force one.
PROVIDERS = []
if os.getenv("MUSE_API_URL"):
    PROVIDERS.append((os.getenv("MUSE_API_URL"), os.getenv("MUSE_MODEL", "muse-spark-1.3")))
PROVIDERS += [("https://api.meta.ai/v1/chat/completions", "muse-spark-1.3"),
              ("https://api.aimlapi.com/v1/chat/completions", "meta/muse-spark-1.3")]
_working = {}   # remembers which provider worked

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


def smtp_ready():
    """True only if real SMTP details are filled in (not the .env.example placeholders)."""
    vals = [SMTP_HOST, SMTP_USER, SMTP_PASS]
    return all(vals) and not any(v.startswith("your") or "yourteam" in v for v in vals)


# ---------------- demo date ----------------
def today(cur=None):
    """The real date, or the coordinator's demo date if one is set."""
    try:
        own = cur is None
        con = connect() if own else None
        c = con.cursor() if own else cur
        c.execute("SELECT Setting_Value FROM App_Setting WHERE Setting_Key='Demo_Date'")
        row = c.fetchone()
        if own:
            con.close()
        v = row and (row[0] if not isinstance(row, dict) else row["Setting_Value"])
        if v:
            return dt.date.fromisoformat(v)
    except Exception:
        pass
    return dt.date.today()


def now(cur=None):
    return dt.datetime.combine(today(cur), dt.datetime.now().time()).replace(microsecond=0)


def use_demo_dates(sql, cur=None):
    """Swap CURDATE()/NOW() in a query for the (demo) date, so every screen agrees."""
    return sql.replace("CURDATE()", f"'{today(cur)}'").replace("NOW()", f"'{now(cur)}'")

SYSTEM = ("You are the AI assistant for the Surrey Community Food Bank management system. "
          "You help coordinators reduce food waste and run distributions. Be short, clear and practical. "
          "Plain text only, no markdown symbols like ** or #.")


def connect():
    return mysql.connector.connect(**DB)


# ---------------- Muse AI ----------------
def muse_enabled():
    return bool(MUSE_API_KEY)


def muse_chat(prompt, max_tokens=700):
    """Send one prompt to Muse AI. Tries each provider until one accepts the key. Raises with a clear reason."""
    order = ([_working["p"]] if "p" in _working else []) + [p for p in PROVIDERS if p != _working.get("p")]
    errors = []
    for url, model in order:
        try:
            r = requests.post(url, timeout=60,
                              headers={"Authorization": f"Bearer {MUSE_API_KEY}", "Content-Type": "application/json"},
                              json={"model": model, "max_tokens": max_tokens,
                                    "messages": [{"role": "system", "content": SYSTEM},
                                                 {"role": "user", "content": prompt}]})
            if r.status_code in (401, 403, 404):
                errors.append(f"{url.split('/')[2]}: {r.status_code} {r.text[:160]}")
                continue
            r.raise_for_status()
            _working["p"] = (url, model)
            return r.json()["choices"][0]["message"]["content"].strip()
        except requests.RequestException as e:
            errors.append(f"{url.split('/')[2]}: {e.__class__.__name__}")
    raise RuntimeError("Muse AI rejected the request. " + " | ".join(errors))


def muse_status():
    if not MUSE_API_KEY:
        return "no key"
    return f"connected via {_working['p'][0].split('/')[2]}" if "p" in _working else "key set"


def muse_email(task, data, log):
    """Ask Muse to write an email. Returns (subject, body) or None."""
    if not muse_enabled():
        return None
    try:
        text = muse_chat(f"Task: {task}\nReturn JSON only: {{\"subject\": \"...\", \"body\": \"...\"}}\n"
                         f"Data: {json.dumps(data, default=str)}")
        out = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return out["subject"][:250], out["body"]
    except Exception as e:
        log.append(f"Muse AI unavailable, used template ({e.__class__.__name__})")
        return None


# ---------------- email ----------------
log_once = {}


def coordinators(cur):
    cur.execute("""SELECT u.User_ID, u.Email, c.Name FROM Coordinator c
                   JOIN User_Account u ON u.User_ID = c.User_ID WHERE u.Is_Active = 1""")
    return cur.fetchall()


def send_to_coordinators(cur, alert_id, subject, body, written_by, mode, dry, log):
    for c in coordinators(cur):
        status = "Logged only"
        if smtp_ready() and not dry:
            try:
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = SMTP_USER, c["Email"], subject
                msg.set_content(body)
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                    s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
                status = "Sent"
            except Exception as e:
                status = "Failed"; log.append(f"Email to {c['Email']} failed: {str(e)[:150]}")
        if not dry:
            cur.execute("""INSERT INTO Email_Log (Alert_ID,To_User_ID,To_Email,Subject,Body,Written_By,Run_Mode,Status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (alert_id, c["User_ID"], c["Email"], subject, body, written_by, mode, status))
        log.append(f"Email to {c['Name']} ({c['Email']}): {status} - {subject}")
        if status == "Logged only" and not dry and not log_once.get("smtp"):
            log_once["smtp"] = True
            log.append("  (Saved in Email_Log only. Add your Gmail App Password to .env to really send emails.)")


# ---------------- Algorithm 3: expiry ----------------
def expiry_check(cur, mode, dry, log):
    day = today(cur)
    cur.execute("""SELECT i.Item_ID, i.Name, i.Quantity, i.Unit, i.Expiration_Date, i.Category_ID, c.Name AS Category
                   FROM Inventory_Item i JOIN Category c USING (Category_ID)
                   WHERE i.Status='Available' AND i.Quantity > 0""")
    expired, high = [], []
    for it in cur.fetchall():
        left = (it["Expiration_Date"] - day).days
        if left < 0:
            expired.append(it)
            if not dry:
                cur.execute("UPDATE Inventory_Item SET Status='Expired', Risk_Level='OK' WHERE Item_ID=%s", (it["Item_ID"],))
                cur.execute("""INSERT IGNORE INTO Expiry_Record (Item_ID,Quantity,Expired_On,Category_ID,Recorded_At)
                               VALUES (%s,%s,%s,%s,%s)""",
                            (it["Item_ID"], it["Quantity"], it["Expiration_Date"], it["Category_ID"], now(cur)))
                log.append(f"  Removed from inventory: {it['Name']} ({it['Quantity']:g} {it['Unit']}), expired {it['Expiration_Date']}")
        elif left <= 3:
            it["days_left"] = left
            if not dry:
                cur.execute("UPDATE Inventory_Item SET Risk_Level='HIGH' WHERE Item_ID=%s", (it["Item_ID"],))
            cur.execute(use_demo_dates("""SELECT 1 FROM Alert WHERE Type='Expiry Risk' AND Item_ID=%s
                           AND Date_Time >= NOW() - INTERVAL 24 HOUR""", cur), (it["Item_ID"],))
            if not cur.fetchall():
                high.append(it)
        elif not dry:
            cur.execute("UPDATE Inventory_Item SET Risk_Level='OK' WHERE Item_ID=%s", (it["Item_ID"],))

    log.append(f"Expiry check: {len(expired)} items moved to the expiry table, {len(high)} new at-risk items")
    if not high:
        return {"expired": len(expired), "at_risk": 0}

    alert_id = None
    for it in high:
        if not dry:
            cur.execute("INSERT INTO Alert (Type, Item_ID, Message, Date_Time) VALUES ('Expiry Risk', %s, %s, %s)",
                        (it["Item_ID"], f"{it['Name']}: {it['Quantity']} {it['Unit']} expires {it['Expiration_Date']}", now(cur)))
            alert_id = alert_id or cur.lastrowid

    rows = sorted([{"item": i["Name"], "category": i["Category"], "qty": f"{i['Quantity']:g} {i['Unit']}",
                    "expires": i["Expiration_Date"], "days_left": i["days_left"]} for i in high],
                  key=lambda r: r["days_left"])
    ai = muse_email("Write ONE email to the food bank coordinators listing these at-risk items, most urgent first, "
                    "and recommend putting them in the next hampers.", rows, log)
    if ai:
        subject, body, by = ai[0], ai[1], "Muse AI"
    else:
        by = "Template"
        subject = f"[Food Bank] {len(high)} items expiring within 3 days - priority distribution"
        body = "Hi Harsh and AJ,\n\nThese items need to go out in the next hampers:\n\n" + "\n".join(
            f"- {r['item']} ({r['qty']}), expires {r['expires']}, {r['days_left']} day(s) left" for r in rows) + \
            "\n\nAutomated alert from the Food Bank system."
    send_to_coordinators(cur, alert_id, subject, body, by, mode, dry, log)
    return {"expired": len(expired), "at_risk": len(high)}


# ---------------- Algorithm 4: missed / delayed pickups ----------------
def pickup_check(cur, mode, dry, log):
    cur_now = now(cur)
    cur.execute(use_demo_dates("""SELECT d.Distribution_ID, d.Pickup_Date_Time, d.Status, r.Name, r.Phone
                   FROM Distribution d JOIN Recipient r USING (Recipient_ID)
                   WHERE d.Status IN ('Scheduled','Delayed') AND DATE(d.Pickup_Date_Time) <= CURDATE()""", cur))
    for d in cur.fetchall():
        new = None
        if d["Pickup_Date_Time"].date() < cur_now.date():
            new = "Missed"
        elif d["Status"] == "Scheduled" and cur_now >= d["Pickup_Date_Time"] + dt.timedelta(minutes=30):
            new = "Delayed"
        if new and not dry:
            cur.execute("UPDATE Distribution SET Status=%s WHERE Distribution_ID=%s", (new, d["Distribution_ID"]))
            if new == "Missed":
                cur.execute("""UPDATE Inventory_Item i JOIN Distribution_Item di ON di.Item_ID=i.Item_ID
                               SET i.Quantity=i.Quantity+di.Quantity, i.Status='Available'
                               WHERE di.Distribution_ID=%s""", (d["Distribution_ID"],))

    # any Missed/Delayed pickup (automatic or marked by a volunteer) without an alert yet
    cur.execute("""SELECT d.Distribution_ID, d.Pickup_Date_Time, d.Status, r.Name, r.Phone
                   FROM Distribution d JOIN Recipient r USING (Recipient_ID)
                   WHERE d.Status IN ('Missed','Delayed')
                   AND NOT EXISTS (SELECT 1 FROM Alert a WHERE a.Distribution_ID=d.Distribution_ID AND a.Type=d.Status)""")
    todo = cur.fetchall()
    log.append(f"Pickup check: {len(todo)} missed/delayed pickups need an alert")
    for d in todo:
        alert_id = None
        if not dry:
            cur.execute("INSERT INTO Alert (Type, Distribution_ID, Message) VALUES (%s,%s,%s)",
                        (d["Status"], d["Distribution_ID"], f"{d['Name']} pickup {d['Status'].lower()}"))
            alert_id = cur.lastrowid
        data = {"recipient": d["Name"], "phone": d["Phone"], "pickup_time": d["Pickup_Date_Time"], "status": d["Status"]}
        ai = muse_email(f"Tell the coordinators this hamper pickup was {d['Status'].lower()} and suggest "
                        "calling the recipient to reschedule.", data, log)
        if ai:
            subject, body, by = ai[0], ai[1], "Muse AI"
        else:
            by = "Template"
            subject = f"[Food Bank] Pickup {d['Status'].lower()}: {d['Name']}"
            body = (f"Hi Harsh and AJ,\n\nRecipient: {d['Name']}\nPhone: {d['Phone']}\n"
                    f"Scheduled pickup: {d['Pickup_Date_Time']}\nStatus: {d['Status']}\n\n"
                    "Please contact the recipient to reschedule.")
        send_to_coordinators(cur, alert_id, subject, body, by, mode, dry, log)
    return {"pickup_alerts": len(todo)}


def run_check(mode="Manual", dry=False):
    """One full AI check. Returns a summary dict with a readable log."""
    log_once.clear()
    con = connect()
    cur = con.cursor(dictionary=True, buffered=True)
    d = today(cur)
    log = [f"AI check started ({mode}{', dry run' if dry else ''}) for date {d}"
           + (" (DEMO DATE)" if d != dt.date.today() else ""),
           "Muse AI: key set" if muse_enabled() else "Muse AI: no API key set, using templates"]
    try:
        res = pickup_check(cur, mode, dry, log)   # first, so items returned from missed pickups get checked too
        res.update(expiry_check(cur, mode, dry, log))
        if not dry:
            con.commit()
    finally:
        con.close()
    res["log"] = log
    return res


# ---------------- Muse AI: insights + Q&A from live tables ----------------
def data_snapshot(cur):
    """Small summary of the live tables to give Muse context (keeps prompts short and cheap)."""
    q = lambda s: (cur.execute(use_demo_dates(s, cur)), cur.fetchall())[1]
    return {
        "today": str(today(cur)),
        "stock_by_category": q("""SELECT c.Name category, COUNT(*) item_lines, SUM(i.Risk_Level='HIGH') high_risk
                                  FROM Inventory_Item i JOIN Category c USING(Category_ID)
                                  WHERE i.Status='Available' AND i.Quantity>0 GROUP BY c.Name"""),
        "expiring_soon": q("""SELECT i.Name item, i.Quantity qty, i.Unit unit, i.Expiration_Date expires,
                              DATEDIFF(i.Expiration_Date,CURDATE()) days_left FROM Inventory_Item i
                              WHERE i.Status='Available' AND i.Quantity>0 AND DATEDIFF(i.Expiration_Date,CURDATE()) BETWEEN 0 AND 5
                              ORDER BY i.Expiration_Date LIMIT 25"""),
        "waste_by_category": q("""SELECT c.Name category, COUNT(*) expired_items, SUM(e.Quantity) qty
                                  FROM Expiry_Record e JOIN Category c ON c.Category_ID=e.Category_ID
                                  GROUP BY c.Name ORDER BY expired_items DESC"""),
        "top_donors": q("""SELECT dn.Name donor, COUNT(DISTINCT d.Donation_ID) donations FROM Donation d
                           JOIN Donor dn USING(Donor_ID) GROUP BY dn.Name ORDER BY donations DESC LIMIT 5"""),
        "recipients": q("""SELECT r.Name, r.Household_Size, r.Food_Preferences,
                           SUM(d.Status='Fulfilled') hampers, SUM(d.Status IN ('Missed','Delayed')) missed_or_delayed
                           FROM Recipient r LEFT JOIN Distribution d USING(Recipient_ID)
                           WHERE r.Approval_Status='Approved' GROUP BY r.Recipient_ID"""),
        "upcoming_pickups": q("""SELECT r.Name recipient, d.Pickup_Date_Time pickup FROM Distribution d
                                 JOIN Recipient r USING(Recipient_ID) WHERE d.Status='Scheduled'"""),
    }


def basic_report(snap):
    """Backup report from the same data, used when Muse AI can't be reached."""
    L = [f"Inventory report for {snap['today']} (basic report: Muse AI unavailable)", ""]
    L.append("Waste by category (most first):")
    L += [f"  {w['category']}: {w['expired_items']} expired items" for w in snap["waste_by_category"]] or ["  none"]
    L += ["", "Use first (expiring within 5 days):"]
    L += [f"  {e['item']} - {float(e['qty']):g} {e['unit']}, {e['days_left']} day(s) left" for e in snap["expiring_soon"][:10]] or ["  nothing urgent"]
    L += ["", "Upcoming pickups:"]
    for p in snap["upcoming_pickups"]:
        r = next((x for x in snap["recipients"] if x["Name"] == p["recipient"]), {})
        L.append(f"  {p['recipient']} on {p['pickup']} - dietary needs: {r.get('Food_Preferences') or 'none'}")
    if not snap["upcoming_pickups"]:
        L.append("  none scheduled")
    return "\n".join(L)


def insights(question=None):
    """Muse AI reads the live tables and writes a report, or answers a question."""
    con = connect()
    cur = con.cursor(dictionary=True, buffered=True)
    try:
        snap = data_snapshot(cur)
    finally:
        con.close()
    if question:
        prompt = (f"Answer the coordinator's question using ONLY this live data from the food bank database. "
                  f"If the data does not contain the answer, say so.\nQuestion: {question}\n"
                  f"Data: {json.dumps(snap, default=str)}")
    else:
        prompt = ("Using this live data, write a short inventory insight report for the coordinators with these parts: "
                  "1) Shelf-life trend: which categories expire fastest and waste the most. "
                  "2) Use first: the most urgent items. "
                  "3) Hamper suggestion: for each upcoming pickup, suggest items that respect the recipient's dietary needs. "
                  "4) One practical tip to reduce waste.\n"
                  f"Data: {json.dumps(snap, default=str)}")
    if not muse_enabled():
        return {"ok": False, "text": "Muse AI key is missing in .env, so here is the basic report instead.\n\n" + basic_report(snap)}
    try:
        return {"ok": True, "text": muse_chat(prompt, max_tokens=900)}
    except Exception as e:
        return {"ok": False, "text": f"{e}\n\nShowing the basic report instead:\n\n" + basic_report(snap)}


if __name__ == "__main__":
    out = run_check(mode="Manual", dry="--dry-run" in sys.argv)
    print("\n".join(out["log"]))
