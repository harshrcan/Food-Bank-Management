"""
AI engine for the Food Bank system (Algorithm 3: expiry risk, Algorithm 4: missed/delayed pickups).

Used two ways:
  - by the web app (app.py): "Run AI check" button + automatic run every 6 hours
  - from the command line:   python ai_engine.py            (one manual run)
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

SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASS = (os.getenv("SMTP_PASS") or "").replace(" ", "")       # Gmail shows App Passwords with spaces
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME") or "Surrey Community Food Bank"
SMTP_SECURITY = (os.getenv("SMTP_SECURITY") or ("ssl" if SMTP_PORT == 465 else "starttls")).lower()


def smtp_ready():
    """True only if real SMTP details are filled in (not the .env.example placeholders)."""
    vals = [SMTP_HOST, SMTP_USER, SMTP_PASS]
    return all(vals) and not any(v.lower().startswith("your") or "yourteam" in v.lower() for v in vals)


def is_real_address(addr):
    """Made-up test accounts (.test, .example, example.com) are logged but never emailed."""
    addr = addr.lower()
    return not (addr.endswith((".test", ".example", ".invalid"))
                or addr.split("@")[-1] in ("example.com", "example.org", "example.net"))


def smtp_settings_problem():
    """Catches the common mix-up before trying: a non-Gmail address or a normal password used with Gmail."""
    if "gmail" in SMTP_HOST.lower():
        if not SMTP_USER.lower().endswith(("@gmail.com", "@googlemail.com")):
            return (f"SMTP_USER is {SMTP_USER.split('@')[0][:2]}***@{SMTP_USER.split('@')[-1]}, but smtp.gmail.com only "
                    "accepts a Gmail address. Put a Gmail address in SMTP_USER and that account's App Password in SMTP_PASS. "
                    "(Do not put your school password in .env.)")
        if len(SMTP_PASS) != 16 or not SMTP_PASS.isalpha():
            return ("SMTP_PASS does not look like a Gmail App Password (16 letters). Make one at "
                    "myaccount.google.com/apppasswords. Your normal Gmail password will not work.")
    return None


def explain_smtp_error(e):
    """Turns mail-server errors into a plain fix."""
    hint = smtp_settings_problem()
    if hint:
        return hint
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ("The mail server rejected the login. For Gmail, SMTP_PASS must be a 16-letter App Password "
                "(myaccount.google.com/apppasswords), not your normal password, and SMTP_USER must be that Gmail address.")
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient address."
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return ("The mail server closed the connection. Usually the login details are wrong (Gmail needs a Gmail "
                "address and an App Password), or antivirus or the network is blocking email. Try another network, "
                "or set SMTP_PORT=465 in .env.")
    if isinstance(e, (OSError, smtplib.SMTPConnectError)):
        return f"Could not reach the mail server {SMTP_HOST}:{SMTP_PORT} ({e.__class__.__name__}). Check SMTP_HOST, SMTP_PORT and your internet."
    return str(e)[:300] if isinstance(e, ValueError) else f"{e.__class__.__name__}: {str(e)[:150]}"


def smtp_connect():
    """Opens one logged-in connection to the mail server (reused for every email in a batch)."""
    hint = smtp_settings_problem()
    if hint:
        raise ValueError(hint)
    if SMTP_SECURITY == "ssl":
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
    else:
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        if SMTP_SECURITY == "starttls":
            s.starttls()
    s.login(SMTP_USER, SMTP_PASS)
    return s


def send_emails(batch):
    """batch: list of (to_address, subject, body). Returns a list of (status, error) in the same order."""
    if not batch:
        return []
    try:
        server = smtp_connect()
    except Exception as e:
        err = explain_smtp_error(e)
        return [("Failed", err)] * len(batch)
    results = []
    try:
        for to, subject, body in batch:
            msg = EmailMessage()
            msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
            msg["To"], msg["Subject"] = to, subject
            msg.set_content(body + "\n\n--\nSent automatically by the Surrey Community Food Bank system.")
            try:
                server.send_message(msg)
                results.append(("Sent", None))
            except Exception as e:
                results.append(("Failed", explain_smtp_error(e)))
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return results


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


def shift_volunteers(cur, until):
    """Volunteers assigned to shifts between now and `until` (they can prioritise at-risk food)."""
    cur.execute(use_demo_dates("""SELECT DISTINCT u.User_ID, u.Email, v.Name FROM Shift s
                   JOIN Shift_Assignment sa USING (Shift_ID) JOIN Volunteer v USING (Volunteer_ID)
                   JOIN User_Account u ON u.User_ID = v.User_ID
                   WHERE u.Is_Active = 1 AND s.End_Time >= NOW() AND s.Start_Time <= %s""", cur), (until,))
    return cur.fetchall()


def send_alert(cur, people, alert_id, subject, body, written_by, mode, dry, log):
    """Emails every real address in one connection, and records every recipient in Email_Log."""
    to_send = [c for c in people if smtp_ready() and is_real_address(c["Email"]) and not dry]
    results = dict(zip([c["User_ID"] for c in to_send], send_emails([(c["Email"], subject, body) for c in to_send])))
    for c in people:
        status, err = results.get(c["User_ID"], ("Logged only", None))
        if err and not log_once.get(err):
            log_once[err] = True
            log.append(f"  Email problem: {err}")
        if not dry:
            cur.execute("""INSERT INTO Email_Log (Alert_ID,To_User_ID,To_Email,Subject,Body,Written_By,Run_Mode,Status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (alert_id, c["User_ID"], c["Email"], subject, body, written_by, mode, status))
        log.append(f"Email to {c['Name']} ({c['Email']}): {status} - {subject}")
    if not smtp_ready() and not dry and not log_once.get("smtp"):
        log_once["smtp"] = True
        log.append("  (Saved in Email_Log only. Add SMTP_USER and SMTP_PASS to .env to really send emails.)")


