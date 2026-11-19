"""
AI engine for the Food Bank system (Algorithm 3: expiry risk, Algorithm 4: missed/delayed pickups).

Runs automatically, no button needed:
  - when app.py starts, then every AI_EVERY_HOURS, plus a quick pickup check every PICKUP_CHECK_MINUTES
  - right after data changes (an expiry date or the demo date changes, test data is reset)
  - from the command line / Windows Task Scheduler:  python ai_engine.py
                             python ai_engine.py --dry-run  (preview, changes nothing)

Who gets the alert emails: every active coordinator AND every volunteer working a shift that day
(for expiry alerts, also volunteers on any shift before the items expire).
                             python ai_engine.py --dry-run  (preview, changes nothing)

What the AI does:
  1. Writes the alert emails sent to the coordinators
  2. Writes an inventory insight report from the live tables
  3. Answers coordinator questions about the data

The expiry and late-pickup rules are plain code, so the data is always correct.
The AI only writes text. If it is unreachable, a built-in template is used, so alerts never stop.
Works with any OpenAI-compatible service (Google Gemini free tier by default).
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

# Any OpenAI-compatible AI service works. Set AI_API_KEY / AI_API_URL / AI_MODEL in .env
# (the older MUSE_* names still work). Default: Google Gemini free tier.
MUSE_API_KEY = os.getenv("AI_API_KEY") or os.getenv("MUSE_API_KEY")
_url = os.getenv("AI_API_URL") or os.getenv("MUSE_API_URL")
_model = os.getenv("AI_MODEL") or os.getenv("MUSE_MODEL")
_G = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# Free-tier Gemini models, newest first. If Google retires one, the next is tried automatically.
GEMINI_MODELS = [(_G, m) for m in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")]
GEMINI = GEMINI_MODELS[0]
PROVIDERS = []
if _url:
    PROVIDERS.append((_url, _model or GEMINI[1]))
if MUSE_API_KEY and MUSE_API_KEY.startswith("AIza"):      # Google keys start with AIza
    PROVIDERS += GEMINI_MODELS
PROVIDERS += [("https://api.meta.ai/v1/chat/completions", "muse-spark-1.3"),
              ("https://api.aimlapi.com/v1/chat/completions", "meta/muse-spark-1.3")]
PROVIDERS = list(dict.fromkeys(PROVIDERS))
_working = {}   # remembers which provider worked

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER
# Test accounts use fake addresses (@surreyfoodbank.test). Put a real inbox here and their alerts are
# delivered to it (marked with who they were for), so every email really arrives during testing/demo.
ALERT_REDIRECT_TO = (os.getenv("ALERT_REDIRECT_TO") or "").strip()
FAKE_DOMAINS = (".test", ".example", ".invalid")
RISK_DAYS = int(os.getenv("RISK_DAYS", "3"))      # always at risk with this many days or fewer left
LOW_STOCK = int(os.getenv("LOW_STOCK", "5"))      # category is "running low" below this many item lines


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


# ---------------- AI service ----------------
def muse_enabled():
    return bool(MUSE_API_KEY)


def muse_chat(prompt, max_tokens=2000):
    """Send one prompt to the AI. Tries each provider until one accepts the key. Raises with a clear reason."""
    order = ([_working["p"]] if "p" in _working else []) + [p for p in PROVIDERS if p != _working.get("p")]
    errors = []
    for url, model in order:
        try:
            body = {"model": model, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": prompt}]}
            if "googleapis" in url:
                body["reasoning_effort"] = "low"     # faster answers, fewer timeouts
            r = requests.post(url, timeout=90, json=body,
                              headers={"Authorization": f"Bearer {MUSE_API_KEY}", "Content-Type": "application/json"})
            if r.status_code in (400, 401, 403, 404, 429) or r.status_code >= 500:
                errors.append(f"{url.split('/')[2]} ({model}): {r.status_code} {' '.join(r.text.split())[:160]}")
                continue
            r.raise_for_status()
            _working["p"] = (url, model)
            return r.json()["choices"][0]["message"]["content"].strip()
        except requests.RequestException as e:
            errors.append(f"{url.split('/')[2]}: {e.__class__.__name__}")
    raise RuntimeError("The AI service rejected the request. " + " | ".join(errors))


def muse_status():
    if not MUSE_API_KEY:
        return "no key"
    return f"connected ({_working['p'][1]})" if "p" in _working else "key set"


def muse_email(task, data, log):
    """Ask the AI to write an email. Returns (subject, body) or None."""
    if not muse_enabled():
        return None
    try:
        text = muse_chat(f"Task: {task}\nReturn JSON only: {{\"subject\": \"...\", \"body\": \"...\"}}\n"
                         f"Data: {json.dumps(data, default=str)}")
        out = json.loads(text[text.find("{"): text.rfind("}") + 1])
        subject, body = str(out["subject"]).strip()[:250], str(out["body"]).strip()
        if not subject or not body:
            raise ValueError("empty email")
        return subject, body
    except Exception as e:
        log.append(f"AI unavailable, used template ({e.__class__.__name__})")
        return None


# ---------------- email ----------------
log_once = {}


def coordinators(cur):
    cur.execute("""SELECT u.User_ID, u.Email, c.Name FROM Coordinator c
                   JOIN User_Account u ON u.User_ID = c.User_ID WHERE u.Is_Active = 1""")
    return cur.fetchall()


def day_volunteers(cur):
    """Volunteers working a shift today (demo date aware). They are on site, so they get every alert."""
    cur.execute("""SELECT DISTINCT u.User_ID, u.Email, v.Name FROM Shift s
                   JOIN Shift_Assignment sa USING (Shift_ID) JOIN Volunteer v USING (Volunteer_ID)
                   JOIN User_Account u ON u.User_ID = v.User_ID
                   WHERE u.Is_Active = 1 AND DATE(s.Start_Time) = %s""", (today(cur),))
    return cur.fetchall()


def alert_people(cur, log, until=None):
    """Coordinators + volunteers working today (+ volunteers on shifts before `until`), no duplicates."""
    coords, today_vols = coordinators(cur), day_volunteers(cur)
    extra = shift_volunteers(cur, until) if until else []
    people = {p["User_ID"]: p for p in coords + today_vols + extra}
    log.append(f"  Recipients: {len(coords)} coordinator(s), "
               + (f"{len(today_vols)} volunteer(s) on shift today ({', '.join(v['Name'] for v in today_vols)})"
                  if today_vols else "no volunteer on shift today")
               + (f", {len(people) - len(coords) - len(today_vols)} more on upcoming shifts" if until else ""))
    return list(people.values())


def shift_volunteers(cur, until):
    """Volunteers assigned to shifts between now and `until` (they can prioritise at-risk food)."""
    cur.execute(use_demo_dates("""SELECT DISTINCT u.User_ID, u.Email, v.Name FROM Shift s
                   JOIN Shift_Assignment sa USING (Shift_ID) JOIN Volunteer v USING (Volunteer_ID)
                   JOIN User_Account u ON u.User_ID = v.User_ID
                   WHERE u.Is_Active = 1 AND s.End_Time >= NOW() AND s.Start_Time <= %s""", cur), (until,))
    return cur.fetchall()


def _deliver(smtp, to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SMTP_FROM, to, subject
    msg.set_content(body)
    smtp.send_message(msg)


def _smtp():
    """One SMTP connection for a whole batch. Port 465 = SSL, otherwise STARTTLS.
    SMTP_SECURITY=none is only for a local test mail catcher."""
    mode = os.getenv("SMTP_SECURITY") or ("ssl" if SMTP_PORT == 465 else "starttls")
    if mode == "ssl":
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    else:
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        if mode == "starttls":
            s.starttls()
    if mode != "none":
        s.login(SMTP_USER, SMTP_PASS)
    return s


def send_alert(cur, people, alert_id, subject, body, written_by, mode, dry, log):
    """Email every person and record each one in Email_Log (Sent / Logged only / Failed)."""
    smtp, smtp_error = None, None
    if smtp_ready() and not dry:
        try:
            smtp = _smtp()
        except Exception as e:
            smtp_error = str(e)[:150]
            log.append(f"  Could not connect to the email server: {smtp_error}")
    try:
        for c in people:
            status, note = "Logged only", ""
            fake = c["Email"].lower().endswith(FAKE_DOMAINS)
            to = ALERT_REDIRECT_TO if fake and ALERT_REDIRECT_TO else (None if fake else c["Email"])
            if smtp and to:
                try:
                    text = body if to == c["Email"] else f"[Test account: this alert is for {c['Name']} <{c['Email']}>]\n\n{body}"
                    _deliver(smtp, to, subject, text)
                    status, note = "Sent", (f" (delivered to {to})" if to != c["Email"] else "")
                except Exception as e:
                    status = "Failed"; log.append(f"  Email to {c['Email']} failed: {str(e)[:150]}")
            elif smtp_error:
                status = "Failed"
            if not dry:
                cur.execute("""INSERT INTO Email_Log (Alert_ID,To_User_ID,To_Email,Subject,Body,Written_By,Run_Mode,Status)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (alert_id, c["User_ID"], c["Email"], subject, body, written_by, mode, status))
            log.append(f"  Email to {c['Name']} ({c['Email']}): {status}{note} - {subject}")
            if status == "Logged only" and not dry and not log_once.get("smtp"):
                log_once["smtp"] = True
                log.append("  (Saved in Email_Log only. " + (
                    "Set ALERT_REDIRECT_TO in .env to receive test-account emails in a real inbox.)" if smtp_ready()
                    else "Add SMTP_USER and SMTP_PASS (Gmail App Password) to .env to really send emails.)"))
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                pass


