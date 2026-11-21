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
    recip = webapp.app.test_client(); recip.post("/api/login", json={"email": r_email, "password": "Password123!"})
    donor = webapp.app.test_client(); donor.post("/api/login", json={"email": d_email, "password": "Password123!"})
    staff = webapp.app.test_client()
    last = r_name.split()[-1]
    actions = [
        ("Page load: viewer page (HTML)", staff, "/"),
        ("Page load: all tables (/api/data)", staff, "/api/data"),
        ("Search: recipient's own history by date", recip, "/api/my/history?from=2026-10-01&to=2026-11-30"),
        ("Search: recipient's own history (all)", recip, "/api/my/history"),
        ("Search: donor's own donations by date + category", donor, "/api/my/history?from=2026-10-01&to=2026-11-30&category=Canned%20Goods"),
        ("Search: distributions by recipient name", staff, f"/api/search/distributions?recipient={last}"),
        ("Search: distributions by date range", staff, "/api/search/distributions?from=2026-11-01&to=2026-11-30"),
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
            if r.is_json and isinstance(r.get_json().get("rows"), list):
                size = f"{len(r.get_json()['rows'])} rows"
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