def send_test_email():
    """Sends a test email to every coordinator, so you can confirm real sending works."""
    log = []
    log_once.clear()
    if not smtp_ready():
        return {"ok": False, "log": ["Email is not set up. Put your Gmail address in SMTP_USER and a Gmail App Password "
                                     "in SMTP_PASS in .env, then restart the app."]}
    con = connect()
    cur = con.cursor(dictionary=True, buffered=True)
    try:
        people = coordinators(cur)
        body = (f"Hi {', '.join(p['Name'] for p in people)},\n\nThis is a test email from the Food Bank system, sent "
                f"{dt.datetime.now():%Y-%m-%d %H:%M}. If you can read this, alert emails are working.\n\n"
                "You will get emails like this when a pickup is missed or delayed, and when food is about to expire.")
        send_alert(cur, people, None, "[Food Bank] Test email: alerts are working", body, "Template", "Manual", False, log)
        con.commit()
    finally:
        con.close()
    return {"ok": not any("Email problem" in x for x in log), "log": log}


# ---------------- Algorithm 3: expiry ----------------
RISK_HIGH_DAYS = 3        # 3 days or less left: give it out in the next hampers
WATCH_DAYS = 7            # look this far ahead for food that cannot all be given out in time
OUTFLOW_DAYS = 28         # recent hamper history used to estimate how fast each category goes out
SUPPLY_DAYS_MIN = 7       # less than a week of supply that will still be good next week: declining


def category_rates(cur):
    """Units given out per day for each category, over the last OUTFLOW_DAYS days."""
    cur.execute(use_demo_dates(f"""SELECT i.Category_ID, SUM(di.Quantity) qty FROM Distribution d
                   JOIN Distribution_Item di USING (Distribution_ID) JOIN Inventory_Item i USING (Item_ID)
                   WHERE d.Status IN ('Fulfilled','Delayed')
                   AND d.Pickup_Date_Time BETWEEN NOW() - INTERVAL {OUTFLOW_DAYS} DAY AND NOW()
                   GROUP BY i.Category_ID""", cur))
    return {r["Category_ID"]: float(r["qty"]) / OUTFLOW_DAYS for r in cur.fetchall()}


def declining_categories(cur, rates):
    """Categories running low: the stock that will STILL be good a week from now would last less than
    SUPPLY_DAYS_MIN days at the current pace. (Plenty of food that all expires this week is not real supply.)"""
    cur.execute(use_demo_dates("""SELECT c.Category_ID, c.Name,
                   COALESCE(SUM(IF(i.Expiration_Date >= CURDATE(), i.Quantity, 0)), 0) stock_now,
                   COALESCE(SUM(IF(i.Expiration_Date > CURDATE() + INTERVAL 7 DAY, i.Quantity, 0)), 0) stock_next_week
                   FROM Category c LEFT JOIN Inventory_Item i ON i.Category_ID=c.Category_ID AND i.Status='Available'
                   GROUP BY c.Category_ID, c.Name""", cur))
    out = []
    for r in cur.fetchall():
        rate = rates.get(r["Category_ID"], 0)
        if not rate:
            continue
        days = float(r["stock_next_week"]) / rate
        if days < SUPPLY_DAYS_MIN:
            out.append({"category": r["Name"], "days_of_supply_next_week": round(days, 1),
                        "why": (f"only {float(r['stock_next_week']):g} of {float(r['stock_now']):g} units will still be good "
                                f"in a week, about {days:.0f} days of supply at {rate:.1f} given out per day")})
    return out


