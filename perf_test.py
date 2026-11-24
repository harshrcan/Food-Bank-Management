"""
Performance test for the SRS non-functional requirement:
  "95% of page loads, searches, and reports shall complete in under 5 seconds with at least
   1,000 inventory records and 200 recipients in the database."

    python perf_test.py            (20 runs of each action)
    python perf_test.py 50         (50 runs of each action)

It runs every action many times against your real MySQL database, measures each one, and reports
the 95th percentile (the time 95% of runs finish within). Results are also saved to perf_results.txt
for the testing report. It only reads data (the report runs add a row to the Report log).
"""
import sys, time, statistics, datetime as dt
import app as webapp
import ai_engine

RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
LIMIT = 5.0


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)]


def main():
    con = ai_engine.connect(); cur = con.cursor()
    counts = {}
    for label, sql in [("Inventory records", "SELECT COUNT(*) FROM Inventory_Item"),
                       ("Items in stock", "SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0"),
                       ("Recipients", "SELECT COUNT(*) FROM Recipient"), ("Categories", "SELECT COUNT(*) FROM Category"),
                       ("Hampers (distributions)", "SELECT COUNT(*) FROM Distribution"),
                       ("Hamper item lines", "SELECT COUNT(*) FROM Distribution_Item"), ("Donations", "SELECT COUNT(*) FROM Donation")]:
        cur.execute(sql); counts[label] = cur.fetchone()[0]
    cur.execute("SELECT MIN(Expiration_Date), MAX(Expiration_Date) FROM Inventory_Item WHERE Status='Available' AND Quantity>0")
    lo, hi = cur.fetchone()
    cur.execute("""SELECT u.Email, r.Name FROM Recipient r JOIN User_Account u USING(User_ID)
                   JOIN Distribution d USING(Recipient_ID) GROUP BY r.Recipient_ID ORDER BY COUNT(*) DESC LIMIT 1""")
    r_email, r_name = cur.fetchone()
    cur.execute("SELECT u.Email FROM Donor dn JOIN User_Account u USING(User_ID) LIMIT 1")
    d_email = cur.fetchone()[0]
    con.close()

    year = dt.date.today().year
    month = dt.date.today().month

    def logged_in(email):
        c = webapp.app.test_client()
        r = c.post("/api/login", json={"email": email, "password": "Password123!"})
        if r.status_code != 200:
            raise SystemExit(f"Could not log in as {email}: {r.get_json()}. Run python setup_db.py first.")
        return c

    con = ai_engine.connect(); cur = con.cursor()
    cur.execute("SELECT u.Email FROM Coordinator c JOIN User_Account u USING(User_ID) LIMIT 1"); c_email = cur.fetchone()[0]
    cur.execute("""SELECT u.Email FROM Volunteer v JOIN User_Account u USING(User_ID) JOIN Shift_Assignment USING(Volunteer_ID)
                   GROUP BY v.Volunteer_ID ORDER BY COUNT(*) DESC LIMIT 1"""); v_email = cur.fetchone()[0]
    cur.execute("SELECT Category_ID FROM Category LIMIT 1"); cat = cur.fetchone()[0]
    con.close()
    recip, donor, staff, vol = logged_in(r_email), logged_in(d_email), logged_in(c_email), logged_in(v_email)
    last = r_name.split()[-1]
    actions = [
        ("Page load: app page (HTML)", staff, "/"),
        ("Page load: coordinator overview", staff, "/api/dashboard"),
        ("Page load: volunteer today", vol, "/api/dashboard"),
        ("Page load: recipient home", recip, "/api/dashboard"),
        ("Page load: inventory (all in stock)", staff, "/api/inventory"),
        ("Page load: database viewer data", staff, "/api/data"),
        ("Search: recipient's own hampers by date", recip, "/api/recipient/hampers?from=2026-10-01&to=2026-11-30"),
        ("Search: donor's own donations by date + category", donor, f"/api/donor/donations?from=2026-10-01&to=2026-11-30&category_id={cat}"),
        ("Search: distributions by recipient name", staff, f"/api/distributions?recipient={last}"),
        ("Search: distributions by date range", staff, "/api/distributions?from=2026-11-01&to=2026-11-30"),
        ("Search: inventory by category + expiry", vol, f"/api/inventory?category_id={cat}&expires_before=2026-12-01"),
        ("Report: Donation & Distribution (month)", staff, f"/api/report?type=donation&year={year}&month={month}"),
        ("Report: Donation & Distribution (year)", staff, f"/api/report?type=donation&year={year}"),
        ("Report: Inventory Waste (month)", staff, f"/api/report?type=waste&year={year}&month={month}"),
        ("Report: Inventory Waste (year)", staff, f"/api/report?type=waste&year={year}"),
    ]

    out = [f"Performance test, {dt.datetime.now():%Y-%m-%d %H:%M}, {RUNS} runs per action, target: 95% under {LIMIT:.0f} s", ""]
    out.append("Database size:")
    out += [f"  {k}: {v:,}" for k, v in counts.items()]
    out.append(f"  Stock expiry dates: {lo} to {hi}")
    ok_all = counts["Inventory records"] >= 1000 and counts["Recipients"] >= 200
    out.append(f"  Meets the test size (1,000+ inventory records, 200+ recipients): {'YES' if ok_all else 'NO'}")
    out += ["", f"{'Action':<50} {'Rows/size':>12} {'Median':>8} {'95th %':>8} {'Max':>8}  Result", "-" * 100]
    for label, client, url in actions:
        times, size = [], 0
        for _ in range(RUNS):
            t0 = time.perf_counter()
            r = client.get(url)
            times.append(time.perf_counter() - t0)
            if r.status_code != 200:
                raise SystemExit(f"{label} failed: HTTP {r.status_code} {r.get_data(as_text=True)[:200]}")
            size = len(r.get_data())
            if r.is_json:
                j = r.get_json()
                lists = [v for v in j.values() if isinstance(v, list)] if isinstance(j, dict) else []
                if lists:
                    size = f"{max(len(v) for v in lists)} rows"
        good = p95(times) < LIMIT
        ok_all &= good
        sz = size if isinstance(size, str) else f"{size / 1024:.0f} KB"
        out.append(f"{label:<50} {sz:>12} {statistics.median(times):>7.3f}s {p95(times):>7.3f}s {max(times):>7.3f}s  "
                   f"{'PASS' if good else 'FAIL'}")
    out += ["", "OVERALL: PASS (every action: 95% of runs under 5 seconds)" if ok_all else "OVERALL: FAIL"]
    text = "\n".join(out)
    print(text)
    open("perf_results.txt", "w", encoding="utf-8").write(text + "\n")
    print("\nSaved to perf_results.txt")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