# ---------------- Algorithm 3: expiry ----------------
def expiry_check(cur, mode, dry, log):
    day = today(cur)
    # SRS 3.1.3: "at risk of expiring before distribution" = expires before the next distribution
    # shift (or within RISK_DAYS days, whichever is later)
    cur.execute(use_demo_dates("""SELECT MIN(Start_Time) AS t FROM Shift WHERE Start_Time >= NOW()
                   AND (Task LIKE '%%istribution%%' OR Task LIKE '%%amper%%')""", cur))
    row = cur.fetchone()
    next_dist = row["t"].date() if row and row["t"] else None
    log.append(f"  Next distribution shift: {next_dist or 'none scheduled'}")
    cur.execute("""SELECT i.Item_ID, i.Name, i.Quantity, i.Unit, i.Expiration_Date, i.Category_ID, c.Name AS Category
                   FROM Inventory_Item i JOIN Category c USING (Category_ID)
                   WHERE i.Status='Available' AND i.Quantity > 0""")
    expired, high = [], []
    for it in cur.fetchall():
        left = (it["Expiration_Date"] - day).days
        if left < 0:
            expired.append(it)
            if not dry:
                # SRS 3.1.2: quantity goes down when expired items are removed (amount kept in Expiry_Record)
                cur.execute("UPDATE Inventory_Item SET Status='Expired', Risk_Level='OK', Quantity=0 WHERE Item_ID=%s", (it["Item_ID"],))
                cur.execute("""INSERT IGNORE INTO Expiry_Record (Item_ID,Quantity,Expired_On,Category_ID,Recorded_At)
                               VALUES (%s,%s,%s,%s,%s)""",
                            (it["Item_ID"], it["Quantity"], it["Expiration_Date"], it["Category_ID"], now(cur)))
                log.append(f"  Removed from inventory: {it['Name']} ({it['Quantity']:g} {it['Unit']}), expired {it['Expiration_Date']}")
        elif left <= RISK_DAYS or (next_dist and it["Expiration_Date"] < next_dist):
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
    low = declining_stock(cur, dry, log)
    if not high and not low:
        return {"expired": len(expired), "at_risk": 0, "low_stock": 0}

    alert_id = None
    for it in high:
        if not dry:
            cur.execute("INSERT INTO Alert (Type, Item_ID, Message, Date_Time) VALUES ('Expiry Risk', %s, %s, %s)",
                        (it["Item_ID"], f"{it['Name']}: {it['Quantity']} {it['Unit']} expires {it['Expiration_Date']}", now(cur)))
            alert_id = alert_id or cur.lastrowid

    rows = sorted([{"item": i["Name"], "category": i["Category"], "qty": f"{i['Quantity']:g} {i['Unit']}",
                    "expires": i["Expiration_Date"], "days_left": i["days_left"]} for i in high],
                  key=lambda r: r["days_left"])
    ai = muse_email("Write ONE email to the food bank coordinators and the volunteers on shift. List these at-risk "
                    "items, most urgent first, and ask for them to go out in the next hampers. If low_stock is not "
                    "empty, add a short section about those categories running low.",
                    {"at_risk_items": rows, "low_stock": low, "next_distribution_shift": next_dist}, log)
    if ai:
        subject, body, by = ai[0], ai[1], "AI"
    else:
        by = "Template"
        subject = (f"[Food Bank] {len(high)} items at risk of expiring - priority distribution" if high
                   else f"[Food Bank] {len(low)} categories running low")
        body = "Hi team,\n\n"
        if high:
            body += "These items need to go out in the next hampers:\n\n" + "\n".join(
                f"- {r['item']} ({r['qty']}), expires {r['expires']}, {r['days_left']} day(s) left" for r in rows) + "\n\n"
        if low:
            body += "Running low (fewer than %d item lines in stock):\n\n" % LOW_STOCK + "\n".join(
                f"- {c['category']}: {c['lines']} item lines left" for c in low) + "\n\n"
        body += "Automated alert from the Food Bank system."
    # SRS 3.1.3: coordinators AND volunteers on upcoming shifts before these items expire (+ today's volunteers)
    alert_id = alert_id or low_alert_id[0]
    until = dt.datetime.combine(max([i["Expiration_Date"] for i in high] or [today(cur)]), dt.time.max)
    send_alert(cur, alert_people(cur, log, until), alert_id, subject, body, by, mode, dry, log)
    return {"expired": len(expired), "at_risk": len(high), "low_stock": len(low)}