def expiry_check(cur, mode, dry, log):
    """Algorithm 3. For every item in stock: expired, HIGH (3 days or less), WATCH (the category cannot
    give it all out before it expires, at the current pace) or OK. Also flags declining categories."""
    day = today(cur)
    cur.execute("""SELECT i.Item_ID, i.Name, i.Quantity, i.Unit, i.Expiration_Date, i.Category_ID, c.Name AS Category
                   FROM Inventory_Item i JOIN Category c USING (Category_ID)
                   WHERE i.Status='Available' AND i.Quantity > 0
                   ORDER BY i.Category_ID, i.Expiration_Date, i.Item_ID""")
    rows = cur.fetchall()
    rates = category_rates(cur)
    cur.execute(use_demo_dates("""SELECT DISTINCT Item_ID FROM Alert WHERE Type='Expiry Risk'
                   AND Date_Time >= NOW() - INTERVAL 24 HOUR""", cur))
    alerted = {r["Item_ID"] for r in cur.fetchall()}

    expired, high, watch, ok, new_high = [], [], [], [], []
    ahead = {}                              # units of this category that expire before (or with) this item
    for it in rows:
        left = (it["Expiration_Date"] - day).days
        it["days_left"] = left
        if left < 0:
            expired.append(it)
            continue
        ahead[it["Category_ID"]] = ahead.get(it["Category_ID"], 0) + float(it["Quantity"])
        can_give = rates.get(it["Category_ID"], 0) * (left + 1)          # what we can hand out before it expires
        if left <= RISK_HIGH_DAYS:
            high.append(it)
            if it["Item_ID"] not in alerted:
                new_high.append(it)
        elif left <= WATCH_DAYS and ahead[it["Category_ID"]] > can_give:
            watch.append(it)
        else:
            ok.append(it)

    if not dry:
        for it in expired:
            cur.execute("""INSERT IGNORE INTO Expiry_Record (Item_ID,Quantity,Expired_On,Category_ID,Recorded_At)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (it["Item_ID"], it["Quantity"], it["Expiration_Date"], it["Category_ID"], now(cur)))
        for level, group in (("Expired", expired), ("HIGH", high), ("WATCH", watch), ("OK", ok)):
            ids = [it["Item_ID"] for it in group]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join(["%s"] * len(chunk))
                if level == "Expired":
                    cur.execute(f"UPDATE Inventory_Item SET Status='Expired', Risk_Level='OK' WHERE Item_ID IN ({marks})", chunk)
                else:
                    cur.execute(f"UPDATE Inventory_Item SET Risk_Level=%s WHERE Item_ID IN ({marks})", [level] + chunk)
    for it in expired[:10]:
        log.append(f"  Removed from inventory: {it['Name']} ({it['Quantity']:g} {it['Unit']}), expired {it['Expiration_Date']}")
    if len(expired) > 10:
        log.append(f"  ...and {len(expired) - 10} more (see the Expiry section)")

    declining = declining_categories(cur, rates)
    new_declining = []
    for d in declining:
        cur.execute(use_demo_dates("""SELECT 1 FROM Alert WHERE Type='Inventory Trend' AND Message LIKE %s
                       AND Date_Time >= NOW() - INTERVAL 24 HOUR""", cur), (f"Declining stock: {d['category']}%",))
        if not cur.fetchall():
            new_declining.append(d)
    log.append(f"Expiry check: {len(expired)} expired and removed, {len(high)} HIGH risk ({len(new_high)} new), "
               f"{len(watch)} on WATCH (may expire before they can be given out), {len(declining)} declining categories")
    for d in declining:
        log.append(f"  Declining: {d['category']}: {d['why']}")
    if not new_high and not new_declining:
        return {"expired": len(expired), "at_risk": 0, "watch": len(watch)}

    alert_id = None
    if not dry:
        for it in new_high:
            cur.execute("INSERT INTO Alert (Type, Item_ID, Message, Date_Time) VALUES ('Expiry Risk', %s, %s, %s)",
                        (it["Item_ID"], f"{it['Name']}: {it['Quantity']:g} {it['Unit']} expires {it['Expiration_Date']}", now(cur)))
            alert_id = alert_id or cur.lastrowid
        for d in new_declining:
            cur.execute("INSERT INTO Alert (Type, Message, Date_Time) VALUES ('Inventory Trend', %s, %s)",
                        (f"Declining stock: {d['category']}: {d['why']}", now(cur)))
            alert_id = alert_id or cur.lastrowid

    urgent = sorted(new_high, key=lambda i: (i["days_left"], -float(i["Quantity"])))
    rows_out = [{"item": i["Name"], "category": i["Category"], "qty": f"{i['Quantity']:g} {i['Unit']}",
                 "expires": i["Expiration_Date"], "days_left": i["days_left"]} for i in urgent[:40]]
    watch_by_cat = {}
    for it in watch:
        watch_by_cat[it["Category"]] = watch_by_cat.get(it["Category"], 0) + 1
    data = {"new_high_risk_count": len(new_high), "most_urgent": rows_out, "watch_items_by_category": watch_by_cat,
            "declining_categories": new_declining}
    ai = muse_email("Write ONE email to the food bank coordinators and the volunteers on upcoming shifts. List the most "
                    "urgent at-risk items first (they expire within 3 days) and ask for them to go out in the next hampers. "
                    "Then briefly mention the WATCH counts per category and any declining categories.", data, log)
    if ai:
        subject, body, by = ai[0], ai[1], "AI"
    else:
        by = "Template"
        subject = (f"[Food Bank] {len(new_high)} items expiring within 3 days - priority distribution" if new_high
                   else "[Food Bank] Declining stock")
        lines = [f"- {r['item']} ({r['qty']}), expires {r['expires']}, {r['days_left']} day(s) left" for r in rows_out[:30]]
        if len(new_high) > 30:
            lines.append(f"...and {len(new_high) - 30} more (see the Inventory page, HIGH risk)")
        body = "Hi team,\n\n"
        if lines:
            body += "These items need to go out in the next hampers:\n\n" + "\n".join(lines) + "\n\n"
        if watch_by_cat:
            body += ("May expire before they can be given out (WATCH): " +
                     ", ".join(f"{c} {n}" for c, n in sorted(watch_by_cat.items(), key=lambda x: -x[1])) + ".\n\n")
        if new_declining:
            body += "Declining stock:\n" + "\n".join(f"- {d['category']}: {d['why']}" for d in new_declining) + "\n\n"
        body += "Automated alert from the Food Bank system."
    # project requirement: coordinators AND volunteers on upcoming shifts before these items expire
    last = max([i["Expiration_Date"] for i in new_high] or [day + dt.timedelta(days=RISK_HIGH_DAYS)])
    people = {p["User_ID"]: p for p in coordinators(cur) + shift_volunteers(cur, dt.datetime.combine(last, dt.time.max))}
    send_alert(cur, list(people.values()), alert_id, subject, body, by, mode, dry, log)
    return {"expired": len(expired), "at_risk": len(new_high), "watch": len(watch)}


# ---------------- Algorithm 4: missed / delayed pickups ----------------
def pickup_check(cur, mode, dry, log):
    cur_now = now(cur)
    cur.execute(use_demo_dates("""SELECT d.Distribution_ID, d.Pickup_Date_Time, d.Status, r.Name, r.Phone
                   FROM Distribution d JOIN Recipient r USING (Recipient_ID)
                   WHERE d.Status IN ('Scheduled','Delayed') AND DATE(d.Pickup_Date_Time) <= CURDATE()
                   AND d.Pickup_Date_Time >= CURDATE() - INTERVAL 7 DAY      -- older pickups were already closed by volunteers""", cur))
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
                                   i.Status=IF(i.Status='Expired','Expired','Available')   -- expired food is then removed by the expiry check
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
    ai = muse_email("Write ONE email telling the coordinators about these missed or delayed hamper pickups, "
                    "and suggest calling each recipient to reschedule.", rows, log)
    if ai:
        subject, body, by = ai[0], ai[1], "AI"
    else:
        by = "Template"
        subject = f"[Food Bank] {len(todo)} pickup(s) missed or delayed"
        body = "Hi coordinators,\n\nThese pickups need follow-up:\n\n" + "\n".join(
            f"- {r['recipient']} ({r['phone']}), pickup {r['pickup_time']}: {r['status']}" for r in rows) + \
            "\n\nPlease contact them to reschedule."
    send_alert(cur, coordinators(cur), alert_id, subject, body, by, mode, dry, log)   # coordinators only
    return {"pickup_alerts": len(todo)}


def run_check(mode="Manual", dry=False, pickups_only=False):
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
    if "--test-email" in sys.argv:
        out = send_test_email()
    else:
        out = run_check(mode="Manual", dry="--dry-run" in sys.argv)
    print("\n".join(out["log"]))
