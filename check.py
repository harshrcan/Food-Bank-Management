"""
Pre-demo checklist. Run this before the presentation:

    python check.py

It checks your settings, the database, the logins and the AI connection, and tells you what to fix.
It does not change any data.
"""
import os, sys, datetime as dt

ok_all = True


def show(ok, label, fix=""):
    global ok_all
    mark = "[ OK ]" if ok else ("[WARN]" if ok is None else "[FAIL]")
    print(f"{mark} {label}" + (f"\n       -> {fix}" if fix and ok is not True else ""))
    if ok is False:
        ok_all = False


show(True if os.path.exists(".env") else None, ".env file found", "Copy .env.example to .env and fill it in.")
try:
    import ai_engine, setup_db
except ImportError as e:
    show(False, f"Python packages installed ({e})", "Run: pip install -r requirements.txt")
    sys.exit(1)
show(True, "Python packages installed")

try:
    con = ai_engine.connect(); cur = con.cursor()
    show(True, "MySQL reachable and foodbank database exists")
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()")
    n = cur.fetchone()[0]
    show(n >= 19, f"All tables and views present ({n})", "Run: python setup_db.py")
    cur.execute("SELECT COUNT(*), SUM(Expiration_Date < CURDATE()), SUM(Expiration_Date >= CURDATE()) "
                "FROM Inventory_Item WHERE Status='Available' AND Quantity>0")
    total, old, fresh = cur.fetchone()
    show(bool(fresh) and fresh >= 50, f"Test data is fresh ({fresh or 0} items in date, {old or 0} waiting for the AI check)",
         "Run: python setup_db.py  (reloads test data with today's dates)")
    cur.execute("SELECT Password_Hash FROM User_Account LIMIT 1")
    row = cur.fetchone()
    show(bool(row) and setup_db.check_password(setup_db.TEST_PASSWORD, row[0]),
         f"Test logins work (password: {setup_db.TEST_PASSWORD})", "Run: python setup_db.py")
    cur.execute("SELECT GROUP_CONCAT(u.Email SEPARATOR ', ') FROM Coordinator c JOIN User_Account u USING(User_ID)")
    show(True, f"Alert emails go to: {cur.fetchone()[0]}")
    cur.execute("SELECT Setting_Value FROM App_Setting WHERE Setting_Key='Demo_Date'")
    row = cur.fetchone()
    if row and row[0]:
        show(None, f"A demo date is active ({row[0]})", "Click 'Use real date' on the AI page if you did not mean to leave it on.")
    con.close()
except Exception as e:
    show(False, f"MySQL / database ({str(e)[:120]})",
         "Start the MySQL service, check DB_PASS in .env, then run: python setup_db.py")

if not ai_engine.muse_enabled():
    show(None, "AI key not set (alerts and reports will use the built-in templates)",
         "Add AI_API_KEY to .env. Free key: https://aistudio.google.com/apikey")
else:
    try:
        ai_engine.muse_chat("Reply with the single word: ready", max_tokens=200)
        show(True, f"AI answers ({ai_engine.muse_status()})")
    except Exception as e:
        show(False, "AI did not answer", str(e)[:300] + "  (If it says 429, wait one minute: free tier limit.)")

show(True if ai_engine.smtp_ready() else None,
     "Email sending is set up" if ai_engine.smtp_ready() else "Email not set up (alerts are saved in Email_Log only)",
     "Optional: put a Gmail address and App Password in SMTP_USER / SMTP_PASS in .env.")

print("\nReady for the demo." if ok_all else "\nFix the FAIL lines above, then run this again.")
sys.exit(0 if ok_all else 1)