low_alert_id = [None]


def declining_stock(cur, dry, log):
    """SRS 3.1.3 'flagging declining stock': categories with fewer than LOW_STOCK item lines left in date.
    One 'Inventory Trend' alert per category per 24 hours."""
    low_alert_id[0] = None
    cur.execute(use_demo_dates("""SELECT c.Category_ID, c.Name AS category,
                   SUM(i.Status='Available' AND i.Quantity>0 AND i.Expiration_Date>=CURDATE()) AS line_count
                   FROM Category c LEFT JOIN Inventory_Item i USING (Category_ID)
                   GROUP BY c.Category_ID HAVING line_count < %s""", cur), (LOW_STOCK,))
    out = []
    for c in cur.fetchall():
        msg = f"Low stock: {c['category']} ({int(c['line_count'] or 0)} item lines left)"
        cur.execute(use_demo_dates("""SELECT 1 FROM Alert WHERE Type='Inventory Trend' AND Message LIKE %s
                       AND Date_Time >= NOW() - INTERVAL 24 HOUR""", cur), (f"Low stock: {c['category']} %",))
        if cur.fetchall():
            continue
        if not dry:
            cur.execute("INSERT INTO Alert (Type, Message, Date_Time) VALUES ('Inventory Trend', %s, %s)", (msg, now(cur)))
            low_alert_id[0] = low_alert_id[0] or cur.lastrowid
        out.append({"category": c["category"], "lines": int(c["line_count"] or 0)})
    log.append(f"Stock trend check: {len(out)} categories newly running low")
    return out


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
                # put the reserved food back on the shelf (items that expired meanwhile stay expired)
                cur.execute("""UPDATE Inventory_Item i JOIN Distribution_Item di ON di.Item_ID=i.Item_ID
                               SET i.Quantity=i.Quantity+di.Quantity,
                                   i.Status=IF(i.Status='Expired','Expired','Available')
                               WHERE di.Distribution_ID=%s""", (d["Distribution_ID"],))
                cur.execute("""UPDATE Expiry_Record e JOIN Distribution_Item di ON di.Item_ID=e.Item_ID
                               SET e.Quantity=e.Quantity+di.Quantity WHERE di.Distribution_ID=%s""",
                            (d["Distribution_ID"],))

    # any Missed/Delayed pickup (automatic or marked by a volunteer) without an alert yet
    cur.execute("""SELECT d.Distribution_ID, d.Pickup_Date_Time, d.Status, r.Name, r.Phone
                   FROM Distribution d JOIN Recipient r USING (Recipient_ID)
                   WHERE d.Status IN ('Missed','Delayed')
                   AND NOT EXISTS (SELECT 1 FROM Alert a WHERE a.Distribution_ID=d.Distribution_ID AND a.Type=d.Status)""")
    todo = cur.fetchall()
    log.append(f"Pickup check: {len(todo)} missed/delayed pickups need an alert")
    if not todo:
        return {"pickup_alerts": 0}
    alert_id = None
    for d in todo:
        if not dry:
            cur.execute("INSERT INTO Alert (Type, Distribution_ID, Message, Date_Time) VALUES (%s,%s,%s,%s)",
                        (d["Status"], d["Distribution_ID"], f"{d['Name']} pickup {d['Status'].lower()}", cur_now))
            alert_id = alert_id or cur.lastrowid
    # one combined email (one AI request) for all missed/delayed pickups, to stay inside free-tier limits
    rows = [{"recipient": d["Name"], "phone": d["Phone"], "pickup_time": d["Pickup_Date_Time"], "status": d["Status"]}
            for d in todo]
    ai = muse_email("Write ONE email telling the coordinators and today's shift volunteers about these missed or "
                    "delayed hamper pickups, and suggest calling each recipient to reschedule.", rows, log)
    if ai:
        subject, body, by = ai[0], ai[1], "AI"
    else:
        by = "Template"
        subject = f"[Food Bank] {len(todo)} pickup(s) missed or delayed"
        body = "Hi team,\n\nThese pickups need follow-up:\n\n" + "\n".join(
            f"- {r['recipient']} ({r['phone']}), pickup {r['pickup_time']}: {r['status']}" for r in rows) + \
            "\n\nPlease contact them to reschedule."
    send_alert(cur, alert_people(cur, log), alert_id, subject, body, by, mode, dry, log)   # coordinators + today's volunteers
    return {"pickup_alerts": len(todo)}


def run_check(mode="Automatic", dry=False, pickups_only=False):
    """One full check (or only the quick pickup check). Returns a summary dict with a readable log."""
    log_once.clear()
    con = connect()
    cur = con.cursor(dictionary=True, buffered=True)
    d = today(cur)
    log = [f"AI check started ({mode}{', dry run' if dry else ''}) for date {d}"
           + (" (DEMO DATE)" if d != dt.date.today() else ""),
           "AI: key set" if muse_enabled() else "AI: no API key set, using templates"]
    try:
        res = pickup_check(cur, mode, dry, log)   # first, so items returned from missed pickups get checked too
        if not pickups_only:
            res.update(expiry_check(cur, mode, dry, log))
        if not dry:
            con.commit()
    finally:
        con.close()
    res["log"] = log
    return res


# ---------------- AI: insights + Q&A from live tables ----------------
def data_snapshot(cur):
    """Small summary of the live tables to give the AI context (keeps prompts short and cheap)."""
    q = lambda s: (cur.execute(use_demo_dates(s, cur)), cur.fetchall())[1]
    return {
        "today": str(today(cur)),
        "stock_by_category": q("""SELECT c.Name category, COUNT(*) item_lines,
                                  SUM(DATEDIFF(i.Expiration_Date,CURDATE())<=3) high_risk
                                  FROM Inventory_Item i JOIN Category c USING(Category_ID)
                                  WHERE i.Status='Available' AND i.Quantity>0 AND i.Expiration_Date>=CURDATE()
                                  GROUP BY c.Name"""),
        "expiring_soon": q("""SELECT i.Name item, i.Quantity qty, i.Unit unit, i.Expiration_Date expires,
                              DATEDIFF(i.Expiration_Date,CURDATE()) days_left FROM Inventory_Item i
                              WHERE i.Status='Available' AND i.Quantity>0 AND DATEDIFF(i.Expiration_Date,CURDATE()) BETWEEN 0 AND 5
                              ORDER BY i.Expiration_Date LIMIT 25"""),
        "waste_by_category": q("""SELECT c.Name category, COUNT(*) expired_items, SUM(e.Quantity) qty
                                  FROM Expiry_Record e JOIN Category c ON c.Category_ID=e.Category_ID
                                  GROUP BY c.Name ORDER BY expired_items DESC"""),
        "in_stock_items": q("""SELECT i.Name item, c.Name category, i.Quantity qty, i.Unit unit,
                               DATEDIFF(i.Expiration_Date,CURDATE()) days_left
                               FROM Inventory_Item i JOIN Category c USING(Category_ID)
                               WHERE i.Status='Available' AND i.Quantity>0 AND i.Expiration_Date>=CURDATE()
                               ORDER BY i.Expiration_Date LIMIT 120"""),
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
    """Backup report from the same data, used when the AI can't be reached."""
    L = [f"Inventory report for {snap['today']} (basic report: AI unavailable)", ""]
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
    """The AI reads the live tables and writes a report, or answers a question."""
    con = connect()
    cur = con.cursor(dictionary=True, buffered=True)
    try:
        snap = data_snapshot(cur)
    finally:
        con.close()
    if question:
        prompt = (f"Answer the coordinator's question using ONLY this live data from the food bank database. "
                  f"For hamper questions, pick specific items from in_stock_items (soonest expiry first) that fit the "
                  f"recipient's household size and dietary needs, with quantities. If the data truly cannot answer, say so.\nQuestion: {question}\n"
                  f"Data: {json.dumps(snap, default=str)}")
    else:
        prompt = ("Using this live data, write a short inventory insight report for the coordinators with these parts: "
                  "1) Shelf-life trend: which categories expire fastest and waste the most. "
                  "2) Use first: the most urgent items. "
                  "3) Hamper suggestion: for each upcoming pickup, suggest items that respect the recipient's dietary needs. "
                  "4) One practical tip to reduce waste.\n"
                  f"Data: {json.dumps(snap, default=str)}")
    if not muse_enabled():
        return {"ok": False, "text": "AI key is missing in .env, so here is the basic report instead.\n\n" + basic_report(snap)}
    try:
        return {"ok": True, "text": muse_chat(prompt, max_tokens=2500)}
    except Exception as e:
        return {"ok": False, "text": f"{e}\n\nShowing the basic report instead:\n\n" + basic_report(snap)}


if __name__ == "__main__":
    out = run_check(mode="Automatic", dry="--dry-run" in sys.argv)   # scheduled task / command line
    print("\n".join(out["log"]))
